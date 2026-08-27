from __future__ import annotations

import json
from pathlib import Path


TOPIC_QUERIES: dict[int, tuple[str, ...]] = {
    1001: ("paid time off allowance", "time away approval", "休假额度规则", "请假审批依据"),
    1002: ("official holiday dates", "calendar closure days", "法定假期安排", "放假日期依据"),
    1003: ("daily work schedule", "remote work hours", "日常工作时段", "远程办公时间"),
    1004: ("claiming business expenses", "invoice reimbursement rules", "费用报销依据", "发票报销要求"),
    1005: ("business trip allowance", "travel per diem rules", "出差补助标准", "差旅餐补依据"),
    1006: ("buying approval threshold", "procurement signoff", "采购审批额度", "预算采购签批"),
    1007: ("reporting a security breach", "credential incident response", "安全事件上报", "凭据泄露处置"),
    1008: ("new starter checklist", "leaver handover steps", "新员工入职事项", "离职交接清单"),
    1009: ("employee review cycle", "promotion assessment", "员工绩效周期", "晋升评估依据"),
    1010: ("benefit enrollment window", "medical coverage option", "福利登记期限", "医疗保障计划"),
    1011: ("department owner table", "team responsibility matrix", "部门负责人表", "团队职责矩阵"),
    1012: ("quarterly objective", "next quarter target", "季度目标", "下季度指标"),
    1013: ("release rollback steps", "deployment checklist", "发布回滚步骤", "上线检查清单"),
    1014: ("incident priority level", "service objective target", "事件优先级", "服务目标阈值"),
    1015: ("support desk coverage", "escalation route", "客服值班时间", "支持升级路径"),
    1016: ("retaining business records", "remove personal data request", "数据留存期限", "删除数据申请"),
    1017: ("API request quota", "access token handling", "接口调用限额", "访问令牌管理"),
    1018: ("feature toggle ownership", "runtime setting", "功能开关管理", "运行时配置项"),
    1019: ("warehouse visitor access", "visitor sign in", "仓库访问登记", "访客登记流程"),
    1020: ("staff directory owner", "contact details change", "团队通讯录", "联系人更新"),
    2001: ("paid leave entitlement", "absence request approval", "带薪休假额度", "请假审批规则"),
    2002: ("company closure calendar", "public holiday schedule", "公司假期日历", "节假日日期"),
    2003: ("standard office hours", "working time window", "标准办公时段", "工作时间窗口"),
    2004: ("expense claim evidence", "receipt reimbursement", "报销凭证要求", "费用报销流程"),
    2005: ("purchase authorization", "spend approval limit", "采购授权额度", "支出审批限制"),
    2006: ("security incident escalation", "breach response owner", "安全事件处置", "事件上报负责人"),
    2007: ("onboarding handoff", "new joiner tasks", "入职交接事项", "新员工任务"),
    2008: ("review and promotion cycle", "performance evidence", "绩效与晋升周期", "绩效证明材料"),
    2009: ("record retention period", "privacy deletion workflow", "记录保留期限", "隐私删除流程"),
    2010: ("API quota policy", "token rotation rule", "接口配额政策", "令牌轮换规则"),
    2011: ("home working schedule", "remote access hours", "居家办公时段", "远程访问时间"),
    2012: ("rollback approval", "release recovery procedure", "回滚审批", "发布恢复流程"),
}


TOPIC_DOCUMENTS: dict[int, list[str]] = {
    label: [
        f"Synthetic handbook reference {label} defines the approved {queries[0]} process and owner.",
        "The reference also records an escalation contact and a review interval for this topic.",
    ]
    for label, queries in TOPIC_QUERIES.items()
}


def build_fixture(source: Path, destination: Path) -> None:
    original = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(original) != 100:
        raise ValueError(f"expected 100 source rows, got {len(original)}")
    output: list[dict[str, object]] = []
    seen_by_tenant: dict[str, list[int]] = {}
    for index, row in enumerate(original, start=1):
        labels = row["expected_entry_ids"]
        if not isinstance(labels, list) or len(labels) != 1 or type(labels[0]) is not int:
            raise ValueError(f"row {index} must contain one integer expected entry")
        label = labels[0]
        tenant = row["tenant"]
        if label not in TOPIC_QUERIES:
            raise ValueError(f"no synthetic topic for entry {label}")
        variants = TOPIC_QUERIES[label]
        query = variants[(index - 1) % len(variants)]
        seen_by_tenant.setdefault(tenant, []).append(label)
        output.append(
            {
                "case_id": f"rag-{index:03d}",
                "query": query,
                "expected_entry_ids": [label],
                "expected_chunk_ids": [f"{label}:0"],
                "hard_negative_entry_ids": [],
                "tenant": tenant,
                "document_chunks": TOPIC_DOCUMENTS[label],
            }
        )

    for row in output:
        tenant = str(row["tenant"])
        label = int(row["expected_entry_ids"][0])
        candidates = [candidate for candidate in dict.fromkeys(seen_by_tenant[tenant]) if candidate != label]
        row["hard_negative_entry_ids"] = candidates[:2]

    destination.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in output),
        encoding="utf-8",
    )


if __name__ == "__main__":
    root = Path(__file__).parents[1]
    build_fixture(
        root / "tests/fixtures/rag/evaluation.jsonl",
        root / "tests/fixtures/rag/evaluation.jsonl",
    )
