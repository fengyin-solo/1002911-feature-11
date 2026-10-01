"""作业人员接口：人员台账、复审名单，以及复审登记、注销、调动等归属受控的动作。

所有写接口都要求请求头带操作人身份（X-Operator-Name/Role/Unit），
鉴权与状态规则全部在 service 层；路由层只负责把身份和入参传下去。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.operator import DISPLAY_STATUSES, OperatorService
from app.services.operator_auth import Actor, require_actor

router = APIRouter(prefix="/api/operator", tags=["作业人员"])

service = OperatorService()

LIST_FIELDS = ["人员编号", "姓名", "证书类别", "证书编号", "发证日期", "复审日期", "所属单位", "证书状态"]


@router.get("/roster", response_model=dict)
def review_roster(
    period: str | None = Query(default=None, description="复审期，如 2026Q4；缺省取当前季度"),
    unit: str | None = Query(default=None, description="可选：按所属单位过滤"),
) -> dict[str, Any]:
    """下一期复审名单：终态（已过期/已注销）证件不返回，名单与台账共用状态口径。"""
    items, period = service.review_roster(period=period, unit=unit)
    return {"period": period, "total": len(items), "items": items}


@router.get("/units", response_model=dict)
def list_units() -> dict[str, Any]:
    """台账中出现过的所属单位，供筛选与身份切换使用。"""
    return {"items": service.list_units()}


@router.get("/grants", response_model=dict)
def list_grants(actor: Actor = Depends(require_actor)) -> dict[str, Any]:
    """跨单位代办授权台账，驳回时页面可据此核对缺哪一项。"""
    return {"items": service.list_grants()}


@router.get("/export")
def export_entries(actor: Actor = Depends(require_actor)) -> dict[str, Any]:
    """导出作业人员清单：全量数据，状态按统一口径现算。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "operator", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按人员编号或姓名检索"),
    status: str | None = Query(default=None, description="持证有效/即将到期/逾期未复审/已过期/已注销"),
    unit: str | None = Query(default=None, description="按所属单位过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、姓名、状态与单位过滤人员台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in DISPLAY_STATUSES:
        raise HTTPException(status_code=400, detail=f"未知证书状态：{status}")
    items, total = service.list_entries(keyword=keyword, status=status, unit=unit, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条作业人员明细，含历次复审经办记录与单位沿革；不存在时给可读错误。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"作业人员 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(
    payload: EntryPayload,
    actor: Actor = Depends(require_actor),
) -> ActionResult:
    """登记作业人员：只许本单位证书管理员登记本单位人员，跨单位须持专项授权。"""
    entry, message = service.create_entry(payload.values, actor)
    if entry is None:
        return ActionResult(ok=False, message=message or "登记失败")
    return ActionResult(ok=True, message="作业人员已登记", entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(
    entry_id: int,
    payload: EntryPayload,
    actor: Actor = Depends(require_actor),
) -> ActionResult:
    """修改一般资料；证书类别与复审日期受保护，必须走重新发证或登记复审结果。"""
    entry, message = service.update_entry(entry_id, payload.values, actor)
    if entry is None:
        return ActionResult(ok=False, message=message or "修改失败")
    return ActionResult(ok=True, message=message or "资料已更新", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    actor: Actor = Depends(require_actor),
) -> ActionResult:
    """安排复审、登记复审结果、登记过期、注销证书、人员调动。

    非本单位证书管理员、缺少专项授权的代办、只读岗的写操作都会在此被拦下，
    返回的 message 会说明缺哪项授权或为什么不能做。
    """
    action = str(payload.values.get("action") or "").strip()
    form = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message = service.run_action(entry_id, action, actor, form)
    if entry is None:
        return ActionResult(ok=False, message=message or "动作未生效")
    return ActionResult(ok=True, message=message or f"作业人员已{action}", entry=entry)
