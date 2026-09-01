"""利润测算 API。"""

from __future__ import annotations

import frappe

from overseas_costing.services import profit_service


@frappe.whitelist()
def save_profit_inputs(batch_name: str, rows_payload: str, version_name: str | None = None) -> dict:
    """保存批次销售数据并返回利润测算结果。"""

    return profit_service.save_profit_inputs(
        batch_name=batch_name,
        version_name=version_name,
        rows_payload=rows_payload,
    )
