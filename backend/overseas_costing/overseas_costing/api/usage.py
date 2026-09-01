"""中文用途：工作台使用记录 API。"""

from __future__ import annotations

import json

import frappe

from overseas_costing.services import usage_service


def _loads_extra(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {"value": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


@frappe.whitelist()
def record_usage(
    action_type: str,
    batch_name: str | None = None,
    version_name: str | None = None,
    status: str | None = "Success",
    remark: str | None = "",
    route: str | None = "",
    extra_json: str | None = None,
) -> dict:
    """记录一次工作台使用行为。"""

    return usage_service.record_usage(
        action_type=action_type,
        batch_name=batch_name,
        version_name=version_name,
        status=status,
        remark=remark,
        route=route,
        extra=_loads_extra(extra_json),
    )


@frappe.whitelist()
def get_usage_logs(
    batch_name: str | None = None,
    action_type: str | None = None,
    user: str | None = None,
    limit: int | str = 80,
) -> dict:
    """返回使用记录明细。"""

    return usage_service.get_usage_logs(batch_name=batch_name, action_type=action_type, user=user, limit=limit)


@frappe.whitelist()
def get_usage_summary(days: int | str = 30, limit: int | str = 20) -> dict:
    """返回最近使用情况汇总。"""

    return usage_service.get_usage_summary(days=days, limit=limit)
