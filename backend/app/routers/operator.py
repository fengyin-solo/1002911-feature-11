"""作业人员接口：证书台账、下一期复审名单，以及复审/注销/过期/调动等动作。

归属与岗位授权全部在 service 层判定；路由层只负责还原当前经办人并把
:class:`BusinessError` 翻译成 ``{ok:false,message}`` 的标准响应。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.actor_registry import ACTOR_HEADER, actor_dicts, get_actor
from app.errors import BusinessError
from app.schemas import ActionResult, PageResult
from app.services.operator import (
    RESULT_FAIL,
    RESULT_PASS,
    OperatorService,
    _today,
)

router = APIRouter(prefix="/api/operator", tags=["作业人员"])

service = OperatorService()

STATUSES = ["持证有效", "即将到期", "已过期", "已注销"]


class ReviewPayload(BaseModel):
    result: str = Field(description="复审结果：合格 / 不合格")
    next_review_date: str | None = None
    remark: str | None = None


class RemarkPayload(BaseModel):
    remark: str | None = None


class TransferPayload(BaseModel):
    target_unit: str
    remark: str | None = None


class CertPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def _denied(exc: BusinessError) -> JSONResponse:
    """驳回仍返回统一的 {ok:false,message} 结构，但带上 403/409 等正确状态码。"""
    return JSONResponse(status_code=exc.status, content=ActionResult(ok=False, message=exc.message).model_dump())


@router.get("/actors")
def list_actors() -> dict[str, Any]:
    """列出可切换的经办人（单位/岗位/代办授权），供前端还原登录态。"""
    return {"items": actor_dicts()}


@router.get("/review-roster")
def review_roster(
    unit: str | None = Query(default=None, description="按所属单位过滤"),
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> dict[str, Any]:
    """下一期复审名单：只含未锁定、复审已到/临近的证件，按复审日期升序。"""
    actor = get_actor(x_actor_key)
    items = service.review_roster(actor, unit=unit)
    return {
        "total": len(items),
        "asOf": _today().isoformat(),
        "items": items,
        "actor": {"name": actor.name, "unit": actor.unit, "role": actor.role},
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按人员编号/姓名/证书编号检索"),
    unit: str | None = Query(default=None, description="按所属单位过滤"),
    status: str | None = Query(default=None, description="持证有效、即将到期、已过期、已注销"),
    page: int = 1,
    size: int = 20,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> PageResult[dict]:
    """按编号、单位与状态过滤作业人员台账；状态由 service 统一推导。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    actor = get_actor(x_actor_key)
    items, total = service.list_entries(actor, keyword=keyword, unit=unit, status=status,
                                        page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> dict[str, Any]:
    """导出作业人员台账全量数据（只读）。"""
    actor = get_actor(x_actor_key)
    items, total = service.list_entries(actor, page=1, size=10000)
    return {"module": "operator", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(
    entry_id: int,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> dict[str, Any]:
    """读取单条作业人员明细与完整复审/经办历史；读不到给出可读说明。"""
    actor = get_actor(x_actor_key)
    try:
        return service.get_entry(entry_id, actor)
    except BusinessError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.post("", response_model=ActionResult)
def create_entry(
    payload: CertPayload,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> ActionResult:
    """登记一条作业人员证书；归属/岗位不符或缺字段都会说明原因。"""
    actor = get_actor(x_actor_key)
    try:
        entry, missing = service.create_entry(actor, payload.values)
        if missing:
            return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
        return ActionResult(ok=True, message="作业人员证书已登记", entry=entry)
    except BusinessError as exc:
        return _denied(exc)


@router.post("/{entry_id}/review", response_model=ActionResult)
def register_review(
    entry_id: int,
    payload: ReviewPayload,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> ActionResult:
    """登记复审结果：合格→有效并顺延复审日期；不合格→已过期并锁定。"""
    actor = get_actor(x_actor_key)
    result = (payload.result or "").strip()
    try:
        entry = service.register_review(
            entry_id, actor,
            result=result,
            next_review_date=payload.next_review_date,
            remark=payload.remark or "",
        )
        if result == RESULT_PASS:
            message = "复审合格，证书状态已落定为持证有效，复审日期已顺延"
        else:
            message = "复审不合格，证书已登记为已过期并锁定，不再排进下一期复审"
        return ActionResult(ok=True, message=message, entry=entry)
    except BusinessError as exc:
        return _denied(exc)


@router.post("/{entry_id}/expire", response_model=ActionResult)
def register_expired(
    entry_id: int,
    payload: RemarkPayload,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> ActionResult:
    """手工登记过期：证件锁定为已过期，不再排进下一期复审。"""
    actor = get_actor(x_actor_key)
    try:
        entry = service.register_expired(entry_id, actor, remark=payload.remark or "")
        return ActionResult(ok=True, message="已登记为过期，证件锁定，不再排进复审名单", entry=entry)
    except BusinessError as exc:
        return _denied(exc)


@router.post("/{entry_id}/revoke", response_model=ActionResult)
def revoke(
    entry_id: int,
    payload: RemarkPayload,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> ActionResult:
    """注销证书：锁定为已注销。"""
    actor = get_actor(x_actor_key)
    try:
        entry = service.revoke(entry_id, actor, remark=payload.remark or "")
        return ActionResult(ok=True, message="证书已注销并锁定", entry=entry)
    except BusinessError as exc:
        return _denied(exc)


@router.post("/{entry_id}/transfer", response_model=ActionResult)
def transfer(
    entry_id: int,
    payload: TransferPayload,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> ActionResult:
    """人员调动：仅现归属单位证书管理员可发起，历史保留原经办单位。"""
    actor = get_actor(x_actor_key)
    try:
        entry = service.transfer(entry_id, actor, target_unit=payload.target_unit,
                                 remark=payload.remark or "")
        return ActionResult(ok=True, message=f"已调动至{payload.target_unit.strip()}", entry=entry)
    except BusinessError as exc:
        return _denied(exc)


@router.put("/{entry_id}/cert", response_model=ActionResult)
def update_cert(
    entry_id: int,
    payload: CertPayload,
    x_actor_key: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> ActionResult:
    """变更证书类别/复审日期：只读岗与越权代办一律驳回。"""
    actor = get_actor(x_actor_key)
    try:
        entry = service.update_cert_fields(entry_id, actor, payload.values)
        return ActionResult(ok=True, message="证书信息已更新", entry=entry)
    except BusinessError as exc:
        return _denied(exc)
