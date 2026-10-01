"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.operator_seed import build_operator_rows
from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        # 作业人员要演示归属/复审流转，使用按当天动态生成的数据，覆盖脚手架里
        # 无差别的占位样例；其余模块沿用 seed 里的示例。
        tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}
        tables["operator"] = build_operator_rows()
        self._tables: dict[str, list[dict[str, Any]]] = tables

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            # 作业人员证书状态是 service 按复审结果/复审日期统一推导的，
            # 看板也必须走同一口径，不能回头去读已经不落库的 pending/abnormal，
            # 否则概览卡片会和人员台账、复审名单各说各话。
            if name == "operator":
                from app.services.operator import (
                    STATUS_EXPIRING,
                    STATUS_OVERDUE,
                    derive_status,
                )

                def is_pending(row: dict[str, Any]) -> bool:
                    return (not row.get("locked")) and derive_status(row) in (
                        STATUS_EXPIRING,
                        STATUS_OVERDUE,
                    )

                def is_abnormal(row: dict[str, Any]) -> bool:
                    return derive_status(row) in (STATUS_EXPIRING, STATUS_OVERDUE)
            else:
                def is_pending(row: dict[str, Any]) -> bool:
                    return bool(row.get("pending"))

                def is_abnormal(row: dict[str, Any]) -> bool:
                    return bool(row.get("abnormal"))

            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if is_pending(row)),
                "abnormal": sum(1 for row in rows if is_abnormal(row)),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
