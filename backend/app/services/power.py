"""供电保障业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "power"
REQUIRED_FIELDS = ["供电编号", "所属站点", "供电方式", "备电时长"]
STATUS_ORDER = ["待巡检", "供电正常", "备电不足", "已断电"]
ACTION_RULES = {"安排巡检": "供电正常", "确认正常": "备电不足", "标记断电": "已断电"}
NEGATIVE_ACTIONS: list[str] = []

# 备电时长下限（小时）：低于该值的供电单元在列表与统计里单独标为「备电不足」
BACKUP_HOURS_MIN = 4.0

# 合并重复记录时保持不变的字段：编号本身与状态流转相关字段以首条记录为准
WORKFLOW_FIELDS = {"id", "status", "pending", "abnormal", "供电编号"}

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def _parse_backup_hours(value: Any) -> float | None:
    """把「3.5小时」「4h」「6」这类备电时长统一解析成小时数；解析不出返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_PATTERN.search(str(value))
    return float(match.group()) if match else None


class PowerService:
    def __init__(self) -> None:
        self._dedupe_rows()

    # ---- 内部工具 ----

    @staticmethod
    def _merge_into(base: dict[str, Any], values: dict[str, Any]) -> None:
        """把重复记录的非空字段并进来；编号与状态流转字段保持首条记录不变。"""
        for key, value in values.items():
            if key in WORKFLOW_FIELDS:
                continue
            if value is not None and str(value).strip():
                base[key] = value

    def _dedupe_rows(self) -> None:
        """把供电编号重复的记录合并成一条，避免列表条数与统计对不上。"""
        rows = store.rows(MODULE)
        seen: dict[str, dict[str, Any]] = {}
        merged: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("供电编号") or "").strip()
            if code and code in seen:
                self._merge_into(seen[code], row)
                continue
            if code:
                seen[code] = row
            merged.append(row)
        rows[:] = merged

    @staticmethod
    def _derive_status(row: dict[str, Any]) -> str:
        """列表展示口径：已断电保持不变；备电时长低于下限的一律标成备电不足。"""
        status = str(row.get("status") or STATUS_ORDER[0])
        if status == "已断电":
            return status
        hours = _parse_backup_hours(row.get("备电时长"))
        if hours is not None and hours < BACKUP_HOURS_MIN:
            return "备电不足"
        return status

    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        status = self._derive_status(row)
        item["status"] = status
        item["供电状态"] = status
        return item

    def _presented_rows(self) -> list[dict[str, Any]]:
        return [self._present(row) for row in store.rows(MODULE)]

    # ---- 查询 ----

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        code: str | None = None,
        station: str | None = None,
        supply: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._presented_rows()
        code_keyword = (code or keyword or "").strip()
        if code_keyword:
            rows = [row for row in rows if code_keyword in str(row.get("供电编号", ""))]
        if station:
            rows = [row for row in rows if station in str(row.get("所属站点", ""))]
        if supply:
            rows = [row for row in rows if supply in str(row.get("供电方式", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def summary(self) -> dict[str, Any]:
        """列表统计口径：与列表使用同一套派生状态，保证备电不足条数对得上。"""
        rows = self._presented_rows()
        return {
            "在册供电单元": len(rows),
            "备电不足": sum(1 for row in rows if row["status"] == "备电不足"),
            "已断电站点": sum(1 for row in rows if row["status"] == "已断电"),
            "备电时长下限": BACKUP_HOURS_MIN,
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._present(row) if row is not None else None

    # ---- 登记与合并 ----

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        rows = store.rows(MODULE)
        code = str(values.get("供电编号") or "").strip()
        for row in rows:
            if str(row.get("供电编号") or "").strip() == code:
                self._merge_into(row, values)
                return self._present(row), [], True
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for key, value in values.items():
            if key in WORKFLOW_FIELDS:
                continue
            if value is not None and str(value).strip():
                entry[key] = value
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), [], False

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"供电单元 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于供电保障可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 标记断电只流转状态：上次放电测试、责任人员、最近巡检结论原样保留，断电前后都能查到
        return self._present(entry), f"供电单元已{action}"
