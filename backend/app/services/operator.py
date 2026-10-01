"""作业人员业务规则：证书状态口径、复审流转、归属鉴权与经办留痕都收在这里。

状态口径只有一个来源：``certificate_status``。人员台账（list_entries）与
复审名单（review_roster）都调用它，杜绝两处各算一套。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store
from app.services.operator_auth import Actor, ensure_can_operate

MODULE = "operator"
GRANT_MODULE = "operator_grant"

REQUIRED_FIELDS = ["人员编号", "姓名", "证书类别", "证书编号", "发证日期", "所属单位"]
# 敏感字段：不允许走通用编辑直接改，复审日期只能由「登记复审结果」带出新日期，
# 证书类别变更需重新发证，同样不允许在本页直接改。
PROTECTED_FIELDS = ["证书类别", "复审日期", "证书状态", "所属单位"]

STATUS_VALID = "持证有效"
STATUS_DUE_SOON = "即将到期"
STATUS_OVERDUE = "逾期未复审"
STATUS_EXPIRED = "已过期"
STATUS_CANCELLED = "已注销"
DISPLAY_STATUSES = [STATUS_VALID, STATUS_DUE_SOON, STATUS_OVERDUE, STATUS_EXPIRED, STATUS_CANCELLED]
# 终态：登记为已过期/已注销的证件不得再排进下一期复审名单，也不允许再做动作。
TERMINAL_STATUSES = (STATUS_EXPIRED, STATUS_CANCELLED)

DUE_SOON_DAYS = 90

VALID_RESULTS = ("合格", "不合格")
RESULT_PASS = "合格"
RESULT_FAIL = "不合格"


def _today() -> date:
    return date.today()


def current_period(today: date | None = None) -> str:
    today = today or _today()
    return f"{today.year}Q{(today.month - 1) // 3 + 1}"


def certificate_status(row: dict[str, Any], today: date | None = None) -> str:
    """证书状态的唯一推导口径。

    - 复审结论为「不合格」登记过期，或人工登记过期：已过期（终态）
    - 注销证书：已注销（终态）
    - 复审日期已过但尚未登记结论：逾期未复审（仍须补办，不直接等于已过期）
    - 距复审日 90 天内：即将到期；其余：持证有效
    """
    today = today or _today()
    lifecycle = str(row.get("status") or "")
    if lifecycle == "已注销":
        return STATUS_CANCELLED

    records = row.get("复审记录") or []
    last_result = next(
        (
            rec.get("复审结果")
            for rec in reversed(records)
            if rec.get("动作") == "登记复审结果"
        ),
        None,
    )
    if last_result == RESULT_FAIL or row.get("终态原因") == "登记过期":
        return STATUS_EXPIRED

    review_date_text = str(row.get("复审日期") or "")
    review_date = _parse_date(review_date_text)
    if review_date is not None and review_date < today:
        return STATUS_OVERDUE
    if review_date is not None and (review_date - today).days <= DUE_SOON_DAYS:
        return STATUS_DUE_SOON
    return STATUS_VALID


def is_terminal(row: dict[str, Any]) -> bool:
    return certificate_status(row) in TERMINAL_STATUSES


def _parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_period(period: str) -> tuple[int, int] | None:
    """解析 2026Q4 形式的复审期。"""
    period = (period or "").strip().upper()
    if len(period) == 6 and period[4] == "Q" and period[:4].isdigit() and period[5] in "1234":
        return int(period[:4]), int(period[5])
    return None


def period_range(period: str) -> tuple[date, date] | None:
    parsed = _parse_period(period)
    if parsed is None:
        return None
    year, quarter = parsed
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    if quarter == 4:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, start_month + 3, 1)
    return start, end


def _grants() -> list[dict[str, Any]]:
    return store.rows(GRANT_MODULE)


def _audit(row: dict[str, Any], actor: Actor, action: str, details: dict[str, Any]) -> dict[str, Any]:
    record = {
        "动作": action,
        "经办人": actor.name,
        "经办单位": actor.unit,
        "经办时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    record.update({key: value for key, value in details.items() if value not in (None, "")})
    row.setdefault("复审记录", []).append(record)
    return record


def serialize(row: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """台账与名单共用的输出口径：状态一律现算，不读历史填的「证书状态」。"""
    today = today or _today()
    status = certificate_status(row, today)
    history = list(row.get("复审记录") or [])
    last_record = history[-1] if history else {}
    return {
        "id": row.get("id"),
        "人员编号": row.get("人员编号"),
        "姓名": row.get("姓名"),
        "证书类别": row.get("证书类别"),
        "证书编号": row.get("证书编号"),
        "发证日期": row.get("发证日期"),
        "复审日期": row.get("复审日期"),
        "所属单位": row.get("所属单位"),
        "证书状态": status,
        "复审期": row.get("复审期"),
        "终态": status in TERMINAL_STATUSES,
        "安排复审期": row.get("复审期"),
        "最近动作": last_record.get("动作"),
        "最近经办人": last_record.get("经办人"),
        "最近经办单位": last_record.get("经办单位"),
        "最近经办时间": last_record.get("经办时间"),
        "复审记录": history,
        "单位沿革": list(row.get("单位沿革") or []),
    }


class OperatorService:
    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        unit: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("人员编号", "")) or keyword in str(row.get("姓名", ""))
            ]
        if unit:
            rows = [row for row in rows if row.get("所属单位") == unit]
        if status:
            rows = [row for row in rows if certificate_status(row) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return serialize(row) if row is not None else None

    def review_roster(
        self,
        *,
        period: str | None = None,
        unit: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """某一期复审名单。

        入期条件（满足其一，且非终态）：已安排到本期、复审日期落在本期、
        逾期未复审须并入本期补办。已过期/已注销一律不进名单。
        """
        period = period or current_period()
        if _parse_period(period) is None:
            return [], period
        bounds = period_range(period)
        assert bounds is not None
        start, end = bounds
        today = _today()

        items: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            status = certificate_status(row, today)
            if status in TERMINAL_STATUSES:
                continue
            if unit and row.get("所属单位") != unit:
                continue
            review_date = _parse_date(str(row.get("复审日期") or ""))
            scheduled = str(row.get("复审期") or "").upper() == period.upper()
            in_date = review_date is not None and start <= review_date < end
            overdue = status == STATUS_OVERDUE
            if scheduled or in_date or overdue:
                view = serialize(row, today)
                view["入期原因"] = (
                    "已安排本期" if scheduled else "逾期补办" if overdue else "复审日期在本期"
                )
                items.append(view)
        items.sort(key=lambda item: (str(item.get("复审日期") or "9999"), int(item.get("id") or 0)))
        return items, period

    def list_units(self) -> list[str]:
        units = sorted({str(row.get("所属单位") or "") for row in store.rows(MODULE)})
        return [unit for unit in units if unit]

    def list_grants(self) -> list[dict[str, Any]]:
        return [dict(grant) for grant in _grants()]

    # ---------- 写入：登记 / 编辑 ----------

    def create_entry(
        self, values: dict[str, Any], actor: Actor
    ) -> tuple[dict[str, Any] | None, str | None]:
        if actor.is_viewer:
            return None, "只读岗仅可查看，作业人员登记须由证书管理员办理"
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        unit = str(values.get("所属单位") or "").strip()
        # 新登记同样按归属卡：只许登记本单位人员，代办登记要求复审登记事项授权。
        reason = ensure_can_operate(
            actor,
            owner_unit=unit,
            action="安排复审",
            grants=_grants(),
        )
        if reason is not None:
            # ensure_can_operate 的文案围绕“动作”命名，这里改写为登记语境。
            return None, reason.replace("跨单位代办被驳回：", "跨单位登记被驳回：").replace(
                "本次「安排复审」", "本次「新人员登记」"
            )

        rows = store.rows(MODULE)
        code = str(values.get("人员编号") or "").strip()
        if any(row.get("人员编号") == code for row in rows):
            return None, f"人员编号「{code}」已存在，请勿重复登记"

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": "在册",
            "pending": True,
            "abnormal": False,
            "复审期": None,
            "终态": False,
            "复审记录": [],
            "单位沿革": [],
        }
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry["单位沿革"].append(
            {"单位": unit, "起": str(values.get("发证日期") or "").strip(),
             "经办人": actor.name, "经办单位": actor.unit, "经办时间": stamp}
        )
        rows.append(entry)
        return serialize(entry), None

    def update_entry(
        self, entry_id: int, values: dict[str, Any], actor: Actor
    ) -> tuple[dict[str, Any] | None, str | None]:
        """通用资料编辑：证书类别、复审日期、证书状态、所属单位一律不允许在此直接改。"""
        if actor.is_viewer:
            return None, "只读岗仅可查看，证书资料修改须由证书管理员办理"
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"作业人员 {entry_id} 不存在或已归档"

        owner_unit = str(row.get("所属单位") or "")
        reason = ensure_can_operate(
            actor,
            owner_unit=owner_unit,
            # 资料编辑沿用复审登记的归属口径：本单位管理员或持复审事项授权者可改。
            action="安排复审",
            grants=_grants(),
        )
        if reason is not None:
            return None, reason

        touched = [field for field in PROTECTED_FIELDS if field in values and str(values[field] or "").strip()]
        if touched:
            return None, (
                f"字段「{'、'.join(touched)}」不允许直接修改：复审日期请走「登记复审结果」，"
                "证书类别变更须重新发证，所属单位变更请走「人员调动」"
            )

        editable = ["姓名", "证书编号", "发证日期"]
        changed: list[str] = []
        for field in editable:
            if field in values and str(values[field] or "").strip():
                new_value = str(values[field]).strip()
                if row.get(field) != new_value:
                    row[field] = new_value
                    changed.append(field)
        if not changed:
            return None, "没有可更新的资料字段（仅姓名、证书编号、发证日期可在此修改）"
        _audit(row, actor, "资料修改", {"修改字段": "、".join(changed)})
        return serialize(row), None

    # ---------- 写入：状态流转 ----------

    def run_action(
        self,
        entry_id: int,
        action: str,
        actor: Actor,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        values = values or {}
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"作业人员 {entry_id} 不存在或已归档"

        owner_unit = str(row.get("所属单位") or "")
        reason = ensure_can_operate(
            actor, owner_unit=owner_unit, action=action, grants=_grants()
        )
        if reason is not None:
            return None, reason

        handler = {
            "安排复审": self._schedule_review,
            "登记复审结果": self._register_result,
            "登记过期": self._register_expired,
            "注销证书": self._cancel,
            "人员调动": self._transfer,
        }.get(action)
        if handler is None:
            return None, f"动作「{action}」不属于作业人员可执行范围"

        message = handler(row, actor, values)
        if message is not None:
            return None, message
        success_message = row.pop("_last_message", None) or f"已{action}"
        return serialize(row), success_message

    def _schedule_review(self, row: dict[str, Any], actor: Actor, values: dict[str, Any]) -> str | None:
        if is_terminal(row):
            return (
                f"证件已处于「{certificate_status(row)}」终态，"
                "不允许再排进下一期复审名单"
            )
        period = str(values.get("复审期") or current_period()).strip().upper()
        if _parse_period(period) is None:
            return f"复审期格式不正确：{period}，应为 2026Q4 这样的年份加季度"
        row["复审期"] = period
        row["status"] = "已安排复审"
        row["pending"] = True
        row["abnormal"] = False
        _audit(row, actor, "安排复审", {"复审期": period, "备注": values.get("备注")})
        return None

    def _register_result(self, row: dict[str, Any], actor: Actor, values: dict[str, Any]) -> str | None:
        if is_terminal(row):
            return f"证件已处于「{certificate_status(row)}」终态，复审结果不再受理"
        result = str(values.get("复审结果") or "").strip()
        if result not in VALID_RESULTS:
            return f"复审结果须为「{RESULT_PASS}」或「{RESULT_FAIL}」，收到的是：{result or '空'}"
        review_date_text = str(values.get("复审日期") or "").strip()
        review_date = _parse_date(review_date_text)
        if review_date is None:
            return "复审日期缺失或格式不正确，应为 2026-10-01 这样的日期"

        details: dict[str, Any] = {"复审日期": review_date_text, "复审结果": result}
        if result == RESULT_PASS:
            next_date_text = str(values.get("新复审日期") or "").strip()
            next_date = _parse_date(next_date_text)
            if next_date is None:
                return "复审合格时必须填写下一次复审日期"
            if next_date <= review_date:
                return "新复审日期必须晚于本次复审日期"
            row["复审日期"] = next_date_text
            row["复审期"] = None
            row["status"] = "在册"
            row["终态"] = False
            row["终态原因"] = None
            row["pending"] = True
            row["abnormal"] = False
            details["新复审日期"] = next_date_text
            message = f"复审合格，证书状态为「{STATUS_VALID}」，下期复审日期 {next_date_text}"
        else:
            # 不合格即按复审结果落定为已过期，终态锁定，不再进入下一期名单。
            row["复审日期"] = review_date_text
            row["复审期"] = None
            row["status"] = "在册"
            row["终态"] = True
            row["终态原因"] = "复审不合格"
            row["pending"] = False
            row["abnormal"] = True
            message = f"复审不合格，证书状态已落定为「{STATUS_EXPIRED}」，不再排入复审名单"
        details["备注"] = values.get("备注")
        _audit(row, actor, "登记复审结果", details)
        # 通过返回值带消息：借用调用方拼 ok 文案的能力——见 run_action 外层。
        row["_last_message"] = message
        return None

    def _register_expired(self, row: dict[str, Any], actor: Actor, values: dict[str, Any]) -> str | None:
        if is_terminal(row):
            return f"证件已处于「{certificate_status(row)}」终态，不能重复登记过期"
        current = certificate_status(row)
        if current != STATUS_OVERDUE:
            return f"当前状态为「{current}」，只有逾期未复审且确认不再补办的证件才能登记过期"
        expired_date = str(values.get("复审日期") or _today().isoformat()).strip()
        if _parse_date(expired_date) is None:
            return "登记过期的日期格式不正确，应为 2026-10-01 这样的日期"
        row["复审期"] = None
        row["status"] = "在册"
        row["终态"] = True
        row["终态原因"] = "登记过期"
        row["pending"] = False
        row["abnormal"] = True
        _audit(row, actor, "登记过期", {"复审日期": expired_date, "备注": values.get("备注")})
        row["_last_message"] = f"已登记过期，证书状态落定为「{STATUS_EXPIRED}」，不再排入复审名单"
        return None

    def _cancel(self, row: dict[str, Any], actor: Actor, values: dict[str, Any]) -> str | None:
        current = certificate_status(row)
        if current == STATUS_CANCELLED:
            return "证书已注销，不能重复注销"
        row["复审期"] = None
        row["status"] = "已注销"
        row["终态"] = True
        row["终态原因"] = "证书注销"
        row["pending"] = False
        row["abnormal"] = False
        _audit(row, actor, "注销证书", {"备注": values.get("备注")})
        row["_last_message"] = f"证书已注销，状态落定为「{STATUS_CANCELLED}」"
        return None

    def _transfer(self, row: dict[str, Any], actor: Actor, values: dict[str, Any]) -> str | None:
        new_unit = str(values.get("新单位") or "").strip()
        if not new_unit:
            return "人员调动必须填写调入单位"
        old_unit = str(row.get("所属单位") or "")
        if new_unit == old_unit:
            return "调入单位与现所属单位相同，无需调动"
        transfer_date = str(values.get("调动日期") or _today().isoformat()).strip()
        if _parse_date(transfer_date) is None:
            return "调动日期格式不正确，应为 2026-10-01 这样的日期"

        history = row.setdefault("单位沿革", [])
        history[-1]["止"] = transfer_date
        history.append(
            {
                "单位": new_unit,
                "起": transfer_date,
                "经办人": actor.name,
                "经办单位": actor.unit,
                "经办时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "备注": f"由 {old_unit} 调入；归属变更后复审记录仍可追溯",
            }
        )
        row["所属单位"] = new_unit
        row["复审期"] = None  # 到新单位后重新排期，旧排期不自动带过去
        _audit(
            row,
            actor,
            "人员调动",
            {"原单位": old_unit, "新单位": new_unit, "调动日期": transfer_date,
             "备注": values.get("备注")},
        )
        row["_last_message"] = (
            f"人员已调入 {new_unit}；{old_unit} 经办的历次复审记录保留可查"
        )
        return None

    def last_message(self, entry_id: int) -> str | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        message = row.pop("_last_message", None)
        return message
