"""作业人员（证书）业务规则。

这里是证书状态唯一的判定与落定位置：
- 人员台账与复审名单共用同一份数据和同一个 :func:`derive_status`，
  杜绝两处各说各话；
- 证书状态按复审结果落定：复审合格回到「持证有效」并顺延复审日期，
  复审不合格登记为「已过期」并锁定，注销锁定为「已注销」；
- 写操作（复审登记、登记过期、注销、调动、改证书）一律先过归属与岗位校验：
  只有本单位证书管理员能动，跨单位代办缺授权当场驳回并说明缺哪项授权，
  只读岗只能查看；
- 每一次写操作都留经手人、经办时点单位与动作，人员调动后历史仍可追溯；
- 已锁定（过期/注销）的证件不再排进下一期复审名单。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.actors import Actor
from app.errors import BusinessError
from app.store import store

MODULE = "operator"

# 台账展示列与可检索字段。
LIST_FIELDS = ["人员编号", "姓名", "证书类别", "证书编号", "发证日期", "复审日期", "所属单位"]
REQUIRED_FIELDS = ["人员编号", "姓名", "证书类别", "证书编号", "所属单位"]

# 证书状态（终局状态会被锁定，不再排复审）。
STATUS_VALID = "持证有效"
STATUS_EXPIRING = "即将到期"
STATUS_OVERDUE = "已过期"
STATUS_REVOKED = "已注销"
OPEN_STATUSES = (STATUS_VALID, STATUS_EXPIRING, STATUS_OVERDUE)
TERMINAL_STATUSES = (STATUS_OVERDUE, STATUS_REVOKED)

# 距复审日期多少天内算「即将到期」。
EXPIRING_WINDOW_DAYS = 30
# 复审合格后复审日期顺延的周期。
REVIEW_CYCLE_DAYS = 365 * 2

# 复审结果。
RESULT_PASS = "合格"
RESULT_FAIL = "不合格"

# 证书类别与复审日期属于受控字段：只读岗、越权代办都不允许改。
PROTECTED_CERT_FIELDS = ("证书类别", "复审日期")

ACTION_REVIEW = "复审登记"
ACTION_EXPIRE = "登记过期"
ACTION_REVOKE = "注销证书"
ACTION_TRANSFER = "人员调动"
ACTION_EDIT = "变更证书"
ACTION_CREATE = "登记证书"

# 前端按 key 触发动作，这里给出中文名用于历史与提示。
PERMISSION_BY_ACTION = {
    ACTION_REVIEW: "review",
    ACTION_EXPIRE: "expire",
    ACTION_REVOKE: "revoke",
    ACTION_TRANSFER: "transfer",
    ACTION_EDIT: "edit_cert",
    ACTION_CREATE: "create",
}


def _today() -> date:
    # 单独包一层，测试时可以 monkeypatch services.operator._today。
    return date.today()


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise BusinessError(f"日期「{text}」格式应为 YYYY-MM-DD") from exc


def _add_history(
    row: dict[str, Any],
    actor: Actor,
    *,
    action: str,
    result: str,
    remark: str = "",
    unit: str | None = None,
) -> None:
    """追加一条经办记录。``unit`` 记录经办时点单位，调动后也不被改写。"""
    row.setdefault("history", []).append({
        "动作": action,
        "结果": result,
        "经办人": actor.name,
        "经办单位": unit or actor.unit,
        "经办日期": _today().isoformat(),
        "备注": remark,
    })


def derive_status(row: dict[str, Any], today: date | None = None) -> str:
    """证书状态的唯一推导口径，台账与复审名单都调它。

    锁定（已按复审不合格登记过期 / 已注销）以显式的 ``锁定状态`` 为准，
    复审日期不再参与；未锁定的按复审日期推导：逾期→已过期(待复审)，
    窗口内→即将到期，否则有效。
    """
    today = today or _today()
    if row.get("locked"):
        return str(row.get("锁定状态") or STATUS_OVERDUE)
    review = _parse_date(row.get("复审日期"))
    if review is None:
        return STATUS_VALID
    delta = (review - today).days
    if delta < 0:
        return STATUS_OVERDUE
    if delta <= EXPIRING_WINDOW_DAYS:
        return STATUS_EXPIRING
    return STATUS_VALID


def _is_locked(row: dict[str, Any]) -> bool:
    return bool(row.get("locked"))


def _capabilities(row: dict[str, Any], actor: Actor) -> dict[str, Any]:
    """算出当前经办人对这条证件可执行的动作及被驳回原因，供前端按归属置灰。"""
    unit = str(row.get("所属单位") or "")
    reachable = actor.can_reach_unit(unit)
    locked = _is_locked(row)

    def perm(action: str) -> dict[str, Any]:
        permission = PERMISSION_BY_ACTION[action]
        allowed = False
        reasons: list[str] = []
        if actor.is_viewer or not reachable:
            reasons.append(actor.deny_reason(unit, permission))
        elif action == ACTION_REVOKE and derive_status(row) == STATUS_REVOKED:
            reasons.append("该证书已注销，无需重复注销")
        elif action in (ACTION_REVIEW, ACTION_EXPIRE, ACTION_EDIT) and locked:
            reasons.append("证件已终局锁定，不能再复审或改证书信息")
        else:
            allowed = True
        return {"allowed": allowed, "reason": "；".join(reasons)}

    return {
        "reviewable": perm(ACTION_REVIEW)["allowed"],
        "expirable": perm(ACTION_EXPIRE)["allowed"],
        "revocable": perm(ACTION_REVOKE)["allowed"],
        "transferable": perm(ACTION_TRANSFER)["allowed"],
        "editable": perm(ACTION_EDIT)["allowed"],
        # 逐条给出驳回理由，前端在悬浮/点击时能当场说明缺哪项授权。
        "denyReasons": {action: perm(action)["reason"] for action in PERMISSION_BY_ACTION
                        if action != ACTION_CREATE},
    }


def _serialize(row: dict[str, Any], actor: Actor | None) -> dict[str, Any]:
    """台账/名单统一的对外结构：状态实时推导，历史单位原样带出。"""
    item = dict(row)
    item["证书状态"] = derive_status(row)
    # 兼容脚手架里通用看板用到的 status/pending/abnormal 字段，口径同样收敛到这里。
    item["status"] = item["证书状态"]
    item["pending"] = item["证书状态"] in (STATUS_VALID, STATUS_EXPIRING, STATUS_OVERDUE) and not _is_locked(row)
    item["abnormal"] = item["证书状态"] in (STATUS_EXPIRING, STATUS_OVERDUE)
    item["locked"] = _is_locked(row)
    if actor is not None:
        item["permissions"] = _capabilities(row, actor)
    return item


class OperatorService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        actor: Actor,
        *,
        keyword: str | None = None,
        unit: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("人员编号", ""))
                    or keyword in str(r.get("姓名", ""))
                    or keyword in str(r.get("证书编号", ""))]
        if unit:
            rows = [r for r in rows if str(r.get("所属单位") or "") == unit]
        if status:
            rows = [r for r in rows if derive_status(r) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_serialize(r, actor) for r in rows[start:start + size]], total

    def review_roster(self, actor: Actor, *, unit: str | None = None) -> list[dict[str, Any]]:
        """下一期复审名单：只收未锁定、且复审日期已到/临近的证件。

        已按复审结果登记为过期、以及已注销的证件被锁定，永不入列；
        其余证件按复审日期升序，越临近（或已逾期）越靠前。
        """
        rows = store.rows(MODULE)
        if unit:
            rows = [r for r in rows if str(r.get("所属单位") or "") == unit]
        candidates = [r for r in rows if not _is_locked(r)]

        def sort_key(row: dict[str, Any]) -> date:
            parsed = _parse_date(row.get("复审日期"))
            return parsed or date.max

        candidates.sort(key=sort_key)
        result = []
        for row in candidates:
            status = derive_status(row)
            if status in (STATUS_EXPIRING, STATUS_OVERDUE):
                item = _serialize(row, actor)
                result.append(item)
        return result

    def get_entry(self, entry_id: int, actor: Actor) -> dict[str, Any]:
        row = self._require_row(entry_id)
        item = _serialize(row, actor)
        item["history"] = list(row.get("history", []))
        return item

    # ---------- 写操作 ----------
    def create_entry(self, actor: Actor, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        unit = str(values.get("所属单位") or "").strip()
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        # 归属校验：只有该单位的证书管理员能登记新证。
        actor.require_unit_write(unit, PERMISSION_BY_ACTION[ACTION_CREATE])
        review = _parse_date(values.get("复审日期"))
        issue = _parse_date(values.get("发证日期"))
        rows = store.rows(MODULE)
        row: dict[str, Any] = {"id": max((int(r.get("id", 0)) for r in rows), default=0) + 1}
        row.update({f: str(values.get(f)).strip() for f in REQUIRED_FIELDS})
        row["发证日期"] = issue.isoformat() if issue else _today().isoformat()
        row["复审日期"] = review.isoformat() if review else (
            _today() + timedelta(days=REVIEW_CYCLE_DAYS)
        ).isoformat()
        row["locked"] = False
        row["history"] = []
        _add_history(row, actor, action=ACTION_CREATE, result="新建登记",
                     remark="登记作业人员证书", unit=unit)
        rows.append(row)
        return _serialize(row, actor), []

    def register_review(
        self,
        entry_id: int,
        actor: Actor,
        *,
        result: str,
        next_review_date: str | None = None,
        remark: str = "",
    ) -> dict[str, Any]:
        """登记一次复审：状态按复审结果落定。"""
        row = self._require_row(entry_id)
        actor.require_unit_write(str(row.get("所属单位") or ""), PERMISSION_BY_ACTION[ACTION_REVIEW])
        if _is_locked(row):
            raise BusinessError("该证件已终局锁定（已过期/已注销），不能再登记复审", status=409)
        if result not in (RESULT_PASS, RESULT_FAIL):
            raise BusinessError(f"复审结果只能是「{RESULT_PASS}」或「{RESULT_FAIL}」")

        if result == RESULT_PASS:
            next_date = _parse_date(next_review_date)
            if next_date is None:
                next_date = _today() + timedelta(days=REVIEW_CYCLE_DAYS)
            if next_date <= _today():
                raise BusinessError("复审合格后，下一次复审日期必须晚于今天")
            row["复审日期"] = next_date.isoformat()
            row["locked"] = False
            row.pop("锁定状态", None)
            row.pop("锁定原因", None)
            note = f"复审合格，下次复审日期 {row['复审日期']}"
        else:
            # 不合格 → 当场登记为已过期并锁定，不再排进下一期复审名单。
            row["复审日期"] = _today().isoformat()
            row["locked"] = True
            row["锁定状态"] = STATUS_OVERDUE
            row["锁定原因"] = "复审不合格，登记为已过期"
            note = "复审不合格，证件登记为已过期并锁定"

        _add_history(row, actor, action=ACTION_REVIEW, result=result,
                     remark=remark or note, unit=str(row.get("所属单位") or ""))
        return _serialize(row, actor)

    def register_expired(self, entry_id: int, actor: Actor, *, remark: str = "") -> dict[str, Any]:
        """手工登记过期：证件终局落定为已过期并锁定。"""
        row = self._require_row(entry_id)
        actor.require_unit_write(str(row.get("所属单位") or ""), PERMISSION_BY_ACTION[ACTION_EXPIRE])
        if _is_locked(row):
            raise BusinessError("该证件已是终局状态，无需重复登记过期", status=409)
        row["locked"] = True
        row["锁定状态"] = STATUS_OVERDUE
        row["锁定原因"] = "手工登记为已过期"
        _add_history(row, actor, action=ACTION_EXPIRE, result=STATUS_OVERDUE,
                     remark=remark or "持证未按期复审，登记为已过期并锁定",
                     unit=str(row.get("所属单位") or ""))
        return _serialize(row, actor)

    def revoke(self, entry_id: int, actor: Actor, *, remark: str = "") -> dict[str, Any]:
        """注销证书：终局落定为已注销并锁定。"""
        row = self._require_row(entry_id)
        actor.require_unit_write(str(row.get("所属单位") or ""), PERMISSION_BY_ACTION[ACTION_REVOKE])
        if derive_status(row) == STATUS_REVOKED:
            raise BusinessError("该证书已注销，无需重复注销", status=409)
        row["locked"] = True
        row["锁定状态"] = STATUS_REVOKED
        row["锁定原因"] = "证书已注销"
        _add_history(row, actor, action=ACTION_REVOKE, result=STATUS_REVOKED,
                     remark=remark or "证书注销，停止使用",
                     unit=str(row.get("所属单位") or ""))
        return _serialize(row, actor)

    def transfer(self, entry_id: int, actor: Actor, *, target_unit: str, remark: str = "") -> dict[str, Any]:
        """人员调动：变更归属单位；历史保留原经办单位，调动本身也留痕。"""
        row = self._require_row(entry_id)
        old_unit = str(row.get("所属单位") or "")
        new_unit = (target_unit or "").strip()
        if not new_unit:
            raise BusinessError("请填写调入单位")
        if new_unit == old_unit:
            raise BusinessError("调入单位与现归属单位相同，无需调动")
        # 调动必须由现归属单位的证书管理员发起；调入方或无授权的他单位不能代办。
        actor.require_unit_write(old_unit, PERMISSION_BY_ACTION[ACTION_TRANSFER])
        row["所属单位"] = new_unit
        _add_history(row, actor, action=ACTION_TRANSFER, result=f"{old_unit} → {new_unit}",
                     remark=remark or f"由{old_unit}调入{new_unit}", unit=old_unit)
        return _serialize(row, actor)

    def update_cert_fields(
        self,
        entry_id: int,
        actor: Actor,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """修改证书信息：证书类别、复审日期属受控字段，按归属与岗位卡控。"""
        row = self._require_row(entry_id)
        actor.require_unit_write(str(row.get("所属单位") or ""), PERMISSION_BY_ACTION[ACTION_EDIT])
        if _is_locked(row):
            raise BusinessError("证件已终局锁定，证书类别与复审日期不能再修改", status=409)
        changes: list[str] = []
        if "证书类别" in values and str(values["证书类别"]).strip():
            new_cat = str(values["证书类别"]).strip()
            if new_cat != str(row.get("证书类别") or ""):
                changes.append(f"证书类别：{row.get('证书类别')} → {new_cat}")
                row["证书类别"] = new_cat
        if "复审日期" in values and str(values["复审日期"]).strip():
            new_date = _parse_date(values["复审日期"])
            assert new_date is not None
            if new_date.isoformat() != str(row.get("复审日期") or ""):
                changes.append(f"复审日期：{row.get('复审日期')} → {new_date.isoformat()}")
                row["复审日期"] = new_date.isoformat()
        if not changes:
            raise BusinessError("没有可更新的证书类别或复审日期")
        _add_history(row, actor, action=ACTION_EDIT, result="已变更",
                     remark="；".join(changes), unit=str(row.get("所属单位") or ""))
        return _serialize(row, actor)

    # ---------- 内部 ----------
    def _require_row(self, entry_id: int) -> dict[str, Any]:
        row = store.find(MODULE, entry_id)
        if row is None:
            raise BusinessError(f"作业人员 {entry_id} 不存在或已归档", status=404)
        return row
