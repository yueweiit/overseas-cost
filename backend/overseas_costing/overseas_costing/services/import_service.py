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
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
DEFAULT_FX_USD_TO_RMB = round(1 / 0.1393, 6)
DEFAULT_DINGTALK_CORP_ID = "ding144583309b2fb01c35c2f4657eb6378f"
PURCHASE_WRITEBACK_FIELDS = (
    "unit_price",
    "purchase_currency",
    "goods_value",
)
PURCHASE_FIELD_LABELS = {
    "unit_price": "单价Precio",
    "purchase_currency": "币种Moneda",
    "goods_value": "总金额Monto Total",
    "source_type": "来源类型",
    "source_doc_no": "来源审批编号",
    "dingtalk_instance_id": "钉钉实例ID",
    "dingtalk_official_url": "钉钉原单链接",
    "parse_status": "解析状态",
}
PACKING_WRITEBACK_FIELDS = (
    "actual_shipped_qty",
    "gross_weight_kg",
    "volume_m3",
    "volume_weight_kg",
    "chargeable_weight_kg",
)
PACKING_FIELD_LABELS = {
    "actual_shipped_qty": "实际发货数量",
    "gross_weight_kg": "毛重 KG",
    "volume_m3": "体积 m3",
    "volume_weight_kg": "体积重 KG",
    "chargeable_weight_kg": "计费重 KG",
    "hs_code": "海关编码",
    "source_type": "来源类型",
    "source_file_name": "来源文件",
    "source_doc_no": "来源单号",
    "parse_status": "解析状态",
}
DINGTALK_ENV_FILE_CANDIDATES = (
    "/mnt/e/Yuewei开发/预算管理系统/dingtalk-expense-sync-main/.env",
    "/mnt/e/Yuewei开发/预算管理系统/dingtalk-budget-main/server/.env",
    "/mnt/e/Yuewei开发/dingtalk-expense-sync-main/.env",
    "/mnt/e/Yuewei开发/dingtalk-budget-main/server/.env",
    "E:/Yuewei开发/预算管理系统/dingtalk-expense-sync-main/.env",
    "E:/Yuewei开发/预算管理系统/dingtalk-budget-main/server/.env",
    "E:/Yuewei开发/dingtalk-expense-sync-main/.env",
    "E:/Yuewei开发/dingtalk-budget-main/server/.env",
)
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
    resolved_fx_usd_to_rmb = fx_usd_to_rmb or DEFAULT_FX_USD_TO_RMB
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
            fx_usd_to_rmb=resolved_fx_usd_to_rmb,
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


def list_oa_form_attachments(batch_name: str, limit: int | None = 50) -> dict:
    """返回钉钉发起表单附件记录；评论附件本阶段不纳入。"""

    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "items": [],
            "total": 0,
            "message": "当前未连接 Frappe，返回空附件记录。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {
            "ok": False,
            "batch_name": batch_name,
            "items": [],
            "total": 0,
            "message": f"未找到批次：{batch_name}",
        }

    requested_limit = max(1, min(int(limit or 50), 200))
    rows = frappe.get_all(
        "Overseas Cost Attachment",
        filters={"batch": batch_doc_name, "source_type": "OA"},
        fields=[
            "name",
            "batch",
            "version",
            "source_type",
            "attachment_type",
            "source_doc_no",
            "file_name",
            "file_url",
            "parse_status",
            "parse_result_json",
            "mapped_result_json",
            "remark",
            "creation",
            "modified",
        ],
        order_by="creation asc",
        limit_page_length=requested_limit,
    )

    items = []
    for row in rows:
        parse_result = _json_loads_dict(row.get("parse_result_json"))
        mapped_result = _json_loads_dict(row.get("mapped_result_json"))
        items.append(
            {
                "name": row.get("name"),
                "batch": row.get("batch"),
                "version": row.get("version"),
                "attachment_type": row.get("attachment_type") or "Other",
                "source_doc_no": row.get("source_doc_no") or "",
                "file_name": row.get("file_name") or "",
                "file_url": row.get("file_url") or "",
                "parse_status": row.get("parse_status") or "",
                "source_field": parse_result.get("source_field") or "",
                "file_id": parse_result.get("file_id") or "",
                "space_id": parse_result.get("space_id") or "",
                "file_ext": parse_result.get("file_ext") or "",
                "parse_targets": mapped_result.get("parse_targets") or [],
                "can_download": bool(parse_result.get("file_id")) and not bool(row.get("file_url")),
                "remark": row.get("remark") or "",
                "creation": row.get("creation"),
                "modified": row.get("modified"),
            }
        )

    return {
        "ok": True,
        "batch_name": batch_name,
        "batch_doc_name": batch_doc_name,
        "items": items,
        "total": len(items),
        "comment_attachments_included": False,
        "message": "钉钉发起表单附件记录已返回；评论附件未纳入。",
    }


def download_oa_form_attachment(
    attachment_name: str,
    env_file: str | None = None,
    access_token: str | None = None,
) -> dict:
    """下载钉钉审批发起表单附件，并回填系统文件地址。"""

    resolved_attachment_name = str(attachment_name or "").strip()
    if not resolved_attachment_name:
        return {"ok": False, "message": "缺少附件记录名称。"}

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "attachment_name": resolved_attachment_name,
            "message": "当前未连接 Frappe，不能下载并保存钉钉附件。",
        }

    try:
        attachment_doc = frappe.get_doc("Overseas Cost Attachment", resolved_attachment_name)
    except Exception as exc:
        return {
            "ok": False,
            "attachment_name": resolved_attachment_name,
            "message": f"未找到附件记录：{exc}",
        }

    if getattr(attachment_doc, "source_type", "") != "OA":
        return {
            "ok": False,
            "attachment_name": resolved_attachment_name,
            "message": "该记录不是钉钉 OA 发起附件，不能用钉钉附件下载接口处理。",
        }

    existing_file_url = str(getattr(attachment_doc, "file_url", "") or "").strip()
    if existing_file_url:
        return {
            "ok": True,
            "downloaded": False,
            "attachment_name": resolved_attachment_name,
            "file_url": existing_file_url,
            "message": "附件已经有系统文件地址，无需重复下载。",
        }

    parse_snapshot = _json_loads_dict(getattr(attachment_doc, "parse_result_json", ""))
    raw_attachment = parse_snapshot.get("raw_attachment") if isinstance(parse_snapshot.get("raw_attachment"), dict) else {}
    process_instance_id = str(
        parse_snapshot.get("instance_id")
        or parse_snapshot.get("process_instance_id")
        or parse_snapshot.get("proc_inst_id")
        or ""
    ).strip()
    file_id = str(
        parse_snapshot.get("file_id")
        or raw_attachment.get("fileId")
        or raw_attachment.get("file_id")
        or raw_attachment.get("mediaId")
        or raw_attachment.get("id")
        or ""
    ).strip()

    if not process_instance_id or not file_id:
        return {
            "ok": False,
            "attachment_name": resolved_attachment_name,
            "message": "附件记录缺少钉钉审批实例 ID 或 file_id，请先重新拉取国际物流 OA。",
            "missing": {
                "process_instance_id": not bool(process_instance_id),
                "file_id": not bool(file_id),
            },
        }

    file_name = str(getattr(attachment_doc, "file_name", "") or raw_attachment.get("fileName") or file_id).strip()
    try:
        from overseas_costing.scripts.import_oa_logistics import (
            get_access_token,
            get_process_attachment_download_url,
            load_env_file,
        )

        resolved_env_file = _resolve_dingtalk_env_file(env_file)
        if resolved_env_file:
            load_env_file(resolved_env_file)
        corp_id = _resolve_attachment_corp_id(attachment_doc, parse_snapshot)
        token = get_access_token(
            api_style="new",
            access_token=str(access_token or "").strip(),
            corp_id=corp_id,
        )
        download_info = get_process_attachment_download_url(
            token=token,
            process_instance_id=process_instance_id,
            file_id=file_id,
        )
        content, response_meta = _fetch_dingtalk_attachment_content(download_info["download_uri"])
        file_doc = _save_content_as_frappe_file(
            file_name=file_name,
            content=content,
            attached_to_name=resolved_attachment_name,
        )
    except Exception as exc:
        return {
            "ok": False,
            "attachment_name": resolved_attachment_name,
            "file_name": file_name,
            "message": f"钉钉附件下载失败：{exc}",
        }

    file_url = _get_doc_value(file_doc, "file_url") or ""
    parse_snapshot["download"] = {
        "source": "dingtalk_oa_form_attachment",
        "process_instance_id": process_instance_id,
        "file_id": file_id,
        "download_uri_obtained": True,
        "content_type": response_meta.get("content_type") or "",
        "content_length": response_meta.get("content_length") or len(content),
    }
    attachment_doc.file_url = file_url
    attachment_doc.parse_status = getattr(attachment_doc, "parse_status", "") or "Queued"
    attachment_doc.parse_result_json = _json_dumps(parse_snapshot)
    attachment_doc.remark = "钉钉发起表单附件已保存，可在附件列表中下载到本地；评论附件暂不处理。"
    attachment_doc.save(ignore_permissions=True)
    if hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "downloaded": True,
        "attachment_name": resolved_attachment_name,
        "file_name": file_name,
        "file_url": file_url,
        "content_type": response_meta.get("content_type") or "",
        "content_length": response_meta.get("content_length") or len(content),
        "message": "钉钉附件已保存，可点击下载到本地，也可以继续解析预览。",
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


def _load_json_list(rows_json: str | None) -> list[dict]:
    if not rows_json:
        return []

    loaded = json.loads(rows_json)
    if isinstance(loaded, dict):
        loaded = [loaded]
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


def _fetch_dingtalk_attachment_content(download_uri: str) -> tuple[bytes, dict]:
    url = str(download_uri or "").strip()
    if not url:
        raise ValueError("缺少钉钉附件下载地址。")
    request = Request(url, headers={"User-Agent": "overseas-costing/1.0"})
    try:
        with urlopen(request, timeout=60) as response:
            content = response.read()
            return content, {
                "content_type": response.headers.get("Content-Type", ""),
                "content_length": int(response.headers.get("Content-Length") or len(content)),
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"附件下载 HTTP {exc.code}: {body[:300]}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"附件下载网络失败：{exc}") from exc


def _save_content_as_frappe_file(*, file_name: str, content: bytes, attached_to_name: str):
    if frappe is None:
        raise RuntimeError("当前未连接 Frappe。")
    from frappe.utils.file_manager import save_file

    try:
        return save_file(
            fname=file_name or "dingtalk-attachment",
            content=content,
            dt="Overseas Cost Attachment",
            dn=attached_to_name,
            is_private=1,
            decode=False,
        )
    except Exception as exc:
        if not _is_frappe_file_size_error(exc):
            raise
        return _save_large_content_as_private_file(
            file_name=file_name,
            content=content,
            attached_to_name=attached_to_name,
        )


def _is_frappe_file_size_error(exc: Exception) -> bool:
    text = str(exc)
    return "File size exceeded" in text or "maximum allowed size" in text


def _save_large_content_as_private_file(*, file_name: str, content: bytes, attached_to_name: str):
    safe_name = _safe_private_file_name(file_name or "dingtalk-attachment")
    private_dir = Path(frappe.get_site_path("private", "files"))
    private_dir.mkdir(parents=True, exist_ok=True)
    target_path = _deduplicate_private_file_path(private_dir / safe_name)
    target_path.write_bytes(content)
    file_url = f"/private/files/{target_path.name}"
    return frappe.get_doc(
        {
            "doctype": "File",
            "file_name": target_path.name,
            "file_url": file_url,
            "is_private": 1,
            "attached_to_doctype": "Overseas Cost Attachment",
            "attached_to_name": attached_to_name,
            "folder": "Home/Attachments",
        }
    ).insert(ignore_permissions=True)


def _safe_private_file_name(file_name: str) -> str:
    name = Path(str(file_name or "dingtalk-attachment")).name.strip() or "dingtalk-attachment"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def _deduplicate_private_file_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成不重名的附件文件名：{path.name}")


def _get_doc_value(doc, fieldname: str, default: str = ""):
    if isinstance(doc, dict):
        return doc.get(fieldname, default)
    return getattr(doc, fieldname, default)


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _extract_dingtalk_corp_id(value: str | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(?:[?&]|^)corpid=([^&#]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _resolve_attachment_corp_id(attachment_doc, parse_snapshot: dict) -> str:
    env_value = (
        os.environ.get("DINGTALK_CORP_ID")
        or os.environ.get("DINGTALK_CORPID")
        or os.environ.get("DINGTALK_CORP")
        or ""
    )
    corp_id = _extract_dingtalk_corp_id(env_value) or str(env_value or "").strip()
    if corp_id:
        return corp_id

    for key in ("source_dingtalk_url", "official_url", "url", "open_url"):
        corp_id = _extract_dingtalk_corp_id(parse_snapshot.get(key))
        if corp_id:
            return corp_id

    batch_name = str(getattr(attachment_doc, "batch", "") or "").strip()
    if frappe is not None and batch_name:
        try:
            row = frappe.db.get_value(
                "Overseas Cost Batch",
                batch_name,
                ["source_dingtalk_url"],
                as_dict=True,
            )
        except Exception:
            row = None
        if row:
            corp_id = _extract_dingtalk_corp_id(row.get("source_dingtalk_url"))
            if corp_id:
                return corp_id
    return DEFAULT_DINGTALK_CORP_ID


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
        return abs(float(old_value) - float(new_value)) <= 0.000001
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


def _normalize_currency_code(value) -> str:
    normalized = _normalize_key(value).replace(" ", "")
    if not normalized:
        return "RMB"
    if any(token in normalized for token in ("rmb", "cny", "人民币")):
        return "RMB"
    if any(token in normalized for token in ("usd", "dólar", "dolar", "美元", "美金")):
        return "USD"
    if any(token in normalized for token in ("mxn", "peso", "pesos", "墨西哥")):
        return "MXN"
    return normalized.upper()


def _get_version_fx_context(version_name: str | None) -> dict:
    context = {
        "fx_usd_to_rmb": DEFAULT_FX_USD_TO_RMB,
        "fx_rmb_to_mxn": DEFAULT_FX_RMB_TO_MXN,
    }
    if frappe is None or not version_name:
        return context

    row = frappe.db.get_value(
        "Overseas Cost Version",
        version_name,
        ["fx_usd_to_rmb", "fx_rmb_to_mxn"],
        as_dict=True,
    )
    if row:
        fx_usd_to_rmb = _to_float(row.get("fx_usd_to_rmb")) or DEFAULT_FX_USD_TO_RMB
        fx_rmb_to_mxn = _to_float(row.get("fx_rmb_to_mxn")) or DEFAULT_FX_RMB_TO_MXN
        context["fx_usd_to_rmb"] = fx_usd_to_rmb
        context["fx_rmb_to_mxn"] = fx_rmb_to_mxn
        updates = {}
        if not _to_float(row.get("fx_usd_to_rmb")):
            updates["fx_usd_to_rmb"] = fx_usd_to_rmb
        if not _to_float(row.get("fx_rmb_to_mxn")):
            updates["fx_rmb_to_mxn"] = fx_rmb_to_mxn
        if updates:
            frappe.db.set_value("Overseas Cost Version", version_name, updates, update_modified=False)
    return context


def _amount_to_rmb(amount, currency, fx_context: dict) -> float:
    value = _to_float(amount, default=0.0)
    currency_code = _normalize_currency_code(currency)
    if currency_code == "USD":
        return value * (_to_float(fx_context.get("fx_usd_to_rmb")) or DEFAULT_FX_USD_TO_RMB)
    if currency_code == "MXN":
        return value / (_to_float(fx_context.get("fx_rmb_to_mxn")) or DEFAULT_FX_RMB_TO_MXN)
    return value


def _convert_purchase_updates_to_rmb(field_updates: dict, fx_context: dict) -> dict:
    converted = dict(field_updates or {})
    currency = converted.get("purchase_currency")
    if "unit_price" in converted:
        converted["unit_price"] = _amount_to_rmb(converted.get("unit_price"), currency, fx_context)
    if "goods_value" in converted:
        converted["goods_value"] = _amount_to_rmb(converted.get("goods_value"), currency, fx_context)
    return converted


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


def _get_batch_trace_row(batch_doc_name: str) -> dict:
    if frappe is None:
        return {}
    return frappe.db.get_value(
        "Overseas Cost Batch",
        batch_doc_name,
        [
            "name",
            "batch_no",
            "source_approval_no",
            "source_instance_id",
            "source_dingtalk_url",
            "extra_json",
        ],
        as_dict=True,
    ) or {}


def _get_linked_purchase_approvals_from_extra(extra_json: str | dict | None) -> list[dict]:
    payload = _json_loads_dict(extra_json)
    trace = payload.get("oa_logistics_trace") if isinstance(payload.get("oa_logistics_trace"), dict) else {}
    candidates = [
        payload.get("linked_purchase_approvals"),
        trace.get("linked_purchase_approvals"),
    ]
    linked: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for value in candidates:
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            approval_no = str(row.get("approval_no") or row.get("source_approval_no") or row.get("business_id") or "").strip()
            instance_id = str(
                row.get("source_instance_id")
                or row.get("proc_inst_id")
                or row.get("procInstId")
                or row.get("instance_id")
                or ""
            ).strip()
            key = (approval_no, instance_id)
            if key in seen:
                continue
            seen.add(key)
            linked.append({**row, "approval_no": approval_no, "source_instance_id": instance_id})
    return linked


def _normalize_purchase_summary(summary: dict) -> dict:
    mapped_items = summary.get("mapped_preview_items")
    if not isinstance(mapped_items, list):
        mapped_items = []
    return {
        "ok": summary.get("ok", True),
        "source_approval_no": summary.get("source_approval_no") or summary.get("approval_no") or "",
        "source_instance_id": summary.get("source_instance_id") or "",
        "source_dingtalk_url": summary.get("source_dingtalk_url") or summary.get("official_url") or "",
        "approval_title": summary.get("approval_title") or "",
        "approval_status": summary.get("approval_status") or "",
        "purchase_currency": summary.get("purchase_currency") or "",
        "detail_row_count": summary.get("detail_row_count") or len(mapped_items),
        "mapped_preview_items": mapped_items,
        "message": summary.get("message") or "",
    }


def _load_purchase_summaries_from_json(purchase_summaries_json: str | None) -> list[dict]:
    return [_normalize_purchase_summary(summary) for summary in _load_json_list(purchase_summaries_json)]


def _build_purchase_summary_preview_row(summary: dict) -> dict:
    approval_no = summary.get("source_approval_no") or ""
    instance_id = summary.get("source_instance_id") or ""
    official_url = summary.get("source_dingtalk_url") or ""
    dingtalk_payload = build_dingtalk_order_payload(
        approval_no=approval_no,
        instance_id=instance_id,
        official_url=official_url,
    )
    return {
        "source_approval_no": approval_no,
        "source_instance_id": instance_id,
        "source_dingtalk_url": official_url,
        "approval_title": summary.get("approval_title"),
        "approval_status": summary.get("approval_status"),
        "purchase_currency": summary.get("purchase_currency"),
        "detail_row_count": summary.get("detail_row_count"),
        "open_url": dingtalk_payload.get("open_url") or "",
        "open_mode": dingtalk_payload.get("open_mode") or "unavailable",
        "can_open": bool(dingtalk_payload.get("can_open")),
    }


def _resolve_dingtalk_env_file(env_file: str | None = None) -> str:
    explicit = str(env_file or os.environ.get("DINGTALK_ENV_FILE") or "").strip()
    if explicit:
        return explicit
    for candidate in DINGTALK_ENV_FILE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return ""


def _pull_purchase_summaries_from_dingtalk(*, linked_approvals: list[dict], env_file: str | None = None) -> list[dict]:
    from overseas_costing.scripts.import_oa_logistics import (
        get_access_token,
        load_env_file,
        pull_linked_purchase_approval_details,
    )

    resolved_env_file = _resolve_dingtalk_env_file(env_file)
    if resolved_env_file:
        load_env_file(resolved_env_file)
    token = get_access_token()
    return [
        _normalize_purchase_summary(summary)
        for summary in pull_linked_purchase_approval_details(token=token, linked_approvals=linked_approvals)
    ]


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
            "quantity",
            "unit_price",
            "purchase_currency",
            "goods_value",
            "actual_shipped_qty",
            "gross_weight_kg",
            "volume_m3",
            "volume_weight_kg",
            "chargeable_weight_kg",
            "source_type",
            "source_doc_no",
            "dingtalk_instance_id",
            "dingtalk_official_url",
            "parse_status",
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


def _match_item(
    mapped_row: dict,
    indexes: dict[str, dict[str, list[dict]]],
    *,
    trust_unique_material_code: bool = False,
) -> tuple[str, list[dict]]:
    for field in ITEM_KEY_FIELDS:
        key = _normalize_key(mapped_row.get(field))
        if not key:
            continue
        candidates = indexes[field].get(key, [])
        if candidates:
            if field == "material_code" and trust_unique_material_code and len(candidates) == 1:
                return field, candidates
            return field, _narrow_item_candidates(mapped_row, candidates)
    return "", []


def _source_quantity_for_sequence_match(mapped_row: dict) -> float | None:
    for fieldname in ("actual_shipped_qty", "quantity"):
        value = mapped_row.get(fieldname)
        if value not in (None, ""):
            return _to_float(value, default=0.0)
    return None


def _candidate_sort_key(candidate: dict) -> tuple[int, str]:
    try:
        row_no = int(candidate.get("row_no") or 0)
    except (TypeError, ValueError):
        row_no = 0
    return row_no, str(candidate.get("name") or "")


def _assign_sequence_candidate(match: dict, candidate: dict, strategy: str) -> None:
    match["assigned_candidate"] = candidate
    match["disambiguation_strategy"] = strategy


def _resolve_ambiguous_matches_by_sequence(raw_matches: list[dict]) -> None:
    """把来源多行和系统重复物料多行按数量/顺序拆开。

    只在“同一批来源行数量 = 同一组候选行数量”时生效，避免把不确定的单行强行写入。
    """

    groups: dict[tuple[str, tuple[str, ...]], list[dict]] = defaultdict(list)
    for match in raw_matches:
        candidates = match.get("candidates") or []
        if len(candidates) <= 1:
            continue
        candidate_names = tuple(sorted(str(candidate.get("name") or "") for candidate in candidates if candidate.get("name")))
        if len(candidate_names) != len(candidates):
            continue
        groups[(match.get("matched_by") or "", candidate_names)].append(match)

    for group in groups.values():
        first_candidates = group[0].get("candidates") or []
        candidates_by_name = {str(candidate.get("name")): candidate for candidate in first_candidates if candidate.get("name")}
        if len(group) != len(candidates_by_name):
            continue

        available = dict(candidates_by_name)
        for match in sorted(group, key=lambda row: row.get("source_index") or 0):
            source_quantity = _source_quantity_for_sequence_match(match.get("mapped_row") or {})
            if source_quantity is None:
                continue
            exact_candidates = [
                candidate
                for candidate in available.values()
                if _values_equal_for_import(candidate.get("quantity"), source_quantity)
            ]
            if len(exact_candidates) == 1:
                candidate = exact_candidates[0]
                _assign_sequence_candidate(match, candidate, "duplicate_quantity")
                available.pop(str(candidate.get("name")), None)

        remaining_matches = [match for match in group if not match.get("assigned_candidate")]
        remaining_candidates = sorted(available.values(), key=_candidate_sort_key)
        if len(remaining_matches) != len(remaining_candidates):
            continue
        for match, candidate in zip(sorted(remaining_matches, key=lambda row: row.get("source_index") or 0), remaining_candidates):
            _assign_sequence_candidate(match, candidate, "duplicate_row_order")


def _narrow_item_candidates(mapped_row: dict, candidates: list[dict]) -> list[dict]:
    spec_key = _normalize_key(mapped_row.get("spec_model"))
    if spec_key:
        spec_candidates = [candidate for candidate in candidates if _normalize_key(candidate.get("spec_model")) == spec_key]
        if spec_candidates:
            return spec_candidates
        if any(_normalize_key(candidate.get("spec_model")) for candidate in candidates):
            return []

    product_key = _normalize_key(mapped_row.get("product_name"))
    if product_key:
        product_candidates = [
            candidate for candidate in candidates if _normalize_key(candidate.get("product_name")) == product_key
        ]
        if product_candidates:
            return product_candidates
    return candidates


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
        if _values_equal_for_import(old_value, new_value):
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


def _mark_attachment_parsed(attachment_name: str | None, summary: dict) -> bool:
    if frappe is None or not attachment_name:
        return False

    exists = getattr(getattr(frappe, "db", None), "exists", None)
    if callable(exists):
        try:
            if not exists("Overseas Cost Attachment", attachment_name):
                return False
        except Exception:
            return False

    snapshot = {
        "source": "packing_list_writeback",
        "updated_count": summary.get("updated_count", 0),
        "changed_field_count": summary.get("changed_field_count", 0),
        "skipped_count": summary.get("skipped_count", 0),
        "conflict_row_count": summary.get("conflict_row_count", 0),
        "unmatched_count": summary.get("unmatched_count", 0),
        "ambiguous_count": summary.get("ambiguous_count", 0),
    }
    parse_targets = summary.get("parse_targets")
    if parse_targets:
        snapshot["parse_targets"] = parse_targets
    try:
        frappe.db.set_value("Overseas Cost Attachment", attachment_name, "parse_status", "Parsed", update_modified=True)
        frappe.db.set_value(
            "Overseas Cost Attachment",
            attachment_name,
            "mapped_result_json",
            _json_dumps(snapshot),
            update_modified=True,
        )
    except Exception:
        return False
    return True


def _run_item_writeback(
    *,
    batch_name: str,
    version_name: str | None,
    mapped_rows: list[dict],
    update_builder: Callable[[dict, dict], dict],
    action_remark: str,
    trust_unique_material_code: bool = False,
    resolve_ambiguous_by_sequence: bool = False,
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

    raw_matches: list[dict] = []
    for source_index, mapped_row in enumerate(mapped_rows):
        matched_by, candidates = _match_item(
            mapped_row,
            indexes,
            trust_unique_material_code=trust_unique_material_code,
        )
        raw_matches.append(
            {
                "source_index": source_index,
                "mapped_row": mapped_row,
                "matched_by": matched_by,
                "candidates": candidates,
            }
        )

    if resolve_ambiguous_by_sequence:
        _resolve_ambiguous_matches_by_sequence(raw_matches)

    for match in raw_matches:
        mapped_row = match["mapped_row"]
        matched_by = match.get("matched_by") or ""
        candidates = match.get("candidates") or []
        if not candidates:
            unmatched_rows.append(mapped_row)
            continue
        if match.get("assigned_candidate"):
            candidates = [match["assigned_candidate"]]
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


def _compact_purchase_row(mapped_row: dict) -> dict:
    return {
        "material_code": mapped_row.get("material_code"),
        "product_name": mapped_row.get("product_name"),
        "spec_model": mapped_row.get("spec_model"),
        "quantity": mapped_row.get("quantity"),
        "unit": mapped_row.get("unit"),
        "unit_price": mapped_row.get("unit_price"),
        "goods_value": mapped_row.get("goods_value"),
        "purchase_currency": mapped_row.get("purchase_currency"),
        "source_approval_no": mapped_row.get("source_approval_no"),
        "source_instance_id": mapped_row.get("source_instance_id"),
    }


def _compact_packing_row(mapped_row: dict) -> dict:
    return {
        "material_code": mapped_row.get("material_code"),
        "product_name": mapped_row.get("product_name"),
        "spec_model": mapped_row.get("spec_model"),
        "actual_shipped_qty": mapped_row.get("actual_shipped_qty"),
        "gross_weight_kg": mapped_row.get("gross_weight_kg"),
        "volume_m3": mapped_row.get("volume_m3"),
        "volume_weight_kg": mapped_row.get("volume_weight_kg"),
        "chargeable_weight_kg": mapped_row.get("chargeable_weight_kg"),
        "source_doc_no": mapped_row.get("source_doc_no"),
        "source_file_name": mapped_row.get("source_file_name"),
    }


def _build_purchase_updates_for_preview(mapped_row: dict, _target: dict) -> dict:
    return {
        "unit_price": mapped_row.get("unit_price"),
        "purchase_currency": mapped_row.get("purchase_currency"),
        "goods_value": mapped_row.get("goods_value"),
        "source_type": mapped_row.get("source_type"),
        "source_doc_no": mapped_row.get("source_approval_no") or mapped_row.get("source_instance_id") or "",
        "dingtalk_instance_id": mapped_row.get("source_instance_id") or "",
        "dingtalk_official_url": mapped_row.get("source_dingtalk_url") or "",
        "parse_status": "SUCCESS",
    }


def _currency_group_key(value) -> str:
    return _normalize_key(value) or "unknown"


def _unique_join(values: list) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "、".join(seen)


def _sum_purchase_rows(rows: list[dict], fieldname: str) -> float:
    return sum(_to_float((row.get("mapped_row") or {}).get(fieldname), default=0.0) for row in rows)


def _select_purchase_rows_for_target(rows: list[dict]) -> tuple[list[dict], list[dict], str]:
    if len(rows) <= 1:
        return rows, [], "single"

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        mapped_row = row.get("mapped_row") or {}
        groups[_currency_group_key(mapped_row.get("purchase_currency"))].append(row)

    if len(groups) <= 1:
        return rows, [], "same_currency"

    target_quantity = _to_float(rows[0].get("target_quantity"), default=0.0)

    def score(group_rows: list[dict]) -> tuple[float, float]:
        group_quantity = _sum_purchase_rows(group_rows, "quantity")
        group_goods_value = _sum_purchase_rows(group_rows, "goods_value")
        quantity_delta = abs(group_quantity - target_quantity) if target_quantity else 0
        return (quantity_delta, -group_goods_value)

    selected = min(groups.values(), key=score)
    selected_ids = {id(row) for row in selected}
    ignored = [row for row in rows if id(row) not in selected_ids]
    return selected, ignored, "closest_quantity_currency_group"


def _build_aggregated_purchase_updates(rows: list[dict]) -> tuple[dict, dict]:
    selected_rows, ignored_rows, strategy = _select_purchase_rows_for_target(rows)
    if not selected_rows:
        return {}, {"strategy": "empty", "selected_count": 0, "ignored_count": len(ignored_rows)}

    mapped_rows = [row.get("mapped_row") or {} for row in selected_rows]
    total_source_quantity = sum(_to_float(row.get("quantity"), default=0.0) for row in mapped_rows)
    total_source_goods_value = sum(_to_float(row.get("goods_value"), default=0.0) for row in mapped_rows)
    target_quantity = _to_float(selected_rows[0].get("target_quantity"), default=0.0)
    unit_price = total_source_goods_value / total_source_quantity if total_source_goods_value and total_source_quantity else 0
    if not unit_price:
        unit_price = _to_float(mapped_rows[0].get("unit_price"), default=0.0)
    goods_value = unit_price * target_quantity if unit_price and target_quantity else total_source_goods_value
    purchase_currency = mapped_rows[0].get("purchase_currency") or ""

    updates = {
        "unit_price": unit_price,
        "purchase_currency": purchase_currency,
        "goods_value": goods_value,
    }
    meta = {
        "strategy": strategy,
        "selected_count": len(selected_rows),
        "ignored_count": len(ignored_rows),
        "selected_source_approval_no": _unique_join([row.get("source_approval_no") for row in mapped_rows]),
        "ignored_source_approval_no": _unique_join([(row.get("mapped_row") or {}).get("source_approval_no") for row in ignored_rows]),
        "source_quantity": total_source_quantity,
        "target_quantity": target_quantity,
    }
    return updates, meta


def _field_change_status(field_name: str, old_value, new_value, numeric_zero_fillable_fields: set[str] | None = None) -> str:
    if new_value in (None, ""):
        return "empty_source"
    if old_value in (None, ""):
        return "fillable"
    zero_fields = numeric_zero_fillable_fields or {"unit_price", "goods_value"}
    if field_name in zero_fields and _to_float(old_value, default=0) == 0:
        return "fillable"
    if _values_equal_for_import(old_value, new_value):
        return "same"
    return "conflict"


def _build_proposed_changes(
    target: dict,
    field_updates: dict,
    *,
    field_labels: dict[str, str] | None = None,
    business_fields: tuple[str, ...] | set[str] | None = None,
    numeric_zero_fillable_fields: set[str] | None = None,
) -> list[dict]:
    resolved_labels = field_labels or PURCHASE_FIELD_LABELS
    resolved_business_fields = set(business_fields or PURCHASE_WRITEBACK_FIELDS)
    changes: list[dict] = []
    for field_name, new_value in field_updates.items():
        old_value = target.get(field_name)
        status = _field_change_status(
            field_name,
            old_value,
            new_value,
            numeric_zero_fillable_fields=numeric_zero_fillable_fields,
        )
        changes.append(
            {
                "field_name": field_name,
                "field_label": resolved_labels.get(field_name, field_name),
                "old_value": old_value,
                "new_value": new_value,
                "status": status,
                "is_business_field": field_name in resolved_business_fields,
            }
        )
    return changes


def _preview_item_writeback(
    *,
    batch_name: str,
    version_name: str | None,
    mapped_rows: list[dict],
    update_builder: Callable[[dict, dict], dict],
    field_labels: dict[str, str] | None = None,
    business_fields: tuple[str, ...] | set[str] | None = None,
    compact_row: Callable[[dict], dict] | None = None,
    numeric_zero_fillable_fields: set[str] | None = None,
    preview_message_prefix: str = "采购支出 OA",
    fillable_message: str = "可写入匹配行的业务字段。",
    trust_unique_material_code: bool = False,
    resolve_ambiguous_by_sequence: bool = False,
) -> dict:
    compact = compact_row or _compact_purchase_row
    if frappe is None:
        return {
            "dry_run": True,
            "matched_count": 0,
            "fillable_row_count": 0,
            "writable_row_count": 0,
            "conflict_row_count": 0,
            "same_row_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": len(mapped_rows),
            "matched_rows": [],
            "ambiguous_rows": [],
            "unmatched_rows": [compact(row) for row in mapped_rows],
            "message": "当前未连接 Frappe，仅完成来源行解析，无法匹配批次 SKU。",
        }

    batch_doc_name = _resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {
            "matched_count": 0,
            "fillable_row_count": 0,
            "writable_row_count": 0,
            "conflict_row_count": 0,
            "same_row_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": len(mapped_rows),
            "matched_rows": [],
            "ambiguous_rows": [],
            "unmatched_rows": [compact(row) for row in mapped_rows],
            "message": f"未找到批次：{batch_name}",
        }

    resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
    if not resolved_version_name:
        return {
            "batch_doc_name": batch_doc_name,
            "matched_count": 0,
            "fillable_row_count": 0,
            "writable_row_count": 0,
            "conflict_row_count": 0,
            "same_row_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": len(mapped_rows),
            "matched_rows": [],
            "ambiguous_rows": [],
            "unmatched_rows": [compact(row) for row in mapped_rows],
            "message": f"批次 {batch_name} 暂无可用版本，无法匹配。",
        }

    items = _get_batch_items(batch_doc_name, resolved_version_name)
    indexes = _index_items(items)
    matched_rows: list[dict] = []
    ambiguous_rows: list[dict] = []
    unmatched_rows: list[dict] = []

    raw_matches: list[dict] = []
    for source_index, mapped_row in enumerate(mapped_rows):
        matched_by, candidates = _match_item(
            mapped_row,
            indexes,
            trust_unique_material_code=trust_unique_material_code,
        )
        raw_matches.append(
            {
                "source_index": source_index,
                "mapped_row": mapped_row,
                "matched_by": matched_by,
                "candidates": candidates,
            }
        )

    if resolve_ambiguous_by_sequence:
        _resolve_ambiguous_matches_by_sequence(raw_matches)

    for match in raw_matches:
        mapped_row = match["mapped_row"]
        matched_by = match.get("matched_by") or ""
        candidates = match.get("candidates") or []
        if not candidates:
            unmatched_rows.append(compact(mapped_row))
            continue
        if match.get("assigned_candidate"):
            candidates = [match["assigned_candidate"]]
        if len(candidates) > 1:
            ambiguous_rows.append(
                {
                    "matched_by": matched_by,
                    "mapped_row": compact(mapped_row),
                    "candidate_row_nos": [candidate.get("row_no") for candidate in candidates],
                    "candidate_items": [
                        {
                            "name": candidate.get("name"),
                            "row_no": candidate.get("row_no"),
                            "material_code": candidate.get("material_code"),
                            "product_name": candidate.get("product_name"),
                            "spec_model": candidate.get("spec_model"),
                        }
                        for candidate in candidates[:10]
                    ],
                }
            )
            continue

        target = candidates[0]
        proposed_changes = _build_proposed_changes(
            target,
            update_builder(mapped_row, target),
            field_labels=field_labels,
            business_fields=business_fields,
            numeric_zero_fillable_fields=numeric_zero_fillable_fields,
        )
        business_changes = [change for change in proposed_changes if change["is_business_field"]]
        matched_rows.append(
            {
                "matched_by": matched_by,
                "target_item_name": target.get("name"),
                "target_row_no": target.get("row_no"),
                "target_material_code": target.get("material_code"),
                "target_product_name": target.get("product_name"),
                "target_spec_model": target.get("spec_model"),
                "target_quantity": target.get("quantity"),
                "mapped_row": compact(mapped_row),
                "disambiguation_strategy": match.get("disambiguation_strategy") or "",
                "proposed_changes": proposed_changes,
                "business_changes": business_changes,
                "has_fillable": any(change["status"] == "fillable" for change in business_changes),
                "has_conflict": any(change["status"] == "conflict" for change in business_changes),
                "all_business_same": bool(business_changes)
                and all(change["status"] == "same" for change in business_changes),
            }
        )

    fillable_row_count = sum(1 for row in matched_rows if row["has_fillable"])
    conflict_row_count = sum(1 for row in matched_rows if row["has_conflict"])
    same_row_count = sum(1 for row in matched_rows if row["all_business_same"])
    writable_row_count = sum(
        1
        for row in matched_rows
        if any(change["status"] in {"fillable", "conflict"} for change in row.get("business_changes") or [])
    )
    message = f"{preview_message_prefix} 预览已完成，当前未写入任何成本字段。"
    if conflict_row_count:
        message += " 发现系统已有值与来源数据不一致，写入时将按来源字段更新并保留修改记录。"
    elif writable_row_count:
        message += f" {fillable_message}"

    return {
        "batch_doc_name": batch_doc_name,
        "version_name": resolved_version_name,
        "matched_count": len(matched_rows),
        "fillable_row_count": fillable_row_count,
        "writable_row_count": writable_row_count,
        "conflict_row_count": conflict_row_count,
        "same_row_count": same_row_count,
        "ambiguous_count": len(ambiguous_rows),
        "unmatched_count": len(unmatched_rows),
        "matched_rows": matched_rows,
        "ambiguous_rows": ambiguous_rows,
        "unmatched_rows": unmatched_rows,
        "message": message,
    }


def preview_linked_purchase_expense_oa(
    *,
    batch_name: str,
    version_name: str | None = None,
    env_file: str | None = None,
    linked_purchase_json: str | None = None,
    purchase_summaries_json: str | None = None,
) -> dict:
    """预览当前批次关联采购支出 OA 能补哪些采购价格字段，不写入数据。"""

    batch_doc_name = _resolve_batch_name(batch_name) if frappe is not None else None
    batch_trace = _get_batch_trace_row(batch_doc_name) if batch_doc_name else {"batch_no": batch_name}
    linked_approvals = _load_json_list(linked_purchase_json) or _get_linked_purchase_approvals_from_extra(
        batch_trace.get("extra_json")
    )
    purchase_summaries = _load_purchase_summaries_from_json(purchase_summaries_json)

    if not linked_approvals and not purchase_summaries:
        return {
            "ok": True,
            "dry_run": frappe is None,
            "batch_name": batch_name,
            "batch_doc_name": batch_doc_name,
            "batch_no": batch_trace.get("batch_no") or batch_name,
            "linked_purchase_count": 0,
            "purchase_summary_count": 0,
            "mapped_purchase_row_count": 0,
            "writeback_preview": {
                "matched_count": 0,
                "fillable_row_count": 0,
                "writable_row_count": 0,
                "conflict_row_count": 0,
                "same_row_count": 0,
                "ambiguous_count": 0,
                "unmatched_count": 0,
                "matched_rows": [],
                "ambiguous_rows": [],
                "unmatched_rows": [],
                "message": "当前批次没有关联采购支出审批单。",
            },
            "message": "当前批次没有关联采购支出审批单。",
        }

    if not purchase_summaries:
        purchase_summaries = _pull_purchase_summaries_from_dingtalk(
            linked_approvals=linked_approvals,
            env_file=env_file,
        )

    mapped_rows: list[dict] = []
    for summary in purchase_summaries:
        source_approval_no = summary.get("source_approval_no") or ""
        source_instance_id = summary.get("source_instance_id") or ""
        source_dingtalk_url = summary.get("source_dingtalk_url") or ""
        for row in summary.get("mapped_preview_items") or []:
            if not isinstance(row, dict):
                continue
            mapped_rows.append(
                {
                    **row,
                    "source_approval_no": row.get("source_approval_no") or source_approval_no,
                    "source_instance_id": row.get("source_instance_id") or source_instance_id,
                    "source_dingtalk_url": row.get("source_dingtalk_url") or source_dingtalk_url,
                    "source_type": row.get("source_type") or "PURCHASE_EXPENSE_OA",
                }
            )

    preview_version_name = _resolve_version_name(batch_doc_name, version_name) if batch_doc_name else version_name
    fx_context = _get_version_fx_context(preview_version_name)

    def build_purchase_updates(mapped_row: dict, target: dict) -> dict:
        return _convert_purchase_updates_to_rmb(
            _build_purchase_updates_for_preview(mapped_row, target),
            fx_context,
        )

    writeback_preview = _preview_item_writeback(
        batch_name=batch_doc_name or batch_name,
        version_name=version_name,
        mapped_rows=mapped_rows,
        update_builder=build_purchase_updates,
        fillable_message="可写入匹配行的单价Precio、币种Moneda、总金额Monto Total。",
        trust_unique_material_code=True,
    )

    return {
        "ok": True,
        "dry_run": frappe is None,
        "batch_name": batch_name,
        "batch_doc_name": batch_doc_name or writeback_preview.get("batch_doc_name"),
        "batch_no": batch_trace.get("batch_no") or batch_name,
        "version_name": writeback_preview.get("version_name") or version_name,
        "linked_purchase_count": len(linked_approvals),
        "linked_purchase_approvals": linked_approvals,
        "purchase_summary_count": len(purchase_summaries),
        "purchase_summaries": [_build_purchase_summary_preview_row(summary) for summary in purchase_summaries],
        "mapped_purchase_row_count": len(mapped_rows),
        "mapped_preview_items": [_compact_purchase_row(row) for row in mapped_rows[:20]],
        "writeback_targets": [PURCHASE_FIELD_LABELS[field] for field in PURCHASE_WRITEBACK_FIELDS],
        "writeback_preview": writeback_preview,
        "message": writeback_preview.get("message") or "采购支出 OA 回填预览已生成，当前未写入任何字段。",
    }


def apply_linked_purchase_expense_fillable_fields(
    *,
    batch_name: str,
    version_name: str | None = None,
    env_file: str | None = None,
    linked_purchase_json: str | None = None,
    purchase_summaries_json: str | None = None,
) -> dict:
    """写入关联采购支出 OA 中已匹配物料行的采购字段。

    当前口径：
    1. 只处理预览已匹配到唯一物料行的数据。
    2. 按钉钉采购审批字段写入单价、币种、总金额。
    3. 未匹配、多匹配行不写入；已写入字段保留修改记录，后续可人工双击修正。
    """

    preview_result = preview_linked_purchase_expense_oa(
        batch_name=batch_name,
        version_name=version_name,
        env_file=env_file,
        linked_purchase_json=linked_purchase_json,
        purchase_summaries_json=purchase_summaries_json,
    )
    if not preview_result.get("ok"):
        return {
            "ok": False,
            "preview_result": preview_result,
            "message": preview_result.get("message") or "采购支出 OA 预览失败，未写入数据。",
        }
    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "preview_result": preview_result,
            "message": "当前未连接 Frappe，不能保存采购字段。",
        }

    writeback_preview = preview_result.get("writeback_preview") or {}
    batch_doc_name = preview_result.get("batch_doc_name") or writeback_preview.get("batch_doc_name")
    resolved_version_name = preview_result.get("version_name") or writeback_preview.get("version_name") or version_name
    if not batch_doc_name or not resolved_version_name:
        return {
            "ok": False,
            "preview_result": preview_result,
            "message": "当前批次或版本未匹配成功，未写入数据。",
        }

    applied_rows: list[dict] = []
    skipped_rows: list[dict] = []
    changed_field_count = 0
    matched_rows = writeback_preview.get("matched_rows") or []
    fx_context = _get_version_fx_context(resolved_version_name)
    matched_rows_by_target: dict[str, list[dict]] = defaultdict(list)
    for row in matched_rows:
        target_item_name = row.get("target_item_name")
        if target_item_name:
            matched_rows_by_target[target_item_name].append(row)

    processed_duplicate_targets: set[str] = set()
    for row in matched_rows:
        target_item_name = row.get("target_item_name")
        business_changes = row.get("business_changes") or []
        if not target_item_name:
            skipped_rows.append({"row": row, "reason": "缺少目标物料行"})
            continue
        duplicate_group = matched_rows_by_target.get(target_item_name) or []
        if len(duplicate_group) > 1:
            if target_item_name in processed_duplicate_targets:
                continue
            processed_duplicate_targets.add(target_item_name)
            field_updates, aggregate_meta = _build_aggregated_purchase_updates(duplicate_group)
            field_updates = _convert_purchase_updates_to_rmb(field_updates, fx_context)
            if not field_updates:
                skipped_rows.append({"row": row, "reason": "同一物料多条采购明细聚合失败", "aggregate_meta": aggregate_meta})
                continue
            source_no = aggregate_meta.get("selected_source_approval_no") or "关联采购支出 OA"
            changed_fields = _update_item_fields(
                item_name=target_item_name,
                batch_doc_name=batch_doc_name,
                version_name=resolved_version_name,
                row_no=row.get("target_row_no"),
                field_updates=field_updates,
                action_remark=f"采购支出 OA 多行聚合写入；来源审批：{source_no}；策略：{aggregate_meta.get('strategy')}",
            )
            if changed_fields:
                applied_rows.append(
                    {
                        "target_item_name": target_item_name,
                        "target_row_no": row.get("target_row_no"),
                        "source_approval_no": source_no,
                        "changed_fields": changed_fields,
                        "aggregate_meta": aggregate_meta,
                    }
                )
                changed_field_count += len(changed_fields)
            if int(aggregate_meta.get("ignored_count") or 0) > 0:
                skipped_rows.append({"row": row, "reason": "同一物料存在多币种采购来源，已按数量最接近的一组写入，其余组未写入", "aggregate_meta": aggregate_meta})
            continue
        field_updates = {
            change.get("field_name"): change.get("new_value")
            for change in business_changes
            if change.get("field_name") in PURCHASE_WRITEBACK_FIELDS
            and change.get("status") in {"fillable", "conflict", "same"}
        }
        field_updates = {field_name: value for field_name, value in field_updates.items() if field_name}
        if not field_updates:
            skipped_rows.append({"row": row, "reason": "没有可写入字段"})
            continue

        mapped_row = row.get("mapped_row") or {}
        source_no = mapped_row.get("source_approval_no") or mapped_row.get("source_instance_id") or "关联采购支出 OA"
        changed_fields = _update_item_fields(
            item_name=target_item_name,
            batch_doc_name=batch_doc_name,
            version_name=resolved_version_name,
            row_no=row.get("target_row_no"),
            field_updates=field_updates,
            action_remark=f"采购支出 OA 写入匹配字段；来源审批：{source_no}",
        )
        if changed_fields:
            applied_rows.append(
                {
                    "target_item_name": target_item_name,
                    "target_row_no": row.get("target_row_no"),
                    "source_approval_no": mapped_row.get("source_approval_no"),
                    "changed_fields": changed_fields,
                }
            )
            changed_field_count += len(changed_fields)

    if applied_rows:
        _mark_batch_dirty(batch_doc_name)
        commit = getattr(getattr(frappe, "db", None), "commit", None)
        if callable(commit):
            commit()

    updated_count = len(applied_rows)
    return {
        "ok": True,
        "batch_name": batch_name,
        "batch_doc_name": batch_doc_name,
        "version_name": resolved_version_name,
        "updated_count": updated_count,
        "changed_field_count": changed_field_count,
        "skipped_count": len(skipped_rows),
        "conflict_row_count": writeback_preview.get("conflict_row_count", 0),
        "unmatched_count": writeback_preview.get("unmatched_count", 0),
        "ambiguous_count": writeback_preview.get("ambiguous_count", 0),
        "applied_rows": applied_rows,
        "skipped_rows": skipped_rows,
        "preview_result": preview_result,
        "message": (
            f"已同步 {updated_count} 行采购字段，共 {changed_field_count} 个字段；未匹配、多匹配或多币种保留的行未写入。"
            if updated_count
            else "没有可同步的采购字段，未写入数据。"
        ),
    }


def _build_packing_updates_for_preview(mapped_row: dict, _target: dict) -> dict:
    return {
        "actual_shipped_qty": mapped_row.get("actual_shipped_qty"),
        "gross_weight_kg": mapped_row.get("gross_weight_kg"),
        "volume_m3": mapped_row.get("volume_m3"),
        "volume_weight_kg": mapped_row.get("volume_weight_kg"),
        "chargeable_weight_kg": mapped_row.get("chargeable_weight_kg"),
        "hs_code": mapped_row.get("hs_code"),
        "source_type": mapped_row.get("source_type") or "PACKING_LIST",
        "source_file_name": mapped_row.get("source_file_name") or "",
        "source_doc_no": mapped_row.get("source_doc_no") or mapped_row.get("purchase_order_no") or "",
        "parse_status": "SUCCESS",
    }


def _build_packing_preview_items(
    *,
    attachment_name: str | None = None,
    file_url: str | None = None,
    sheet_rows_json: str | None = None,
) -> tuple[list[dict], dict]:
    if sheet_rows_json:
        rows = _build_preview_rows(_load_rows(sheet_rows_json), map_packing_list_row_to_item)
        for row in rows:
            row["source_file_name"] = attachment_name or row.get("source_file_name") or ""
            row["source_doc_no"] = file_url or row.get("source_doc_no") or attachment_name or ""
        return rows, {"parser": "json_rows", "source": "sheet_rows_json"}

    if not file_url:
        return [], {"parser": "empty", "source": "none"}

    path = _resolve_excel_file_path(file_url=file_url)
    parser_meta, blocks = parse_yuewei_excel_workbook(path)
    rows: list[dict] = []
    for block in blocks:
        for index, item_row in enumerate(block.get("items") or [], start=1):
            mapped = map_yuewei_excel_block_item_to_item(block, item_row, row_index=index)
            mapped["source_type"] = "PACKING_LIST"
            mapped["source_file_name"] = attachment_name or path.name
            mapped["source_doc_no"] = mapped.get("source_doc_no") or block.get("sourceDocNo") or block.get("id") or ""
            rows.append(mapped)

    return rows, {
        **(parser_meta or {}),
        "block_count": len(blocks),
        "item_count": len(rows),
        "source": "file_url",
    }


def preview_packing_list_attachment(
    *,
    batch_name: str,
    attachment_name: str | None = None,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
) -> dict:
    """预览装箱单/物流附件可补哪些实际发货、重量、体积字段，不写入数据。"""

    preview_items, parser_meta = _build_packing_preview_items(
        attachment_name=attachment_name,
        file_url=file_url,
        sheet_rows_json=sheet_rows_json,
    )
    parse_task = attachment_parse_service.build_packing_list_parse_task(
        batch_name=batch_name,
        version_name=version_name,
        attachment_name=attachment_name,
        file_url=file_url,
        template_hint=template_hint,
    )
    writeback_preview = _preview_item_writeback(
        batch_name=batch_name,
        version_name=version_name,
        mapped_rows=preview_items,
        update_builder=_build_packing_updates_for_preview,
        field_labels=PACKING_FIELD_LABELS,
        business_fields=PACKING_WRITEBACK_FIELDS,
        compact_row=_compact_packing_row,
        numeric_zero_fillable_fields=set(PACKING_WRITEBACK_FIELDS),
        preview_message_prefix="装箱单/物流附件",
        fillable_message="可用于补齐空的实际发货数量、毛重或体积。",
        resolve_ambiguous_by_sequence=True,
    )

    return {
        "ok": True,
        "dry_run": frappe is None,
        "batch_name": batch_name,
        "batch_doc_name": writeback_preview.get("batch_doc_name"),
        "version_name": writeback_preview.get("version_name") or version_name,
        "attachment_name": attachment_name,
        "file_url": file_url,
        "source_type": "PACKING_LIST",
        "parser_meta": parser_meta,
        "parse_task": parse_task,
        "mapped_preview_count": len(preview_items),
        "mapped_preview_items": [_compact_packing_row(row) for row in preview_items[:20]],
        "writeback_targets": [PACKING_FIELD_LABELS[field] for field in PACKING_WRITEBACK_FIELDS],
        "writeback_preview": writeback_preview,
        "message": writeback_preview.get("message") or "装箱单/物流附件预览已生成，当前未写入任何字段。",
    }


def apply_packing_list_fillable_fields(
    *,
    batch_name: str,
    attachment_name: str | None = None,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
) -> dict:
    """确认补入装箱单/物流附件中可安全写入的实际发货、重量、体积字段。"""

    preview_result = preview_packing_list_attachment(
        batch_name=batch_name,
        attachment_name=attachment_name,
        file_url=file_url,
        version_name=version_name,
        template_hint=template_hint,
        sheet_rows_json=sheet_rows_json,
    )
    if not preview_result.get("ok"):
        return {
            "ok": False,
            "preview_result": preview_result,
            "message": preview_result.get("message") or "装箱单/物流附件预览失败，未写入数据。",
        }
    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "preview_result": preview_result,
            "message": "当前未连接 Frappe，不能保存装箱单字段。",
        }

    writeback_preview = preview_result.get("writeback_preview") or {}
    batch_doc_name = preview_result.get("batch_doc_name") or writeback_preview.get("batch_doc_name")
    resolved_version_name = preview_result.get("version_name") or writeback_preview.get("version_name") or version_name
    if not batch_doc_name or not resolved_version_name:
        return {
            "ok": False,
            "preview_result": preview_result,
            "message": "当前批次或版本未匹配成功，未写入数据。",
        }

    applied_rows: list[dict] = []
    skipped_rows: list[dict] = []
    changed_field_count = 0

    for row in writeback_preview.get("matched_rows") or []:
        target_item_name = row.get("target_item_name")
        business_changes = row.get("business_changes") or []
        if not target_item_name:
            skipped_rows.append({"row": row, "reason": "缺少目标物料行"})
            continue
        if row.get("has_conflict"):
            skipped_rows.append({"row": row, "reason": "存在差异，需人工确认"})
            continue

        field_updates = {
            change.get("field_name"): change.get("new_value")
            for change in business_changes
            if change.get("field_name") in PACKING_WRITEBACK_FIELDS and change.get("status") == "fillable"
        }
        field_updates = {field_name: value for field_name, value in field_updates.items() if field_name}
        if not field_updates:
            skipped_rows.append({"row": row, "reason": "没有可补字段"})
            continue

        mapped_row = row.get("mapped_row") or {}
        source_no = mapped_row.get("source_doc_no") or mapped_row.get("source_file_name") or attachment_name or "装箱单/物流附件"
        changed_fields = _update_item_fields(
            item_name=target_item_name,
            batch_doc_name=batch_doc_name,
            version_name=resolved_version_name,
            row_no=row.get("target_row_no"),
            field_updates=field_updates,
            action_remark=f"装箱单/物流附件确认补入可补字段；来源：{source_no}",
        )
        if changed_fields:
            applied_rows.append(
                {
                    "target_item_name": target_item_name,
                    "target_row_no": row.get("target_row_no"),
                    "source_doc_no": mapped_row.get("source_doc_no"),
                    "changed_fields": changed_fields,
                }
            )
            changed_field_count += len(changed_fields)

    if applied_rows:
        _mark_batch_dirty(batch_doc_name)
        attachment_marked = _mark_attachment_parsed(
            attachment_name,
            {
                "updated_count": len(applied_rows),
                "changed_field_count": changed_field_count,
                "skipped_count": len(skipped_rows),
                "conflict_row_count": writeback_preview.get("conflict_row_count", 0),
                "unmatched_count": writeback_preview.get("unmatched_count", 0),
                "ambiguous_count": writeback_preview.get("ambiguous_count", 0),
                "parse_targets": list(PACKING_WRITEBACK_FIELDS),
            },
        )
        commit = getattr(getattr(frappe, "db", None), "commit", None)
        if callable(commit):
            commit()
    else:
        attachment_marked = False

    updated_count = len(applied_rows)
    return {
        "ok": True,
        "batch_name": batch_name,
        "batch_doc_name": batch_doc_name,
        "version_name": resolved_version_name,
        "updated_count": updated_count,
        "changed_field_count": changed_field_count,
        "skipped_count": len(skipped_rows),
        "conflict_row_count": writeback_preview.get("conflict_row_count", 0),
        "unmatched_count": writeback_preview.get("unmatched_count", 0),
        "ambiguous_count": writeback_preview.get("ambiguous_count", 0),
        "applied_rows": applied_rows,
        "skipped_rows": skipped_rows,
        "attachment_marked_parsed": attachment_marked,
        "preview_result": preview_result,
        "message": (
            f"已补入 {updated_count} 行装箱单字段，共 {changed_field_count} 个字段；冲突、未匹配和多匹配行未写入。"
            if updated_count
            else "没有可安全补入的装箱单字段，未写入数据。"
        ),
    }


def _attachment_ext_from_row(row: dict) -> str:
    parse_result = _json_loads_dict(row.get("parse_result_json"))
    explicit = str(parse_result.get("file_ext") or "").strip().lower().lstrip(".")
    if explicit:
        return explicit
    for fieldname in ("file_url", "file_name"):
        value = str(row.get(fieldname) or "").strip()
        if value:
            suffix = Path(value.split("?", 1)[0]).suffix.lower().lstrip(".")
            if suffix:
                return suffix
    return ""


def _attachment_parse_targets_from_row(row: dict) -> list[str]:
    mapped_result = _json_loads_dict(row.get("mapped_result_json"))
    targets = mapped_result.get("parse_targets") or []
    return [str(target) for target in targets if target]


def _is_excel_packing_attachment(row: dict) -> bool:
    extension = _attachment_ext_from_row(row)
    if extension not in {"xlsx", "xlsm"}:
        return False
    targets = _attachment_parse_targets_from_row(row)
    return row.get("attachment_type") == "Packing List" or "actual_shipped_qty" in targets


def _query_oa_attachment_rows(batch_name: str | None = None, limit: int | None = 200) -> tuple[str, list[dict]]:
    resolved_batch_name = _resolve_batch_name(batch_name) if batch_name else ""
    filters = {"source_type": "OA"}
    if batch_name:
        if not resolved_batch_name:
            return "", []
        filters["batch"] = resolved_batch_name

    rows = frappe.get_all(
        "Overseas Cost Attachment",
        filters=filters,
        fields=[
            "name",
            "batch",
            "version",
            "source_type",
            "attachment_type",
            "source_doc_no",
            "file_name",
            "file_url",
            "parse_status",
            "parse_result_json",
            "mapped_result_json",
        ],
        order_by="creation asc",
        limit_page_length=max(1, min(int(limit or 200), 1000)),
    )
    return resolved_batch_name, rows


def _compact_download_result(result: dict) -> dict:
    return {
        "ok": result.get("ok"),
        "downloaded": result.get("downloaded"),
        "file_url": result.get("file_url") or "",
        "message": result.get("message") or "",
    }


def _compact_packing_apply_result(result: dict) -> dict:
    return {
        "ok": result.get("ok"),
        "updated_count": result.get("updated_count", 0),
        "changed_field_count": result.get("changed_field_count", 0),
        "skipped_count": result.get("skipped_count", 0),
        "conflict_row_count": result.get("conflict_row_count", 0),
        "unmatched_count": result.get("unmatched_count", 0),
        "ambiguous_count": result.get("ambiguous_count", 0),
        "attachment_marked_parsed": result.get("attachment_marked_parsed", False),
        "message": result.get("message") or "",
    }


def _extract_dingtalk_permission_scopes(message: str | None) -> list[str]:
    text = str(message or "")
    scopes: list[str] = []
    for match in re.finditer(r"Workflow\.[A-Za-z.]+", text):
        scope = match.group(0)
        if scope not in scopes:
            scopes.append(scope)
    return scopes


def _is_dingtalk_permission_error(message: str | None) -> bool:
    text = str(message or "")
    return (
        "AccessTokenPermissionDenied" in text
        or "requiredScopes" in text
        or "未开通所需的权限" in text
    )


def _build_oa_packing_parse_message(
    *,
    scanned_count: int,
    downloaded_count: int,
    parsed_count: int,
    updated_count: int,
    changed_field_count: int,
    skipped_count: int,
    failed_count: int,
    permission_blocked_count: int,
    permission_scopes: list[str],
) -> str:
    base = (
        f"已扫描 {scanned_count} 个 OA 发起附件，下载 {downloaded_count} 个 Excel 装箱单，"
        f"解析 {parsed_count} 个，写入 {updated_count} 行、{changed_field_count} 个字段；"
        f"跳过 {skipped_count} 个，失败 {failed_count} 个。"
    )
    if permission_blocked_count:
        scope_text = "、".join(permission_scopes) or "钉钉审批附件下载"
        return f"{base} 其中 {permission_blocked_count} 个 Excel 装箱单因钉钉应用缺少 {scope_text} 权限，暂时无法下载解析。"
    return base


def _recalculate_batches_after_attachment_parse(batch_versions: dict[str, str]) -> list[dict]:
    if not batch_versions:
        return []

    results: list[dict] = []
    try:
        from overseas_costing.services.calculate_service import recalculate_batch
    except Exception as exc:
        return [{"ok": False, "message": f"成本重算服务不可用：{exc}"}]

    for batch_doc_name, version_name in batch_versions.items():
        try:
            result = recalculate_batch(batch_name=batch_doc_name, version_name=version_name or None)
            results.append(
                {
                    "ok": result.get("ok", True) if isinstance(result, dict) else True,
                    "batch_name": batch_doc_name,
                    "version_name": version_name,
                    "message": result.get("message") if isinstance(result, dict) else "",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "batch_name": batch_doc_name,
                    "version_name": version_name,
                    "message": str(exc),
                }
            )
    return results


def parse_oa_packing_list_attachments(
    *,
    batch_name: str | None = None,
    limit: int | None = 200,
    env_file: str | None = None,
    access_token: str | None = None,
    skip_parsed: bool = True,
    recalculate: bool = True,
) -> dict:
    """批量下载并解析钉钉发起附件里的 Excel 装箱单，写入可补字段。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，不能批量解析钉钉附件。",
        }

    resolved_batch_name, rows = _query_oa_attachment_rows(batch_name=batch_name, limit=limit)
    if batch_name and not resolved_batch_name:
        return {
            "ok": False,
            "batch_name": batch_name,
            "message": f"未找到批次：{batch_name}",
            "items": [],
        }

    processed_items: list[dict] = []
    parsed_batch_versions: dict[str, str] = {}
    downloaded_count = 0
    parsed_count = 0
    updated_count = 0
    changed_field_count = 0
    skipped_count = 0
    failed_count = 0
    permission_blocked_count = 0
    permission_scopes: list[str] = []
    permission_blocked = False

    for row in rows:
        item = {
            "attachment_name": row.get("name"),
            "batch_name": row.get("batch"),
            "version_name": row.get("version"),
            "file_name": row.get("file_name") or "",
            "attachment_type": row.get("attachment_type") or "Other",
            "parse_status": row.get("parse_status") or "",
            "file_ext": _attachment_ext_from_row(row),
        }
        if skip_parsed and str(row.get("parse_status") or "").strip().lower() == "parsed":
            item["action"] = "skipped"
            item["reason"] = "附件已解析"
            skipped_count += 1
            processed_items.append(item)
            continue

        if not _is_excel_packing_attachment(row):
            item["action"] = "skipped"
            item["reason"] = "当前批处理只解析 Excel 装箱单；PDF、PO、合同和其他资料等待对应解析器。"
            skipped_count += 1
            processed_items.append(item)
            continue

        file_url = str(row.get("file_url") or "").strip()
        if not file_url and permission_blocked:
            item["action"] = "blocked"
            item["error_type"] = "dingtalk_permission"
            item["permission_scopes"] = permission_scopes
            item["reason"] = (
                f"本次批处理已确认钉钉应用缺少 {'、'.join(permission_scopes) or '审批附件下载'} 权限，"
                "该 Excel 装箱单暂不重复请求下载。"
            )
            permission_blocked_count += 1
            skipped_count += 1
            processed_items.append(item)
            continue

        if not file_url:
            download_result = download_oa_form_attachment(
                row.get("name"),
                env_file=env_file,
                access_token=access_token,
            )
            item["download"] = _compact_download_result(download_result)
            if not download_result.get("ok"):
                item["action"] = "failed"
                item["reason"] = download_result.get("message") or "附件下载失败"
                if _is_dingtalk_permission_error(item["reason"]):
                    item["error_type"] = "dingtalk_permission"
                    scopes = _extract_dingtalk_permission_scopes(item["reason"])
                    item["permission_scopes"] = scopes
                    permission_blocked = True
                    permission_blocked_count += 1
                    for scope in scopes:
                        if scope not in permission_scopes:
                            permission_scopes.append(scope)
                failed_count += 1
                processed_items.append(item)
                continue
            if download_result.get("downloaded"):
                downloaded_count += 1
            file_url = download_result.get("file_url") or file_url

        if not file_url:
            item["action"] = "failed"
            item["reason"] = "附件没有系统文件地址，无法解析。"
            failed_count += 1
            processed_items.append(item)
            continue

        try:
            parse_result = apply_packing_list_fillable_fields(
                batch_name=row.get("batch"),
                version_name=row.get("version"),
                attachment_name=row.get("name"),
                file_url=file_url,
            )
        except Exception as exc:
            item["action"] = "failed"
            item["reason"] = f"装箱单解析失败：{exc}"
            failed_count += 1
            processed_items.append(item)
            continue

        item["parse"] = _compact_packing_apply_result(parse_result)
        if not parse_result.get("ok"):
            item["action"] = "failed"
            item["reason"] = parse_result.get("message") or "装箱单解析失败"
            failed_count += 1
            processed_items.append(item)
            continue

        item["action"] = "parsed"
        parsed_count += 1
        row_updated_count = int(parse_result.get("updated_count") or 0)
        row_changed_field_count = int(parse_result.get("changed_field_count") or 0)
        updated_count += row_updated_count
        changed_field_count += row_changed_field_count
        if row_updated_count:
            parsed_batch_versions[parse_result.get("batch_doc_name") or row.get("batch")] = (
                parse_result.get("version_name") or row.get("version") or ""
            )
        processed_items.append(item)

    recalculate_results = _recalculate_batches_after_attachment_parse(parsed_batch_versions) if recalculate else []

    return {
        "ok": failed_count == 0,
        "batch_name": batch_name or "",
        "resolved_batch_name": resolved_batch_name,
        "scanned_count": len(rows),
        "downloaded_count": downloaded_count,
        "parsed_count": parsed_count,
        "updated_count": updated_count,
        "changed_field_count": changed_field_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "permission_blocked_count": permission_blocked_count,
        "permission_scopes": permission_scopes,
        "recalculate_results": recalculate_results,
        "items": processed_items,
        "message": _build_oa_packing_parse_message(
            scanned_count=len(rows),
            downloaded_count=downloaded_count,
            parsed_count=parsed_count,
            updated_count=updated_count,
            changed_field_count=changed_field_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            permission_blocked_count=permission_blocked_count,
            permission_scopes=permission_scopes,
        ),
    }


def preview_linked_purchase_expense_oa_from_env() -> dict:
    """从环境变量预览关联采购支出 OA，适合 bench execute 调试。"""

    batch_name = str(os.environ.get("OVERSEAS_COST_BATCH") or os.environ.get("OVERSEAS_COST_BATCH_NAME") or "").strip()
    if not batch_name:
        raise ValueError("请设置 OVERSEAS_COST_BATCH。")
    return preview_linked_purchase_expense_oa(
        batch_name=batch_name,
        version_name=str(os.environ.get("OVERSEAS_COST_VERSION") or "").strip() or None,
        env_file=str(os.environ.get("DINGTALK_ENV_FILE") or "").strip() or None,
    )


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
        trust_unique_material_code=True,
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
        resolve_ambiguous_by_sequence=True,
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
