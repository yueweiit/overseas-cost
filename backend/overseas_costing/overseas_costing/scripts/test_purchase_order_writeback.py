"""本地验证海外成本写入 ERPNext 采购订单明细。

本脚本只使用 ``development.localhost``。先用 ``list_complete_candidates``
只读筛选合格批次，再用 ``run_complete_batch`` 复制指定批次的全部明细，
生成 ``ERPTEST-`` 前缀的 Item 和 Draft Purchase Order，并回读字段。
不调用 DeepLinkERP HTTP 接口，不提交采购订单，也不改库存估值。

用法：
bench --site development.localhost execute \
  overseas_costing.scripts.test_purchase_order_writeback.run_hpcu5155607

清理某次测试：
bench --site development.localhost execute \
  overseas_costing.scripts.test_purchase_order_writeback.cleanup --kwargs \
  '{"test_batch_no":"ERPTEST-HPCU5155607-20260901103000"}'
"""

from __future__ import annotations

from datetime import datetime

try:
    import frappe
    from frappe.utils import flt
except ModuleNotFoundError:  # pragma: no cover - bench execute provides Frappe
    frappe = None

    def flt(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0


SOURCE_BATCH_NO = "HPCU5155607"
TEST_PREFIX = "ERPTEST-HPCU5155607-"
TEST_ITEM_PREFIX = "ERPTEST-HPCU5155607-"
TEST_ITEM_COUNT = 4
# This is an executable bench script, not a pytest module.
__test__ = False
ITEM_FIELDS = [
    "item_code",
    "rate",
    "custom_overseas_original_unit_price",
    "custom_overseas_comprehensive_unit_price",
    "custom_overseas_original_amount",
    "custom_overseas_comprehensive_amount",
    "custom_overseas_freight_alloc_amount",
    "custom_overseas_clearance_alloc_amount",
    "custom_overseas_tax_alloc_amount",
    "custom_overseas_batch_no",
    "custom_overseas_cost_version",
    "custom_overseas_business_entity",
    "custom_overseas_cost_center",
]


def run_hpcu5155607(test_batch_no: str | None = None, reuse_existing: bool = True) -> dict:
    """验证本地草稿采购订单，默认复用最近一条测试单，避免重复创建。"""

    return _run_source_batch(SOURCE_BATCH_NO, test_batch_no, reuse_existing, TEST_ITEM_COUNT)


def run_complete_batch(batch_no: str, test_batch_no: str | None = None, reuse_existing: bool = True) -> dict:
    """将指定合格批次的全部物料写入本地草稿并回读，不提交订单。"""

    batch_no = str(batch_no or "").strip()
    if not batch_no:
        return {"ok": False, "stage": "input", "message": "必须提供海外成本批次号。"}
    return _run_source_batch(batch_no, test_batch_no, reuse_existing, None)


def list_complete_candidates(limit: int = 20) -> dict:
    """只读筛选适合本地 ERP 草稿验证的海外成本批次，按 SKU 数量降序返回。"""

    from overseas_costing.services import batch_service
    from overseas_costing.scripts.import_oa_logistics import is_completed_approval_status

    limit = max(1, min(int(limit or 20), 100))
    fields = [
        "name", "batch_no", "status", "confirm_status", "item_count",
        "actual_total_cost_rmb", "estimated_total_cost_rmb", "source_approval_status",
        "extra_json", "modified",
    ]
    if batch_service._db_has_column("Overseas Cost Batch", "subsidiary_code"):
        fields.append("subsidiary_code")
    rows = frappe.get_all("Overseas Cost Batch", fields=fields, order_by="modified desc", limit_page_length=2000)
    eligible = []
    for row in rows:
        context = batch_service._load_erp_push_context(row.get("name"))
        if not context.get("ok"):
            continue
        batch = context.get("batch") or row
        items = context.get("items") or []
        source_status = batch_service._build_batch_source_status(batch)
        reasons = []
        entity = batch_service._resolve_batch_subsidiary_code(batch)
        if not entity:
            reasons.append("缺少业务主体")
        approval_statuses = source_status.get("linked_purchase_approval_statuses") or []
        if source_status.get("purchase_approval_sync_state") != "valid":
            reasons.append(source_status.get("purchase_approval_sync_message") or "采购审批未满足有效条件")
        elif not approval_statuses or not all(
            is_completed_approval_status(status, allow_empty=False) for status in approval_statuses
        ):
            reasons.append("关联采购审批仍在进行中或尚未完成")
        if source_status.get("invalid_business"):
            reasons.append(source_status.get("invalid_business_reason") or "存在无效审批")
        if not context.get("version_name"):
            reasons.append("缺少成本版本")
        if not items:
            reasons.append("没有物料明细")
        if batch.get("confirm_status") != "Confirmed":
            reasons.append("计算结果尚未确认")
        if batch.get("status") == "Dirty":
            reasons.append("存在未重新计算数据")
        missing_count = 0
        for item in items:
            required = ("material_code", "quantity", "unit_price", "purchase_currency", "total_cost_rmb", "total_unit_rmb")
            if any(item.get(fieldname) in (None, "", 0, 0.0) for fieldname in required):
                missing_count += 1
        if missing_count:
            reasons.append(f"有 {missing_count} 条物料字段不完整")
        if len(items) != int(batch.get("item_count") or len(items)):
            reasons.append(f"记录明细数与实际明细数不一致（记录 {batch.get('item_count') or 0}，实际 {len(items)}）")
        if not reasons:
            eligible.append({
                "batch_name": batch.get("name"),
                "batch_no": batch.get("batch_no") or batch.get("name"),
                "item_count": len(items),
                "total_cost_rmb": batch.get("actual_total_cost_rmb") or batch.get("estimated_total_cost_rmb") or 0,
                "business_entity": entity,
                "status": batch.get("status") or "",
                "confirm_status": batch.get("confirm_status") or "",
                "purchase_approval_nos": source_status.get("linked_purchase_approval_nos") or [],
                "purchase_approval_statuses": source_status.get("linked_purchase_approval_statuses") or [],
                "modified": batch.get("modified") or row.get("modified") or "",
            })
    eligible.sort(key=lambda value: (-value["item_count"], str(value.get("modified") or "")))
    return {"ok": True, "read_only": True, "count": len(eligible[:limit]), "candidates": eligible[:limit]}


def _run_source_batch(
    source_batch_no: str,
    test_batch_no: str | None,
    reuse_existing: bool,
    item_limit: int | None,
) -> dict:

    from overseas_costing.install import ensure_erpnext_standard_fields
    from overseas_costing.services import erp_client

    field_result = ensure_erpnext_standard_fields()
    if not field_result.get("ok"):
        return {"ok": False, "stage": "ensure_fields", **field_result}

    source = _load_source_payload(source_batch_no, item_limit)
    if not source.get("ok"):
        return source

    if not test_batch_no and reuse_existing:
        test_batch_no = _find_latest_test_batch_no(f"ERPTEST-{source_batch_no}-")
    test_batch_no = test_batch_no or f"ERPTEST-{source_batch_no}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    config = _resolve_local_config(test_batch_no)
    payload = _build_test_payload(source["payload"], test_batch_no, config)

    existing_order = _find_local_test_order(test_batch_no)
    if existing_order:
        actual_items = frappe.get_all(
            "Purchase Order Item",
            filters={"parent": existing_order["name"]},
            fields=ITEM_FIELDS,
            order_by="idx asc",
            limit_page_length=len(payload["items"]),
        )
        checks = _compare_items(payload, actual_items, test_batch_no, config)
        return {
            "ok": all(row["ok"] for row in checks),
            "source_batch_no": source_batch_no,
            "test_batch_no": test_batch_no,
            "purchase_order": existing_order["name"],
            "purchase_order_status": existing_order["docstatus"],
            "test_items": [row.get("item_code") for row in actual_items],
            "reused_existing": True,
            "checks": checks,
            "message": "已复用现有本地草稿采购订单并完成字段回读。"
            if all(row["ok"] for row in checks)
            else "已复用现有本地草稿，但字段回读存在差异。",
        }

    try:
        _ensure_test_supplier(config["supplier"])
        item_names = _insert_test_items(payload, config)
        po_body = erp_client._build_purchase_order_body(payload, config)
        purchase_order = frappe.get_doc({"doctype": "Purchase Order", **po_body}).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as exc:
        frappe.db.rollback()
        return {
            "ok": False,
            "stage": "write_local_erp",
            "test_batch_no": test_batch_no,
            "message": f"本地测试写入失败，已回滚本次未提交的数据：{exc}",
        }

    actual_items = frappe.get_all(
        "Purchase Order Item",
        filters={"parent": purchase_order.name},
        fields=ITEM_FIELDS,
        order_by="idx asc",
        limit_page_length=len(payload["items"]),
    )
    checks = _compare_items(payload, actual_items, test_batch_no, config)
    return {
        "ok": all(row["ok"] for row in checks),
        "source_batch_no": source_batch_no,
        "test_batch_no": test_batch_no,
        "purchase_order": purchase_order.name,
        "purchase_order_status": purchase_order.docstatus,
        "test_items": item_names,
        "checks": checks,
        "message": "本地草稿采购订单已写入并完成字段回读。" if all(row["ok"] for row in checks) else "本地草稿已写入，但字段回读存在差异。",
    }


def _find_latest_test_batch_no(test_prefix: str = TEST_PREFIX) -> str:
    rows = frappe.get_all(
        "Purchase Order",
        filters={"custom_overseas_batch_no": ["like", f"{test_prefix}%"], "docstatus": 0},
        fields=["custom_overseas_batch_no"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return str(rows[0].get("custom_overseas_batch_no") or "").strip() if rows else ""


def _find_local_test_order(test_batch_no: str) -> dict:
    rows = frappe.get_all(
        "Purchase Order",
        filters={"custom_overseas_batch_no": test_batch_no},
        fields=["name", "docstatus"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return rows[0] if rows and rows[0].get("docstatus") == 0 else {}


def cleanup(test_batch_no: str) -> dict:
    """清理明确指定的一次 ERPTEST 本地测试，不影响正式采购订单和物料。"""

    test_batch_no = str(test_batch_no or "").strip()
    if not test_batch_no.startswith(TEST_PREFIX):
        return {"ok": False, "message": f"只允许清理 {TEST_PREFIX} 前缀的测试批次。"}

    orders = frappe.get_all(
        "Purchase Order",
        filters={"custom_overseas_batch_no": test_batch_no},
        fields=["name", "docstatus"],
        limit_page_length=20,
    )
    submitted = [row["name"] for row in orders if row.get("docstatus") != 0]
    if submitted:
        return {"ok": False, "message": f"测试采购订单已提交，拒绝自动删除：{', '.join(submitted)}"}

    for row in orders:
        frappe.delete_doc("Purchase Order", row["name"], ignore_permissions=True, force=True)

    item_codes = frappe.get_all(
        "Item",
        filters={"item_code": ["like", f"{test_batch_no}-%"]},
        pluck="name",
        limit_page_length=10000,
    )
    for item_code in item_codes:
        frappe.delete_doc("Item", item_code, ignore_permissions=True, force=True)

    frappe.db.commit()
    return {
        "ok": True,
        "test_batch_no": test_batch_no,
        "deleted_purchase_orders": [row["name"] for row in orders],
        "deleted_items": item_codes,
    }


def _load_source_payload(source_batch_no: str = SOURCE_BATCH_NO, item_limit: int | None = TEST_ITEM_COUNT) -> dict:
    from overseas_costing.services import batch_service

    context = batch_service._load_erp_push_context(source_batch_no)
    if not context.get("ok"):
        return {"ok": False, "stage": "load_source", "message": context.get("message") or "未找到测试来源批次。"}

    source_items = [row for row in context.get("items") or [] if str(row.get("material_code") or "").strip()]
    if item_limit and len(source_items) < item_limit:
        return {
            "ok": False,
            "stage": "load_source",
            "message": f"测试来源批次至少需要 {item_limit} 条带物料编码的明细，当前只有 {len(source_items)} 条。",
        }

    payload = batch_service._build_erp_push_payload(
        batch=context["batch"],
        version=context["version"],
        items=source_items if not item_limit else source_items[:item_limit],
        rules=context["rules"],
        readiness={"total_cost_rmb": sum(flt(row.get("total_cost_rmb")) for row in (source_items if not item_limit else source_items[:item_limit]))},
    )
    return {"ok": True, "payload": payload}


def _resolve_local_config(test_batch_no: str) -> dict:
    companies = frappe.get_all("Company", fields=["name"], order_by="creation asc", limit_page_length=1)
    company = companies[0]["name"] if companies else ""
    if not company:
        frappe.throw("本地 ERP 没有 Company，无法创建采购订单测试。")

    return {
        "company": company,
        "supplier": f"ERPTEST Supplier {test_batch_no[-14:]}",
        "cost_center": frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name") or "",
        "item_group": frappe.db.get_value("Item Group", {"name": "All Item Groups"}, "name")
        or frappe.db.get_value("Item Group", {}, "name"),
        "stock_uom": frappe.db.get_value("UOM", {"name": "Nos"}, "name") or frappe.db.get_value("UOM", {}, "name"),
        "default_currency": frappe.db.get_value("Company", company, "default_currency") or "CNY",
        "schedule_date": datetime.now().date().isoformat(),
    }


def _build_test_payload(source_payload: dict, test_batch_no: str, config: dict) -> dict:
    payload = {**source_payload}
    payload["batch_no"] = test_batch_no
    payload["batch_name"] = test_batch_no
    payload["supplier"] = config["supplier"]
    payload["cost_center"] = config["cost_center"]
    payload["subsidiary_code"] = source_payload.get("subsidiary_code") or config["company"]
    payload["items"] = []
    for index, source_item in enumerate(source_payload.get("items") or [], start=1):
        item = {**source_item}
        original_code = str(item.get("material_code") or f"ROW{index}").replace(" ", "-")
        item["material_code"] = f"{test_batch_no}-{index:02d}-{original_code}"
        item["supplier"] = config["supplier"]
        payload["items"].append(item)
    return payload


def _ensure_test_supplier(supplier_name: str) -> None:
    if frappe.db.exists("Supplier", supplier_name):
        return
    supplier_group = frappe.db.get_value("Supplier Group", {"name": "All Supplier Groups"}, "name") or frappe.db.get_value(
        "Supplier Group", {}, "name"
    )
    frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": supplier_name,
            "supplier_group": supplier_group,
        }
    ).insert(ignore_permissions=True)


def _insert_test_items(payload: dict, config: dict) -> list[str]:
    from overseas_costing.services import erp_client

    names = []
    for row in payload["items"]:
        body = erp_client._build_item_body(row, payload, config)
        names.append(frappe.get_doc({"doctype": "Item", **body}).insert(ignore_permissions=True).name)
    return names


def _compare_items(payload: dict, actual_items: list[dict], test_batch_no: str, config: dict) -> list[dict]:
    expected_items = payload["items"]
    if len(expected_items) != len(actual_items):
        return [{"ok": False, "field": "item_count", "expected": len(expected_items), "actual": len(actual_items)}]

    results = []
    for expected, actual in zip(expected_items, actual_items, strict=True):
        formula = expected.get("cost_formula") or {}
        expense = expected.get("expense_detail") or {}
        logistics = expense.get("logistics") or {}
        clearance_tax = expense.get("clearance_and_tax") or {}
        original_amount = expected.get("goods_value") or formula.get("goods_value") or 0
        comprehensive_amount = formula.get("total_cost") or 0
        freight_amount = logistics.get("freight_alloc_rmb") or formula.get("allocated_logistics_cost") or 0
        clearance_amount = clearance_tax.get("clearance_alloc_rmb")
        if clearance_amount is None:
            clearance_amount = clearance_tax.get("mexico_customs_rmb") or clearance_tax.get("mexico_customs_mxn") or 0
        tax_amount = clearance_tax.get("tax_alloc_rmb")
        if tax_amount is None:
            tax_amount = clearance_tax.get("import_tax_total") or flt(clearance_tax.get("igi_amount")) + flt(clearance_tax.get("iva_amount"))

        original_amount = round(flt(original_amount), 2)
        comprehensive_amount = round(flt(comprehensive_amount), 2)
        freight_amount = round(flt(freight_amount), 2)
        tax_amount = round(flt(tax_amount), 2)
        clearance_amount = round(comprehensive_amount - original_amount - freight_amount - tax_amount, 2)
        expected_values = {
            "item_code": expected.get("material_code") or "",
            "rate": expected.get("original_unit_price") or formula.get("original_unit_price") or 0,
            "custom_overseas_original_unit_price": expected.get("original_unit_price") or formula.get("original_unit_price") or 0,
            "custom_overseas_comprehensive_unit_price": expected.get("comprehensive_unit_price") or formula.get("comprehensive_unit_price") or 0,
            "custom_overseas_original_amount": original_amount,
            "custom_overseas_comprehensive_amount": comprehensive_amount,
            "custom_overseas_freight_alloc_amount": freight_amount,
            "custom_overseas_clearance_alloc_amount": clearance_amount,
            "custom_overseas_tax_alloc_amount": tax_amount,
            "custom_overseas_batch_no": test_batch_no,
            "custom_overseas_cost_version": payload.get("version_code") or "",
            "custom_overseas_business_entity": expected.get("subsidiary_code") or "",
            "custom_overseas_cost_center": config.get("cost_center") or "",
        }
        differences = {
            field: {"expected": value, "actual": actual.get(field)}
            for field, value in expected_values.items()
            if not _same_value(value, actual.get(field))
        }
        actual_breakdown = sum(
            flt(actual.get(fieldname))
            for fieldname in (
                "custom_overseas_original_amount",
                "custom_overseas_freight_alloc_amount",
                "custom_overseas_clearance_alloc_amount",
                "custom_overseas_tax_alloc_amount",
            )
        )
        actual_total_cost = flt(actual.get("custom_overseas_comprehensive_amount"))
        if abs(actual_breakdown - actual_total_cost) >= 0.01:
            differences["cost_breakdown"] = {
                "expected": actual_total_cost,
                "actual": actual_breakdown,
            }
        results.append({"item_code": actual.get("item_code"), "ok": not differences, "differences": differences})
    return results


def _same_value(expected, actual) -> bool:
    if isinstance(expected, (int, float)) or isinstance(actual, (int, float)):
        return round(flt(expected), 2) == round(flt(actual), 2)
    return str(expected or "") == str(actual or "")
