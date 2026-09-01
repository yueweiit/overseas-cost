"""本地测试样本辅助脚本。

用于从真实批次复制一份测试样本，避免直接在真实业务数据上测试 ERP 推送。
"""

from __future__ import annotations

from datetime import datetime

import frappe


SKIP_FIELDS = {
    "name",
    "owner",
    "creation",
    "modified",
    "modified_by",
    "docstatus",
    "idx",
    "_user_tags",
    "_comments",
    "_assign",
    "_liked_by",
}


def list_batches_by_item_count(item_count: int = 24, limit: int = 20) -> list[dict]:
    rows = frappe.db.sql(
        """
        select
            i.batch,
            b.batch_no,
            b.subsidiary_code,
            b.status,
            b.confirm_status,
            b.writeback_status,
            count(*) as item_count,
            max(i.modified) as last_item_modified
        from `tabOverseas Cost Item` i
        left join `tabOverseas Cost Batch` b on b.name = i.batch
        group by i.batch, b.batch_no, b.subsidiary_code, b.status, b.confirm_status, b.writeback_status
        having count(*) = %(item_count)s
        order by last_item_modified desc
        limit %(limit)s
        """,
        {"item_count": int(item_count), "limit": int(limit)},
        as_dict=True,
    )
    return [dict(row) for row in rows]


def list_push_ready_candidates(min_item_count: int = 1, limit: int = 20) -> list[dict]:
    rows = frappe.db.sql(
        """
        select
            i.batch,
            b.batch_no,
            b.subsidiary_code,
            b.status,
            b.confirm_status,
            b.writeback_status,
            count(*) as item_count,
            sum(case when coalesce(i.material_code, '') <> '' then 1 else 0 end) as material_code_count,
            sum(case when coalesce(i.supplier, '') <> '' then 1 else 0 end) as supplier_count,
            sum(case when coalesce(i.unit_price, 0) > 0 or coalesce(i.goods_value, 0) > 0 then 1 else 0 end) as price_count,
            sum(case when coalesce(i.actual_shipped_qty, 0) > 0 or coalesce(i.quantity, 0) > 0 then 1 else 0 end) as qty_count,
            sum(case when coalesce(i.total_unit_rmb, 0) > 0 then 1 else 0 end) as cost_count,
            max(i.modified) as last_item_modified
        from `tabOverseas Cost Item` i
        left join `tabOverseas Cost Batch` b on b.name = i.batch
        group by i.batch, b.batch_no, b.subsidiary_code, b.status, b.confirm_status, b.writeback_status
        having item_count >= %(min_item_count)s
            and price_count > 0
            and qty_count > 0
        order by
            cost_count desc,
            price_count desc,
            material_code_count desc,
            item_count desc,
            last_item_modified desc
        limit %(limit)s
        """,
        {"min_item_count": int(min_item_count), "limit": int(limit)},
        as_dict=True,
    )
    return [dict(row) for row in rows]


def summarize_batch_readiness(batch_name: str) -> dict:
    resolved_batch_name = _resolve_batch_name(batch_name)
    if not resolved_batch_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    rows = frappe.db.sql(
        """
        select
            count(*) as item_count,
            sum(case when coalesce(material_code, '') <> '' then 1 else 0 end) as material_code_count,
            sum(case when coalesce(supplier, '') <> '' then 1 else 0 end) as supplier_count,
            sum(case when coalesce(actual_shipped_qty, 0) > 0 or coalesce(quantity, 0) > 0 then 1 else 0 end) as qty_count,
            sum(case when coalesce(unit_price, 0) > 0 or coalesce(goods_value, 0) > 0 then 1 else 0 end) as price_count,
            sum(case when coalesce(total_unit_rmb, 0) > 0 then 1 else 0 end) as cost_count
        from `tabOverseas Cost Item`
        where batch = %(batch)s
        """,
        {"batch": resolved_batch_name},
        as_dict=True,
    )
    rule_count = frappe.db.count("Overseas Cost Allocation Rule", {"batch": resolved_batch_name})
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        resolved_batch_name,
        ["name", "batch_no", "status", "confirm_status", "writeback_status", "current_version"],
        as_dict=True,
    )
    summary = dict(rows[0] if rows else {})
    missing = []
    item_count = int(summary.get("item_count") or 0)
    checks = [
        ("material_code_count", "物料编码"),
        ("qty_count", "数量"),
        ("price_count", "采购单价或金额"),
        ("cost_count", "综合成本"),
    ]
    for key, label in checks:
        if int(summary.get(key) or 0) < item_count:
            missing.append(label)
    if not rule_count:
        missing.append("费用分摊规则")

    return {
        "ok": True,
        "batch": dict(batch or {}),
        "summary": summary,
        "allocation_rule_count": rule_count,
        "missing": missing,
    }


def clone_batch_for_sample(batch_name: str, sample_prefix: str = "TEST") -> dict:
    source_batch_name = _resolve_batch_name(batch_name)
    if not source_batch_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    source_batch = frappe.get_doc("Overseas Cost Batch", source_batch_name)
    source_version_name = source_batch.current_version or _latest_version_name(source_batch_name)
    source_version = frappe.get_doc("Overseas Cost Version", source_version_name) if source_version_name else None

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    target_batch_no = f"{sample_prefix}-{source_batch.batch_no or source_batch.name}-{stamp}"
    target_batch = _copy_doc_data(source_batch)
    target_batch.update(
        {
            "doctype": "Overseas Cost Batch",
            "batch_no": target_batch_no,
            "status": "Calculated" if source_batch.status in ("Confirmed", "Written Back") else source_batch.status,
            "confirm_status": "Pending",
            "writeback_status": "Not Started",
            "writeback_time": None,
            "writeback_message": "",
            "erp_target_doc": "",
            "current_version": None,
            "is_locked": 0,
            "import_remark": f"本地测试样本，复制自 {source_batch.batch_no or source_batch.name}",
        }
    )
    target_batch_doc = frappe.get_doc(target_batch).insert(ignore_permissions=True)

    target_version_doc = None
    if source_version:
        target_version = _copy_doc_data(source_version)
        target_version.update(
            {
                "doctype": "Overseas Cost Version",
                "batch": target_batch_doc.name,
                "status": "Draft" if source_version.status == "Confirmed" else source_version.status,
                "is_current": 1,
            }
        )
        target_version_doc = frappe.get_doc(target_version).insert(ignore_permissions=True)
        target_batch_doc.current_version = target_version_doc.name
        target_batch_doc.save(ignore_permissions=True)

    copied_items = _copy_child_docs(
        doctype="Overseas Cost Item",
        filters={"batch": source_batch_name, **({"version": source_version_name} if source_version_name else {})},
        updates={"batch": target_batch_doc.name, "version": target_version_doc.name if target_version_doc else None},
    )
    copied_rules = _copy_child_docs(
        doctype="Overseas Cost Allocation Rule",
        filters={"batch": source_batch_name, **({"version": source_version_name} if source_version_name else {})},
        updates={"batch": target_batch_doc.name, "version": target_version_doc.name if target_version_doc else None},
    )

    frappe.db.commit()
    return {
        "ok": True,
        "source_batch": source_batch_name,
        "source_batch_no": source_batch.batch_no,
        "sample_batch": target_batch_doc.name,
        "sample_batch_no": target_batch_doc.batch_no,
        "sample_version": target_version_doc.name if target_version_doc else "",
        "copied_item_count": copied_items,
        "copied_rule_count": copied_rules,
        "message": f"已复制测试样本：{target_batch_doc.batch_no}，明细 {copied_items} 条。",
    }


def _copy_child_docs(doctype: str, filters: dict, updates: dict) -> int:
    names = frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=10000)
    for name in names:
        values = _copy_doc_data(frappe.get_doc(doctype, name))
        values.update({"doctype": doctype, **updates})
        frappe.get_doc(values).insert(ignore_permissions=True)
    return len(names)


def _copy_doc_data(doc) -> dict:
    data = {}
    meta = frappe.get_meta(doc.doctype)
    table_fields = {field.fieldname for field in meta.fields if field.fieldtype == "Table"}
    for key, value in doc.as_dict(no_nulls=False).items():
        if key in SKIP_FIELDS or key in table_fields:
            continue
        data[key] = value
    return data


def _resolve_batch_name(batch_name: str) -> str:
    value = str(batch_name or "").strip()
    if not value:
        return ""
    return (
        frappe.db.exists("Overseas Cost Batch", value)
        or frappe.db.get_value("Overseas Cost Batch", {"batch_no": value}, "name")
        or ""
    )


def _latest_version_name(batch_name: str) -> str:
    rows = frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_name},
        fields=["name"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return rows[0]["name"] if rows else ""
