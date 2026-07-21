"""
中文用途：导入服务。

一期这里逐步承接：
1. 主 Excel 导入
2. OA 国际物流单导入
3. 采购支出 OA 回填采购价格
4. 装箱单解析结果回填实际发货物理属性
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Callable

try:
    import frappe
except Exception:  # pragma: no cover - 本地无 Frappe 环境时保持可导入
    frappe = None

from overseas_costing.services import attachment_parse_service
from overseas_costing.utils.dingtalk import build_dingtalk_order_payload, extract_dingtalk_instance_id
from overseas_costing.utils.excel_blocks import (
    select_excel_blocks,
    summarize_excel_blocks,
    to_bool,
)
from overseas_costing.utils.excel_workbook import parse_yuewei_excel_workbook
from overseas_costing.utils.field_mapper import (
    map_packing_list_row_to_item,
    map_purchase_expense_row_to_item,
    map_yuewei_excel_block_item_to_item,
    normalize_transport_mode,
)

ITEM_KEY_FIELDS = ("material_code", "product_name", "spec_model")
DEFAULT_FX_RMB_TO_MXN = 2.6
NUMERIC_ITEM_FIELDS = {
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


def import_main_excel(
    source_name: str,
    source_type: str = "excel",
    transport_mode: str = "SEA",
    source_sheet: str | None = None,
    project_collection: str | None = None,
    version_type: str = "Estimated",
    blocks_json: str | None = None,
    fx_usd_to_rmb: float | None = None,
    fx_rmb_to_mxn: float | None = None,
) -> dict:
    """Import parsed Yuewei Excel blocks into Batch / Version / Item.

    The real Excel parser can feed `blocks_json` later. Until then this keeps a
    stable JSON entry point for the frontend-demo block structure.
    """

    blocks = _load_blocks(blocks_json)
    preview_batches = [_build_excel_block_preview(block) for block in blocks]

    if frappe is None:
        return {
            "ok": True,
            "queued": False,
            "dry_run": True,
            "source_name": source_name,
            "source_type": source_type,
            "transport_mode": transport_mode,
            "source_sheet": source_sheet,
            "project_collection": project_collection,
            "message": "当前未连接 Frappe，已返回 Excel 导入预览结果。",
            "created_batches": [],
            "preview_batches": preview_batches,
        }

    created_batches = []
    resolved_fx_rmb_to_mxn = fx_rmb_to_mxn or DEFAULT_FX_RMB_TO_MXN

    for block in blocks:
        batch_doc, batch_action = _resolve_or_create_excel_batch(
            block=block,
            source_name=source_name,
            transport_mode=transport_mode,
            source_sheet=source_sheet,
            project_collection=project_collection,
        )
        version_doc, version_action = _resolve_or_create_excel_version(
            batch_doc_name=batch_doc.name,
            version_type=version_type,
            fx_usd_to_rmb=fx_usd_to_rmb,
            fx_rmb_to_mxn=resolved_fx_rmb_to_mxn,
        )
        frappe.db.set_value(
            "Overseas Cost Batch",
            batch_doc.name,
            "current_version",
            version_doc.name,
            update_modified=False,
        )

        raw_rows = block.get("items") or []
        mapped_rows = [
            map_yuewei_excel_block_item_to_item(block, row, row_index=index + 1)
            for index, row in enumerate(raw_rows)
        ]
        item_result = _upsert_excel_items(
            batch_doc_name=batch_doc.name,
            version_name=version_doc.name,
            mapped_rows=mapped_rows,
            raw_rows=raw_rows,
        )
        rules = _upsert_default_allocation_rules(
            batch_doc_name=batch_doc.name,
            version_name=version_doc.name,
            block=block,
            mapped_rows=mapped_rows,
        )

        created_batch = {
            "batch_name": batch_doc.name,
            "batch_no": batch_doc.batch_no,
            "batch_action": batch_action,
            "version_name": version_doc.name,
            "version_type": version_doc.version_type,
            "version_action": version_action,
            "item_count": item_result["total_count"],
            "created_item_count": item_result["created_count"],
            "updated_item_count": item_result["updated_count"],
            "unchanged_item_count": item_result["unchanged_count"],
            "rule_count": len(rules),
        }

        try:
            from overseas_costing.services.calculate_service import recalculate_batch

            created_batch["recalculate_result"] = recalculate_batch(
                batch_name=batch_doc.name,
                version_name=version_doc.name,
            )
        except Exception as exc:
            created_batch["recalculate_error"] = str(exc)

        created_batches.append(created_batch)

    if hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "queued": False,
        "source_name": source_name,
        "source_type": source_type,
        "transport_mode": transport_mode,
        "source_sheet": source_sheet,
        "project_collection": project_collection,
        "message": "Excel 主表已生成批次、版本、明细和默认分摊规则。",
        "created_batches": created_batches,
        "preview_batches": preview_batches,
    }


def import_parsed_excel_blocks(
    source_name: str,
    blocks_json: str,
    source_sheet: str | None = None,
    transport_keyword: str = "",
    include_double_clear=False,
    batch_ids: str | None = None,
    limit: int | None = None,
    project_collection: str | None = None,
    version_type: str = "Estimated",
    fx_usd_to_rmb: float | None = None,
    fx_rmb_to_mxn: float | None = None,
) -> dict:
    """导入已经从 Excel 解析出的 block JSON。

    这是从前端 Demo 的 excel-imported-blocks.js 过渡到正式后端导入的桥。
    默认只导入一期普通海运，不导入“海运双清”。
    """

    blocks = _load_blocks(blocks_json)
    selected_blocks = select_excel_blocks(
        blocks,
        source_sheet=source_sheet,
        transport_keyword=transport_keyword,
        include_double_clear=to_bool(include_double_clear),
        batch_ids=batch_ids,
        limit=limit,
    )
    selected_summary = summarize_excel_blocks(selected_blocks)

    result = import_main_excel(
        source_name=source_name,
        source_type="excel",
        transport_mode="SEA",
        source_sheet=source_sheet,
        project_collection=project_collection,
        version_type=version_type,
        blocks_json=json.dumps(selected_blocks, ensure_ascii=False),
        fx_usd_to_rmb=fx_usd_to_rmb,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
    )
    result.update(
        {
            "source_summary": summarize_excel_blocks(blocks),
            "selected_summary": selected_summary,
            "selection": {
                "source_sheet": source_sheet,
                "transport_keyword": transport_keyword,
                "include_double_clear": to_bool(include_double_clear),
                "batch_ids": batch_ids or "",
                "limit": limit,
            },
        }
    )
    return result


def import_yuewei_excel_file(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    source_sheet: str | None = None,
    transport_keyword: str = "",
    include_double_clear=False,
    batch_ids: str | None = None,
    limit: int | None = None,
    project_collection: str | None = None,
    version_type: str = "Estimated",
    fx_usd_to_rmb: float | None = None,
    fx_rmb_to_mxn: float | None = None,
) -> dict:
    """导入真实 Yuewei 成本总表 xlsx。

    解析层输出与 `excel-imported-blocks.js` 相同的 block JSON，再复用现有落库链路。
    """

    resolved_path = _resolve_excel_file_path(file_path=file_path, file_url=file_url)
    source_sheet = (source_sheet or "").strip() or None
    meta, blocks = parse_yuewei_excel_workbook(resolved_path, sheet_name=source_sheet)
    resolved_source_name = source_name or Path(resolved_path).name
    resolved_source_sheet = meta.get("sourceSheet") or source_sheet

    result = import_parsed_excel_blocks(
        source_name=resolved_source_name,
        blocks_json=json.dumps(blocks, ensure_ascii=False),
        source_sheet=resolved_source_sheet,
        transport_keyword=transport_keyword,
        include_double_clear=include_double_clear,
        batch_ids=batch_ids,
        limit=limit,
        project_collection=project_collection,
        version_type=version_type,
        fx_usd_to_rmb=fx_usd_to_rmb,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
    )
    result.update(
        {
            "parser_meta": meta,
            "file_path": str(resolved_path),
            "file_url": file_url or "",
        }
    )
    return result


def preview_yuewei_excel_file(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    source_sheet: str | None = None,
    transport_keyword: str = "",
    include_double_clear=True,
    batch_ids: str | None = None,
    limit: int | None = None,
) -> dict:
    """预览真实 xlsx 解析结果，不写入数据库。"""

    resolved_path = _resolve_excel_file_path(file_path=file_path, file_url=file_url)
    source_sheet = (source_sheet or "").strip() or None
    meta, blocks = parse_yuewei_excel_workbook(resolved_path, sheet_name=source_sheet)
    resolved_source_sheet = meta.get("sourceSheet") or source_sheet
    selected_blocks = select_excel_blocks(
        blocks,
        source_sheet=resolved_source_sheet,
        transport_keyword=transport_keyword,
        include_double_clear=include_double_clear,
        batch_ids=batch_ids,
        limit=limit,
    )
    return {
        "ok": True,
        "source_name": source_name or Path(resolved_path).name,
        "file_path": str(resolved_path),
        "file_url": file_url or "",
        "parser_meta": meta,
        "source_summary": summarize_excel_blocks(blocks),
        "selected_summary": summarize_excel_blocks(selected_blocks),
        "preview_batches": [_build_excel_block_preview(block) for block in selected_blocks[:20]],
        "selection": {
            "source_sheet": resolved_source_sheet or "",
            "transport_keyword": transport_keyword or "",
            "include_double_clear": to_bool(include_double_clear),
            "batch_ids": batch_ids or "",
            "limit": limit,
        },
    }


def upload_attachment(batch_name: str, version_name: str | None = None, file_url: str | None = None) -> dict:
    return {
        "ok": True,
        "queued": True,
        "batch_name": batch_name,
        "version_name": version_name,
        "file_url": file_url,
        "message": "附件登记骨架已创建，后续接 OCR / AI 解析。",
    }


def preview_tax_certificate_pdf(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
    batch_name: str | None = None,
) -> dict:
    """预览解析进口完税凭证 PDF，不写库。"""

    return attachment_parse_service.preview_tax_certificate_pdf(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        text=text,
        batch_name=batch_name,
    )


def save_tax_certificate_parse_result(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
    batch_name: str | None = None,
) -> dict:
    """保存完税凭证解析结果到附件记录，不写成本字段。"""

    return attachment_parse_service.save_tax_certificate_parse_result(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        text=text,
        batch_name=batch_name,
    )


def list_tax_certificate_parse_records(batch_name: str | None = None, limit: int | None = 20) -> dict:
    """查询完税凭证解析快照摘要。"""

    return attachment_parse_service.list_tax_certificate_parse_records(
        batch_name=batch_name,
        limit=limit,
    )


def get_tax_certificate_parse_record(record_name: str | None = None) -> dict:
    """查询单条完税凭证解析快照详情。"""

    return attachment_parse_service.get_tax_certificate_parse_record(record_name=record_name)


def resolve_tax_certificate_reconciliation(
    record_name: str | None = None,
    resolution_action: str | None = None,
    adjusted_tax_total_mxn: float | str | None = None,
    remark: str | None = None,
) -> dict:
    """保存完税凭证差异人工处理结果，不写成本字段。"""

    return attachment_parse_service.resolve_tax_certificate_reconciliation(
        record_name=record_name,
        resolution_action=resolution_action,
        adjusted_tax_total_mxn=adjusted_tax_total_mxn,
        remark=remark,
    )


def _load_rows(rows_json: str | None) -> list[dict]:
    if not rows_json:
        return []

    loaded = json.loads(rows_json)
    if isinstance(loaded, list):
        return [row for row in loaded if isinstance(row, dict)]
    return []


def _load_blocks(blocks_json: str | None) -> list[dict]:
    if not blocks_json:
        return []

    loaded = json.loads(blocks_json)
    if isinstance(loaded, dict):
        loaded = [loaded]
    if isinstance(loaded, list):
        return [block for block in loaded if isinstance(block, dict)]
    return []


def _resolve_excel_file_path(*, file_path: str | None = None, file_url: str | None = None) -> Path:
    if file_path:
        path = Path(file_path).expanduser()
        if path.exists():
            return _ensure_supported_excel_path(path)
        raise FileNotFoundError(f"未找到 Excel 文件：{file_path}")

    if not file_url:
        raise ValueError("请传入 file_path 或 file_url。")

    if frappe is None:
        path = Path(file_url).expanduser()
        if path.exists():
            return _ensure_supported_excel_path(path)
        raise FileNotFoundError(f"未连接 Frappe，且本地路径不存在：{file_url}")

    resolved_file_url = file_url
    if not resolved_file_url.startswith("/"):
        file_row = frappe.db.get_value("File", resolved_file_url, ["file_url"], as_dict=True)
        if file_row and file_row.get("file_url"):
            resolved_file_url = file_row["file_url"]

    if resolved_file_url.startswith("/private/files/"):
        relative_name = resolved_file_url.split("/private/files/", 1)[1]
        return _ensure_supported_excel_path(Path(frappe.get_site_path("private", "files", relative_name)))
    if resolved_file_url.startswith("/files/"):
        relative_name = resolved_file_url.split("/files/", 1)[1]
        return _ensure_supported_excel_path(Path(frappe.get_site_path("public", "files", relative_name)))

    path = Path(resolved_file_url).expanduser()
    if path.exists():
        return _ensure_supported_excel_path(path)
    raise FileNotFoundError(f"无法解析 Excel 文件路径：{file_url}")


def _ensure_supported_excel_path(path: Path) -> Path:
    suffix = path.suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError("当前仅支持 .xlsx / .xlsm 格式的 Excel 文件。")
    return path


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _to_float(value, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_non_empty(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _first_mapped_value(mapped_rows: list[dict], fieldname: str, default: float = 0.0) -> float:
    for row in mapped_rows:
        value = row.get(fieldname)
        if value not in (None, ""):
            return _to_float(value, default=default)
    return default


def _filter_doctype_values(doctype: str, values: dict, *, keep_doctype: bool = False) -> dict:
    if frappe is None:
        return dict(values)

    meta = frappe.get_meta(doctype)
    filtered = {
        fieldname: value
        for fieldname, value in values.items()
        if meta.has_field(fieldname) or (keep_doctype and fieldname == "doctype")
    }
    return filtered


def _coerce_item_numeric_defaults(values: dict) -> dict:
    normalized = dict(values)
    for fieldname in NUMERIC_ITEM_FIELDS:
        if normalized.get(fieldname) in (None, ""):
            normalized[fieldname] = 0
    return normalized


def _values_equal_for_import(old_value, new_value) -> bool:
    if old_value in (None, "") and new_value in (None, ""):
        return True
    try:
        return float(old_value) == float(new_value)
    except (TypeError, ValueError):
        return str(old_value or "").strip() == str(new_value or "").strip()


def _item_values_changed(item_name: str, values: dict) -> bool:
    if frappe is None:
        return True
    fieldnames = [fieldname for fieldname in values if fieldname not in {"doctype", "name"}]
    if not fieldnames:
        return False
    current = frappe.db.get_value("Overseas Cost Item", item_name, fieldnames, as_dict=True) or {}
    return any(not _values_equal_for_import(current.get(fieldname), value) for fieldname, value in values.items())


def _build_excel_block_preview(block: dict) -> dict:
    items = block.get("items") or []
    mapped_preview_items = [
        map_yuewei_excel_block_item_to_item(block, row, row_index=index + 1)
        for index, row in enumerate(items[:20])
    ]
    return {
        "batch_no": block.get("id") or block.get("waybillNo"),
        "source_sheet": block.get("sourceSheet"),
        "source_range": block.get("sourceRange"),
        "customs_no": block.get("customsNo"),
        "waybill_no": block.get("waybillNo"),
        "transport_mode": normalize_transport_mode(block.get("transportMode")),
        "item_count": len(items),
        "mapped_preview_items": mapped_preview_items,
    }


def _resolve_or_create_excel_batch(
    *,
    block: dict,
    source_name: str,
    transport_mode: str,
    source_sheet: str | None,
    project_collection: str | None,
):
    is_attachment_detail = block.get("sourceTemplate") == "oa_attachment_detail"
    batch_no = _first_non_empty(block.get("batchNo"), block.get("id"), block.get("waybillNo"), source_name)
    existing_name = frappe.db.get_value("Overseas Cost Batch", {"batch_no": batch_no}, "name")
    source_meta = {key: value for key, value in block.items() if key != "items" and value not in (None, "")}
    waybill_no = block.get("waybillNo") or ("" if is_attachment_detail else batch_no)
    source_dingtalk_url = block.get("sourceDingtalkUrl") or block.get("dingtalkUrl") or block.get("officialUrl") or ""
    source_instance_id = block.get("sourceInstanceId") or extract_dingtalk_instance_id(source_dingtalk_url) or ""
    values = {
        "batch_no": batch_no,
        "customs_no": block.get("customsNo") or "",
        "waybill_no": waybill_no,
        "transport_mode": normalize_transport_mode(block.get("transportMode") or transport_mode) or "SEA",
        "project_collection": project_collection or block.get("projectCollection") or "",
        "source_type": "excel",
        "source_file_name": source_name,
        "source_sheet": source_sheet or block.get("sourceSheet") or "",
        "source_range": block.get("sourceRange") or "",
        "source_approval_no": block.get("sourceApprovalNo") or "",
        "source_instance_id": source_instance_id,
        "source_dingtalk_url": source_dingtalk_url,
        "status": "Imported",
        "import_remark": "Imported from Excel parser",
        "source_remark": block.get("remark") or "",
        "extra_json": _json_dumps(source_meta),
    }

    if existing_name:
        frappe.db.set_value("Overseas Cost Batch", existing_name, values, update_modified=True)
        return frappe.get_doc("Overseas Cost Batch", existing_name), "updated"

    values["doctype"] = "Overseas Cost Batch"
    return frappe.get_doc(values).insert(ignore_permissions=True), "created"


def _resolve_or_create_excel_version(
    *,
    batch_doc_name: str,
    version_type: str,
    fx_usd_to_rmb: float | None,
    fx_rmb_to_mxn: float,
):
    existing_name = frappe.db.get_value(
        "Overseas Cost Version",
        {"batch": batch_doc_name, "version_code": version_type},
        "name",
    )
    values = {
        "batch": batch_doc_name,
        "version_code": version_type,
        "version_type": version_type,
        "is_current": 1,
        "source_type": "Import",
        "fx_usd_to_rmb": fx_usd_to_rmb or 0,
        "fx_rmb_to_mxn": fx_rmb_to_mxn or DEFAULT_FX_RMB_TO_MXN,
    }

    existing_versions = frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=["name"],
        limit_page_length=500,
    )
    for row in existing_versions:
        frappe.db.set_value("Overseas Cost Version", row["name"], "is_current", 0, update_modified=False)

    if existing_name:
        frappe.db.set_value("Overseas Cost Version", existing_name, values, update_modified=True)
        return frappe.get_doc("Overseas Cost Version", existing_name), "updated"

    values["doctype"] = "Overseas Cost Version"
    return frappe.get_doc(values).insert(ignore_permissions=True), "created"


def _upsert_excel_items(
    *,
    batch_doc_name: str,
    version_name: str,
    mapped_rows: list[dict],
    raw_rows: list,
) -> dict:
    upserted_items: list[str] = []
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    for index, mapped_row in enumerate(mapped_rows):
        mapped_row = _coerce_item_numeric_defaults(mapped_row)
        row_no = mapped_row.get("row_no") or index + 1
        quantity = _to_float(mapped_row.get("quantity"))
        unit_price = _to_float(mapped_row.get("unit_price"))
        if mapped_row.get("goods_value") in (None, "") and unit_price and quantity:
            mapped_row["goods_value"] = unit_price * quantity

        values = {
            **mapped_row,
            "batch": batch_doc_name,
            "version": version_name,
            "row_no": row_no,
            "raw_excel_json": _json_dumps(raw_rows[index] if index < len(raw_rows) else mapped_row),
        }
        existing_name = frappe.db.get_value(
            "Overseas Cost Item",
            {"batch": batch_doc_name, "version": version_name, "row_no": row_no},
            "name",
        )
        if existing_name:
            filtered_values = _filter_doctype_values("Overseas Cost Item", values)
            if _item_values_changed(existing_name, filtered_values):
                frappe.db.set_value(
                    "Overseas Cost Item",
                    existing_name,
                    filtered_values,
                    update_modified=True,
                )
                updated_count += 1
            else:
                unchanged_count += 1
            upserted_items.append(existing_name)
            continue

        values["doctype"] = "Overseas Cost Item"
        values = _filter_doctype_values("Overseas Cost Item", values, keep_doctype=True)
        upserted_items.append(frappe.get_doc(values).insert(ignore_permissions=True).name)
        created_count += 1

    return {
        "item_names": upserted_items,
        "created_count": created_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "total_count": len(upserted_items),
    }


def _upsert_default_allocation_rules(
    *,
    batch_doc_name: str,
    version_name: str,
    block: dict,
    mapped_rows: list[dict],
) -> list[str]:
    rule_specs = [
        {
            "rule_code": "china_misc_rmb",
            "expense_category": "China misc RMB",
            "allocation_basis": "goods_value",
            "currency": "RMB",
            "amount": _to_float(block.get("chinaMiscRmb")),
            "priority_no": 10,
        },
        {
            "rule_code": "china_to_mexico_freight_rmb",
            "expense_category": "China to Mexico freight RMB",
            "allocation_basis": "gross_weight",
            "currency": "RMB",
            "amount": _to_float(
                _first_non_empty(
                    block.get("chinaToMexicoFreightRmb"),
                    _first_mapped_value(mapped_rows, "china_to_mexico_freight_rmb", default=0),
                )
            ),
            "priority_no": 20,
        },
        {
            "rule_code": "mexico_inland_misc_rmb",
            "expense_category": "Mexico inland and misc RMB",
            "allocation_basis": "gross_weight",
            "currency": "RMB",
            "amount": _to_float(
                _first_non_empty(
                    block.get("mexicoInlandMiscRmb"),
                    _first_mapped_value(mapped_rows, "mexico_inland_misc_rmb", default=0),
                )
            ),
            "priority_no": 30,
        },
    ]

    upserted_rules: list[str] = []
    for spec in rule_specs:
        existing_name = frappe.db.get_value(
            "Overseas Cost Allocation Rule",
            {"batch": batch_doc_name, "version": version_name, "rule_code": spec["rule_code"]},
            "name",
        )
        values = {
            **spec,
            "batch": batch_doc_name,
            "version": version_name,
            "basis_field": spec["allocation_basis"],
            "is_active": 1,
            "is_enabled": 1,
        }
        if existing_name:
            frappe.db.set_value("Overseas Cost Allocation Rule", existing_name, values, update_modified=True)
            upserted_rules.append(existing_name)
            continue

        values["doctype"] = "Overseas Cost Allocation Rule"
        upserted_rules.append(frappe.get_doc(values).insert(ignore_permissions=True).name)

    return upserted_rules


def _normalize_key(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _build_preview_rows(
    raw_rows: list[dict],
    mapper: Callable[[dict], dict],
) -> list[dict]:
    return [mapper(row) for row in raw_rows]


def _resolve_batch_name(batch_name: str) -> str | None:
    if frappe is None:
        return None

    batch = frappe.db.get_value("Overseas Cost Batch", batch_name, ["name"], as_dict=True)
    if batch:
        return batch["name"]

    batch = frappe.db.get_value("Overseas Cost Batch", {"batch_no": batch_name}, ["name"], as_dict=True)
    if batch:
        return batch["name"]
    return None


def _resolve_version_name(batch_doc_name: str, version_name: str | None = None) -> str | None:
    if frappe is None:
        return version_name
    if version_name:
        return version_name

    batch_row = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_doc_name,
        ["current_version"],
        as_dict=True,
    )
    current_version = (batch_row or {}).get("current_version")
    if current_version:
        return current_version

    latest_rows = frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=["name"],
        order_by="modified desc",
        limit_page_length=1,
    )
    if latest_rows:
        return latest_rows[0]["name"]
    return None


def _get_batch_items(batch_doc_name: str, version_name: str | None) -> list[dict]:
    if frappe is None or not version_name:
        return []

    return frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": version_name},
        fields=[
            "name",
            "row_no",
            "material_code",
            "product_name",
            "spec_model",
            "unit_price",
            "purchase_currency",
            "goods_value",
            "actual_shipped_qty",
            "gross_weight_kg",
            "volume_m3",
            "volume_weight_kg",
            "chargeable_weight_kg",
        ],
        order_by="row_no asc",
        limit_page_length=5000,
    )


def _index_items(items: list[dict]) -> dict[str, dict[str, list[dict]]]:
    indexes = {
        "material_code": defaultdict(list),
        "product_name": defaultdict(list),
        "spec_model": defaultdict(list),
    }
    for item in items:
        for field in ITEM_KEY_FIELDS:
            key = _normalize_key(item.get(field))
            if key:
                indexes[field][key].append(item)
    return indexes


def _match_item(mapped_row: dict, indexes: dict[str, dict[str, list[dict]]]) -> tuple[str, list[dict]]:
    for field in ITEM_KEY_FIELDS:
        key = _normalize_key(mapped_row.get(field))
        if not key:
            continue
        candidates = indexes[field].get(key, [])
        if candidates:
            return field, candidates
    return "", []


def _create_audit_log(
    *,
    batch_doc_name: str,
    version_name: str | None,
    row_no: int | None,
    field_name: str,
    old_value,
    new_value,
    action_remark: str,
) -> None:
    if frappe is None:
        return

    operator_name = ""
    session_user = getattr(getattr(frappe, "session", None), "user", None)
    if session_user and session_user != "Guest":
        operator_name = session_user

    frappe.get_doc(
        {
            "doctype": "Overseas Cost Audit Log",
            "batch": batch_doc_name,
            "version": version_name,
            "action_type": "IMPORT",
            "field_name": field_name,
            "row_no": row_no,
            "old_value": "" if old_value is None else str(old_value),
            "new_value": "" if new_value is None else str(new_value),
            "operator_name": operator_name,
            "action_remark": action_remark,
        }
    ).insert(ignore_permissions=True)


def _update_item_fields(
    *,
    item_name: str,
    batch_doc_name: str,
    version_name: str | None,
    row_no: int | None,
    field_updates: dict,
    action_remark: str,
) -> list[dict]:
    if frappe is None:
        return []

    item_doc = frappe.get_doc("Overseas Cost Item", item_name)
    changed_fields: list[dict] = []

    for field_name, new_value in field_updates.items():
        old_value = getattr(item_doc, field_name, None)
        if old_value == new_value:
            continue
        setattr(item_doc, field_name, new_value)
        changed_fields.append(
            {
                "field_name": field_name,
                "old_value": old_value,
                "new_value": new_value,
            }
        )

    if not changed_fields:
        return []

    item_doc.save(ignore_permissions=True)

    for changed in changed_fields:
        _create_audit_log(
            batch_doc_name=batch_doc_name,
            version_name=version_name,
            row_no=row_no,
            field_name=changed["field_name"],
            old_value=changed["old_value"],
            new_value=changed["new_value"],
            action_remark=action_remark,
        )

    return changed_fields


def _mark_batch_dirty(batch_doc_name: str) -> None:
    if frappe is None:
        return
    frappe.db.set_value("Overseas Cost Batch", batch_doc_name, "status", "Dirty", update_modified=True)


def _run_item_writeback(
    *,
    batch_name: str,
    version_name: str | None,
    mapped_rows: list[dict],
    update_builder: Callable[[dict, dict], dict],
    action_remark: str,
) -> dict:
    if frappe is None:
        return {
            "matched_count": 0,
            "updated_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": len(mapped_rows),
            "matched_rows": [],
            "ambiguous_rows": [],
            "unmatched_rows": mapped_rows,
            "message": "当前未连接 Frappe，返回预览结果。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {
            "matched_count": 0,
            "updated_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": len(mapped_rows),
            "matched_rows": [],
            "ambiguous_rows": [],
            "unmatched_rows": mapped_rows,
            "message": f"未找到批次：{batch_name}",
        }

    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    if not resolved_version_name:
        return {
            "matched_count": 0,
            "updated_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": len(mapped_rows),
            "matched_rows": [],
            "ambiguous_rows": [],
            "unmatched_rows": mapped_rows,
            "message": f"批次 {batch_name} 暂无可用版本，无法回填。",
        }

    items = _get_batch_items(batch_doc_name, resolved_version_name)
    indexes = _index_items(items)
    matched_rows: list[dict] = []
    ambiguous_rows: list[dict] = []
    unmatched_rows: list[dict] = []
    updated_count = 0

    for mapped_row in mapped_rows:
        matched_by, candidates = _match_item(mapped_row, indexes)
        if not candidates:
            unmatched_rows.append(mapped_row)
            continue
        if len(candidates) > 1:
            ambiguous_rows.append(
                {
                    "matched_by": matched_by,
                    "mapped_row": mapped_row,
                    "candidate_row_nos": [candidate.get("row_no") for candidate in candidates],
                }
            )
            continue

        target = candidates[0]
        field_updates = update_builder(mapped_row, target)
        changed_fields = _update_item_fields(
            item_name=target["name"],
            batch_doc_name=batch_doc_name,
            version_name=resolved_version_name,
            row_no=target.get("row_no"),
            field_updates=field_updates,
            action_remark=action_remark,
        )
        matched_rows.append(
            {
                "matched_by": matched_by,
                "target_item_name": target["name"],
                "target_row_no": target.get("row_no"),
                "mapped_row": mapped_row,
                "changed_fields": changed_fields,
            }
        )
        if changed_fields:
            updated_count += 1

    if updated_count:
        _mark_batch_dirty(batch_doc_name)

    return {
        "batch_doc_name": batch_doc_name,
        "version_name": resolved_version_name,
        "matched_count": len(matched_rows),
        "updated_count": updated_count,
        "ambiguous_count": len(ambiguous_rows),
        "unmatched_count": len(unmatched_rows),
        "matched_rows": matched_rows,
        "ambiguous_rows": ambiguous_rows,
        "unmatched_rows": unmatched_rows,
        "message": "已完成批次内明细匹配并执行可回填字段更新。" if updated_count else "已完成匹配，但当前没有字段变化需要写入。",
    }


def import_purchase_expense_oa(
    *,
    batch_name: str,
    source_instance_id: str | None = None,
    approval_no: str | None = None,
    official_url: str | None = None,
    version_name: str | None = None,
    detail_rows_json: str | None = None,
) -> dict:
    """第一版采购支出 OA 导入。

    当前职责：
    1. 收口采购支出 OA 的来源标识
    2. 预览明细行会映射到哪些采购字段
    3. 有 Frappe 环境时，按批次内 SKU 自动匹配并回填采购价格字段
    """

    raw_rows = _load_rows(detail_rows_json)
    preview_items = _build_preview_rows(raw_rows, map_purchase_expense_row_to_item)
    dingtalk_payload = build_dingtalk_order_payload(
        batch_name=batch_name,
        approval_no=approval_no,
        instance_id=source_instance_id,
        official_url=official_url,
    )

    def build_purchase_updates(mapped_row: dict, _target: dict) -> dict:
        return {
            "unit_price": mapped_row.get("unit_price"),
            "purchase_currency": mapped_row.get("purchase_currency"),
            "goods_value": mapped_row.get("goods_value"),
            "source_type": mapped_row.get("source_type"),
            "source_doc_no": approval_no or source_instance_id or "",
            "dingtalk_instance_id": source_instance_id or "",
            "dingtalk_official_url": official_url or "",
            "parse_status": "SUCCESS",
        }

    writeback_result = _run_item_writeback(
        batch_name=batch_name,
        version_name=version_name,
        mapped_rows=preview_items,
        update_builder=build_purchase_updates,
        action_remark="采购支出 OA 导入回填采购价格字段",
    )

    return {
        "ok": True,
        "queued": False,
        "batch_name": batch_name,
        "version_name": writeback_result.get("version_name") or version_name,
        "source_type": "PURCHASE_EXPENSE_OA",
        "approval_no": approval_no,
        "source_instance_id": source_instance_id,
        "official_url": official_url,
        "mapped_preview_count": len(preview_items),
        "mapped_preview_items": preview_items[:20],
        "dingtalk_payload": dingtalk_payload,
        "writeback_targets": [
            "unit_price",
            "purchase_currency",
            "goods_value",
            "source_type",
            "source_doc_no",
            "dingtalk_instance_id",
            "dingtalk_official_url",
            "parse_status",
        ],
        "writeback_result": writeback_result,
        "message": writeback_result["message"],
    }


def parse_packing_list_attachment(
    *,
    batch_name: str,
    attachment_name: str | None = None,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
) -> dict:
    """第一版装箱单解析回填。

    当前职责：
    1. 描述解析任务与模板策略
    2. 预览装箱单明细会映射到哪些物理属性字段
    3. 有 Frappe 环境时，把已解析出的字段回填到批次明细
    """

    raw_rows = _load_rows(sheet_rows_json)
    preview_items = _build_preview_rows(raw_rows, map_packing_list_row_to_item)
    parse_task = attachment_parse_service.build_packing_list_parse_task(
        batch_name=batch_name,
        version_name=version_name,
        attachment_name=attachment_name,
        file_url=file_url,
        template_hint=template_hint,
    )

    def build_packing_updates(mapped_row: dict, _target: dict) -> dict:
        return {
            "actual_shipped_qty": mapped_row.get("actual_shipped_qty"),
            "gross_weight_kg": mapped_row.get("gross_weight_kg"),
            "volume_m3": mapped_row.get("volume_m3"),
            "volume_weight_kg": mapped_row.get("volume_weight_kg"),
            "chargeable_weight_kg": mapped_row.get("chargeable_weight_kg"),
            "hs_code": mapped_row.get("hs_code"),
            "source_type": mapped_row.get("source_type"),
            "source_file_name": attachment_name or "",
            "source_doc_no": file_url or attachment_name or "",
            "parse_status": "SUCCESS",
        }

    writeback_result = _run_item_writeback(
        batch_name=batch_name,
        version_name=version_name,
        mapped_rows=preview_items,
        update_builder=build_packing_updates,
        action_remark="装箱单附件解析回填实际发货与物理属性字段",
    )

    return {
        "ok": True,
        "queued": False,
        "batch_name": batch_name,
        "version_name": writeback_result.get("version_name") or version_name,
        "attachment_name": attachment_name,
        "file_url": file_url,
        "source_type": "PACKING_LIST",
        "mapped_preview_count": len(preview_items),
        "mapped_preview_items": preview_items[:20],
        "parse_task": parse_task,
        "writeback_targets": parse_task["parse_targets"],
        "writeback_result": writeback_result,
        "message": writeback_result["message"],
    }
