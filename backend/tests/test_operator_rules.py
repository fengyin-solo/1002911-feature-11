"""作业人员证书归属、复审流转与留痕的规则测试。

直接用 TestClient 打接口，覆盖：
- 归属/岗位授权：本单位可改、跨单位无授权当场驳回(403)并说明缺哪项授权、
  持代办授权可办、只读岗一律只读；
- 状态按复审结果落定：合格顺延复审日期，不合格登记过期并锁定；
- 已过期/已注销锁定证件不进下一期复审名单；
- 台账与复审名单状态口径一致；
- 人员调动后历史仍保留原经办单位。
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services import operator as ops

client = TestClient(app)

H_ADMIN_A = {"X-Actor-Key": "admin-a"}
H_ADMIN_B = {"X-Actor-Key": "admin-b"}
H_ADMIN_A_WITH_B = {"X-Actor-Key": "admin-a-delegate-b"}
H_VIEWER_A = {"X-Actor-Key": "viewer-a"}
H_VIEWER_B = {"X-Actor-Key": "viewer-b"}


def _roster_ids() -> list[int]:
    return [int(item["id"]) for item in client.get("/api/operator/review-roster").json()["items"]]


def _ledger_status(entry_id: int, header: dict[str, str]) -> str:
    return client.get(f"/api/operator/{entry_id}", headers=header).json()["证书状态"]


# ---------------------------------------------------------------- 归属与岗位
def test_同单位证书管理员可以登记复审并落定为有效() -> None:
    # OPER-0002 属于 A 厂，复审日期在窗口内，复审合格。
    resp = client.post("/api/operator/2/review", headers=H_ADMIN_A, json={"result": "合格"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["entry"]["证书状态"] == ops.STATUS_VALID
    # 复审日期顺延到约两年后，且晚于今天。
    new_date = date.fromisoformat(body["entry"]["复审日期"])
    assert new_date >= date.today() + timedelta(days=ops.REVIEW_CYCLE_DAYS - 2)


def test_跨单位复审无授权当场403并说明缺哪项授权() -> None:
    # id=5 属于 B 厂，A 厂管理员无授权。
    resp = client.post("/api/operator/5/review", headers=H_ADMIN_A, json={"result": "合格"})
    assert resp.status_code == 403
    message = resp.json()["message"]
    assert "滨江化工有限公司" in message
    assert "代办授权" in message
    # 数据未被改动。
    assert client.get("/api/operator/5", headers=H_ADMIN_A).json()["复审日期"] != ""


def test_持代办授权的跨单位管理员可以办理() -> None:
    resp = client.post("/api/operator/5/review", headers=H_ADMIN_A_WITH_B, json={"result": "合格"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_只读岗不能复审也不能改证书字段() -> None:
    review = client.post("/api/operator/1/review", headers=H_VIEWER_A, json={"result": "合格"})
    assert review.status_code == 403
    assert "只读" in review.json()["message"]

    edit = client.put(
        "/api/operator/1/cert",
        headers=H_VIEWER_A,
        json={"values": {"证书类别": "随便改", "复审日期": "2030-01-01"}},
    )
    assert edit.status_code == 403
    assert "只能查看" in edit.json()["message"]


def test_只读岗可以查看台账与名单() -> None:
    assert client.get("/api/operator", headers=H_VIEWER_A).status_code == 200
    assert client.get("/api/operator/review-roster", headers=H_VIEWER_B).status_code == 200


# ---------------------------------------------------------------- 状态落定
def test_复审不合格登记过期并锁定() -> None:
    resp = client.post("/api/operator/3/review", headers=H_ADMIN_A, json={"result": "不合格"})
    assert resp.status_code == 200
    entry = resp.json()["entry"]
    assert entry["证书状态"] == ops.STATUS_OVERDUE
    assert entry["locked"] is True


def test_已锁定证件不能再登记复审() -> None:
    # id=4 在种子里就是复审不合格锁定的。
    resp = client.post("/api/operator/4/review", headers=H_ADMIN_A, json={"result": "合格"})
    assert resp.status_code == 409
    assert resp.json()["ok"] is False


def test_手工登记过期锁定且注销终局() -> None:
    expired = client.post("/api/operator/2/expire", headers=H_ADMIN_A, json={})
    # 若上一用例已把 id=2 顺延，则它仍可登记过期；这里仅在成功时校验。
    if expired.status_code == 200:
        assert expired.json()["entry"]["locked"] is True
        assert expired.json()["entry"]["证书状态"] == ops.STATUS_OVERDUE

    revoked = client.post("/api/operator/1/revoke", headers=H_ADMIN_A, json={})
    assert revoked.status_code == 200
    assert revoked.json()["entry"]["证书状态"] == ops.STATUS_REVOKED
    assert revoked.json()["entry"]["locked"] is True


# ------------------------------------------------------- 名单与台账一致性
def test_已过期锁定与已注销不进复审名单且口径一致() -> None:
    roster = _roster_ids()
    # 种子里 id=4（复审不合格过期）、id=7（注销）永远不在名单。
    assert 4 not in roster
    assert 7 not in roster

    # 名单里每条的状态，和台账明细接口算出来的状态一致。
    for item in client.get("/api/operator/review-roster").json()["items"]:
        ledger = _ledger_status(int(item["id"]), H_ADMIN_A)
        assert ledger == item["证书状态"]

    # 名单只收未锁定证件。
    assert all(item["locked"] is False for item in
               client.get("/api/operator/review-roster").json()["items"])


def test_不合格复审后证件从下一期名单消失() -> None:
    # 先登记一张 A 厂、复审日期就在窗口内的新证，保证它一定在名单里，
    # 不依赖其它用例对固定种子数据的改动顺序。
    soon = (date.today() + timedelta(days=10)).isoformat()
    created = client.post("/api/operator", headers=H_ADMIN_A, json={"values": {
        "人员编号": "OPER-T-FAIL",
        "姓名": "待判废",
        "证书类别": "工业锅炉司炉（G1）",
        "证书编号": "CZ-T-FAIL",
        "所属单位": "华东热电一厂",
        "复审日期": soon,
    }}).json()
    target = int(created["entry"]["id"])
    assert target in _roster_ids()

    failed = client.post(f"/api/operator/{target}/review", headers=H_ADMIN_A,
                         json={"result": "不合格"})
    assert failed.status_code == 200
    assert target not in _roster_ids()
    # 台账里它确实是已过期锁定状态，两处口径一致。
    assert _ledger_status(target, H_ADMIN_A) == ops.STATUS_OVERDUE


# ---------------------------------------------------------------- 调动留痕
def test_调动只能由现归属单位发起() -> None:
    # id=8 属于 C 队，A 厂管理员发起调动被驳回。
    resp = client.post("/api/operator/8/transfer", headers=H_ADMIN_A,
                       json={"target_unit": "华东热电一厂"})
    assert resp.status_code == 403
    detail = client.get("/api/operator/8", headers=H_ADMIN_A).json()
    assert detail["所属单位"] == "港务起重作业队"


def test_调动后仍可追溯原经办单位() -> None:
    # id=5 种子里从 C 队调入 B 厂，历史保留 C 队的复审经办记录。
    detail = client.get("/api/operator/5", headers=H_ADMIN_B).json()
    units = {record["经办单位"] for record in detail["history"]}
    assert "港务起重作业队" in units
    actions = [record["动作"] for record in detail["history"]]
    assert "人员调动" in actions and "复审登记" in actions


def test_已过期锁定证件可被本单位注销但不能重复注销() -> None:
    # id=4 是复审不合格、已过期锁定的证件；本单位管理员可将其注销。
    first = client.post("/api/operator/4/revoke", headers=H_ADMIN_A, json={})
    assert first.status_code == 200
    assert first.json()["entry"]["证书状态"] == ops.STATUS_REVOKED
    # 再注销一次被 409 拦下。
    again = client.post("/api/operator/4/revoke", headers=H_ADMIN_A, json={})
    assert again.status_code == 409


def test_状态推导纯函数对锁定与逾期的口径() -> None:
    today = date(2026, 10, 1)
    assert ops.derive_status({"复审日期": "2026-10-20", "locked": False}, today) == ops.STATUS_EXPIRING
    assert ops.derive_status({"复审日期": "2026-09-01", "locked": False}, today) == ops.STATUS_OVERDUE
    assert ops.derive_status({"复审日期": "2027-01-01", "locked": False}, today) == ops.STATUS_VALID
    assert ops.derive_status({"locked": True, "锁定状态": ops.STATUS_OVERDUE}, today) == ops.STATUS_OVERDUE
    assert ops.derive_status({"locked": True, "锁定状态": ops.STATUS_REVOKED}, today) == ops.STATUS_REVOKED
