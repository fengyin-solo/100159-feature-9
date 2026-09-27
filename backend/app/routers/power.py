"""供电保障接口：维护供电单元，覆盖安排巡检、确认正常、标记断电等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.power import BACKUP_HOURS_MIN
from app.services.power import PowerService

router = APIRouter(prefix="/api/power", tags=["供电保障"])

service = PowerService()

STATUSES = ["待巡检", "供电正常", "备电不足", "已断电"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按供电编号检索"),
    status: str | None = Query(default=None, description="待巡检、供电正常、备电不足、已断电"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按供电编号与状态过滤供电保障列表；没有数据时返回空页，不报错。

    重复的供电编号已在服务层合并，total 与 items 口径一致；stats 与列表同源，
    备电不足条数可直接对得上。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"供电状态「{status}」不在可选范围内")
    items, total, stats = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size, stats=stats)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出供电保障清单：返回合并重复编号后的全量数据。"""
    items, total, _stats = service.list_entries(page=1, size=200)
    return {"module": "power", "total": total, "items": items, "备电下限小时": BACKUP_HOURS_MIN}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条供电单元明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"供电单元 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条供电单元；备电时长或供电方式等必填项缺失时说明原因。"""
    entry, missing, merged_duplicate = service.create_entry(payload.values)
    if missing:
        return ActionResult(
            ok=False,
            message=f"无法保存：缺少必填字段{'、'.join(missing)}，请补全后再提交",
        )
    if merged_duplicate:
        return ActionResult(ok=True, message="检测到供电编号重复，记录已合并为一条", entry=entry)
    return ActionResult(ok=True, message="供电单元已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条供电单元执行安排巡检、确认正常、标记断电；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
