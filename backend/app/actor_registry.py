"""经办人目录：演示环境里可切换的登录身份。

真实项目会换成根据会话/令牌查库；这里用静态目录，方便前端切换后直接看到
「本单位可改、跨单位被驳回、只读岗不能改」三种归属效果。
"""
from __future__ import annotations

from app.actors import Actor, ROLE_CERT_ADMIN, ROLE_VIEWER

# 三家使用单位，证书分属不同单位，才能体现归属隔离。
UNIT_A = "华东热电一厂"
UNIT_B = "滨江化工有限公司"
UNIT_C = "港务起重作业队"

ACTORS: tuple[Actor, ...] = (
    Actor(
        key="admin-a",
        name="李证书",
        unit=UNIT_A,
        role=ROLE_CERT_ADMIN,
    ),
    Actor(
        key="admin-b",
        name="王管理",
        unit=UNIT_B,
        role=ROLE_CERT_ADMIN,
    ),
    Actor(
        key="admin-a-delegate-b",
        name="李证书(持B厂代办授权)",
        unit=UNIT_A,
        role=ROLE_CERT_ADMIN,
        delegated_units=(UNIT_B,),
    ),
    Actor(
        key="viewer-a",
        name="张查阅",
        unit=UNIT_A,
        role=ROLE_VIEWER,
    ),
    Actor(
        key="viewer-b",
        name="赵只读",
        unit=UNIT_B,
        role=ROLE_VIEWER,
    ),
)

_ACTORS_BY_KEY = {actor.key: actor for actor in ACTORS}

# 请求头里携带经办人 key；缺省给一个本单位管理员，保证旧调用与导出链接可用。
DEFAULT_ACTOR_KEY = "admin-a"
ACTOR_HEADER = "X-Actor-Key"


def get_actor(key: str | None) -> Actor:
    """按 key 取经办人；未知或为空时回退到默认经办人。"""
    if key:
        actor = _ACTORS_BY_KEY.get(key)
        if actor is not None:
            return actor
    return _ACTORS_BY_KEY[DEFAULT_ACTOR_KEY]


def actor_dicts() -> list[dict[str, object]]:
    """给前端身份切换器用的精简列表。"""
    return [
        {
            "key": actor.key,
            "name": actor.name,
            "unit": actor.unit,
            "role": actor.role,
            "delegatedUnits": list(actor.delegated_units),
            "writable": actor.is_admin,
        }
        for actor in ACTORS
    ]
