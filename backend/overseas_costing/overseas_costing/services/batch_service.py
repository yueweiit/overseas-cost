"""
中文用途：批次查询与回写检查服务。

当前先返回稳定的数据结构，占住后续前端对接形态。
后面接数据库时，优先从这里补查询实现。
"""

from __future__ import annotations

import json

try:
    import frappe
except Exception:  # pragma: no cover - 本地无 Frappe 环境时保持可导入
    frappe = None

from overseas_costing.utils.dingtalk import build_dingtalk_order_payload, extract_dingtalk_instance_id


def _get_batch_source_meta(batch_name: str) -> dict:
    """读取批次上的钉钉原单跳转元信息。"""

    meta = {
        "name": batch_name,
        "batch_no": "",
        "source_approval_no": "",
        "source_instance_id": "",
        "source_dingtalk_url": "",
        "source_title": "",
        "source_creator_name": "",
        "source_approval_status": "",
    }
    if frappe is None:
        return meta

    fields = list(meta.keys())
    try:
        rows = frappe.get_all(
            "Overseas Cost Batch",
            filters={"name": batch_name},
            fields=fields,
            limit_page_length=1,
        )
        if not rows:
            rows = frappe.get_all(
                "Overseas Cost Batch",
                filters={"batch_no": batch_name},
                fields=fields,
                limit_page_length=1,
            )
    except Exception:
        return meta

    if rows:
        meta.update(rows[0])
        if not meta.get("source_instance_id") and not meta.get("source_dingtalk_url"):
            try:
                item_rows = frappe.get_all(
                    "Overseas Cost Item",
                    filters={"batch": meta.get("name")},
                    fields=["source_doc_no", "dingtalk_instance_id", "dingtalk_official_url"],
                    limit_page_length=50,
                )
            except Exception:
                item_rows = []
            for item in item_rows:
                if item.get("dingtalk_instance_id") or item.get("dingtalk_official_url"):
                    meta["source_approval_no"] = meta.get("source_approval_no") or item.get("source_doc_no") or ""
                    meta["source_instance_id"] = item.get("dingtalk_instance_id") or extract_dingtalk_instance_id(item.get("dingtalk_official_url")) or ""
                    meta["source_dingtalk_url"] = item.get("dingtalk_official_url") or ""
                    break
    if not meta.get("source_instance_id"):
        meta["source_instance_id"] = extract_dingtalk_instance_id(meta.get("source_dingtalk_url"))
    return meta


def get_batch_list(filters: dict) -> dict:
    return {
        "ok": True,
        "message": "批次列表接口骨架已创建，后续接数据库查询。",
        "filters": filters,
        "items": [],
        "total": 0,
    }


def get_batch_detail(batch_name: str, version_name: str | None = None) -> dict:
    source_meta = _get_batch_source_meta(batch_name)
    return {
        "ok": True,
        "message": "批次详情接口骨架已创建。",
        "batch_name": batch_name,
        "version_name": version_name,
        "header": {
            "batch_no": source_meta.get("batch_no") or batch_name,
            "source_approval_no": source_meta.get("source_approval_no", ""),
            "source_instance_id": source_meta.get("source_instance_id", ""),
            "source_dingtalk_url": source_meta.get("source_dingtalk_url", ""),
            "source_title": source_meta.get("source_title", ""),
            "source_creator_name": source_meta.get("source_creator_name", ""),
            "source_approval_status": source_meta.get("source_approval_status", ""),
        },
        "summary": {},
    }


def get_batch_items(batch_name: str, version_name: str | None = None) -> dict:
    return {
        "ok": True,
        "message": "批次明细接口骨架已创建。",
        "batch_name": batch_name,
        "version_name": version_name,
        "columns": [],
        "items": [],
    }


def get_version_list(batch_name: str) -> dict:
    return {
        "ok": True,
        "message": "版本列表接口骨架已创建。",
        "batch_name": batch_name,
        "items": [],
    }


def get_dingtalk_order_link(batch_name: str) -> dict:
    """返回钉钉原单跳转信息。"""

    source_meta = _get_batch_source_meta(batch_name)
    payload = build_dingtalk_order_payload(
        batch_name=source_meta.get("batch_no") or batch_name,
        approval_no=source_meta.get("source_approval_no"),
        instance_id=source_meta.get("source_instance_id"),
        official_url=source_meta.get("source_dingtalk_url"),
    )
    return {
        "ok": True,
        "batch_name": batch_name,
        "message": "钉钉原单跳转信息已生成。" if payload["can_open"] else "当前批次缺少钉钉实例ID或官方链接。",
        "dingtalk_order": payload,
    }


def check_writeback_ready(batch_name: str, version_name: str | None = None) -> dict:
    return {
        "ok": True,
        "ready": False,
        "batch_name": batch_name,
        "version_name": version_name,
        "checks": {
            "has_current_version": False,
            "is_confirmed": False,
            "has_dirty_data": True,
        },
        "message": "回写检查骨架已创建，后续接正式校验规则。",
    }


def writeback_to_erp(batch_name: str, version_name: str) -> dict:
    return {
        "ok": True,
        "queued": True,
        "batch_name": batch_name,
        "version_name": version_name,
        "message": "ERP 回写骨架已创建，当前仅预留入口。",
    }


# --- Database-backed query implementation for the Excel flat-table MVP. ---

import json as _json

from overseas_costing.utils.field_mapper import normalize_transport_mode

EXCEL_COLUMNS = [
    {"excel_col": "A", "fieldname": "material_code", "label": "物料编码"},
    {"excel_col": "B", "fieldname": "product_name", "label": "产品名称"},
    {"excel_col": "C", "fieldname": "unit_price", "label": "单价"},
    {"excel_col": "C1", "fieldname": "purchase_currency", "label": "采购币种"},
    {"excel_col": "D", "fieldname": "quantity", "label": "数量"},
    {"excel_col": "E", "fieldname": "goods_value", "label": "总货值"},
    {"excel_col": "F", "fieldname": "import_name", "label": "海关进口名称"},
    {"excel_col": "G", "fieldname": "hs_code", "label": "海关分类编码"},
    {"excel_col": "H", "fieldname": "category", "label": "大类分类"},
    {"excel_col": "I", "fieldname": "customs_no", "label": "报关单号"},
    {"excel_col": "J", "fieldname": "waybill_no", "label": "中国到墨西哥运单号"},
    {"excel_col": "K", "fieldname": "china_misc_rmb", "label": "中国运输及相关杂费 RMB"},
    {"excel_col": "L", "fieldname": "china_misc_mxn", "label": "中国运输及相关杂费 MXN"},
    {"excel_col": "M", "fieldname": "china_ocean_usd", "label": "中国海运 USD"},
    {"excel_col": "N", "fieldname": "cc_rate", "label": "C.C税率"},
    {"excel_col": "O", "fieldname": "cc_anti_dumping", "label": "C.C反倾销附加税"},
    {"excel_col": "P", "fieldname": "igi_rate", "label": "IGI关税税率"},
    {"excel_col": "Q", "fieldname": "igi_amount", "label": "IGI关税税额"},
    {"excel_col": "R", "fieldname": "iva_rate", "label": "IVA增值税税率"},
    {"excel_col": "S", "fieldname": "iva_amount", "label": "IVA增值税税额"},
    {"excel_col": "T", "fieldname": "goods_value_ratio", "label": "分摊比例（货值比）"},
    {"excel_col": "U", "fieldname": "dta", "label": "DTA海关递延税款"},
    {"excel_col": "V", "fieldname": "prv_duty", "label": "PRV从价税/关税"},
    {"excel_col": "W", "fieldname": "prv_iva", "label": "PRV的IVA"},
    {"excel_col": "X", "fieldname": "import_tax_total", "label": "IMPUESTOS合计清关税费"},
    {"excel_col": "Y", "fieldname": "revalidacion", "label": "REVALIDACION文件验证费"},
    {"excel_col": "Z", "fieldname": "maniobras", "label": "MANIOBRAS码头操作费"},
    {"excel_col": "AA", "fieldname": "muellaje", "label": "MUELLAJE码头作业费"},
    {"excel_col": "AB", "fieldname": "entrega_mercancia", "label": "ENTREGA DE MERCANCIA配送费用"},
    {"excel_col": "AC", "fieldname": "previo", "label": "PREVIO预检费用"},
    {"excel_col": "AD", "fieldname": "service_aa", "label": "Servicios A.A.货代服务费"},
    {"excel_col": "AE", "fieldname": "almacenajes", "label": "ALMACENAJES仓储费"},
    {"excel_col": "AF", "fieldname": "reconocimiento_aduanero", "label": "RECONOCIMIENTO ADUANERO"},
    {"excel_col": "AG", "fieldname": "honorarios", "label": "HONORARIOS"},
    {"excel_col": "AH", "fieldname": "complemento_maniobras", "label": "COMPLEMENTO DE MANIOBRAS"},
    {"excel_col": "AI", "fieldname": "desconsolidacion", "label": "DESCONSOLIDACION"},
    {"excel_col": "AJ", "fieldname": "maniobra_falso", "label": "MANIOBRA EN FALSO"},
    {"excel_col": "AK", "fieldname": "arrastre", "label": "ARRASTRE拖运费"},
    {"excel_col": "AL", "fieldname": "patio_regulador", "label": "PATIO REGULADOR"},
    {"excel_col": "AM", "fieldname": "entrega_vacio", "label": "ENTREGA DE VACIO还箱费"},
    {"excel_col": "AN", "fieldname": "limpieza_contenedor", "label": "LIMPIEZA DE CONTENEDOR"},
    {"excel_col": "AO", "fieldname": "mexico_customs_mxn", "label": "墨西哥清关费用 MXN"},
    {"excel_col": "AP", "fieldname": "mexico_customs_rmb", "label": "墨西哥清关费用 RMB"},
    {"excel_col": "AQ", "fieldname": "mexico_customs_usd", "label": "墨西哥清关费用 USD"},
    {"excel_col": "AR", "fieldname": "mexico_inland_mxn", "label": "墨西哥内陆运输费用 MXN"},
    {"excel_col": "AS", "fieldname": "mexico_misc_mxn", "label": "墨西哥杂费 MXN"},
    {"excel_col": "AT", "fieldname": "mexico_inland_misc_rmb", "label": "墨西哥内陆运输+杂费 RMB"},
    {"excel_col": "AU", "fieldname": "china_to_mexico_freight_rmb", "label": "中国到墨西哥运费 RMB"},
    {"excel_col": "AV", "fieldname": "gross_weight_kg", "label": "货重毛重 KG"},
    {"excel_col": "AW", "fieldname": "weight_ratio", "label": "分摊比例（重量比）"},
    {"excel_col": "AX", "fieldname": "freight_alloc_rmb", "label": "运输费用分摊 RMB"},
    {"excel_col": "AY", "fieldname": "freight_alloc_mxn", "label": "运输费用分摊 MXN"},
    {"excel_col": "AZ", "fieldname": "total_logistics_mxn", "label": "运输+清关+杂费 MXN"},
    {"excel_col": "BA", "fieldname": "alloc_price_mxn", "label": "分摊物流价格 MXN"},
    {"excel_col": "BB", "fieldname": "total_cost_rmb", "label": "综合成本 RMB"},
    {"excel_col": "BC", "fieldname": "total_unit_rmb", "label": "综合物品单价 RMB"},
    {"excel_col": "BD", "fieldname": "project_collection", "label": "项目归集"},
    {"excel_col": "BE", "fieldname": "transport_mode", "label": "运输方式"},
]
EXCEL_FIELDNAMES = [column["fieldname"] for column in EXCEL_COLUMNS]
EXTRA_ITEM_FIELDS = [
    "name",
    "row_no",
    "excel_row_no",
    "product_name_es",
    "spec_model",
    "unit",
    "recipient",
    "purchase_currency",
    "actual_shipped_qty",
    "volume_m3",
    "volume_weight_kg",
    "chargeable_weight_kg",
    "source_type",
    "source_doc_no",
    "source_file_name",
    "parse_status",
    "manual_override_flag",
    "dingtalk_instance_id",
    "dingtalk_official_url",
]
ITEM_FILTER_FIELDS = (
    "customs_no",
    "waybill_no",
    "material_code",
    "product_name",
    "import_name",
    "hs_code",
    "category",
)
ITEM_KEYWORD_FIELDS = ITEM_FILTER_FIELDS + ("project_collection", "transport_mode")
DEFAULT_FX_RMB_TO_MXN = 2.6
DEFAULT_FX_USD_TO_RMB = round(1 / 0.1393, 6)
HIDDEN_APPROVAL_STATUSES = ("TERMINATED", "CANCELED", "CANCELLED", "REVOKED", "撤销", "已撤销")


def is_hidden_approval_status(status: str | None) -> bool:
    """判断钉钉审批状态是否不应在成本表格中展示。"""

    normalized = str(status or "").strip().upper()
    if not normalized:
        return False
    return any(str(hidden).upper() in normalized for hidden in HIDDEN_APPROVAL_STATUSES)


def _load_batch_payload(batch_payload: str | dict | None) -> dict:
    if not batch_payload:
        return {}
    if isinstance(batch_payload, dict):
        return dict(batch_payload)
    loaded = _json.loads(batch_payload)
    if not isinstance(loaded, dict):
        raise ValueError("新增报关运单参数必须是对象。")
    return loaded


def _clean_payload_text(payload: dict, fieldname: str) -> str:
    return str(payload.get(fieldname) or "").strip()


def _build_manual_batch_values(payload: dict) -> dict:
    batch_no = _clean_payload_text(payload, "batch_no")
    source_dingtalk_url = _clean_payload_text(payload, "source_dingtalk_url")
    source_instance_id = _clean_payload_text(payload, "source_instance_id") or extract_dingtalk_instance_id(source_dingtalk_url)
    values = {
        "batch_no": batch_no,
        "customs_no": _clean_payload_text(payload, "customs_no"),
        "waybill_no": _clean_payload_text(payload, "waybill_no"),
        "container_no": _clean_payload_text(payload, "container_no"),
        "sea_bill_no": _clean_payload_text(payload, "sea_bill_no"),
        "commercial_invoice_no": _clean_payload_text(payload, "commercial_invoice_no"),
        "transport_mode": normalize_transport_mode(payload.get("transport_mode")) or "SEA",
        "project_collection": _clean_payload_text(payload, "project_collection"),
        "source_type": "manual",
        "source_approval_no": _clean_payload_text(payload, "source_approval_no"),
        "source_instance_id": source_instance_id,
        "source_dingtalk_url": source_dingtalk_url,
        "status": "Draft",
        "confirm_status": "Pending",
        "writeback_status": "Not Started",
        "version_count": 1,
        "item_count": 0,
        "import_remark": _clean_payload_text(payload, "import_remark") or "前端手工新增报关运单",
        "source_remark": _clean_payload_text(payload, "source_remark"),
    }
    return values


def create_batch(batch_payload: str | dict | None = None) -> dict:
    """新增一个空批次和默认当前版本，供后续手工加物料或文件补数。"""

    try:
        payload = _load_batch_payload(batch_payload)
    except Exception as exc:
        return {
            "ok": False,
            "dry_run": frappe is None,
            "message": f"新增报关运单参数解析失败：{exc}",
        }

    values = _build_manual_batch_values(payload)
    if not values["batch_no"]:
        return {
            "ok": False,
            "dry_run": frappe is None,
            "message": "请填写批次号/来源单号。",
        }

    version_values = {
        "version_code": f"手工-{values['batch_no']}",
        "version_type": "Estimated",
        "status": "Active",
        "is_current": 1,
        "source_type": "Manual",
        "fx_usd_to_rmb": DEFAULT_FX_USD_TO_RMB,
        "fx_rmb_to_mxn": DEFAULT_FX_RMB_TO_MXN,
        "remark": "前端手工新增批次默认版本",
    }

    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch": values,
            "version": version_values,
            "message": "当前未连接 Frappe，已返回新增报关运单预览。",
        }

    existing_name = frappe.db.get_value("Overseas Cost Batch", {"batch_no": values["batch_no"]}, "name")
    if existing_name:
        return {
            "ok": False,
            "batch_name": existing_name,
            "message": f"批次号已存在：{values['batch_no']}。请直接查询或换一个批次号。",
        }

    batch_doc = frappe.get_doc({"doctype": "Overseas Cost Batch", **values}).insert(ignore_permissions=True)
    version_doc = frappe.get_doc(
        {
            "doctype": "Overseas Cost Version",
            "batch": batch_doc.name,
            **version_values,
        }
    ).insert(ignore_permissions=True)
    frappe.db.set_value(
        "Overseas Cost Batch",
        batch_doc.name,
        {
            "current_version": version_doc.name,
            "version_count": 1,
            "item_count": 0,
        },
        update_modified=False,
    )
    frappe.get_doc(
        {
            "doctype": "Overseas Cost Audit Log",
            "batch": batch_doc.name,
            "version": version_doc.name,
            "action_type": "BATCH_EDIT",
            "field_name": "batch",
            "new_value": _json.dumps(values, ensure_ascii=False, default=str),
            "operator_name": getattr(frappe.session, "user", "") if getattr(frappe, "session", None) else "",
            "action_remark": "前端手工新增报关运单",
        }
    ).insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "ok": True,
        "batch_name": batch_doc.name,
        "version_name": version_doc.name,
        "batch_no": values["batch_no"],
        "message": "报关运单已新增，可继续添加物料或导入附件补数。",
    }


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
    current_version = frappe.db.get_value("Overseas Cost Batch", batch_doc_name, "current_version")
    if current_version:
        return current_version
    rows = frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=["name"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return rows[0]["name"] if rows else None


def _load_json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return _json.loads(text)
    except Exception:
        return {}


def _clean_query_value(value) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _normalize_item_query_filters(filters: dict | None = None, **overrides) -> dict:
    query_filters = {}
    if isinstance(filters, dict):
        query_filters.update(filters)
    for key, value in overrides.items():
        if value not in (None, ""):
            query_filters[key] = value
    return {
        key: _clean_query_value(value)
        for key, value in query_filters.items()
        if _clean_query_value(value)
    }


def _build_item_query_args(
    batch_doc_name: str,
    version_name: str,
    filters: dict | None = None,
    *,
    keyword: str | None = None,
) -> tuple[list[list[str]], list[list[str]]]:
    query_filters = _normalize_item_query_filters(filters)
    keyword_value = _clean_query_value(keyword or query_filters.pop("keyword", ""))
    db_filters = [["batch", "=", batch_doc_name], ["version", "=", version_name]]

    for fieldname in ITEM_FILTER_FIELDS:
        value = query_filters.get(fieldname)
        if value:
            db_filters.append([fieldname, "like", f"%{value}%"])

    or_filters = []
    if keyword_value:
        or_filters = [[fieldname, "like", f"%{keyword_value}%"] for fieldname in ITEM_KEYWORD_FIELDS]

    return db_filters, or_filters


def _has_source_value(value) -> bool:
    return str(value or "").strip() != ""


def _source_status_key(value) -> str:
    return str(value or "").strip().lower()


def _is_parsed_attachment(row: dict) -> bool:
    return _source_status_key(row.get("parse_status")) == "parsed"


def _get_oa_logistics_trace(extra_json) -> dict:
    if isinstance(extra_json, dict):
        payload = dict(extra_json)
    else:
        try:
            payload = json.loads(extra_json or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
    if not isinstance(payload, dict):
        return {}
    trace = payload.get("oa_logistics_trace")
    return trace if isinstance(trace, dict) else payload


def _quote_candidate_summary(candidate: dict) -> dict:
    return {
        "carrier": str(candidate.get("carrier") or "").strip(),
        "amount": candidate.get("amount"),
        "currency": str(candidate.get("currency") or "").strip(),
        "volume_m3": candidate.get("volume_m3"),
        "evidence_line": str(candidate.get("evidence_line") or "").strip(),
        "source_field": str(candidate.get("source_field") or "").strip(),
        "status": str(candidate.get("status") or "待确认").strip(),
    }


def _build_batch_source_status(batch: dict, attachments: list[dict] | None = None) -> dict:
    """按业务资料链路汇总批次来源状态，供前端数据检查展示。"""

    attachment_rows = attachments or []
    source_no = (
        batch.get("source_approval_no")
        or batch.get("source_instance_id")
        or batch.get("batch_no")
        or batch.get("name")
        or ""
    )
    has_oa_logistics = (
        batch.get("source_type") == "oa_logistics"
        or _has_source_value(batch.get("source_approval_no"))
        or _has_source_value(batch.get("source_instance_id"))
        or _has_source_value(batch.get("source_dingtalk_url"))
    )

    oa_attachment_rows = [row for row in attachment_rows if row.get("source_type") == "OA"]
    packing_list_rows = [row for row in attachment_rows if row.get("attachment_type") == "Packing List"]
    tax_certificate_rows = [
        row
        for row in attachment_rows
        if row.get("attachment_type") == "Tax Certificate" or row.get("source_type") == "Voucher"
    ]
    batch_source_attachment_count = int(batch.get("source_attachment_count") or 0)
    oa_attachment_count = max(batch_source_attachment_count, len(oa_attachment_rows))
    trace = _get_oa_logistics_trace(batch.get("extra_json"))
    quote_candidates = trace.get("logistics_quote_candidates") or []
    if not isinstance(quote_candidates, list):
        quote_candidates = []
    if not quote_candidates and isinstance(trace.get("form_fields"), dict):
        try:
            from overseas_costing.scripts.import_oa_logistics import extract_logistics_quote_candidates_from_approval

            quote_candidates = extract_logistics_quote_candidates_from_approval({"form_fields": trace["form_fields"]})
        except Exception:
            quote_candidates = []
    quote_candidates = [_quote_candidate_summary(row) for row in quote_candidates if isinstance(row, dict)]
    confirmed_quote = trace.get("confirmed_logistics_quote")
    confirmed_quote = _quote_candidate_summary(confirmed_quote) if isinstance(confirmed_quote, dict) else {}

    return {
        "source_no": source_no,
        "has_oa_logistics": bool(has_oa_logistics),
        "source_approval_status": batch.get("source_approval_status") or "",
        "oa_attachment_count": oa_attachment_count,
        "registered_attachment_count": len(attachment_rows),
        "packing_list_count": len(packing_list_rows),
        "parsed_packing_list_count": sum(1 for row in packing_list_rows if _is_parsed_attachment(row)),
        "tax_certificate_count": len(tax_certificate_rows),
        "parsed_tax_certificate_count": sum(1 for row in tax_certificate_rows if _is_parsed_attachment(row)),
        "has_form_attachments": oa_attachment_count > 0,
        "has_packing_list": bool(packing_list_rows),
        "has_tax_certificate": bool(tax_certificate_rows),
        "logistics_quote_candidate_count": len(quote_candidates),
        "logistics_quote_candidates": quote_candidates,
        "confirmed_logistics_quote": confirmed_quote,
        "has_confirmed_logistics_quote": bool(confirmed_quote.get("amount")),
    }


def _attach_batch_source_status(items: list[dict]) -> list[dict]:
    if not items:
        return items

    batch_names = [item.get("name") for item in items if item.get("name")]
    attachment_rows: list[dict] = []
    if batch_names:
        try:
            attachment_rows = frappe.get_all(
                "Overseas Cost Attachment",
                filters={"batch": ["in", batch_names]},
                fields=["batch", "source_type", "attachment_type", "parse_status"],
                limit_page_length=10000,
            )
        except Exception:
            attachment_rows = []

    attachments_by_batch: dict[str, list[dict]] = {}
    for row in attachment_rows:
        batch_name = row.get("batch")
        if not batch_name:
            continue
        attachments_by_batch.setdefault(batch_name, []).append(row)

    for item in items:
        item["source_status"] = _build_batch_source_status(
            item,
            attachments_by_batch.get(item.get("name"), []),
        )
    return items


def get_batch_list(filters: dict) -> dict:
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "message": "当前未连接 Frappe，返回空批次列表。",
            "filters": filters,
            "items": [],
            "total": 0,
        }

    db_filters = []
    if filters.get("transport_mode"):
        db_filters.append(["transport_mode", "=", filters["transport_mode"]])
    if filters.get("status"):
        db_filters.append(["status", "=", filters["status"]])

    keyword = filters.get("keyword")
    query_kwargs = {
        "filters": db_filters,
        "fields": [
            "name",
            "batch_no",
            "customs_no",
            "waybill_no",
            "transport_mode",
            "project_collection",
            "source_type",
            "source_file_name",
            "source_sheet",
            "source_range",
            "source_approval_no",
            "source_instance_id",
            "source_dingtalk_url",
            "source_approval_status",
            "source_attachment_count",
            "status",
            "current_version",
            "item_count",
            "total_goods_value",
            "total_gross_weight_kg",
            "estimated_total_cost_rmb",
            "actual_total_cost_rmb",
            "extra_json",
            "modified",
        ],
        "order_by": "modified desc",
        "limit_page_length": 200,
    }
    if keyword:
        like_keyword = f"%{keyword}%"
        query_kwargs["or_filters"] = [
            ["batch_no", "like", like_keyword],
            ["customs_no", "like", like_keyword],
            ["waybill_no", "like", like_keyword],
            ["project_collection", "like", like_keyword],
        ]

    items = [
        item
        for item in frappe.get_all("Overseas Cost Batch", **query_kwargs)
        if not is_hidden_approval_status(item.get("source_approval_status"))
    ]
    items = _attach_batch_source_status(items)
    for item in items:
        item.pop("extra_json", None)
    return {
        "ok": True,
        "message": "批次列表已返回。",
        "filters": filters,
        "items": items,
        "total": len(items),
    }


def get_batch_detail(batch_name: str, version_name: str | None = None) -> dict:
    if frappe is None:
        source_meta = _get_batch_source_meta(batch_name)
        return {
            "ok": True,
            "dry_run": True,
            "message": "当前未连接 Frappe，返回批次详情预览。",
            "batch_name": batch_name,
            "version_name": version_name,
            "header": {"batch_no": source_meta.get("batch_no") or batch_name},
            "summary": {},
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    header = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_doc_name,
        [
            "name",
            "batch_no",
            "customs_no",
            "waybill_no",
            "container_no",
            "sea_bill_no",
            "commercial_invoice_no",
            "transport_mode",
            "project_collection",
            "source_type",
            "source_file_name",
            "source_sheet",
            "source_range",
            "source_approval_no",
            "source_instance_id",
            "source_dingtalk_url",
            "status",
            "current_version",
            "confirm_status",
            "writeback_status",
            "item_count",
            "total_goods_value",
            "total_gross_weight_kg",
            "estimated_total_cost_rmb",
            "actual_total_cost_rmb",
        ],
        as_dict=True,
    )
    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    version = {}
    summary = {}
    if resolved_version_name:
        version = frappe.db.get_value(
            "Overseas Cost Version",
            resolved_version_name,
            [
                "name",
                "version_code",
                "version_type",
                "status",
                "is_current",
                "fx_usd_to_rmb",
                "fx_rmb_to_mxn",
                "calculated_at",
                "summary_snapshot_json",
            ],
            as_dict=True,
        ) or {}
        summary = _load_json(version.get("summary_snapshot_json"))

    rules = []
    if resolved_version_name:
        rules = frappe.get_all(
            "Overseas Cost Allocation Rule",
            filters={"batch": batch_doc_name, "version": resolved_version_name},
            fields=["name", "rule_code", "expense_category", "allocation_basis", "currency", "amount", "is_enabled"],
            order_by="priority_no asc, modified asc",
            limit_page_length=1000,
        )

    return {
        "ok": True,
        "message": "批次详情已返回。",
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "header": header,
        "version": version,
        "summary": summary,
        "allocation_rules": rules,
    }


def get_batch_items(
    batch_name: str,
    version_name: str | None = None,
    filters: dict | None = None,
    keyword: str | None = None,
    customs_no: str | None = None,
    waybill_no: str | None = None,
    material_code: str | None = None,
    product_name: str | None = None,
    import_name: str | None = None,
    hs_code: str | None = None,
    category: str | None = None,
) -> dict:
    query_filters = _normalize_item_query_filters(
        filters,
        keyword=keyword,
        customs_no=customs_no,
        waybill_no=waybill_no,
        material_code=material_code,
        product_name=product_name,
        import_name=import_name,
        hs_code=hs_code,
        category=category,
    )
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "message": "当前未连接 Frappe，返回空明细。",
            "batch_name": batch_name,
            "version_name": version_name,
            "filters": query_filters,
            "columns": EXCEL_COLUMNS,
            "items": [],
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    if not resolved_version_name:
        return {"ok": False, "batch_name": batch_doc_name, "message": "当前批次没有版本。"}

    fields = list(dict.fromkeys(EXTRA_ITEM_FIELDS + EXCEL_FIELDNAMES))
    db_filters, or_filters = _build_item_query_args(
        batch_doc_name,
        resolved_version_name,
        query_filters,
    )
    items = frappe.get_all(
        "Overseas Cost Item",
        filters=db_filters,
        or_filters=or_filters,
        fields=fields,
        order_by="row_no asc",
        limit_page_length=10000,
    )
    return {
        "ok": True,
        "message": "批次明细已返回。",
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "filters": query_filters,
        "columns": EXCEL_COLUMNS,
        "items": items,
        "total": len(items),
    }


def get_version_list(batch_name: str) -> dict:
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "message": "当前未连接 Frappe，返回空版本列表。",
            "batch_name": batch_name,
            "items": [],
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}

    items = frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=[
            "name",
            "version_code",
            "version_type",
            "status",
            "is_current",
            "source_type",
            "fx_usd_to_rmb",
            "fx_rmb_to_mxn",
            "calculated_at",
            "modified",
        ],
        order_by="creation asc",
        limit_page_length=1000,
    )
    return {
        "ok": True,
        "message": "版本列表已返回。",
        "batch_name": batch_doc_name,
        "items": items,
    }


def _normalize_limit(limit, default: int = 80, maximum: int = 300) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def get_audit_logs(batch_name: str, version_name: str | None = None, limit: int | str = 80) -> dict:
    normalized_limit = _normalize_limit(limit)
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "message": "当前未连接 Frappe，返回空修改记录。",
            "batch_name": batch_name,
            "version_name": version_name,
            "items": [],
            "total": 0,
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}", "items": [], "total": 0}

    filters = {"batch": batch_doc_name}
    if version_name:
        filters["version"] = version_name

    items = frappe.get_all(
        "Overseas Cost Audit Log",
        filters=filters,
        fields=[
            "name",
            "batch",
            "version",
            "action_type",
            "field_name",
            "row_no",
            "old_value",
            "new_value",
            "operator_name",
            "action_remark",
            "creation",
        ],
        order_by="creation desc",
        limit_page_length=normalized_limit,
    )
    return {
        "ok": True,
        "message": "修改记录已返回。",
        "batch_name": batch_doc_name,
        "version_name": version_name,
        "items": items,
        "total": len(items),
    }


def check_writeback_ready(batch_name: str, version_name: str | None = None) -> dict:
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "ready": False,
            "batch_name": batch_name,
            "version_name": version_name,
            "checks": {},
            "message": "当前未连接 Frappe，返回回写检查预览。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "ready": False, "message": f"未找到批次：{batch_name}"}

    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_doc_name,
        ["status", "confirm_status", "current_version"],
        as_dict=True,
    ) or {}
    checks = {
        "has_current_version": bool(resolved_version_name or batch.get("current_version")),
        "is_confirmed": batch.get("confirm_status") == "Confirmed",
        "has_dirty_data": batch.get("status") == "Dirty",
    }
    ready = checks["has_current_version"] and checks["is_confirmed"] and not checks["has_dirty_data"]
    return {
        "ok": True,
        "ready": ready,
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "checks": checks,
        "message": "允许回写。" if ready else "当前批次暂不满足回写条件。",
    }
