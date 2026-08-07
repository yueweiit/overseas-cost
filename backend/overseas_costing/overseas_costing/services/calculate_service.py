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

from overseas_costing.services import allocation_service, audit_service, source_priority_service, version_service


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
    "purchase_currency": {"RMB", "USD", "MXN"},
    "parse_status": {"PENDING", "SUCCESS", "PARTIAL", "FAILED", "MANUAL"},
}
SELECT_ITEM_ALIASES = {
    "transport_mode": {
        "海运": "SEA",
        "空运": "AIR",
        "快递": "EXPRESS",
    },
    "purchase_currency": {
        "人民币": "RMB",
        "人民币RMB": "RMB",
        "CNY": "RMB",
        "美元": "USD",
        "美金": "USD",
        "美元Dólar": "USD",
        "美元Dolar": "USD",
        "比索": "MXN",
        "墨西哥比索": "MXN",
    },
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
    "material_code",
    "product_name",
    "spec_model",
    "transport_mode",
    "unit_price",
    "quantity",
    "goods_value",
    "gross_weight_kg",
    "volume_m3",
    "mexico_customs_mxn",
    "mexico_customs_rmb",
    "mexico_customs_usd",
    "china_misc_rmb",
    "china_misc_mxn",
    "china_ocean_usd",
    "china_to_mexico_freight_rmb",
    "mexico_inland_mxn",
    "mexico_misc_mxn",
    "mexico_inland_misc_rmb",
    "igi_amount",
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


def _normalize_currency_code(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "RMB"
    compact = text.replace(" ", "").lower()
    if "rmb" in compact or "cny" in compact or "人民币" in compact:
        return "RMB"
    if "usd" in compact or "dólar" in compact or "dolar" in compact or "美元" in compact or "美金" in compact:
        return "USD"
    if "mxn" in compact or "peso" in compact or "pesos" in compact or "比索" in compact or "墨西哥" in compact:
        return "MXN"
    return text.upper()


def _amount_to_rmb(amount: float, currency: str | None, fx_rmb_to_mxn: float, fx_usd_to_rmb: float | None) -> float:
    currency_code = _normalize_currency_code(currency)
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
    if basis in {"chargeable_weight", "chargeable_weight_kg"}:
        return _chargeable_weight_value(item)
    return _to_float(item.get("goods_value"))


def _chargeable_weight_value(item: dict) -> float:
    explicit = _to_float(item.get("chargeable_weight_kg"))
    if explicit:
        return explicit
    gross_weight = _to_float(item.get("gross_weight_kg"))
    volume_weight = _to_float(item.get("volume_weight_kg"))
    return max(gross_weight, volume_weight)


def _first_nonzero(items: list[dict], fieldname: str) -> float:
    for item in items:
        value = _to_float(item.get(fieldname))
        if value:
            return value
    return 0.0


def _has_any_positive(items: list[dict], fieldname: str) -> bool:
    return any(_to_float(item.get(fieldname)) for item in items)


def _total_value(items: list[dict], fieldname: str) -> float:
    return sum(_to_float(item.get(fieldname)) for item in items)


def _first_transport_mode(items: list[dict]) -> str:
    for item in items:
        value = str(item.get("transport_mode") or "").strip().upper()
        if value:
            return value
    return ""


def _default_freight_basis(items: list[dict]) -> str:
    if _total_value(items, "gross_weight_kg"):
        return "gross_weight"
    if sum(_chargeable_weight_value(item) for item in items):
        return "chargeable_weight"
    if _total_value(items, "volume_m3"):
        return "volume"
    return "goods_value"


def _add_basic_rule(
    specs: list[dict],
    *,
    items: list[dict],
    fieldname: str,
    rule_code: str,
    expense_category: str,
    allocation_basis: str,
    currency: str,
    remark: str,
    priority_no: int,
) -> None:
    amount = _first_nonzero(items, fieldname)
    if not amount:
        return
    specs.append(
        {
            "rule_code": rule_code,
            "expense_category": expense_category,
            "allocation_basis": allocation_basis,
            "basis_field": allocation_basis,
            "currency": currency,
            "amount": amount,
            "remark": remark,
            "priority_no": priority_no,
            "is_enabled": 1,
            "is_system_suggestion": 1,
        }
    )


def _fallback_rules_from_items(items: list[dict]) -> list[dict]:
    freight_basis = _default_freight_basis(items)
    misc_basis = "gross_weight"
    specs: list[dict] = []
    _add_basic_rule(
        specs,
        items=items,
        fieldname="china_misc_rmb",
        rule_code="china_misc_rmb",
        expense_category="中国段杂费",
        allocation_basis=misc_basis,
        currency="RMB",
        remark="系统基础分摊：来自明细字段“中国运输及相关杂费 RMB”，默认先按毛重分摊并填入每行金额；如属于抛货或特殊费用，人工可改为体积/计费重或其他口径后重算。",
        priority_no=10,
    )
    _add_basic_rule(
        specs,
        items=items,
        fieldname="china_misc_mxn",
        rule_code="china_misc_mxn",
        expense_category="中国段杂费",
        allocation_basis=misc_basis,
        currency="MXN",
        remark="系统基础分摊：来自明细字段“中国运输及相关杂费 MXN”，默认先按毛重分摊并填入每行金额；如属于抛货或特殊费用，人工可改为体积/计费重或其他口径后重算。",
        priority_no=11,
    )
    _add_basic_rule(
        specs,
        items=items,
        fieldname="china_ocean_usd",
        rule_code="china_ocean_usd",
        expense_category="中国海运费",
        allocation_basis=freight_basis,
        currency="USD",
        remark="系统基础分摊：来自明细字段“中国海运 USD”，运输费用默认先按毛重分摊；如确认属于抛货，可人工改为体积/计费重后重算，体积小重量大仍按重量。",
        priority_no=20,
    )
    _add_basic_rule(
        specs,
        items=items,
        fieldname="china_to_mexico_freight_rmb",
        rule_code="china_to_mexico_freight_rmb",
        expense_category="中国到墨西哥运费",
        allocation_basis=freight_basis,
        currency="RMB",
        remark="系统基础分摊：来自国际物流 OA、货代账单或明细字段“中国到墨西哥运费 RMB”，运输费用默认先按毛重分摊；如确认属于抛货，可人工改为体积/计费重后重算，体积小重量大仍按重量。",
        priority_no=21,
    )
    _add_basic_rule(
        specs,
        items=items,
        fieldname="mexico_inland_mxn",
        rule_code="mexico_inland_mxn",
        expense_category="墨西哥内陆运输费",
        allocation_basis=misc_basis,
        currency="MXN",
        remark="系统基础分摊：来自明细字段“墨西哥内陆运输费用 MXN”，按重量分摊；缺少重量时暂停该费用分摊并提示补充数据。",
        priority_no=30,
    )
    _add_basic_rule(
        specs,
        items=items,
        fieldname="mexico_misc_mxn",
        rule_code="mexico_misc_mxn",
        expense_category="墨西哥杂费",
        allocation_basis=misc_basis,
        currency="MXN",
        remark="系统基础分摊：来自明细字段“墨西哥杂费 MXN”，按重量分摊；缺少重量时暂停该费用分摊并提示补充数据。",
        priority_no=31,
    )
    _add_basic_rule(
        specs,
        items=items,
        fieldname="mexico_inland_misc_rmb",
        rule_code="mexico_inland_misc_rmb",
        expense_category="墨西哥内陆/杂费",
        allocation_basis=misc_basis,
        currency="RMB",
        remark="系统基础分摊：来自清关资料、墨西哥本地费用资料或明细字段“墨西哥内陆运输+杂费 RMB”，默认按重量分摊并填入每行金额，人工可复核调整。",
        priority_no=32,
    )
    return specs


TAX_COMPONENT_FIELDS = ("igi_amount", "iva_amount", "dta", "prv_duty", "prv_iva")
CUSTOMS_SERVICE_FIELDS = (
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
)


def _direct_customs_amounts(row: dict, fx_rmb_to_mxn: float, fx_usd_to_rmb: float | None) -> tuple[float, float, dict]:
    customs_mxn = _to_float(row.get("mexico_customs_mxn"))
    customs_rmb = _to_float(row.get("mexico_customs_rmb"))
    customs_usd = _to_float(row.get("mexico_customs_usd"))
    source = "墨西哥清关费用字段"
    source_type = "customs_total"
    tax_mxn = 0.0
    service_mxn = 0.0
    policy = "采用清关费用总额，不再叠加关税、增值税和清关服务明细"

    if not customs_mxn and not customs_rmb and customs_usd and fx_usd_to_rmb:
        customs_rmb = customs_usd * fx_usd_to_rmb
        customs_mxn = customs_rmb * fx_rmb_to_mxn
        source = "墨西哥清关费用 USD"

    if not customs_mxn and not customs_rmb:
        source_type = "customs_components"
        tax_mxn = _to_float(row.get("import_tax_total"))
        if not tax_mxn:
            tax_mxn = sum(_to_float(row.get(fieldname)) for fieldname in TAX_COMPONENT_FIELDS)
        service_mxn = sum(_to_float(row.get(fieldname)) for fieldname in CUSTOMS_SERVICE_FIELDS)
        customs_mxn = tax_mxn + service_mxn
        if customs_mxn:
            source = "税费/清关明细字段"
            policy = "未提供清关费用总额，采用物料实际税费与清关服务明细合计"
        else:
            source = "未提供清关费用"
            policy = "未识别到清关费用总额或组成明细"

    if not customs_rmb and customs_mxn:
        customs_rmb = _safe_div(customs_mxn, fx_rmb_to_mxn)
    if not customs_mxn and customs_rmb:
        customs_mxn = customs_rmb * fx_rmb_to_mxn

    return customs_rmb, customs_mxn, {
        "source": source,
        "source_type": source_type,
        "policy": policy,
        "tax_policy": "关税按物料品类/海关编码实际税率；IVA 增值税按 CIF 价值加关税后乘 16%，最终以完税凭证或实际付款为准。",
        "tax_mxn": _round_money(tax_mxn, 6),
        "service_mxn": _round_money(service_mxn, 6),
    }


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
    total_chargeable_weight = sum(_chargeable_weight_value(row) for row in rows)
    basis_totals = {
        "goods_value": total_goods_value,
        "gross_weight": total_gross_weight,
        "volume": total_volume,
        "chargeable_weight": total_chargeable_weight,
        "chargeable_weight_kg": total_chargeable_weight,
    }
    total_fee_pool_rmb = sum(
        _amount_to_rmb(
            _to_float(rule.get("amount")),
            rule.get("currency"),
            fx_rmb_to_mxn,
            fx_usd_to_rmb,
        )
        for rule in enabled_rules
    )

    total_cost_rmb = 0.0
    total_logistics_mxn = 0.0
    calculated_rows = []

    for row in rows:
        goods_value = _to_float(row.get("goods_value"))
        quantity = _to_float(row.get("quantity"))
        mexico_customs_rmb, mexico_customs_mxn, customs_detail = _direct_customs_amounts(
            row,
            fx_rmb_to_mxn,
            fx_usd_to_rmb,
        )

        allocated_other_rmb = 0.0
        allocated_other_mxn = 0.0
        freight_alloc_rmb = 0.0
        freight_alloc_mxn = 0.0
        allocated_rules = []

        for rule in enabled_rules:
            basis = rule.get("allocation_basis") or rule.get("basis_field") or "goods_value"
            basis_total = basis_totals.get(basis, 0.0)
            ratio = _basis_value(row, basis) / basis_total if basis_total else 0.0
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
                    "expense_category": rule.get("expense_category") or "",
                    "amount": _round_money(_to_float(rule.get("amount")), 6),
                    "currency": _normalize_currency_code(rule.get("currency")),
                    "amount_rmb": _round_money(amount_rmb, 6),
                    "basis": basis,
                    "basis_label": rule.get("allocation_basis") or rule.get("basis_field") or basis,
                    "ratio": ratio,
                    "allocated_rmb": _round_money(allocated_rmb, 6),
                    "allocated_mxn": _round_money(allocated_mxn, 6),
                    "remark": rule.get("remark") or "",
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
                        "chargeable_weight_kg": _round_money(_chargeable_weight_value(row), 6),
                        "fx_rmb_to_mxn": fx_rmb_to_mxn,
                        "fx_usd_to_rmb": fx_usd_to_rmb,
                        "allocated_rules": allocated_rules,
                        "allocated_other_rmb": _round_money(allocated_other_rmb, 6),
                        "mexico_customs_rmb": _round_money(mexico_customs_rmb, 6),
                        "mexico_customs_mxn": _round_money(mexico_customs_mxn, 6),
                        "direct_customs": {
                            **customs_detail,
                            "amount_rmb": _round_money(mexico_customs_rmb, 6),
                            "amount_mxn": _round_money(mexico_customs_mxn, 6),
                        },
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
        "total_chargeable_weight_kg": _round_money(total_chargeable_weight, 6),
        "total_logistics_mxn": _round_money(total_logistics_mxn, 6),
        "total_cost_rmb": _round_money(total_cost_rmb, 6),
        "fee_pool_rmb": _round_money(total_fee_pool_rmb, 6),
        "item_count": len(rows),
        "rule_count": len(enabled_rules),
        "source_priority_policy": source_priority_service.get_source_priority_policy(),
    }
    summary["calculation_review"] = _build_calculation_review(calculated_rows, summary, enabled_rules)
    return calculated_rows, summary


def _build_calculation_review(
    calculated_rows: list[dict],
    summary_snapshot: dict,
    rules_for_calculation: list[dict] | None = None,
    ai_allocation: dict | None = None,
) -> dict:
    rows = calculated_rows or []
    rules = rules_for_calculation or []
    positive_rules = [
        rule
        for rule in rules
        if _is_rule_enabled(rule) and (_to_float(rule.get("amount")) or _to_float(rule.get("amount_rmb")))
    ]
    item_count = len(rows) or int(_to_float(summary_snapshot.get("item_count")))
    total_goods_value = _to_float(summary_snapshot.get("total_goods_value"))
    total_cost_rmb = _to_float(summary_snapshot.get("total_cost_rmb"))
    fee_pool_rmb = _to_float(summary_snapshot.get("fee_pool_rmb"))
    basis_values = {str(rule.get("allocation_basis") or rule.get("basis_field") or "") for rule in positive_rules}
    needs_weight = "gross_weight" in basis_values
    needs_volume = "volume" in basis_values or "volume_m3" in basis_values

    counts = {
        "missing_quantity": sum(1 for row in rows if not _to_float(row.get("quantity"))),
        "missing_unit_price": sum(1 for row in rows if not _to_float(row.get("unit_price"))),
        "missing_goods_value": sum(1 for row in rows if not _to_float(row.get("goods_value"))),
        "missing_gross_weight": sum(1 for row in rows if not _to_float(row.get("gross_weight_kg"))),
        "missing_volume": sum(1 for row in rows if not _to_float(row.get("volume_m3"))),
        "missing_total_unit_cost": sum(1 for row in rows if not _to_float(row.get("total_unit_rmb"))),
    }
    allocated_fee_rmb = 0.0
    for row in rows:
        allocated_fee_rmb += _to_float(row.get("freight_alloc_rmb"))
        derived = _load_json_dict(row.get("derived_json"))
        allocated_fee_rmb += _to_float(derived.get("allocated_other_rmb"))

    reasons: list[str] = []
    blocking = False
    if item_count <= 0:
        blocking = True
        reasons.append("当前没有物料明细，不能试算综合成本")
    if item_count > 0 and total_goods_value <= 0:
        blocking = True
        reasons.append("采购货值为空，综合成本没有计算基准")
    basis_totals = {
        "goods_value": sum(_to_float(row.get("goods_value")) for row in rows),
        "gross_weight": sum(_to_float(row.get("gross_weight_kg")) for row in rows),
        "volume": sum(_to_float(row.get("volume_m3")) for row in rows),
        "chargeable_weight": sum(_chargeable_weight_value(row) for row in rows),
        "chargeable_weight_kg": sum(_chargeable_weight_value(row) for row in rows),
    }
    basis_labels = {
        "goods_value": "货值",
        "gross_weight": "毛重",
        "volume": "体积",
        "chargeable_weight": "计费重",
        "chargeable_weight_kg": "计费重",
    }
    unavailable_bases = [basis for basis in basis_values if basis in basis_totals and basis_totals[basis] <= 0]
    if unavailable_bases:
        blocking = True
        missing_labels = "、".join(basis_labels.get(basis, basis) for basis in sorted(unavailable_bases))
        reasons.append(f"当前费用规则需要按{missing_labels}分摊，但整批缺少对应数据，相关费用未分摊")
    if counts["missing_quantity"]:
        reasons.append(
            f"数量缺失或为 0 的物料 {counts['missing_quantity']} 行"
            f"{_problem_row_examples(rows, lambda row: not _to_float(row.get('quantity')))}"
        )
    if counts["missing_unit_price"]:
        reasons.append(
            f"采购单价缺失或为 0 的物料 {counts['missing_unit_price']} 行"
            f"{_problem_row_examples(rows, lambda row: not _to_float(row.get('unit_price')))}"
        )
    if counts["missing_goods_value"]:
        reasons.append(
            f"货值缺失或为 0 的物料 {counts['missing_goods_value']} 行"
            f"{_problem_row_examples(rows, lambda row: not _to_float(row.get('goods_value')))}"
        )
    if needs_weight and counts["missing_gross_weight"]:
        reasons.append(
            f"当前按重量分摊，毛重缺失或为 0 的物料 {counts['missing_gross_weight']} 行"
            f"{_problem_row_examples(rows, lambda row: not _to_float(row.get('gross_weight_kg')))}"
        )
    if basis_values.intersection({"chargeable_weight", "chargeable_weight_kg"}):
        missing_chargeable = sum(1 for row in rows if not _chargeable_weight_value(row))
        if missing_chargeable:
            reasons.append(
                f"当前按计费重分摊，计费重/毛重/体积重均缺失或为 0 的物料 {missing_chargeable} 行"
                f"{_problem_row_examples(rows, lambda row: not _chargeable_weight_value(row))}"
            )
    if needs_volume and counts["missing_volume"]:
        reasons.append(
            f"当前按体积分摊，体积缺失或为 0 的物料 {counts['missing_volume']} 行"
            f"{_problem_row_examples(rows, lambda row: not _to_float(row.get('volume_m3')))}"
        )
    if item_count > 0 and not positive_rules:
        reasons.append("当前没有费用池，费用分摊金额为 0")
    elif positive_rules and allocated_fee_rmb <= 0:
        reasons.append("费用池已识别，但分摊结果为 0，请检查分摊依据字段")
    unallocated_fee_rmb = max(fee_pool_rmb - allocated_fee_rmb, 0.0)
    if positive_rules and unallocated_fee_rmb > 0.01:
        reasons.append(f"费用池仍有 {_round_money(unallocated_fee_rmb, 2):g} RMB 未分摊")
    if total_cost_rmb <= 0 and item_count > 0:
        reasons.append("综合成本未生成或为 0")

    ai_message = ""
    ai_notes: list[str] = []
    if ai_allocation is not None:
        ai_message = ai_allocation.get("message") or ai_allocation.get("reason") or ""
        if ai_allocation.get("ok"):
            ai_notes.append("AI已选择分摊依据，金额由系统按规则计算")
        elif ai_message:
            reasons.append(f"AI未返回可用分摊口径，已使用系统基础规则：{ai_message}")

    if blocking:
        status = "blocked"
        label = "待补数据"
    elif reasons:
        status = "review"
        label = "需人工复核"
    else:
        status = "usable"
        label = "可先采用"
        reasons.append("核心采购金额、费用池和分摊结果已生成，可作为演示试算结果")
    if ai_notes:
        reasons.extend(ai_notes)

    return {
        "status": status,
        "label": label,
        "reason": "；".join(reasons[:4]),
        "reasons": reasons,
        "counts": counts,
        "fee_rule_count": len(positive_rules),
        "fee_pool_rmb": _round_money(fee_pool_rmb, 6),
        "allocated_fee_rmb": _round_money(allocated_fee_rmb, 6),
        "unallocated_fee_rmb": _round_money(unallocated_fee_rmb, 6),
        "total_goods_value": _round_money(total_goods_value, 6),
        "total_cost_rmb": _round_money(total_cost_rmb, 6),
        "ai_used": bool((ai_allocation or {}).get("ok")),
        "ai_message": ai_message,
    }


def _load_json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = _json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _problem_row_examples(rows: list[dict], predicate, limit: int = 3) -> str:
    examples = []
    for row in rows:
        if not predicate(row):
            continue
        row_no = row.get("row_no") or row.get("idx") or ""
        material = str(row.get("material_code") or "").strip()
        product = str(row.get("product_name") or row.get("spec_model") or "").strip()
        parts = []
        if row_no:
            parts.append(f"第{row_no}行")
        if material:
            parts.append(material)
        if product:
            parts.append(product)
        examples.append(" ".join(parts) or str(row.get("name") or "未命名物料"))
        if len(examples) >= limit:
            break
    if not examples:
        return ""
    suffix = "等" if sum(1 for row in rows if predicate(row)) > len(examples) else ""
    return f"（{', '.join(examples)}{suffix}）"


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
            "remark",
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
    candidate_rules = [rule for rule in rules if _is_rule_enabled(rule) and _to_float(rule.get("amount"))]
    if not candidate_rules:
        candidate_rules = _fallback_rules_from_items(items)
    ai_allocation = allocation_service.suggest_allocation_rules_with_ai(
        items=items,
        candidate_rules=candidate_rules,
        context={
            "batch_name": batch_doc_name,
            "version_name": resolved_version_name,
            "transport_mode": items[0].get("transport_mode") if items else "",
            "fx_rmb_to_mxn": fx_rmb_to_mxn,
            "fx_usd_to_rmb": fx_usd_to_rmb,
        },
    )
    rules_for_calculation = ai_allocation.get("rules") or candidate_rules
    calculated_rows, summary_snapshot = calculate_item_rows(
        items,
        rules_for_calculation,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
        fx_usd_to_rmb=fx_usd_to_rmb,
    )
    summary_snapshot["ai_allocation"] = {
        "ok": bool(ai_allocation.get("ok")),
        "action": ai_allocation.get("action") or "",
        "source": ai_allocation.get("source") or "system",
        "model": ai_allocation.get("model") or "",
        "message": ai_allocation.get("message") or ai_allocation.get("reason") or "",
        "rule_count": len(rules_for_calculation),
    }
    summary_snapshot["calculation_review"] = _build_calculation_review(
        calculated_rows,
        summary_snapshot,
        rules_for_calculation,
        ai_allocation,
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
            "rule_snapshot_json": _json_dumps(rules_for_calculation),
            "calculated_at": _now(),
        },
        update_modified=True,
    )
    allocation_source = "AI基础分摊" if ai_allocation.get("ok") else "系统基础分摊"
    _insert_audit_log(
        batch_doc_name=batch_doc_name,
        version_name=resolved_version_name,
        action_type="RECALCULATE",
        action_remark=f"重算完成，{allocation_source}规则数 {summary_snapshot['rule_count']}，明细数 {summary_snapshot['item_count']}",
    )
    _frappe.db.commit()

    ai_message = ai_allocation.get("message") or ai_allocation.get("reason") or ""
    if ai_allocation.get("ok"):
        result_message = "整票重算完成，AI 已选择基础分摊口径并填入每行分摊金额。"
    elif "没有可供 AI 判断的费用池" in ai_message:
        result_message = "整票重算完成，当前没有可用费用池；已填入货值/重量比例和基础综合成本，费用分摊金额为 0。"
    elif "未配置 AI 接口密钥" in ai_message:
        result_message = "整票重算完成，AI 接口密钥未配置，已使用系统基础规则。"
    elif ai_message:
        result_message = f"整票重算完成，AI 未生成分摊口径：{ai_message}"
    else:
        result_message = "整票重算完成，AI 未生成分摊口径，已使用系统基础分摊规则。"

    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "summary_snapshot": summary_snapshot,
        "allocation_rules": rules_for_calculation,
        "message": result_message,
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
