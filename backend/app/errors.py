"""统一的业务异常：状态流转与归属授权都在 service 层判定，

命中不允许的操作时抛出 :class:`BusinessError`，由路由层翻译成
``{ok: false, message}`` 的标准动作响应，而不是让接口抛 500。
"""
from __future__ import annotations


class BusinessError(Exception):
    """业务规则被违反。``status`` 用来区分读不到（404）与被驳回（403/409）。"""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
