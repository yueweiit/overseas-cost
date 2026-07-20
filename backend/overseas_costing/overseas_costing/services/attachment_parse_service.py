"""
中文用途：附件解析服务。

后续这里会接：
1. 凭证文件上传后的解析任务
2. OCR 识别
3. AI 字段抽取
4. 识别结果回填
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import frappe
except Exception:  # pragma: no cover - 本地测试环境不一定有 Frappe
    frappe = None


PACKING_LIST_TEMPLATE_STRATEGIES = {
    "mixed_workbook_router": "多 sheet 混合工作簿，先识别 sheet 类型再分别路由解析。",
    "sea_container_sheet": "海运装柜 / 装箱单模板，重点取物料编码、数量、毛重、体积。",
    "carton_packing_list": "彩盒 / 纸箱装箱单模板，重点取箱数、NW/GW、尺寸。",
    "express_item_list": "快递清单模板，重点取 SKU、数量、收件人、总重。",
}

TAX_CERTIFICATE_PARSE_TARGETS = [
    "pedimento_no",
    "pedimento_ref",
    "payment_date",
    "exchange_rate",
    "gross_weight_kg",
    "container_no",
    "paid_total_mxn",
    "tax_totals",
    "line_items",
]


def enqueue_parse_task(attachment_name: str) -> dict:
    return {
        "ok": True,
        "attachment_name": attachment_name,
        "queued": True,
        "message": "附件解析任务骨架已创建。",
    }


def build_packing_list_parse_task(
    *,
    batch_name: str,
    version_name: str | None = None,
    attachment_name: str | None = None,
    file_url: str | None = None,
    template_hint: str | None = None,
) -> dict:
    """构造装箱单解析任务的第一版描述。"""

    strategy = template_hint or "mixed_workbook_router"
    return {
        "batch_name": batch_name,
        "version_name": version_name,
        "attachment_name": attachment_name,
        "file_url": file_url,
        "template_hint": strategy,
        "parse_targets": [
            "actual_shipped_qty",
            "gross_weight_kg",
            "volume_m3",
            "volume_weight_kg",
            "chargeable_weight_kg",
        ],
        "parser_strategy": strategy,
        "parser_strategy_desc": PACKING_LIST_TEMPLATE_STRATEGIES.get(strategy, "待补充的模板策略。"),
        "needs_manual_review": True,
        "message": "一期先按多模板路由方式解析装箱单，识别后仍允许人工修正并留痕。",
    }


def preview_tax_certificate_pdf(
    *,
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
    batch_name: str | None = None,
) -> dict:
    """预览解析进口完税凭证 PDF，不写入成本明细。"""

    extracted_text = text if text is not None else extract_pdf_text(file_path=file_path, file_url=file_url)
    parsed = parse_tax_certificate_text(extracted_text, source_name=source_name or file_path or file_url or "")
    parsed["reconciliation"] = build_tax_certificate_reconciliation_preview(parsed, batch_name=batch_name)
    parsed["ok"] = True
    parsed["file_name"] = source_name or _file_name_from_ref(file_path or file_url or "")
    parsed["file_path"] = file_path or ""
    parsed["file_url"] = file_url or ""
    parsed["message"] = "完税凭证解析预览已生成，当前不会写入成本表。"
    return parsed


def save_tax_certificate_parse_result(
    *,
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
    batch_name: str | None = None,
) -> dict:
    """保存完税凭证解析快照到附件记录，不写入成本字段。"""

    parsed = preview_tax_certificate_pdf(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        text=text,
        batch_name=batch_name,
    )
    reconciliation = parsed.get("reconciliation") or {}
    matched_batch = reconciliation.get("batch") or {}
    if not _has_frappe_db_context():
        return {
            "ok": True,
            "dry_run": True,
            "saved": False,
            "preview": parsed,
            "message": "当前未连接 Frappe，仅返回保存预览，不写入附件记录。",
        }
    if not matched_batch.get("name"):
        return {
            "ok": False,
            "saved": False,
            "preview": parsed,
            "message": "未匹配到系统批次，暂不保存解析结果。请先确认报关单号或柜号。",
        }

    values = _build_tax_certificate_attachment_values(
        parsed=parsed,
        batch=matched_batch,
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
    )
    existing_name = _find_existing_tax_certificate_attachment(values)
    if existing_name:
        doc = frappe.get_doc("Overseas Cost Attachment", existing_name)
        for fieldname, value in values.items():
            setattr(doc, fieldname, value)
        doc.save(ignore_permissions=True)
        action = "updated"
    else:
        doc = frappe.get_doc({"doctype": "Overseas Cost Attachment", **values}).insert(ignore_permissions=True)
        action = "created"

    frappe.db.commit()
    parsed["saved_attachment_name"] = doc.name
    return {
        "ok": True,
        "saved": True,
        "action": action,
        "attachment_name": doc.name,
        "batch_name": matched_batch.get("name") or "",
        "source_doc_no": values.get("source_doc_no") or "",
        "preview": parsed,
        "message": "完税凭证解析结果已保存到附件记录，未写入成本字段。",
    }


def list_tax_certificate_parse_records(batch_name: str | None = None, limit: int | None = 20) -> dict:
    """返回已保存完税凭证解析记录摘要，方便前端展示。"""

    if not _has_frappe_db_context():
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name or "",
            "items": [],
            "total": 0,
            "message": "当前未连接 Frappe，返回空解析记录。",
        }

    resolved_batch = _find_tax_certificate_batch({}, batch_name=batch_name) if batch_name else None
    requested_limit = max(1, min(int(limit or 20), 100))
    records = _query_tax_certificate_attachment_records(
        batch_name=resolved_batch.get("name") if resolved_batch else None,
        limit=requested_limit,
    )
    fallback_recent = False
    if batch_name and resolved_batch and not records:
        records = _query_tax_certificate_attachment_records(limit=requested_limit)
        fallback_recent = True

    items = [_build_tax_certificate_record_summary(row) for row in records]
    return {
        "ok": True,
        "batch_name": batch_name or "",
        "resolved_batch": _public_batch_snapshot(resolved_batch),
        "fallback_recent": fallback_recent,
        "items": items,
        "total": len(items),
        "message": "完税凭证解析记录已返回。",
    }


def get_tax_certificate_parse_record(record_name: str | None = None) -> dict:
    """返回单条完税凭证解析快照详情，不暴露原始 DocType 表单给业务页面。"""

    if not record_name:
        return {
            "ok": False,
            "message": "请传入要查看的解析记录。",
        }

    if not _has_frappe_db_context():
        return {
            "ok": False,
            "dry_run": True,
            "record_name": record_name,
            "message": "当前未连接 Frappe，无法读取已保存的解析记录。",
        }

    if not frappe.db.exists("Overseas Cost Attachment", record_name):
        return {
            "ok": False,
            "record_name": record_name,
            "message": "未找到对应的完税凭证解析记录。",
        }

    fields = [
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
        "modified",
        "creation",
    ]
    row = frappe.db.get_value("Overseas Cost Attachment", record_name, fields, as_dict=True) or {}
    row["name"] = row.get("name") or record_name
    if row.get("source_type") != "Voucher" or row.get("attachment_type") != "Tax Certificate":
        return {
            "ok": False,
            "record_name": record_name,
            "message": "该附件记录不是完税凭证解析记录。",
        }

    parse_result = _json_loads(row.get("parse_result_json"))
    mapped_result = _json_loads(row.get("mapped_result_json"))
    return {
        "ok": True,
        "record_name": record_name,
        "record_summary": _build_tax_certificate_record_summary(row),
        "parse_result": parse_result,
        "mapped_result": mapped_result,
        "message": "完税凭证解析记录详情已返回。",
    }


def extract_pdf_text(*, file_path: str | None = None, file_url: str | None = None) -> str:
    """从 PDF 中抽取文本；运行环境没有 PDF 库时给出明确提示。"""

    path = _resolve_pdf_file_path(file_path=file_path, file_url=file_url)
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - 取决于部署环境依赖
        raise RuntimeError("当前环境缺少 pypdf，无法解析 PDF。请先在 bench 环境安装 pypdf。") from exc

    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"\n--- Page {index} ---\n{text}")
    return "\n".join(pages).strip()


def parse_tax_certificate_text(text: str, source_name: str | None = None) -> dict:
    """从墨西哥 Pedimento / 完税凭证文本中抽取第一版核算字段。"""

    normalized = _normalize_text(text)
    line_items = _parse_pedimento_items(normalized)
    tax_totals = _parse_tax_totals(normalized)
    paid_total = _first_number(
        _search(r"IMPORTE PAGADO:[\s\S]{0,260}?\$\s*([\d,]+(?:\.\d+)?)", normalized),
        _search(r"\bTOTAL\s*\n\s*([\d,]+(?:\.\d+)?)", normalized),
    )
    tax_total_sum = round(sum(value for value in tax_totals.values() if isinstance(value, (int, float))), 2)

    dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", normalized)
    payment_date = _search(r"FECHA DE PAGO:[\s\S]{0,80}?(\d{2}/\d{2}/\d{4})", normalized) or (dates[0] if dates else "")
    entry_date = dates[0] if dates else ""
    exchange_match = re.search(r"\n\s*\d+\s+(\d+\.\d{4,6})\s+([\d,]+\.\d{3})\s+\d+\s*\n", normalized)
    document_match = re.search(r"\n(COVE[0-9A-Z]+)\s*\n([A-Z0-9\-]+)\s*\n(\d{2}/\d{2}/\d{4})\s+([A-Z]{3})\s+([A-Z]{3})\s+([\d,]+\.\d+)", normalized)
    header = {
        "pedimento_no": _search(r"(\d{2}\s+\d{2}\s+\d{4}\s+\d{7})", normalized),
        "pedimento_short_no": _search(r"Ped\.\s*(\d+)", normalized),
        "pedimento_ref": _search(r"PEDIMENTO REF:\s*([A-Z0-9]+)", normalized),
        "customs_section": _search(r"PEDIMENTO:\s*ADUANA:[\s\S]{0,60}?(\d{4})\s+(\d{3})", normalized),
        "importer_rfc": _search(r"\b([A-Z&Ñ]{3}\d{6}[A-Z0-9]{3})\b", normalized),
        "importer_name": _search(r"\b(YUEWEI SA DE CV)\b", normalized),
        "entry_date": entry_date,
        "payment_date": payment_date,
        "exchange_rate": _to_number(exchange_match.group(1)) if exchange_match else None,
        "gross_weight_kg": _to_number(exchange_match.group(2)) if exchange_match else None,
        "paid_total_mxn": paid_total,
        "line_capture": _search(r"L[ÍI]NEA DE CAPTURA:[\s\S]{0,180}?([0-9]{4}\s+[0-9A-Z]{4}\s+[0-9A-Z]{4}\s+[0-9A-Z]{4}\s+[0-9A-Z]{4})", normalized),
        "bank_operation_no": _search(r"\b(\d{14})\b", normalized),
        "sat_transaction_no": _search(r"\b(\d{20,})\b", normalized),
        "cove_no": document_match.group(1) if document_match else "",
        "invoice_no": document_match.group(2) if document_match else "",
        "invoice_date": document_match.group(3) if document_match else "",
        "incoterm": document_match.group(4) if document_match else "",
        "invoice_currency": document_match.group(5) if document_match else "",
        "invoice_value": _to_number(document_match.group(6)) if document_match else None,
        "guide_no": _search(r"NO\.\s*\(GUIA/ORDEN EMBARQUE\)/ID:\s*([A-Z0-9]+)", normalized),
        "container_no": _first_match(r"\b[A-Z]{4}\d{7}\b", normalized),
    }
    summary = {
        "item_count": len(line_items),
        "declared_item_count": _parse_declared_item_count(normalized),
        "tax_total_sum_mxn": tax_total_sum,
        "paid_total_mxn": paid_total,
        "tax_total_matches_paid_total": bool(paid_total is not None and abs(tax_total_sum - paid_total) < 0.01),
        "needs_manual_review": not line_items or paid_total is None,
    }
    validation = _build_tax_certificate_validation(
        header=header,
        summary=summary,
        tax_totals=tax_totals,
        line_items=line_items,
    )
    summary["validation_status"] = validation["status"]
    summary["validation_status_label"] = validation["status_label"]
    summary["needs_manual_review"] = validation["status"] != "passed"

    return {
        "source_name": source_name or "",
        "parser": "mexico_tax_certificate_pedimento",
        "parse_targets": TAX_CERTIFICATE_PARSE_TARGETS,
        "summary": summary,
        "header": header,
        "tax_totals": tax_totals,
        "line_items": line_items,
        "validation": validation,
        "raw_text_sample": normalized[:1200],
    }


def _build_tax_certificate_validation(*, header: dict, summary: dict, tax_totals: dict, line_items: list[dict]) -> dict:
    checks: list[dict] = []

    def add_check(code: str, label: str, status: str, message: str, expected=None, actual=None) -> None:
        labels = {"passed": "通过", "review": "需复核", "failed": "失败"}
        checks.append(
            {
                "code": code,
                "label": label,
                "status": status,
                "status_label": labels.get(status, status),
                "message": message,
                "expected": expected,
                "actual": actual,
            }
        )

    required_fields = [
        ("pedimento_no", "报关单号"),
        ("container_no", "柜号"),
        ("payment_date", "支付日期"),
        ("exchange_rate", "汇率"),
        ("paid_total_mxn", "支付总额"),
    ]
    missing = [label for fieldname, label in required_fields if header.get(fieldname) in (None, "")]
    add_check(
        "required_header_fields",
        "凭证基础字段",
        "passed" if not missing else "failed",
        "基础字段完整" if not missing else f"缺少：{'、'.join(missing)}",
        expected="报关单号、柜号、支付日期、汇率、支付总额",
        actual="完整" if not missing else "、".join(missing),
    )

    paid_total = summary.get("paid_total_mxn")
    tax_total = summary.get("tax_total_sum_mxn")
    if paid_total is None:
        add_check("tax_total_matches_paid", "税费合计", "failed", "未识别到支付总额，无法校验税费合计", actual=tax_total)
    elif abs(float(tax_total or 0) - float(paid_total)) < 0.01:
        add_check("tax_total_matches_paid", "税费合计", "passed", "DTA/PRV/IVA/IGI 合计与支付总额一致", expected=paid_total, actual=tax_total)
    else:
        add_check("tax_total_matches_paid", "税费合计", "failed", "DTA/PRV/IVA/IGI 合计与支付总额不一致", expected=paid_total, actual=tax_total)

    declared_count = summary.get("declared_item_count")
    item_count = len(line_items)
    if declared_count is None:
        add_check("line_item_count", "商品分项数量", "review", "未识别到凭证声明的总分项数，需人工确认", actual=item_count)
    elif int(declared_count) == item_count:
        add_check("line_item_count", "商品分项数量", "passed", "识别分项数与凭证声明一致", expected=declared_count, actual=item_count)
    else:
        add_check("line_item_count", "商品分项数量", "failed", "识别分项数与凭证声明不一致", expected=declared_count, actual=item_count)

    invalid_hs_count = sum(1 for item in line_items if not re.fullmatch(r"\d{8}", str(item.get("hs_code") or "")))
    missing_name_count = sum(1 for item in line_items if not item.get("import_name"))
    if not line_items:
        add_check("line_item_fields", "商品分项字段", "failed", "未识别到商品分项")
    elif invalid_hs_count or missing_name_count:
        add_check(
            "line_item_fields",
            "商品分项字段",
            "failed",
            f"HS 编码异常 {invalid_hs_count} 条，海关进口名称缺失 {missing_name_count} 条",
            expected="每条分项有 8 位 HS 编码和海关进口名称",
            actual=f"{item_count} 条",
        )
    else:
        add_check("line_item_fields", "商品分项字段", "passed", "每条分项均识别到 HS 编码和海关进口名称", actual=f"{item_count} 条")

    missing_tax_count = sum(1 for item in line_items if not item.get("taxes"))
    add_check(
        "line_item_tax_fields",
        "分项税率税额",
        "passed" if line_items and not missing_tax_count else "review",
        "每条分项均识别到税率/税额" if line_items and not missing_tax_count else f"有 {missing_tax_count} 条分项缺少税率/税额，需人工复核",
        actual=f"{missing_tax_count} 条缺失",
    )

    status = "passed"
    if any(check["status"] == "failed" for check in checks):
        status = "failed"
    elif any(check["status"] == "review" for check in checks):
        status = "review"

    status_label = {"passed": "通过", "review": "需复核", "failed": "失败"}[status]
    return {
        "status": status,
        "status_label": status_label,
        "checks": checks,
        "failed_count": sum(1 for check in checks if check["status"] == "failed"),
        "review_count": sum(1 for check in checks if check["status"] == "review"),
        "passed_count": sum(1 for check in checks if check["status"] == "passed"),
    }


def build_tax_certificate_reconciliation_preview(parsed: dict, batch_name: str | None = None) -> dict:
    """生成完税凭证与系统批次的对比预览，不写库。"""

    if not _has_frappe_db_context():
        return _build_tax_certificate_reconciliation(
            parsed=parsed,
            batch=None,
            items=[],
            requested_batch_name=batch_name,
            dry_run=True,
        )

    batch = _find_tax_certificate_batch(parsed.get("header") or {}, batch_name=batch_name)
    if not batch:
        return _build_tax_certificate_reconciliation(
            parsed=parsed,
            batch=None,
            items=[],
            requested_batch_name=batch_name,
        )

    filters = {"batch": batch["name"]}
    if batch.get("current_version"):
        filters["version"] = batch["current_version"]

    items = frappe.get_all(
        "Overseas Cost Item",
        filters=filters,
        fields=[
            "name",
            "row_no",
            "material_code",
            "product_name",
            "import_name",
            "hs_code",
            "quantity",
            "goods_value",
            "cc_anti_dumping",
            "igi_amount",
            "iva_amount",
            "dta",
            "prv_duty",
            "prv_iva",
            "import_tax_total",
            "mexico_customs_mxn",
            "mexico_customs_rmb",
        ],
        order_by="row_no asc",
        limit_page_length=10000,
    )
    return _build_tax_certificate_reconciliation(
        parsed=parsed,
        batch=batch,
        items=items,
        requested_batch_name=batch_name,
    )


def _build_tax_certificate_reconciliation(
    *,
    parsed: dict,
    batch: dict | None,
    items: list[dict],
    requested_batch_name: str | None = None,
    dry_run: bool = False,
) -> dict:
    header = parsed.get("header") or {}
    summary = parsed.get("summary") or {}
    validation = parsed.get("validation") or {}
    voucher_total = _first_number(summary.get("paid_total_mxn"), summary.get("tax_total_sum_mxn"))
    system_summary = _summarize_system_tax_items(items)
    system_total = system_summary["system_import_tax_total_mxn"]
    diff = None if voucher_total is None or system_total is None else _round_money(float(voucher_total) - float(system_total), 6)
    checks: list[dict] = []

    def add_check(code: str, label: str, status: str, message: str, expected=None, actual=None) -> None:
        labels = {"passed": "通过", "review": "需复核", "failed": "失败"}
        checks.append(
            {
                "code": code,
                "label": label,
                "status": status,
                "status_label": labels.get(status, status),
                "message": message,
                "expected": expected,
                "actual": actual,
            }
        )

    if dry_run:
        add_check("frappe_connection", "系统批次连接", "review", "当前未连接 Frappe，只能查看凭证解析结果")
    elif batch:
        expected_match = _batch_match_target(batch)
        actual_match = _voucher_match_target(header)
        match_ok = _batch_matches_certificate(batch, header)
        add_check(
            "batch_match",
            "批次匹配",
            "passed" if match_ok else "review",
            "凭证柜号/报关单号已匹配系统批次" if match_ok else "当前批次与凭证柜号/报关单号不完全一致，请确认是否选错批次",
            expected=expected_match,
            actual=actual_match,
        )
    else:
        add_check(
            "batch_match",
            "批次匹配",
            "failed",
            "未根据当前批次、柜号或报关单号匹配到系统批次",
            expected=requested_batch_name or "系统中存在对应批次",
            actual=_voucher_match_target(header),
        )

    validation_status = validation.get("status")
    add_check(
        "voucher_validation",
        "凭证解析校验",
        "passed" if validation_status == "passed" else "failed" if validation_status == "failed" else "review",
        f"完税凭证解析校验{validation.get('status_label') or '未完成'}",
        expected="通过",
        actual=validation.get("status_label") or "--",
    )

    if not batch:
        add_check("system_tax_total", "系统税费金额", "review", "未匹配批次，无法读取系统税费金额")
    elif not items:
        add_check("system_tax_total", "系统税费金额", "review", "当前批次没有可对比的物料明细")
    elif system_total is None:
        add_check("system_tax_total", "系统税费金额", "review", "系统当前物料税费为空，后续需由凭证或人工补齐", expected=voucher_total, actual="空")
    elif voucher_total is None:
        add_check("system_tax_total", "系统税费金额", "failed", "凭证支付总额为空，无法比较系统税费", actual=system_total)
    elif abs(diff or 0) < 0.01:
        add_check("system_tax_total", "系统税费金额", "passed", "凭证税费与系统当前税费一致", expected=voucher_total, actual=system_total)
    else:
        add_check("system_tax_total", "系统税费金额", "review", "凭证税费与系统当前税费存在差额，后续用于多退少补复核", expected=voucher_total, actual=system_total)

    declared_count = summary.get("declared_item_count")
    item_count = len(items)
    if not batch:
        add_check("system_item_count", "系统物料行数", "review", "未匹配批次，无法比较系统物料行数")
    elif declared_count is None:
        add_check("system_item_count", "系统物料行数", "review", "凭证未识别声明分项数，无法比较行数", actual=item_count)
    elif item_count == int(declared_count):
        add_check("system_item_count", "系统物料行数", "passed", "系统物料行数与凭证分项数一致", expected=declared_count, actual=item_count)
    else:
        add_check("system_item_count", "系统物料行数", "review", "系统 SKU 行数与凭证分项数不一致，可能是合并/拆分口径差异", expected=declared_count, actual=item_count)

    status = "matched"
    if any(check["status"] == "failed" for check in checks):
        status = "unmatched" if not batch else "failed"
    elif system_total is None:
        status = "pending"
    elif any(check["status"] == "review" for check in checks):
        status = "review"

    status_labels = {
        "matched": "可对比",
        "review": "需复核",
        "pending": "待补系统税费",
        "unmatched": "未匹配批次",
        "failed": "不可用",
    }
    return {
        "status": status,
        "status_label": status_labels.get(status, status),
        "requested_batch_name": requested_batch_name or "",
        "batch": _public_batch_snapshot(batch),
        "voucher": {
            "customs_no": header.get("pedimento_no") or "",
            "container_no": header.get("container_no") or "",
            "pedimento_ref": header.get("pedimento_ref") or header.get("pedimento_short_no") or "",
            "payment_date": header.get("payment_date") or "",
            "paid_total_mxn": voucher_total,
            "item_count": summary.get("item_count") or 0,
            "declared_item_count": declared_count,
        },
        "system": system_summary,
        "difference": {
            "tax_total_diff_mxn": diff,
            "abs_tax_total_diff_mxn": None if diff is None else _round_money(abs(diff), 6),
            "direction_label": _tax_difference_direction(diff),
        },
        "checks": checks,
        "failed_count": sum(1 for check in checks if check["status"] == "failed"),
        "review_count": sum(1 for check in checks if check["status"] == "review"),
        "passed_count": sum(1 for check in checks if check["status"] == "passed"),
        "message": "对比结果仅用于复核，不会自动写入成本或生成补差。",
    }


def _summarize_system_tax_items(items: list[dict]) -> dict:
    total = 0.0
    has_tax_value = False
    rows_with_tax = 0
    rows_missing_tax = 0
    source_counts = {"import_tax_total": 0, "component_fields": 0}
    hs_codes = set()

    for item in items:
        if item.get("hs_code"):
            hs_codes.add(str(item.get("hs_code")))
        import_tax_total = _to_number(item.get("import_tax_total")) or 0
        component_total = sum(
            _to_number(item.get(fieldname)) or 0
            for fieldname in ("cc_anti_dumping", "igi_amount", "iva_amount", "dta", "prv_duty", "prv_iva")
        )
        if import_tax_total:
            row_tax = import_tax_total
            source_counts["import_tax_total"] += 1
        else:
            row_tax = component_total
            if component_total:
                source_counts["component_fields"] += 1

        if row_tax:
            has_tax_value = True
            rows_with_tax += 1
            total += row_tax
        else:
            rows_missing_tax += 1

    return {
        "item_count": len(items),
        "rows_with_tax_count": rows_with_tax,
        "rows_missing_tax_count": rows_missing_tax,
        "system_import_tax_total_mxn": _round_money(total, 6) if has_tax_value else None,
        "tax_source": _system_tax_source_label(source_counts),
        "hs_code_count": len(hs_codes),
    }


def _build_tax_certificate_attachment_values(
    *,
    parsed: dict,
    batch: dict,
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
) -> dict:
    header = parsed.get("header") or {}
    parse_snapshot = {
        "source_name": parsed.get("source_name") or source_name or "",
        "parser": parsed.get("parser") or "",
        "parse_targets": parsed.get("parse_targets") or [],
        "summary": parsed.get("summary") or {},
        "header": header,
        "tax_totals": parsed.get("tax_totals") or {},
        "line_items": parsed.get("line_items") or [],
        "validation": parsed.get("validation") or {},
    }
    reconciliation_snapshot = parsed.get("reconciliation") or {}
    file_ref = file_url or file_path or parsed.get("file_url") or parsed.get("file_path") or ""
    file_name = source_name or parsed.get("file_name") or _file_name_from_ref(file_ref)
    return {
        "batch": batch.get("name") or "",
        "version": batch.get("current_version") or "",
        "source_type": "Voucher",
        "attachment_type": "Tax Certificate",
        "source_doc_no": header.get("pedimento_no") or header.get("pedimento_ref") or header.get("pedimento_short_no") or "",
        "file_name": file_name,
        "file_url": file_ref,
        "parse_status": "Parsed",
        "parse_result_json": _json_dumps(parse_snapshot),
        "mapped_result_json": _json_dumps(reconciliation_snapshot),
        "remark": "完税凭证解析快照，仅用于复核，未写入成本字段。",
    }


def _find_existing_tax_certificate_attachment(values: dict) -> str | None:
    filters = {
        "batch": values.get("batch"),
        "attachment_type": "Tax Certificate",
    }
    if values.get("source_doc_no"):
        filters["source_doc_no"] = values["source_doc_no"]
    elif values.get("file_url"):
        filters["file_url"] = values["file_url"]
    else:
        return None

    rows = frappe.get_all(
        "Overseas Cost Attachment",
        filters=filters,
        fields=["name"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return rows[0]["name"] if rows else None


def _query_tax_certificate_attachment_records(*, batch_name: str | None = None, limit: int = 20) -> list[dict]:
    filters = {
        "source_type": "Voucher",
        "attachment_type": "Tax Certificate",
    }
    if batch_name:
        filters["batch"] = batch_name
    return frappe.get_all(
        "Overseas Cost Attachment",
        filters=filters,
        fields=[
            "name",
            "batch",
            "version",
            "source_doc_no",
            "file_name",
            "file_url",
            "parse_status",
            "parse_result_json",
            "mapped_result_json",
            "modified",
            "creation",
        ],
        order_by="modified desc",
        limit_page_length=limit,
    )


def _build_tax_certificate_record_summary(row: dict) -> dict:
    parse_result = _json_loads(row.get("parse_result_json")) or {}
    mapped_result = _json_loads(row.get("mapped_result_json")) or {}
    header = parse_result.get("header") or {}
    summary = parse_result.get("summary") or {}
    validation = parse_result.get("validation") or {}
    voucher = mapped_result.get("voucher") or {}
    system = mapped_result.get("system") or {}
    difference = mapped_result.get("difference") or {}
    batch = mapped_result.get("batch") or {}
    return {
        "name": row.get("name") or "",
        "batch": batch or {"name": row.get("batch") or ""},
        "version": row.get("version") or "",
        "source_doc_no": row.get("source_doc_no") or header.get("pedimento_no") or "",
        "file_name": row.get("file_name") or parse_result.get("source_name") or "",
        "file_url": row.get("file_url") or "",
        "parse_status": row.get("parse_status") or "",
        "modified": row.get("modified") or "",
        "creation": row.get("creation") or "",
        "customs_no": header.get("pedimento_no") or voucher.get("customs_no") or row.get("source_doc_no") or "",
        "container_no": header.get("container_no") or voucher.get("container_no") or "",
        "pedimento_ref": header.get("pedimento_ref") or voucher.get("pedimento_ref") or "",
        "payment_date": header.get("payment_date") or voucher.get("payment_date") or "",
        "paid_total_mxn": summary.get("paid_total_mxn") if summary.get("paid_total_mxn") is not None else voucher.get("paid_total_mxn"),
        "tax_total_sum_mxn": summary.get("tax_total_sum_mxn"),
        "system_tax_total_mxn": system.get("system_import_tax_total_mxn"),
        "tax_total_diff_mxn": difference.get("tax_total_diff_mxn"),
        "direction_label": difference.get("direction_label") or "",
        "item_count": summary.get("item_count") or voucher.get("item_count") or 0,
        "declared_item_count": summary.get("declared_item_count") or voucher.get("declared_item_count"),
        "validation_status": validation.get("status") or summary.get("validation_status") or "",
        "validation_status_label": validation.get("status_label") or summary.get("validation_status_label") or "",
        "reconciliation_status": mapped_result.get("status") or "",
        "reconciliation_status_label": mapped_result.get("status_label") or "",
        "review_count": mapped_result.get("review_count") or 0,
        "failed_count": mapped_result.get("failed_count") or 0,
        "passed_count": mapped_result.get("passed_count") or 0,
    }


def _find_tax_certificate_batch(header: dict, batch_name: str | None = None) -> dict | None:
    fields = [
        "name",
        "batch_no",
        "customs_no",
        "waybill_no",
        "container_no",
        "current_version",
        "item_count",
        "total_goods_value",
        "estimated_total_cost_rmb",
        "actual_total_cost_rmb",
    ]

    def first_by(fieldname: str, value: str | None) -> dict | None:
        if not value:
            return None
        rows = frappe.get_all(
            "Overseas Cost Batch",
            filters={fieldname: value},
            fields=fields,
            order_by="modified desc",
            limit_page_length=1,
        )
        return rows[0] if rows else None

    # 完税凭证本身识别出的报关单号/柜号最可信；页面当前批次只作为兜底。
    for fieldname, value in (
        ("customs_no", header.get("pedimento_no")),
        ("waybill_no", header.get("container_no")),
        ("container_no", header.get("container_no")),
        ("batch_no", header.get("container_no")),
    ):
        batch = first_by(fieldname, value)
        if batch:
            return batch

    for value in [batch_name]:
        for fieldname in ("name", "batch_no", "customs_no", "waybill_no", "container_no"):
            batch = first_by(fieldname, value)
            if batch:
                return batch
    return None


def _has_frappe_db_context() -> bool:
    if frappe is None:
        return False
    try:
        return bool(getattr(frappe.local, "site", None)) and getattr(frappe, "db", None) is not None
    except Exception:
        return False


def _public_batch_snapshot(batch: dict | None) -> dict:
    if not batch:
        return {}
    return {
        "name": batch.get("name") or "",
        "batch_no": batch.get("batch_no") or "",
        "customs_no": batch.get("customs_no") or "",
        "waybill_no": batch.get("waybill_no") or "",
        "container_no": batch.get("container_no") or "",
        "current_version": batch.get("current_version") or "",
        "item_count": batch.get("item_count") or 0,
        "total_goods_value": batch.get("total_goods_value"),
        "estimated_total_cost_rmb": batch.get("estimated_total_cost_rmb"),
        "actual_total_cost_rmb": batch.get("actual_total_cost_rmb"),
    }


def _batch_matches_certificate(batch: dict, header: dict) -> bool:
    customs_no = _compact_match_value(header.get("pedimento_no"))
    container_no = _compact_match_value(header.get("container_no"))
    batch_values = {
        _compact_match_value(batch.get("customs_no")),
        _compact_match_value(batch.get("waybill_no")),
        _compact_match_value(batch.get("container_no")),
        _compact_match_value(batch.get("batch_no")),
    }
    return bool((customs_no and customs_no in batch_values) or (container_no and container_no in batch_values))


def _batch_match_target(batch: dict | None) -> str:
    if not batch:
        return ""
    values = [batch.get("customs_no"), batch.get("waybill_no"), batch.get("container_no"), batch.get("batch_no")]
    return " / ".join(str(value) for value in values if value) or batch.get("name") or ""


def _voucher_match_target(header: dict) -> str:
    values = [header.get("pedimento_no"), header.get("container_no")]
    return " / ".join(str(value) for value in values if value) or "--"


def _compact_match_value(value) -> str:
    return re.sub(r"[\s\-_/]+", "", str(value or "")).upper()


def _system_tax_source_label(source_counts: dict) -> str:
    if source_counts.get("import_tax_total"):
        return "IMPUESTOS合计清关税费"
    if source_counts.get("component_fields"):
        return "IGI/IVA/DTA/PRV分项合计"
    return "未填系统税费"


def _tax_difference_direction(diff) -> str:
    if diff is None:
        return "暂无差额"
    if abs(float(diff)) < 0.01:
        return "一致"
    if diff > 0:
        return "凭证金额高于系统"
    return "凭证金额低于系统"


def _parse_tax_totals(text: str) -> dict:
    aliases = {
        "DTA": "dta_mxn",
        "PRV": "prv_mxn",
        "IVA/PRV": "prv_iva_mxn",
        "IVA": "iva_mxn",
        "IGI/IGE": "igi_mxn",
    }
    totals = {}
    for label, fieldname in aliases.items():
        match = re.search(rf"\b{re.escape(label)}\s+0\s+([\d,]+(?:\.\d+)?)\b", text)
        totals[fieldname] = _to_number(match.group(1)) if match else 0
    return totals


def _parse_declared_item_count(text: str) -> int | None:
    match = re.search(r"TOTAL DE PARTIDAS[\s\S]{0,140}?(\d{3,6})\*+", text, flags=re.IGNORECASE)
    if not match:
        return None
    token = re.sub(r"\D", "", match.group(1))
    if not token:
        return None
    if len(token) >= 3:
        value = int(token[-3:])
        if value:
            return value
    return int(token)


def _parse_pedimento_items(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines()]
    items: list[dict] = []
    item_pattern = re.compile(
        r"^(\d{11})\s+(\d{2})\s+\d+\s+\d+\s+\d+\s+([\d,]+\.\d{3})\s+\d+\s+([\d,]+\.\d{5})\s+([A-Z]{3})\s+([A-Z]{3})$"
    )
    index = 0
    while index < len(lines):
        match = item_pattern.match(lines[index])
        if not match:
            index += 1
            continue

        raw_fraction = match.group(1)
        description = _next_description(lines, index + 1)
        tax_lines = _collect_item_tax_lines(lines, index + 1)
        value_line = _next_value_line(lines, index + 1)
        items.append(
            {
                "row_no": len(items) + 1,
                "fraction_raw": raw_fraction,
                "hs_code": raw_fraction[:8],
                "item_seq": raw_fraction[8:],
                "nico": match.group(2),
                "quantity_umc": _to_number(match.group(3)),
                "quantity_umt": _to_number(match.group(4)),
                "origin_country": match.group(5),
                "seller_country": match.group(6),
                "import_name": description,
                "taxes": tax_lines,
                "value_line_raw": value_line,
                "needs_manual_review": not description,
            }
        )
        index += 1
    return items


def _next_description(lines: list[str], start: int) -> str:
    for line in lines[start : start + 5]:
        if not line or _is_noise_line(line):
            continue
        if re.match(r"^(IGI|IVA)\s+", line):
            continue
        if re.match(r"^\d", line):
            continue
        return line
    return ""


def _collect_item_tax_lines(lines: list[str], start: int) -> dict:
    taxes = {}
    for line in lines[start : start + 8]:
        if _is_item_start_line(line):
            break
        match = re.match(r"^(IGI|IVA)\s+([\d.]+)\s+\d+\s+\d+\s+([\d,]+(?:\.\d+)?)$", line)
        if not match:
            continue
        key = match.group(1).lower()
        taxes[f"{key}_rate"] = _to_number(match.group(2))
        taxes[f"{key}_amount_mxn"] = _to_number(match.group(3))
    return taxes


def _is_item_start_line(line: str) -> bool:
    return bool(
        re.match(
            r"^\d{11}\s+\d{2}\s+\d+\s+\d+\s+\d+\s+[\d,]+\.\d{3}\s+\d+\s+[\d,]+\.\d{5}\s+[A-Z]{3}\s+[A-Z]{3}$",
            line,
        )
    )


def _next_value_line(lines: list[str], start: int) -> str:
    for line in lines[start : start + 8]:
        if re.match(r"^[\d,]+\s+[\d.]+$", line):
            return line
    return ""


def _is_noise_line(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            "IDENTIF.",
            "COMPLEMENTO",
            "PARTIDAS",
            "AGENTE ADUANAL",
            "DECLARO BAJO PROTESTA",
        )
    )


def _resolve_pdf_file_path(*, file_path: str | None = None, file_url: str | None = None) -> Path:
    if file_path:
        path = Path(file_path).expanduser()
        if path.exists():
            return _ensure_pdf_path(path)
        raise FileNotFoundError(f"未找到 PDF 文件：{file_path}")

    if not file_url:
        raise ValueError("请传入 file_path 或 file_url。")

    if frappe is not None:
        resolved_file_url = file_url
        if not resolved_file_url.startswith("/"):
            file_row = frappe.db.get_value("File", resolved_file_url, ["file_url"], as_dict=True)
            if file_row and file_row.get("file_url"):
                resolved_file_url = file_row["file_url"]
        if resolved_file_url.startswith("/private/files/"):
            relative_name = resolved_file_url.split("/private/files/", 1)[1]
            return _ensure_pdf_path(Path(frappe.get_site_path("private", "files", relative_name)))
        if resolved_file_url.startswith("/files/"):
            relative_name = resolved_file_url.split("/files/", 1)[1]
            return _ensure_pdf_path(Path(frappe.get_site_path("public", "files", relative_name)))

    path = Path(file_url).expanduser()
    if path.exists():
        return _ensure_pdf_path(path)
    raise FileNotFoundError(f"无法解析 PDF 文件路径：{file_url}")


def _ensure_pdf_path(path: Path) -> Path:
    if path.suffix.lower() != ".pdf":
        raise ValueError("当前仅支持 .pdf 格式的完税凭证。")
    return path


def _normalize_text(text: str | None) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _search(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return ""
    if len(match.groups()) == 1:
        return _clean_spaces(match.group(1))
    return " ".join(_clean_spaces(group) for group in match.groups() if group is not None)


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(0) if match else ""


def _first_number(*values) -> float | None:
    for value in values:
        number = _to_number(value)
        if number is not None:
            return number
    return None


def _to_number(value) -> float | None:
    if value in (None, ""):
        return None
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _round_money(value, digits: int = 2) -> float:
    return round(float(value or 0), digits)


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads(value) -> dict:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _file_name_from_ref(value: str) -> str:
    text = str(value or "").split("?", 1)[0].replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1] if text else ""
