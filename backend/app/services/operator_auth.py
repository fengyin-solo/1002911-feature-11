"""作业人员模块的操作身份与授权规则。

证书复审/注销只允许证件所属单位的证书管理员经办；替别的单位代办时，
必须持有被代办单位出具的专项授权（委托方、受托方、事项齐备）。
只读岗全程只能查看。

当前为内存版原型：身份由请求头带入，真实项目里应换成登录态/Token 解析，
授权台账换成数据库或审批系统接口；鉴权判定口径保持不变。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import Header, HTTPException

ROLE_ADMIN = "证书管理员"
ROLE_VIEWER = "只读岗"
# HTTP 头只能走 ASCII，前端传角色码，这里统一映射为中文岗位名。
ROLE_CODES = {"admin": ROLE_ADMIN, "viewer": ROLE_VIEWER}
ROLES = (ROLE_ADMIN, ROLE_VIEWER)

# 授权事项：代办时必须精确命中其一，缺哪项就驳回并说明缺哪项。
SCOPE_REVIEW = "证书复审登记"
SCOPE_CANCEL = "证书注销"
SCOPE_TRANSFER = "人员调动登记"
SCOPES = (SCOPE_REVIEW, SCOPE_CANCEL, SCOPE_TRANSFER)

# 动作 → 需要的授权事项；本单位经办不需要授权。
ACTION_SCOPES = {
    "安排复审": SCOPE_REVIEW,
    "登记复审结果": SCOPE_REVIEW,
    "注销证书": SCOPE_CANCEL,
    "人员调动": SCOPE_TRANSFER,
}


@dataclass(frozen=True)
class Actor:
    """当前请求的操作人：姓名、岗位与所属单位。"""

    name: str
    role: str
    unit: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_viewer(self) -> bool:
        return self.role == ROLE_VIEWER

    @property
    def identity(self) -> str:
        return f"{self.name}（{self.role}·{self.unit}）"


def require_actor(
    x_operator_name: str | None = Header(default=None, alias="X-Operator-Name"),
    x_operator_role: str | None = Header(default=None, alias="X-Operator-Role"),
    x_operator_unit: str | None = Header(default=None, alias="X-Operator-Unit"),
) -> Actor:
    """从请求头解析操作人；身份不完整或岗位不认识时拒绝，避免匿名改动。"""
    name = unquote(x_operator_name or "").strip()
    role = (x_operator_role or "").strip()
    unit = unquote(x_operator_unit or "").strip()
    # 姓名/单位允许中文，前端会按 RFC 2047 风格做 percent-encode；岗位只收角色码或中文岗位名。
    if role in ROLE_CODES:
        role = ROLE_CODES[role]
    missing = [
        label
        for value, label in (
            (name, "操作人姓名"),
            (role, "岗位"),
            (unit, "所属单位"),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=401,
            detail=f"缺少操作人身份信息（{'、'.join(missing)}），请先在页面顶部选择值班身份",
        )
    if role not in ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"岗位「{role}」无权进入作业人员模块，可选岗位：{'、'.join(ROLES)}",
        )
    return Actor(name=name, role=role, unit=unit)


def has_grant(
    grants: list[dict[str, Any]],
    *,
    trustee_unit: str,
    owner_unit: str,
    scope: str,
) -> dict[str, Any] | None:
    """在授权台账里找一条「所属单位委托→操作人单位受托→事项命中」的有效授权。"""
    for grant in grants:
        if grant.get("委托单位") != owner_unit:
            continue
        if grant.get("受托单位") != trustee_unit:
            continue
        if grant.get("授权事项") != scope:
            continue
        if not grant.get("有效", True):
            continue
        return grant
    return None


def ensure_can_operate(
    actor: Actor,
    *,
    owner_unit: str,
    action: str,
    grants: list[dict[str, Any]],
) -> str | None:
    """鉴权核心：返回 None 表示放行，否则返回应当场告知的驳回原因。

    顺序故意固定为：只读岗 → 跨单位授权事项 → 授权三要素，
    保证驳回信息能精确指出「缺哪项授权」。
    """
    scope = ACTION_SCOPES.get(action)
    if scope is None:
        return f"动作「{action}」不属于证书管理员可经办范围"
    if actor.is_viewer:
        return f"只读岗仅可查看，证书复审与注销须由{owner_unit}的证书管理员经办"
    if actor.unit == owner_unit:
        return None

    grant = has_grant(
        grants,
        trustee_unit=actor.unit,
        owner_unit=owner_unit,
        scope=scope,
    )
    if grant is not None:
        return None

    # 先看有没有「别的事项」的授权，帮助操作人理解是事项不对还是完全没授权。
    same_parties = [
        item
        for item in grants
        if item.get("委托单位") == owner_unit
        and item.get("受托单位") == actor.unit
        and item.get("有效", True)
    ]
    if same_parties:
        held = "、".join(str(item.get("授权事项", "")) for item in same_parties)
        return (
            f"跨单位代办被驳回：{actor.unit}持有的授权事项为「{held}」，"
            f"本次「{action}」缺少「{scope}」事项授权"
        )
    return (
        "跨单位代办被驳回：未查到有效授权，缺少"
        f"委托单位={owner_unit}、受托单位={actor.unit}、授权事项={scope} 的授权书，"
        "请先由证件所属单位出具专项授权"
    )
