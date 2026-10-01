"""作业人员模块的示例数据。

其余模块的 seed 是脚手架里无差别的占位样例；作业人员要演示归属、复审流转与
跨单位驳回，日期必须相对「今天」动态生成，否则过一段时间所有示例都会滑到
过期/即将到期之外。这里统一按当天回推/顺推出不同状态的证书，并给出
归属三家单位、分属不同证书类别的作业人员。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.actor_registry import UNIT_A, UNIT_B, UNIT_C

# 与 services/operator.py 里的状态常量保持一致；seed 不反向依赖 service，
# 否则会和 store 形成循环导入。
STATUS_OVERDUE = "已过期"
STATUS_REVOKED = "已注销"


def _iso(d: date) -> str:
    return d.isoformat()


def build_operator_rows(today: date | None = None) -> list[dict[str, Any]]:
    """生成一组覆盖各状态、各单位的作业人员证书记录。

    状态本身不写死，service 层会依据复审日期与锁定标记统一推导；这里只给
    原始事实（发证/复审日期、所属单位、锁定情况）和复审历史。
    """
    today = today or date.today()

    def days(off: int) -> str:
        return _iso(today + timedelta(days=off))

    # 字段含义见 services/operator.py：locked=True 表示证书已按复审结果/
    # 注销结论终局落定，不再排进下一期复审名单。
    raw: list[dict[str, Any]] = [
        {
            "人员编号": "OPER-0001",
            "姓名": "陈大锤",
            "证书类别": "工业锅炉司炉（G1）",
            "证书编号": "CZ-G1-2021001",
            "发证日期": days(-1100),
            "复审日期": days(20),
            "所属单位": UNIT_A,
            "locked": False,
        },
        {
            "人员编号": "OPER-0002",
            "姓名": "林稳压",
            "证书类别": "快开门式压力容器操作（R1）",
            "证书编号": "CZ-R1-2021002",
            "发证日期": days(-1300),
            "复审日期": days(9),
            "所属单位": UNIT_A,
            "locked": False,
        },
        {
            "人员编号": "OPER-0003",
            "姓名": "高起重",
            "证书类别": "起重机械指挥（Q1）",
            "证书编号": "CZ-Q1-2019003",
            "发证日期": days(-1900),
            "复审日期": days(-25),
            "所属单位": UNIT_A,
            "locked": False,
        },
        {
            "人员编号": "OPER-0004",
            "姓名": "封过期",
            "证书类别": "叉车司机（N1）",
            "证书编号": "CZ-N1-2018004",
            "发证日期": days(-2200),
            "复审日期": days(-180),
            "所属单位": UNIT_A,
            "locked": True,
            "锁定状态": STATUS_OVERDUE,
            "锁定原因": "复审不合格，登记为已过期",
        },
        {
            "人员编号": "OPER-0005",
            "姓名": "沈电梯",
            "证书类别": "电梯修理（T）",
            "证书编号": "CZ-T-2021005",
            "发证日期": days(-900),
            "复审日期": days(15),
            "所属单位": UNIT_B,
            "locked": False,
        },
        {
            "人员编号": "OPER-0006",
            "姓名": "苏压力",
            "证书类别": "移动式压力容器充装（R2）",
            "证书编号": "CZ-R2-2021006",
            "发证日期": days(-1250),
            "复审日期": days(-8),
            "所属单位": UNIT_B,
            "locked": False,
        },
        {
            "人员编号": "OPER-0007",
            "姓名": "注销名",
            "证书类别": "工业锅炉司炉（G1）",
            "证书编号": "CZ-G1-2017007",
            "发证日期": days(-2400),
            "复审日期": days(-400),
            "所属单位": UNIT_B,
            "locked": True,
            "锁定状态": STATUS_REVOKED,
            "锁定原因": "证书已注销",
        },
        {
            "人员编号": "OPER-0008",
            "姓名": "吊长远",
            "证书类别": "桥式起重机司机（Q2）",
            "证书编号": "CZ-Q2-2022008",
            "发证日期": days(-700),
            "复审日期": days(120),
            "所属单位": UNIT_C,
            "locked": False,
        },
    ]

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        row: dict[str, Any] = {"id": index}
        row.update(item)
        # 复审/经办历史：演示「人员调动之后仍能看出是谁经手」。
        history: list[dict[str, Any]] = []
        if item["人员编号"] == "OPER-0001":
            history.append({
                "动作": "复审登记",
                "结果": "合格",
                "经办人": "李证书",
                "经办单位": UNIT_A,
                "经办日期": days(-740),
                "备注": "上一周期复审合格，复审日期顺延",
            })
        if item["人员编号"] == "OPER-0004":
            history.append({
                "动作": "复审登记",
                "结果": "不合格",
                "经办人": "李证书",
                "经办单位": UNIT_A,
                "经办日期": days(-180),
                "备注": "实操考核未通过，证件登记为已过期并锁定",
            })
        if item["人员编号"] == "OPER-0007":
            history.append({
                "动作": "注销证书",
                "结果": "已注销",
                "经办人": "王管理",
                "经办单位": UNIT_B,
                "经办日期": days(-300),
                "备注": "持证人离职，申请注销",
            })
        if item["人员编号"] == "OPER-0005":
            # 调动样例：人已调到 B 厂，但上一次复审是原单位 C 队的管理员经手的，
            # 历史里保留经办时点单位，调动后仍可追溯。
            history.append({
                "动作": "复审登记",
                "结果": "合格",
                "经办人": "吊长远",
                "经办单位": UNIT_C,
                "经办日期": days(-720),
                "备注": "原单位港务起重作业队复审合格",
            })
            history.append({
                "动作": "人员调动",
                "结果": f"{UNIT_C} → {UNIT_B}",
                "经办人": "王管理",
                "经办单位": UNIT_B,
                "经办日期": days(-300),
                "备注": "调入滨江化工有限公司，证件随人员转归属",
            })
        row["history"] = history
        rows.append(row)

    return rows
