"""
中文用途：编辑与重算服务。

这是后续整个后端最核心的服务之一，
后面会承接：
1. 单字段修改
2. 批量字段修改
3. 汇率更新
4. 分摊重算
5. 版本创建与切换
"""

from __future__ import annotations

from overseas_costing.services import audit_service, version_service


def update_item_field(item_name: str, fieldname: str, value: str, version_name: str | None = None) -> dict:
    audit_service.build_audit_stub("EDIT", {"item_name": item_name, "fieldname": fieldname})
    return {
        "ok": True,
        "item_name": item_name,
        "fieldname": fieldname,
        "value": value,
        "version_name": version_name,
        "message": "单字段编辑骨架已创建。",
    }


def batch_update_items(batch_name: str, updates: str, version_name: str | None = None) -> dict:
    audit_service.build_audit_stub("BATCH_EDIT", {"batch_name": batch_name})
    return {
        "ok": True,
        "batch_name": batch_name,
        "version_name": version_name,
        "updates": updates,
        "message": "批量编辑骨架已创建。",
    }


def recalculate_batch(batch_name: str, version_name: str | None = None) -> dict:
    summary_snapshot = version_service.build_empty_summary_snapshot()
    audit_service.build_audit_stub("RECALCULATE", {"batch_name": batch_name})
    return {
        "ok": True,
        "batch_name": batch_name,
        "version_name": version_name,
        "summary_snapshot": summary_snapshot,
        "message": "整票重算骨架已创建，后续补货值比/重量比/费用分摊。",
    }


def update_allocation_rule(batch_name: str, version_name: str, rule_payload: str) -> dict:
    return {
        "ok": True,
        "batch_name": batch_name,
        "version_name": version_name,
        "rule_payload": rule_payload,
        "message": "分摊规则更新骨架已创建。",
    }


def create_version(batch_name: str, source_version_name: str, version_type: str) -> dict:
    audit_service.build_audit_stub("CREATE_VERSION", {"batch_name": batch_name, "version_type": version_type})
    return {
        "ok": True,
        "batch_name": batch_name,
        "source_version_name": source_version_name,
        "version_type": version_type,
        "message": "版本创建骨架已创建。",
    }


def switch_version(batch_name: str, target_version_name: str) -> dict:
    audit_service.build_audit_stub("SWITCH_VERSION", {"batch_name": batch_name, "target_version_name": target_version_name})
    return {
        "ok": True,
        "batch_name": batch_name,
        "target_version_name": target_version_name,
        "message": "版本切换骨架已创建。",
    }


# --- First usable implementation for the Excel -> recalculate MVP. ---

import json as _json
from copy import deepcopy as _deepcopy
from datetime import datetime as _datetime

try:
    import frappe as _frappe
except Exception:  # pragma: no cover - local tests can import without Frappe
    _frappe = None

from overseas_costing.utils.currency import round_money as _round_money

DEFAULT_FX_RMB_TO_MXN = 2.6
EDITABLE_ITEM_FIELDS = frozenset(
    {
        "material_code",
        "product_name",
        "product_name_es",
        "spec_model",
        "unit",
        "recipient",
        "unit_price",
        "purchase_currency",
        "quantity",
        "actual_shipped_qty",
        "goods_value",
        "import_name",
        "hs_code",
        "category",
        "customs_no",
        "waybill_no",
        "container_no",
        "sea_bill_no",
        "commercial_invoice_no",
        "purchase_order_no",
        "china_misc_rmb",
        "china_misc_mxn",
        "china_ocean_usd",
        "cc_rate",
        "cc_anti_dumping",
        "igi_rate",
        "igi_amount",
        "iva_rate",
        "iva_amount",
        "dta",
        "prv_duty",
        "prv_iva",
        "import_tax_total",
        "revalidacion",
        "maniobras",
        "muellaje",
        "entrega_mercancia",
        "previo",
        "service_aa",
        "almacenajes",
        "reconocimiento_aduanero",
        "honorarios",
        "complemento_maniobras",
        "desconsolidacion",
        "maniobra_falso",
        "arrastre",
        "patio_regulador",
        "entrega_vacio",
        "limpieza_contenedor",
        "mexico_customs_mxn",
        "mexico_customs_rmb",
        "mexico_customs_usd",
        "mexico_inland_mxn",
        "mexico_misc_mxn",
        "mexico_inland_misc_rmb",
        "china_to_mexico_freight_rmb",
        "gross_weight_kg",
        "volume_m3",
        "volume_weight_kg",
        "chargeable_weight_kg",
        "project_collection",
        "transport_mode",
        "source_type",
        "source_doc_no",
        "source_file_name",
        "source_attachment_id",
        "parse_status",
        "manual_override_reason",
        "dingtalk_instance_id",
        "dingtalk_official_url",
        "source_remark",
        "raw_excel_json",
        "extra_json",
    }
)
SPECIAL_OVERRIDE_ITEM_FIELDS = frozenset({"weight_ratio", "alloc_price_mxn", "total_cost_rmb", "total_unit_rmb"})
READONLY_CALC_ITEM_FIELDS = frozenset(
    {
        "goods_value_ratio",
        "freight_alloc_rmb",
        "freight_alloc_mxn",
        "total_logistics_mxn",
        "derived_json",
    }
)
NUMERIC_ITEM_FIELDS = frozenset(
    {
        "unit_price",
        "quantity",
        "actual_shipped_qty",
        "goods_value",
        "china_misc_rmb",
        "china_misc_mxn",
        "china_ocean_usd",
        "cc_rate",
        "cc_anti_dumping",
        "igi_rate",
        "igi_amount",
        "iva_rate",
        "iva_amount",
        "goods_value_ratio",
        "dta",
        "prv_duty",
        "prv_iva",
        "import_tax_total",
        "revalidacion",
        "maniobras",
        "muellaje",
        "entrega_mercancia",
        "previo",
        "service_aa",
        "almacenajes",
        "reconocimiento_aduanero",
        "honorarios",
        "complemento_maniobras",
        "desconsolidacion",
        "maniobra_falso",
        "arrastre",
        "patio_regulador",
        "entrega_vacio",
        "limpieza_contenedor",
        "mexico_customs_mxn",
        "mexico_customs_rmb",
        "mexico_customs_usd",
        "mexico_inland_mxn",
        "mexico_misc_mxn",
        "mexico_inland_misc_rmb",
        "china_to_mexico_freight_rmb",
        "gross_weight_kg",
        "volume_m3",
        "volume_weight_kg",
        "chargeable_weight_kg",
        "weight_ratio",
        "freight_alloc_rmb",
        "freight_alloc_mxn",
        "total_logistics_mxn",
        "alloc_price_mxn",
        "total_cost_rmb",
        "total_unit_rmb",
    }
)
CHECK_ITEM_FIELDS = frozenset({"manual_override_flag"})
SELECT_ITEM_OPTIONS = {
    "transport_mode": {"SEA", "AIR", "EXPRESS"},
    "parse_status": {"PENDING", "SUCCESS", "PARTIAL", "FAILED", "MANUAL"},
}
SELECT_ITEM_ALIASES = {
    "transport_mode": {
        "海运": "SEA",
        "空运": "AIR",
        "快递": "EXPRESS",
    }
}
DEFAULT_CALC_FIELDS = [
    "goods_value",
    "goods_value_ratio",
    "weight_ratio",
    "freight_alloc_rmb",
    "freight_alloc_mxn",
    "total_logistics_mxn",
    "alloc_price_mxn",
    "total_cost_rmb",
    "total_unit_rmb",
    "derived_json",
]
ITEM_QUERY_FIELDS = [
    "name",
    "batch",
    "version",
    "row_no",
    "unit_price",
    "quantity",
    "goods_value",
    "gross_weight_kg",
    "volume_m3",
    "mexico_customs_mxn",
    "mexico_customs_rmb",
    "china_misc_rmb",
    "china_to_mexico_freight_rmb",
    "mexico_inland_misc_rmb",
]


def _now() -> str:
    if _frappe is not None:
        try:
            return _frappe.utils.now()
        except Exception:
            pass
    return _datetime.now().isoformat(timespec="seconds")


def _to_float(value, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _json_dumps(value) -> str:
    return _json.dumps(value, ensure_ascii=False, default=str)


def _coerce_check(value) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    text = str(value or "").strip().lower()
    return 1 if text in {"1", "true", "yes", "y", "on", "是"} else 0


def _coerce_edit_value(fieldname: str, value):
    if fieldname in NUMERIC_ITEM_FIELDS:
        return _to_float(value)
    if fieldname in CHECK_ITEM_FIELDS:
        return _coerce_check(value)
    if fieldname in SELECT_ITEM_OPTIONS:
        text = str(value or "").strip()
        text = SELECT_ITEM_ALIASES.get(fieldname, {}).get(text, text.upper())
        if text and text not in SELECT_ITEM_OPTIONS[fieldname]:
            raise ValueError(f"字段 {fieldname} 的值 {text} 不在允许范围内。")
        return text
    if isinstance(value, (dict, list)):
        return _json_dumps(value)
    return "" if value is None else str(value).strip()


def _normalize_edit_remark(remark: str | None = None, manual_override_reason: str | None = None) -> str:
    return str(manual_override_reason or remark or "").strip()


def _validate_edit_field(fieldname: str, remark: str = "") -> tuple[bool, str, str]:
    if not fieldname:
        return False, "字段名不能为空。", "missing"
    if fieldname in EDITABLE_ITEM_FIELDS:
        return True, "", "editable"
    if fieldname in SPECIAL_OVERRIDE_ITEM_FIELDS:
        if remark:
            return True, "", "special_override"
        return False, f"字段 {fieldname} 是计算结果字段，人工覆盖需要填写修改原因。", "reason_required"
    if fieldname in READONLY_CALC_ITEM_FIELDS:
        return False, f"字段 {fieldname} 由重算服务生成，不能直接手工编辑。", "readonly_calc"
    return False, f"字段 {fieldname} 不在可编辑白名单内。", "not_allowed"


def _edit_values_equal(fieldname: str, old_value, new_value) -> bool:
    if fieldname in NUMERIC_ITEM_FIELDS:
        return _to_float(old_value) == _to_float(new_value)
    if fieldname in CHECK_ITEM_FIELDS:
        return _coerce_check(old_value) == _coerce_check(new_value)
    return ("" if old_value is None else str(old_value).strip()) == ("" if new_value is None else str(new_value).strip())


def _load_updates_payload(updates) -> list[dict]:
    if updates in (None, ""):
        return []
    loaded_updates = _json.loads(updates) if isinstance(updates, str) else updates
    if isinstance(loaded_updates, dict):
        return [loaded_updates]
    if isinstance(loaded_updates, list):
        return loaded_updates
    raise ValueError("批量更新参数必须是 JSON 对象或对象数组。")


def _preview_update_result(update: dict, default_remark: str = "") -> dict:
    item_name = update.get("item_name") or update.get("name")
    fieldname = update.get("fieldname") or update.get("field_name")
    value = update.get("value") if "value" in update else update.get("field_value")
    remark = _normalize_edit_remark(update.get("remark") or default_remark, update.get("manual_override_reason"))
    if not item_name or not fieldname:
        return {
            "ok": False,
            "changed": False,
            "item_name": item_name,
            "fieldname": fieldname,
            "message": "批量更新行缺少 item_name/name 或 fieldname/field_name。",
        }
    is_allowed, message, edit_mode = _validate_edit_field(fieldname, remark)
    if not is_allowed:
        return {
            "ok": False,
            "changed": False,
            "item_name": item_name,
            "fieldname": fieldname,
            "message": message,
            "edit_mode": edit_mode,
        }
    try:
        coerced_value = _coerce_edit_value(fieldname, value)
    except ValueError as exc:
        return {
            "ok": False,
            "changed": False,
            "item_name": item_name,
            "fieldname": fieldname,
            "message": str(exc),
            "edit_mode": edit_mode,
        }
    return {
        "ok": True,
        "changed": True,
        "item_name": item_name,
        "fieldname": fieldname,
        "value": coerced_value,
        "manual_override_reason": remark,
        "edit_mode": edit_mode,
    }


def _load_payload(payload) -> dict:
    if payload in (None, ""):
        return {}
    if isinstance(payload, str):
        loaded = _json.loads(payload)
    else:
        loaded = payload
    if not isinstance(loaded, dict):
        raise ValueError("参数必须是 JSON 对象。")
    return loaded


def _build_new_item_values(batch_doc_name: str, version_name: str, payload: dict, row_no: int | None = None) -> dict:
    values = {
        "doctype": "Overseas Cost Item",
        "batch": batch_doc_name,
        "version": version_name,
    }
    if row_no is not None:
        values["row_no"] = row_no

    for fieldname, value in payload.items():
        if fieldname not in EDITABLE_ITEM_FIELDS and fieldname not in SPECIAL_OVERRIDE_ITEM_FIELDS:
            continue
        values[fieldname] = _coerce_edit_value(fieldname, value)

    quantity = _to_float(values.get("quantity"), default=0.0)
    unit_price = _to_float(values.get("unit_price"), default=0.0)
    if values.get("goods_value") in (None, "") and quantity and unit_price:
        values["goods_value"] = quantity * unit_price
    values.setdefault("transport_mode", "SEA")
    values.setdefault("manual_override_flag", 1)
    values.setdefault("manual_override_reason", "手工新增物料")
    return values


def _is_rule_enabled(rule: dict) -> bool:
    return bool(rule.get("is_enabled", rule.get("is_active", 1)))


def _amount_to_rmb(amount: float, currency: str | None, fx_rmb_to_mxn: float, fx_usd_to_rmb: float | None) -> float:
    currency_code = (currency or "RMB").upper()
    if currency_code == "MXN":
        return _safe_div(amount, fx_rmb_to_mxn)
    if currency_code == "USD" and fx_usd_to_rmb:
        return amount * fx_usd_to_rmb
    return amount


def _basis_value(item: dict, basis: str) -> float:
    if basis == "gross_weight":
        return _to_float(item.get("gross_weight_kg"))
    if basis == "volume":
        return _to_float(item.get("volume_m3"))
    return _to_float(item.get("goods_value"))


def _first_nonzero(items: list[dict], fieldname: str) -> float:
    for item in items:
        value = _to_float(item.get(fieldname))
        if value:
            return value
    return 0.0


def _fallback_rules_from_items(items: list[dict]) -> list[dict]:
    return [
        {
            "rule_code": "china_misc_rmb",
            "expense_category": "China misc RMB",
            "allocation_basis": "goods_value",
            "currency": "RMB",
            "amount": _first_nonzero(items, "china_misc_rmb"),
            "is_enabled": 1,
        },
        {
            "rule_code": "china_to_mexico_freight_rmb",
            "expense_category": "China to Mexico freight RMB",
            "allocation_basis": "gross_weight",
            "currency": "RMB",
            "amount": _first_nonzero(items, "china_to_mexico_freight_rmb"),
            "is_enabled": 1,
        },
        {
            "rule_code": "mexico_inland_misc_rmb",
            "expense_category": "Mexico inland and misc RMB",
            "allocation_basis": "gross_weight",
            "currency": "RMB",
            "amount": _first_nonzero(items, "mexico_inland_misc_rmb"),
            "is_enabled": 1,
        },
    ]


def calculate_item_rows(
    items: list[dict],
    rules: list[dict] | None = None,
    *,
    fx_rmb_to_mxn: float = DEFAULT_FX_RMB_TO_MXN,
    fx_usd_to_rmb: float | None = None,
) -> tuple[list[dict], dict]:
    """Pure calculation helper used by Frappe service and local tests."""

    rows = [_deepcopy(item) for item in items]
    for row in rows:
        quantity = _to_float(row.get("quantity"))
        unit_price = _to_float(row.get("unit_price"))
        if row.get("goods_value") in (None, "") and quantity and unit_price:
            row["goods_value"] = quantity * unit_price

    enabled_rules = [rule for rule in (rules or []) if _is_rule_enabled(rule) and _to_float(rule.get("amount"))]
    if not enabled_rules:
        enabled_rules = [rule for rule in _fallback_rules_from_items(rows) if _to_float(rule.get("amount"))]

    total_goods_value = sum(_to_float(row.get("goods_value")) for row in rows)
    total_gross_weight = sum(_to_float(row.get("gross_weight_kg")) for row in rows)
    total_volume = sum(_to_float(row.get("volume_m3")) for row in rows)
    basis_totals = {
        "goods_value": total_goods_value,
        "gross_weight": total_gross_weight,
        "volume": total_volume,
    }

    total_cost_rmb = 0.0
    total_logistics_mxn = 0.0
    calculated_rows = []

    for row in rows:
        goods_value = _to_float(row.get("goods_value"))
        quantity = _to_float(row.get("quantity"))
        mexico_customs_rmb = _to_float(row.get("mexico_customs_rmb"))
        mexico_customs_mxn = _to_float(row.get("mexico_customs_mxn"))
        if not mexico_customs_rmb and mexico_customs_mxn:
            mexico_customs_rmb = _safe_div(mexico_customs_mxn, fx_rmb_to_mxn)
        if not mexico_customs_mxn and mexico_customs_rmb:
            mexico_customs_mxn = mexico_customs_rmb * fx_rmb_to_mxn

        allocated_other_rmb = 0.0
        allocated_other_mxn = 0.0
        freight_alloc_rmb = 0.0
        freight_alloc_mxn = 0.0
        allocated_rules = []

        for rule in enabled_rules:
            basis = rule.get("allocation_basis") or rule.get("basis_field") or "goods_value"
            basis_total = basis_totals.get(basis, 0.0)
            ratio = _basis_value(row, basis) / basis_total if basis_total else _safe_div(1.0, len(rows))
            amount_rmb = _amount_to_rmb(
                _to_float(rule.get("amount")),
                rule.get("currency"),
                fx_rmb_to_mxn,
                fx_usd_to_rmb,
            )
            allocated_rmb = amount_rmb * ratio
            allocated_mxn = allocated_rmb * fx_rmb_to_mxn
            rule_code = rule.get("rule_code") or rule.get("fee_key") or ""

            if "freight" in rule_code or "ocean" in rule_code:
                freight_alloc_rmb += allocated_rmb
                freight_alloc_mxn += allocated_mxn
            else:
                allocated_other_rmb += allocated_rmb
                allocated_other_mxn += allocated_mxn

            allocated_rules.append(
                {
                    "rule_code": rule_code,
                    "basis": basis,
                    "ratio": ratio,
                    "allocated_rmb": _round_money(allocated_rmb, 6),
                    "allocated_mxn": _round_money(allocated_mxn, 6),
                }
            )

        row_total_logistics_mxn = mexico_customs_mxn + freight_alloc_mxn + allocated_other_mxn
        row_total_cost_rmb = goods_value + mexico_customs_rmb + freight_alloc_rmb + allocated_other_rmb
        row_total_unit_rmb = _safe_div(row_total_cost_rmb, quantity)

        row.update(
            {
                "goods_value": _round_money(goods_value, 6),
                "goods_value_ratio": _round_money(_safe_div(goods_value, total_goods_value) * 100, 6),
                "weight_ratio": _round_money(_safe_div(_to_float(row.get("gross_weight_kg")), total_gross_weight) * 100, 6),
                "freight_alloc_rmb": _round_money(freight_alloc_rmb, 6),
                "freight_alloc_mxn": _round_money(freight_alloc_mxn, 6),
                "total_logistics_mxn": _round_money(row_total_logistics_mxn, 6),
                "alloc_price_mxn": _round_money(_safe_div(row_total_logistics_mxn, quantity), 6),
                "total_cost_rmb": _round_money(row_total_cost_rmb, 6),
                "total_unit_rmb": _round_money(row_total_unit_rmb, 6),
                "derived_json": _json_dumps(
                    {
                        "basis_totals": basis_totals,
                        "fx_rmb_to_mxn": fx_rmb_to_mxn,
                        "fx_usd_to_rmb": fx_usd_to_rmb,
                        "allocated_rules": allocated_rules,
                        "allocated_other_rmb": _round_money(allocated_other_rmb, 6),
                        "mexico_customs_rmb": _round_money(mexico_customs_rmb, 6),
                    }
                ),
            }
        )
        total_cost_rmb += row_total_cost_rmb
        total_logistics_mxn += row_total_logistics_mxn
        calculated_rows.append(row)

    summary = {
        "total_goods_value": _round_money(total_goods_value, 6),
        "total_gross_weight_kg": _round_money(total_gross_weight, 6),
        "total_volume_m3": _round_money(total_volume, 6),
        "total_logistics_mxn": _round_money(total_logistics_mxn, 6),
        "total_cost_rmb": _round_money(total_cost_rmb, 6),
        "item_count": len(rows),
        "rule_count": len(enabled_rules),
    }
    return calculated_rows, summary


def _resolve_batch_name(batch_name: str) -> str | None:
    if _frappe is None:
        return None

    batch = _frappe.db.get_value("Overseas Cost Batch", batch_name, ["name"], as_dict=True)
    if batch:
        return batch["name"]
    batch = _frappe.db.get_value("Overseas Cost Batch", {"batch_no": batch_name}, ["name"], as_dict=True)
    if batch:
        return batch["name"]
    return None


def _resolve_version_name(batch_doc_name: str, version_name: str | None = None) -> str | None:
    if _frappe is None:
        return version_name
    if version_name:
        return version_name
    current_version = _frappe.db.get_value("Overseas Cost Batch", batch_doc_name, "current_version")
    if current_version:
        return current_version
    latest_rows = _frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=["name"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return latest_rows[0]["name"] if latest_rows else None


def _get_version_context(version_name: str) -> dict:
    if _frappe is None or not version_name:
        return {}
    row = _frappe.db.get_value(
        "Overseas Cost Version",
        version_name,
        ["name", "fx_usd_to_rmb", "fx_rmb_to_mxn", "version_type"],
        as_dict=True,
    )
    return dict(row or {})


def _get_items(batch_doc_name: str, version_name: str) -> list[dict]:
    return _frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": version_name},
        fields=ITEM_QUERY_FIELDS,
        order_by="row_no asc",
        limit_page_length=10000,
    )


def _get_rules(batch_doc_name: str, version_name: str) -> list[dict]:
    return _frappe.get_all(
        "Overseas Cost Allocation Rule",
        filters={"batch": batch_doc_name, "version": version_name},
        fields=[
            "name",
            "rule_code",
            "expense_category",
            "allocation_basis",
            "basis_field",
            "currency",
            "amount",
            "is_active",
            "is_enabled",
            "priority_no",
        ],
        order_by="priority_no asc, modified asc",
        limit_page_length=1000,
    )


def _insert_audit_log(
    *,
    batch_doc_name: str,
    version_name: str | None,
    action_type: str,
    field_name: str = "",
    row_no: int | None = None,
    old_value=None,
    new_value=None,
    action_remark: str = "",
) -> None:
    if _frappe is None:
        return

    operator_name = ""
    session_user = getattr(getattr(_frappe, "session", None), "user", None)
    if session_user and session_user != "Guest":
        operator_name = session_user

    _frappe.get_doc(
        {
            "doctype": "Overseas Cost Audit Log",
            "batch": batch_doc_name,
            "version": version_name,
            "action_type": action_type,
            "field_name": field_name,
            "row_no": row_no,
            "old_value": "" if old_value is None else str(old_value),
            "new_value": "" if new_value is None else str(new_value),
            "operator_name": operator_name,
            "action_remark": action_remark,
        }
    ).insert(ignore_permissions=True)


def update_item_field(
    item_name: str,
    fieldname: str,
    value: str,
    version_name: str | None = None,
    remark: str | None = None,
    manual_override_reason: str | None = None,
) -> dict:
    edit_remark = _normalize_edit_remark(remark, manual_override_reason)
    is_allowed, validation_message, edit_mode = _validate_edit_field(fieldname, edit_remark)
    if not is_allowed:
        return {
            "ok": False,
            "changed": False,
            "dry_run": _frappe is None,
            "item_name": item_name,
            "fieldname": fieldname,
            "version_name": version_name,
            "edit_mode": edit_mode,
            "message": validation_message,
        }

    try:
        coerced_value = _coerce_edit_value(fieldname, value)
    except ValueError as exc:
        return {
            "ok": False,
            "changed": False,
            "dry_run": _frappe is None,
            "item_name": item_name,
            "fieldname": fieldname,
            "version_name": version_name,
            "edit_mode": edit_mode,
            "message": str(exc),
        }

    if _frappe is None:
        audit_service.build_audit_stub("EDIT", {"item_name": item_name, "fieldname": fieldname})
        return {
            "ok": True,
            "changed": True,
            "dry_run": True,
            "item_name": item_name,
            "fieldname": fieldname,
            "value": coerced_value,
            "version_name": version_name,
            "manual_override_reason": edit_remark,
            "edit_mode": edit_mode,
            "message": "当前未连接 Frappe，已返回编辑预览。",
        }

    item_doc = _frappe.get_doc("Overseas Cost Item", item_name)
    old_value = getattr(item_doc, fieldname, None)
    if _edit_values_equal(fieldname, old_value, coerced_value):
        return {
            "ok": True,
            "changed": False,
            "item_name": item_name,
            "fieldname": fieldname,
            "old_value": old_value,
            "value": coerced_value,
            "version_name": version_name or item_doc.version,
            "edit_mode": edit_mode,
            "message": "字段值未变化，已跳过保存。",
        }

    setattr(item_doc, fieldname, coerced_value)
    if fieldname != "manual_override_flag":
        item_doc.manual_override_flag = 1
    if edit_remark and fieldname != "manual_override_reason":
        item_doc.manual_override_reason = edit_remark
    item_doc.save(ignore_permissions=True)
    _frappe.db.set_value("Overseas Cost Batch", item_doc.batch, "status", "Dirty", update_modified=True)
    _insert_audit_log(
        batch_doc_name=item_doc.batch,
        version_name=version_name or item_doc.version,
        action_type="EDIT",
        field_name=fieldname,
        row_no=getattr(item_doc, "row_no", None),
        old_value=old_value,
        new_value=coerced_value,
        action_remark=f"单字段编辑：{edit_remark}" if edit_remark else "单字段编辑",
    )
    _frappe.db.commit()
    return {
        "ok": True,
        "changed": True,
        "item_name": item_name,
        "fieldname": fieldname,
        "old_value": old_value,
        "value": coerced_value,
        "version_name": version_name or item_doc.version,
        "manual_override_reason": edit_remark,
        "edit_mode": edit_mode,
        "message": "字段已更新，批次已标记为 Dirty。",
    }


def batch_update_items(
    batch_name: str,
    updates: str,
    version_name: str | None = None,
    remark: str | None = None,
) -> dict:
    try:
        loaded_updates = _load_updates_payload(updates)
    except (TypeError, ValueError, _json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "dry_run": _frappe is None,
            "batch_name": batch_name,
            "version_name": version_name,
            "changed_count": 0,
            "skipped_count": 0,
            "error_count": 1,
            "results": [],
            "message": f"批量更新参数解析失败：{exc}",
        }

    if _frappe is None:
        audit_service.build_audit_stub("BATCH_EDIT", {"batch_name": batch_name})
        results = [_preview_update_result(update, default_remark=remark or "") for update in loaded_updates]
        changed_count = sum(1 for result in results if result.get("ok") and result.get("changed"))
        error_count = sum(1 for result in results if not result.get("ok"))
        return {
            "ok": error_count == 0,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "changed_count": changed_count,
            "skipped_count": 0,
            "error_count": error_count,
            "results": results,
            "message": "当前未连接 Frappe，已返回批量编辑预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    changed_count = 0
    skipped_count = 0
    error_count = 0
    results = []
    for update in loaded_updates:
        item_name = update.get("item_name") or update.get("name")
        fieldname = update.get("fieldname") or update.get("field_name")
        value = update.get("value") if "value" in update else update.get("field_value")
        edit_remark = update.get("remark") or update.get("manual_override_reason") or remark
        if not item_name or not fieldname:
            error_count += 1
            results.append(
                {
                    "ok": False,
                    "changed": False,
                    "item_name": item_name,
                    "fieldname": fieldname,
                    "message": "批量更新行缺少 item_name/name 或 fieldname/field_name。",
                }
            )
            continue

        item_batch = _frappe.db.get_value("Overseas Cost Item", item_name, "batch")
        if item_batch != batch_doc_name:
            error_count += 1
            results.append(
                {
                    "ok": False,
                    "changed": False,
                    "item_name": item_name,
                    "fieldname": fieldname,
                    "message": f"明细 {item_name} 不属于批次 {batch_doc_name}。",
                }
            )
            continue

        result = update_item_field(item_name, fieldname, value, version_name=version_name, remark=edit_remark)
        results.append(result)
        if not result.get("ok"):
            error_count += 1
        elif result.get("changed"):
            changed_count += 1
        else:
            skipped_count += 1

    if changed_count or skipped_count or error_count:
        _insert_audit_log(
            batch_doc_name=batch_doc_name,
            version_name=version_name,
            action_type="BATCH_EDIT",
            action_remark=f"批量字段更新：成功 {changed_count}，跳过 {skipped_count}，失败 {error_count}",
        )
        _frappe.db.commit()

    return {
        "ok": error_count == 0,
        "batch_name": batch_doc_name,
        "version_name": version_name,
        "changed_count": changed_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "results": results,
        "message": "批量字段更新完成。" if error_count == 0 else "批量字段更新部分失败，请查看 results。",
    }


def create_item(
    batch_name: str,
    item_payload: str | dict | None = None,
    version_name: str | None = None,
    remark: str | None = None,
) -> dict:
    try:
        payload = _load_payload(item_payload)
    except (TypeError, ValueError, _json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "dry_run": _frappe is None,
            "batch_name": batch_name,
            "version_name": version_name,
            "message": f"新增物料参数解析失败：{exc}",
        }

    if _frappe is None:
        values = _build_new_item_values(batch_name, version_name or "", payload)
        audit_service.build_audit_stub("BATCH_EDIT", {"batch_name": batch_name, "action": "CREATE_ITEM"})
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "item": values,
            "message": "当前未连接 Frappe，已返回新增物料预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    if not resolved_version_name:
        return {"ok": False, "batch_name": batch_doc_name, "message": "当前批次没有可新增明细的版本。"}

    latest = _frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": resolved_version_name},
        fields=["row_no"],
        order_by="row_no desc",
        limit_page_length=1,
    )
    next_row_no = int((latest[0].get("row_no") if latest else 0) or 0) + 1
    values = _build_new_item_values(batch_doc_name, resolved_version_name, payload, row_no=next_row_no)
    item_doc = _frappe.get_doc(values).insert(ignore_permissions=True)
    _frappe.db.set_value("Overseas Cost Batch", batch_doc_name, "status", "Dirty", update_modified=True)
    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=resolved_version_name,
        action_type="BATCH_EDIT",
        field_name="item",
        row_no=next_row_no,
        new_value=_json_dumps({k: v for k, v in values.items() if k != "doctype"}),
        action_remark=remark or "新增物料",
    )
    _frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "item_name": item_doc.name,
        "row_no": next_row_no,
        "message": "物料已新增，批次已标记为 Dirty。",
    }


def delete_item(item_name: str, batch_name: str | None = None, version_name: str | None = None, remark: str | None = None) -> dict:
    if not item_name:
        return {"ok": False, "dry_run": _frappe is None, "message": "缺少要删除的物料明细。"}

    if _frappe is None:
        audit_service.build_audit_stub("BATCH_EDIT", {"item_name": item_name, "action": "DELETE_ITEM"})
        return {
            "ok": True,
            "dry_run": True,
            "item_name": item_name,
            "batch_name": batch_name,
            "version_name": version_name,
            "message": "当前未连接 Frappe，已返回删除物料预览。",
        }

    item_doc = _frappe.get_doc("Overseas Cost Item", item_name)
    if batch_name:
        batch_doc_name = _resolve_batch_name(batch_name)
        if batch_doc_name and item_doc.batch != batch_doc_name:
            return {"ok": False, "message": f"物料 {item_name} 不属于批次 {batch_doc_name}。"}

    old_snapshot = {
        "name": item_doc.name,
        "row_no": getattr(item_doc, "row_no", None),
        "material_code": getattr(item_doc, "material_code", ""),
        "product_name": getattr(item_doc, "product_name", ""),
        "quantity": getattr(item_doc, "quantity", None),
        "goods_value": getattr(item_doc, "goods_value", None),
    }
    batch_doc_name = item_doc.batch
    resolved_version_name = version_name or item_doc.version
    row_no = getattr(item_doc, "row_no", None)

    _frappe.delete_doc("Overseas Cost Item", item_name, ignore_permissions=True)
    _frappe.db.set_value("Overseas Cost Batch", batch_doc_name, "status", "Dirty", update_modified=True)
    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=resolved_version_name,
        action_type="BATCH_EDIT",
        field_name="item",
        row_no=row_no,
        old_value=_json_dumps(old_snapshot),
        action_remark=remark or "删除物料",
    )
    _frappe.db.commit()

    return {
        "ok": True,
        "item_name": item_name,
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "message": "物料已删除，批次已标记为 Dirty。",
    }


def delete_batch(batch_name: str, remark: str | None = None) -> dict:
    if not batch_name:
        return {"ok": False, "dry_run": _frappe is None, "message": "缺少要删除的批次。"}

    if _frappe is None:
        audit_service.build_audit_stub("BATCH_DELETE", {"batch_name": batch_name})
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "deleted_counts": {},
            "message": "当前未连接 Frappe，已返回删除批次预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}。"}

    delete_plan = [
        ("Overseas Cost Audit Log", "audit_log_count"),
        ("Overseas Cost Attachment", "attachment_count"),
        ("Overseas Cost Allocation Rule", "rule_count"),
        ("Overseas Cost Item", "item_count"),
        ("Overseas Cost Version", "version_count"),
    ]
    names_by_doctype: dict[str, list[str]] = {}
    deleted_counts: dict[str, int] = {}
    for doctype, count_key in delete_plan:
        rows = _frappe.get_all(
            doctype,
            filters={"batch": batch_doc_name},
            fields=["name"],
            limit_page_length=10000,
        )
        names = [row["name"] for row in rows]
        names_by_doctype[doctype] = names
        deleted_counts[count_key] = len(names)

    for doctype, _count_key in delete_plan:
        for name in names_by_doctype.get(doctype, []):
            _frappe.db.delete(doctype, {"name": name})

    _frappe.db.delete("Overseas Cost Batch", {"name": batch_doc_name})
    deleted_counts["batch_count"] = 1
    _frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "deleted_counts": deleted_counts,
        "message": remark or "批次及关联数据已删除。",
    }


def recalculate_batch(batch_name: str, version_name: str | None = None) -> dict:
    if _frappe is None:
        summary_snapshot = version_service.build_empty_summary_snapshot()
        audit_service.build_audit_stub("RECALCULATE", {"batch_name": batch_name})
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "summary_snapshot": summary_snapshot,
            "message": "当前未连接 Frappe，已返回重算预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    if not resolved_version_name:
        return {"ok": False, "batch_name": batch_doc_name, "message": "当前批次没有可重算版本。"}

    version_context = _get_version_context(resolved_version_name)
    fx_rmb_to_mxn = _to_float(version_context.get("fx_rmb_to_mxn"), default=DEFAULT_FX_RMB_TO_MXN) or DEFAULT_FX_RMB_TO_MXN
    fx_usd_to_rmb = _to_float(version_context.get("fx_usd_to_rmb")) or None
    items = _get_items(batch_doc_name, resolved_version_name)
    rules = _get_rules(batch_doc_name, resolved_version_name)
    calculated_rows, summary_snapshot = calculate_item_rows(
        items,
        rules,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
        fx_usd_to_rmb=fx_usd_to_rmb,
    )

    for row in calculated_rows:
        updates = {fieldname: row.get(fieldname) for fieldname in DEFAULT_CALC_FIELDS}
        _frappe.db.set_value("Overseas Cost Item", row["name"], updates, update_modified=False)

    _frappe.db.set_value(
        "Overseas Cost Batch",
        batch_doc_name,
        {
            "status": "Calculated",
            "item_count": summary_snapshot["item_count"],
            "total_goods_value": summary_snapshot["total_goods_value"],
            "total_gross_weight_kg": summary_snapshot["total_gross_weight_kg"],
            "estimated_total_cost_rmb": summary_snapshot["total_cost_rmb"],
        },
        update_modified=True,
    )
    _frappe.db.set_value(
        "Overseas Cost Version",
        resolved_version_name,
        {
            "summary_snapshot_json": _json_dumps(summary_snapshot),
            "rule_snapshot_json": _json_dumps(rules),
            "calculated_at": _now(),
        },
        update_modified=True,
    )
    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=resolved_version_name,
        action_type="RECALCULATE",
        action_remark=f"重算完成，规则数 {summary_snapshot['rule_count']}，明细数 {summary_snapshot['item_count']}",
    )
    _frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "summary_snapshot": summary_snapshot,
        "message": "整票重算完成。",
    }


def update_allocation_rule(batch_name: str, version_name: str, rule_payload: str) -> dict:
    if _frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "rule_payload": rule_payload,
            "message": "当前未连接 Frappe，已返回规则更新预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    payload = _json.loads(rule_payload or "{}")
    rule_name = payload.get("rule_id") or payload.get("name")
    rule_code = payload.get("rule_code")
    values = {
        key: payload[key]
        for key in (
            "rule_code",
            "expense_category",
            "allocation_basis",
            "basis_field",
            "currency",
            "amount",
            "priority_no",
            "is_active",
            "is_enabled",
            "remark",
        )
        if key in payload
    }
    values.update({"batch": batch_doc_name, "version": version_name})

    if not rule_name and rule_code:
        rule_name = _frappe.db.get_value(
            "Overseas Cost Allocation Rule",
            {"batch": batch_doc_name, "version": version_name, "rule_code": rule_code},
            "name",
        )

    if rule_name:
        _frappe.db.set_value("Overseas Cost Allocation Rule", rule_name, values, update_modified=True)
    else:
        values["doctype"] = "Overseas Cost Allocation Rule"
        rule_name = _frappe.get_doc(values).insert(ignore_permissions=True).name

    _frappe.db.set_value("Overseas Cost Batch", batch_doc_name, "status", "Dirty", update_modified=True)
    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=version_name,
        action_type="BATCH_EDIT",
        field_name="allocation_rule",
        new_value=rule_payload,
        action_remark="更新分摊规则",
    )
    _frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "version_name": version_name,
        "rule_name": rule_name,
        "message": "分摊规则已更新，批次已标记为 Dirty。",
    }


def create_version(batch_name: str, source_version_name: str, version_type: str) -> dict:
    if _frappe is None:
        audit_service.build_audit_stub("CREATE_VERSION", {"batch_name": batch_name, "version_type": version_type})
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "source_version_name": source_version_name,
            "version_type": version_type,
            "message": "当前未连接 Frappe，已返回版本创建预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    source_version = source_version_name or _resolve_version_name(batch_doc_name)
    if not source_version:
        return {"ok": False, "message": "没有可复制的源版本。"}

    version_code = f"{version_type}-{_now().replace(':', '').replace('-', '').replace(' ', '-')}"
    source_doc = _frappe.get_doc("Overseas Cost Version", source_version)
    new_version = _frappe.get_doc(
        {
            "doctype": "Overseas Cost Version",
            "batch": batch_doc_name,
            "version_code": version_code,
            "version_type": version_type,
            "status": "Active",
            "is_current": 0,
            "source_type": "Clone",
            "fx_usd_to_rmb": getattr(source_doc, "fx_usd_to_rmb", None),
            "fx_rmb_to_mxn": getattr(source_doc, "fx_rmb_to_mxn", None),
            "rule_snapshot_json": getattr(source_doc, "rule_snapshot_json", None),
            "summary_snapshot_json": getattr(source_doc, "summary_snapshot_json", None),
            "remark": f"Cloned from {source_version}",
        }
    ).insert(ignore_permissions=True)

    for row in _frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": source_version},
        fields=["name"],
        limit_page_length=10000,
    ):
        item_doc = _frappe.get_doc("Overseas Cost Item", row["name"])
        new_item = _frappe.copy_doc(item_doc)
        new_item.version = new_version.name
        new_item.insert(ignore_permissions=True)

    for row in _frappe.get_all(
        "Overseas Cost Allocation Rule",
        filters={"batch": batch_doc_name, "version": source_version},
        fields=["name"],
        limit_page_length=1000,
    ):
        rule_doc = _frappe.get_doc("Overseas Cost Allocation Rule", row["name"])
        new_rule = _frappe.copy_doc(rule_doc)
        new_rule.version = new_version.name
        new_rule.insert(ignore_permissions=True)

    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=new_version.name,
        action_type="CREATE_VERSION",
        action_remark=f"从 {source_version} 复制生成 {version_type} 版本",
    )
    _frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "source_version_name": source_version,
        "version_name": new_version.name,
        "version_type": version_type,
        "message": "版本已创建。",
    }


def switch_version(batch_name: str, target_version_name: str) -> dict:
    if _frappe is None:
        audit_service.build_audit_stub("SWITCH_VERSION", {"batch_name": batch_name, "target_version_name": target_version_name})
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "target_version_name": target_version_name,
            "message": "当前未连接 Frappe，已返回版本切换预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    versions = _frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=["name"],
        limit_page_length=1000,
    )
    version_names = {row["name"] for row in versions}
    if target_version_name not in version_names:
        return {
            "ok": False,
            "batch_name": batch_doc_name,
            "target_version_name": target_version_name,
            "message": "目标版本不属于当前批次，无法切换。",
        }

    for row in versions:
        _frappe.db.set_value("Overseas Cost Version", row["name"], "is_current", 1 if row["name"] == target_version_name else 0)

    _frappe.db.set_value("Overseas Cost Batch", batch_doc_name, "current_version", target_version_name, update_modified=True)
    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=target_version_name,
        action_type="SWITCH_VERSION",
        action_remark=f"切换当前版本为 {target_version_name}",
    )
    _frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "target_version_name": target_version_name,
        "message": "当前版本已切换。",
    }
