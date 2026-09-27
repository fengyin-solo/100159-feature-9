"""供电保障业务规则：备电时长与断电处置串联的口径都收在这里。

规则要点：
- 供电编号相同的记录视为同一个供电单元，列表与明细统一先合并再输出；
- 备电时长低于下限（BACKUP_HOURS_MIN）的供电单元单独标记为备电不足；
- 每条记录补充最近一次放电测试/责任人，以及最近一次巡检结论，标记断电前后都能查到；
- 备电时长或供电方式缺失时不允许保存，并说明缺了哪一项。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "power"
REQUIRED_FIELDS = ["供电编号", "所属站点", "供电方式", "备电时长"]
# 登记/补录时允许写入的业务字段
EDITABLE_FIELDS = [
    "所属站点",
    "供电方式",
    "蓄电池容量",
    "上次放电测试",
    "备电时长",
    "责任人员",
]
STATUS_ORDER = ["待巡检", "供电正常", "备电不足", "已断电"]
ACTION_RULES = {"安排巡检": "供电正常", "确认正常": "备电不足", "标记断电": "已断电"}
NEGATIVE_ACTIONS = []

# 备电时长下限（小时）：低于该值即标记为备电不足
BACKUP_HOURS_MIN = 8.0
HOURS_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")

INSPECTION_FIELDS = ["巡检单号", "巡检站点", "巡检人员", "巡检日期", "巡检状态", "巡检结论"]


def _parse_hours(value: Any) -> float | None:
    """从「12小时」「6.5 h」这类写法里取出小时数；取不到数字返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = HOURS_PATTERN.search(text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


class PowerService:
    def _merge_pair(self, base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        """合并同一供电编号的两条记录：保留 id 小的，业务字段与状态取登记更晚的。"""
        keep, older = (base, extra) if int(base.get("id", 0)) >= int(extra.get("id", 0)) else (extra, base)
        result: dict[str, Any] = dict(older)
        result.update({field: keep[field] for field in EDITABLE_FIELDS if str(keep.get(field) or "").strip()})
        result["id"] = int(older.get("id", keep.get("id", 0)))
        result["供电编号"] = keep.get("供电编号")
        result["status"] = keep.get("status", older.get("status"))
        result["pending"] = keep.get("pending", older.get("pending"))
        result["abnormal"] = keep.get("abnormal", older.get("abnormal"))
        if keep.get("断电时刻"):
            result["断电时刻"] = keep["断电时刻"]
        elif older.get("断电时刻"):
            result["断电时刻"] = older["断电时刻"]
        return result

    def _merged_rows(self) -> list[dict[str, Any]]:
        """按供电编号合并重复记录，列表、明细、统计都基于合并结果。"""
        merged: dict[str, dict[str, Any]] = {}
        for row in store.rows(MODULE):
            code = str(row.get("供电编号") or "").strip()
            if not code:
                continue
            current = merged.get(code)
            merged[code] = dict(row) if current is None else self._merge_pair(current, dict(row))
        return list(merged.values())

    def _latest_inspection_map(self) -> dict[str, dict[str, Any]]:
        """以巡检站点为键，取每个站点最近一次巡检（日期相同取序号更大的）。"""
        latest: dict[str, dict[str, Any]] = {}
        for row in store.rows("inspection"):
            site = str(row.get("巡检站点") or "").strip()
            if not site:
                continue
            current = latest.get(site)
            if current is None or self._inspection_rank(row) > self._inspection_rank(current):
                latest[site] = row
        return latest

    @staticmethod
    def _inspection_rank(row: dict[str, Any]) -> tuple[str, int]:
        return str(row.get("巡检日期") or ""), int(row.get("id", 0))

    def _enrich(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """补充备电时长解析结果与最近一次巡检结论；统一字段口径。"""
        latest_map = self._latest_inspection_map()
        enriched: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            hours = _parse_hours(item.get("备电时长"))
            item["备电时长小时"] = hours
            item["有备电数据"] = hours is not None
            item["备电不足"] = hours is not None and hours < BACKUP_HOURS_MIN
            item["备电下限小时"] = BACKUP_HOURS_MIN
            latest = latest_map.get(str(item.get("所属站点") or "").strip())
            item["最近巡检"] = (
                {field: latest.get(field) for field in INSPECTION_FIELDS} if latest is not None else None
            )
            # 列表/明细统一带出放电测试与责任人，标记断电前后都能直接看到
            item["最近放电测试"] = item.get("上次放电测试")
            enriched.append(item)
        return enriched

    @staticmethod
    def _stats(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "在册供电单元": len(rows),
            "备电不足": sum(1 for row in rows if row.get("备电不足")),
            "已断电站点": sum(1 for row in rows if row.get("status") == "已断电"),
        }

    def _query(self, *, keyword: str | None, status: str | None) -> list[dict[str, Any]]:
        rows = self._merged_rows()
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("供电编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = self._enrich(rows)
        # 备电不足、已断电优先排在前面，先扛不住的站点先看到
        rows.sort(key=lambda row: (not row.get("备电不足"), row.get("status") != "已断电", int(row.get("id", 0))))
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows = self._query(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total, self._stats(rows)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        for row in self._enrich(self._merged_rows()):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def _rows_for_code(self, code: str) -> list[dict[str, Any]]:
        return [row for row in store.rows(MODULE) if str(row.get("供电编号") or "").strip() == code]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记或更新供电单元。

        返回 (记录, 缺失字段, 是否合并了重复编号)；备电时长/供电方式缺失时拒绝保存。
        """
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False

        rows = store.rows(MODULE)
        code = str(values.get("供电编号")).strip()
        duplicates = self._rows_for_code(code)
        merged_duplicate = bool(duplicates)
        if duplicates:
            targets = duplicates
        else:
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry["供电编号"] = code
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
            targets = [entry]
        # 同一编号的所有原始记录一起更新，保证合并后的视图与写入一致
        for target in targets:
            for field in EDITABLE_FIELDS:
                value = values.get(field)
                if str(value or "").strip():
                    target[field] = value
        merged_id = min(int(row.get("id", 0)) for row in targets)
        return self.get_entry(merged_id), [], merged_duplicate

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于供电保障可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        merged = self.get_entry(entry_id)
        if merged is None:
            return None, f"供电单元 {entry_id} 不存在或已归档"
        # 动作落到同一供电编号的全部原始记录上，避免重复编号只处置了其中一条
        code = str(merged.get("供电编号") or "").strip()
        for entry in self._rows_for_code(code):
            if action == "标记断电" and entry.get("status") != "已断电":
                entry["断电时刻"] = date.today().isoformat()
            entry["status"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self.get_entry(entry_id), f"供电单元已{action}"
