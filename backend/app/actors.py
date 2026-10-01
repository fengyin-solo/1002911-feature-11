"""作业人员模块的身份与归属模型。

平台没有真正的登录体系，这里用一个可枚举的「当前经办人」来模拟登录态：
前端在顶栏切换经办人，请求时带上 ``X-Actor-Key``，后端据此还原出经办人
的单位、岗位（证书管理员 / 只读员）以及是否具备跨单位代办授权。

归属与授权的判定全部收在 :class:`Actor` 上，service 层只负责调用，
避免把「谁能动哪个单位」的口径散落到各个接口里。
"""
from __future__ import annotations

from dataclasses import dataclass

# 岗位常量：证书管理员可以写，只读员只能看。
ROLE_CERT_ADMIN = "证书管理员"
ROLE_VIEWER = "只读员"

# 证书管理员可执行的写操作，用来在被驳回时说明缺的是哪一项授权。
# 值是「动词 + 事项」，方便直接拼进“无权……”“跨单位……代办授权”。
WRITE_PERMISSIONS = {
    "review": "登记证书复审",
    "expire": "登记证书过期",
    "revoke": "注销证书",
    "transfer": "办理人员调动",
    "edit_cert": "变更证书类别与复审日期",
    "create": "登记作业人员证书",
}


@dataclass(frozen=True)
class Actor:
    """当前经办人：归属单位 + 岗位 + 跨单位代办授权。"""

    key: str
    name: str
    unit: str
    role: str
    delegated_units: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_CERT_ADMIN

    @property
    def is_viewer(self) -> bool:
        return self.role == ROLE_VIEWER

    def can_reach_unit(self, unit: str) -> bool:
        """该经办人是否有权操作某个单位：本单位，或持有该单位的代办授权。"""
        if not self.is_admin:
            return False
        if unit == self.unit:
            return True
        return unit in self.delegated_units

    def deny_reason(self, target_unit: str, permission: str) -> str:
        """生成当场驳回的可读说明，明确点出缺的是哪一项授权。"""
        action_label = WRITE_PERMISSIONS.get(permission, "执行该操作")
        if self.is_viewer:
            return (
                f"当前经办人「{self.name}」是只读岗，只能查看，无权{action_label}；"
                "请由该单位的证书管理员办理"
            )
        if target_unit == self.unit:
            # 同单位理论上进不来，兜底给一条岗位提示。
            return f"「{self.name}」不具备{action_label}权限"
        return (
            f"「{self.name}」归属{self.unit}，目标证件属于{target_unit}，"
            f"缺少{target_unit}出具的跨单位{action_label}代办授权，"
            "已当场驳回；如需代办，请先补该单位的书面授权再办理"
        )

    def require_unit_write(self, target_unit: str, permission: str) -> None:
        """写操作统一入口：无权直接抛 :class:`BusinessError`。"""
        from app.errors import BusinessError

        if self.can_reach_unit(target_unit):
            return
        raise BusinessError(self.deny_reason(target_unit, permission), status=403)
