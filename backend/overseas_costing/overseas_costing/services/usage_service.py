"""
中文用途：工作台使用记录服务。

该服务专门回答交付后“采购人员有没有使用系统”：
1. 前端关键动作打点
2. 单个批次使用记录查询
3. 最近活跃用户与操作次数汇总
"""

from __future__ import annotations

import json
from typing import Any

try:
    import frappe
    from frappe.utils import add_days, now_datetime, nowdate
except Exception:  # pragma: no cover - 本地单测无 Frappe 环境
    frappe = None
    add_days = None
    now_datetime = None
    nowdate = None

from overseas_costing.constants import USAGE_ACTION_TYPES, USAGE_STATUSES


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _normalize_limit(limit: int | str | None, default: int = 80, maximum: int = 300) -> int:
    try:
        value = int(limit or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _session_user() -> str:
    if frappe is None:
        return ""
    user = _clean(getattr(getattr(frappe, "session", None), "user", ""))
    return "" if user == "Guest" else user


def _user_full_name(user: str) -> str:
    if frappe is None or not user:
        return ""
    try:
        return _clean(frappe.db.get_value("User", user, "full_name"))
    except Exception:
        return ""


def _current_route(route: str | None = None) -> str:
    if route:
        return _clean(route)
    if frappe is None:
        return ""
    form_dict = getattr(frappe, "form_dict", None)
    return _clean(getattr(form_dict, "route", "")) or _clean(getattr(form_dict, "cmd", ""))


def _resolve_batch_name(batch_name: str | None = None) -> str:
    if frappe is None:
        return _clean(batch_name)
    value = _clean(batch_name)
    if not value:
        return ""
    if frappe.db.exists("Overseas Cost Batch", value):
        return value
    for fieldname in ("batch_no", "waybill_no", "customs_no", "source_approval_no", "source_instance_id"):
        resolved = frappe.db.get_value("Overseas Cost Batch", {fieldname: value}, "name")
        if resolved:
            return resolved
    return ""


def record_usage(
    *,
    action_type: str,
    batch_name: str | None = None,
    version_name: str | None = None,
    status: str | None = "Success",
    remark: str | None = "",
    route: str | None = "",
    extra: dict | str | None = None,
) -> dict:
    """写入工作台使用记录。失败时不阻断主流程。"""

    normalized_action = _clean(action_type).upper() or "OTHER"
    if normalized_action not in USAGE_ACTION_TYPES:
        normalized_action = "OTHER"
    normalized_status = _clean(status) or "Success"
    if normalized_status not in USAGE_STATUSES:
        normalized_status = "Failed" if normalized_status.lower().startswith("fail") else "Success"
    resolved_batch = _resolve_batch_name(batch_name)
    operator = _session_user()
    payload_extra = extra
    if isinstance(payload_extra, str):
        payload_extra = {"value": payload_extra}
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "action_type": normalized_action,
            "batch_name": resolved_batch,
            "operator_name": operator,
        }
    try:
        doc = frappe.get_doc(
            {
                "doctype": "Overseas Cost Usage Log",
                "action_type": normalized_action,
                "status": normalized_status,
                "batch": resolved_batch,
                "version": _clean(version_name),
                "operator_name": operator,
                "operator_full_name": _user_full_name(operator),
                "route": _current_route(route),
                "action_remark": _clean(remark),
                "extra_json": _json_dumps(payload_extra),
            }
        ).insert(ignore_permissions=True)
        return {"ok": True, "name": doc.name, "action_type": normalized_action, "batch_name": resolved_batch}
    except Exception as exc:
        try:
            frappe.log_error(title="Overseas Cost Usage Log Failed", message=frappe.get_traceback())
        except Exception:
            pass
        return {"ok": False, "message": str(exc), "action_type": normalized_action, "batch_name": resolved_batch}


def get_usage_logs(
    *,
    batch_name: str | None = None,
    action_type: str | None = None,
    user: str | None = None,
    limit: int | str | None = 80,
) -> dict:
    normalized_limit = _normalize_limit(limit)
    if frappe is None:
        return {"ok": True, "dry_run": True, "items": [], "total": 0}

    filters: dict[str, Any] = {}
    resolved_batch = _resolve_batch_name(batch_name)
    if resolved_batch:
        filters["batch"] = resolved_batch
    normalized_action = _clean(action_type).upper()
    if normalized_action:
        filters["action_type"] = normalized_action
    if _clean(user):
        filters["operator_name"] = _clean(user)

    items = frappe.get_all(
        "Overseas Cost Usage Log",
        filters=filters,
        fields=[
            "name",
            "action_type",
            "status",
            "batch",
            "version",
            "operator_name",
            "operator_full_name",
            "route",
            "action_remark",
            "extra_json",
            "creation",
        ],
        order_by="creation desc",
        limit_page_length=normalized_limit,
    )
    return {"ok": True, "items": items, "total": len(items), "batch_name": resolved_batch}


def get_usage_summary(*, days: int | str | None = 30, limit: int | str | None = 20) -> dict:
    normalized_limit = _normalize_limit(limit, default=20, maximum=100)
    try:
        normalized_days = max(1, min(int(days or 30), 365))
    except (TypeError, ValueError):
        normalized_days = 30
    if frappe is None:
        return {"ok": True, "dry_run": True, "days": normalized_days, "users": [], "actions": [], "total": 0}

    since_date = add_days(nowdate(), -normalized_days) if add_days and nowdate else None
    filters = {"creation": [">=", since_date]} if since_date else {}
    users = frappe.get_all(
        "Overseas Cost Usage Log",
        filters=filters,
        fields=[
            "operator_name",
            "operator_full_name",
            "count(name) as action_count",
            "max(creation) as last_seen",
        ],
        group_by="operator_name, operator_full_name",
        order_by="action_count desc",
        limit_page_length=normalized_limit,
    )
    actions = frappe.get_all(
        "Overseas Cost Usage Log",
        filters=filters,
        fields=["action_type", "count(name) as action_count"],
        group_by="action_type",
        order_by="action_count desc",
        limit_page_length=normalized_limit,
    )
    total = frappe.db.count("Overseas Cost Usage Log", filters)
    return {
        "ok": True,
        "days": normalized_days,
        "generated_at": now_datetime() if now_datetime else "",
        "users": users,
        "actions": actions,
        "total": total,
    }
