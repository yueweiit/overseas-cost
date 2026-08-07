"""
中文用途：统一维护海外成本核算的数据来源优先级。

这个模块只定义口径，不直接修改业务数据。后续导入、试算、前端提示都从这里取同一套规则。
"""

from __future__ import annotations


SOURCE_PRIORITY_RULES = {
    "tax_fee": {
        "label": "税费",
        "authoritative_source": "完税凭证",
        "fallback_sources": ["国际物流 OA", "OA 附件/清关资料", "OCR/文本解析候选", "人工补录"],
        "summary": "税费以完税凭证为最终权威；凭证未到前，只能按 OA 或附件做暂估。",
    },
    "purchase_price": {
        "label": "采购价/货值",
        "authoritative_source": "采购支出 OA",
        "fallback_sources": ["商业发票/装箱单等结构化附件", "OCR/文本解析候选", "人工补录"],
        "summary": "采购单价、币种和货值优先采用采购支出 OA；附件只在 OA 缺失时补充。",
    },
    "logistics_fee": {
        "label": "物流费/清关费/杂费",
        "authoritative_source": "国际物流 OA",
        "fallback_sources": ["OA 附件/货代账单/费用清单", "OCR/文本解析候选", "人工补录"],
        "summary": "物流费、清关费和杂费优先采用国际物流 OA；附件和解析结果只做补充或复核。",
    },
    "attachment_candidate": {
        "label": "附件解析候选",
        "authoritative_source": "OA 附件中的结构化表",
        "fallback_sources": ["OCR/文本解析候选", "人工复核"],
        "summary": "附件解析结果必须能追溯到原附件；非结构化 OCR 只作为候选，不直接当最终口径。",
    },
    "manual_override": {
        "label": "人工调整",
        "authoritative_source": "人工确认记录",
        "fallback_sources": [],
        "summary": "人工调整用于缺失、异常或差异处理，必须保留修改记录。",
    },
}


def get_source_priority_policy() -> dict:
    """返回前后端共享的数据来源优先级口径。"""

    order = ["tax_fee", "purchase_price", "logistics_fee", "attachment_candidate", "manual_override"]
    rules = [dict(SOURCE_PRIORITY_RULES[key], code=key, priority=index + 1) for index, key in enumerate(order)]
    return {
        "order": order,
        "rules": rules,
        "short_summary": "税费听完税凭证；采购价听采购支出 OA；物流/清关/杂费听国际物流 OA；附件和 OCR 只做补充；人工调整保留记录。",
    }


def get_source_priority_summary() -> str:
    return get_source_priority_policy()["short_summary"]


def get_field_source_label(field_group: str) -> str:
    rule = SOURCE_PRIORITY_RULES.get(field_group)
    if not rule:
        return "按来源优先级取数"
    return f"{rule['label']}：{rule['authoritative_source']}优先"
