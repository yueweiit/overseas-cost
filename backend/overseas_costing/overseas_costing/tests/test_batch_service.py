"""中文用途：批次查询服务测试。"""

from io import BytesIO
import json

from openpyxl import load_workbook

from overseas_costing.services.batch_service import (
    EXCEL_COLUMNS,
    EXTRA_ITEM_FIELDS,
    _build_item_query_args,
    _build_batch_source_status,
    _build_export_xlsx_content,
    _build_writeback_readiness,
    _export_cell_value,
    _normalize_item_query_filters,
    _normalize_limit,
    check_writeback_ready,
    create_batch,
    get_audit_logs,
    get_batch_list,
    get_batch_items,
    is_hidden_approval_status,
)


def test_normalize_item_query_filters_strips_empty_values() -> None:
    filters = _normalize_item_query_filters(
        {"customs_no": " 26 16 ", "empty": "", "none": None},
        material_code=" YL000098 ",
    )

    assert filters == {
        "customs_no": "26 16",
        "material_code": "YL000098",
    }


def test_build_item_query_args_adds_field_and_keyword_filters() -> None:
    db_filters, or_filters = _build_item_query_args(
        "BATCH-DOC",
        "VERSION-DOC",
        {"customs_no": "6000151", "keyword": "TPU"},
    )

    assert ["batch", "=", "BATCH-DOC"] in db_filters
    assert ["version", "=", "VERSION-DOC"] in db_filters
    assert ["customs_no", "like", "%6000151%"] in db_filters
    assert ["product_name", "like", "%TPU%"] in or_filters
    assert ["material_code", "like", "%TPU%"] in or_filters


def test_get_batch_items_dry_run_keeps_filters() -> None:
    result = get_batch_items(
        batch_name="HPCU5155607",
        product_name="TPU",
        keyword="YL000098",
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["filters"]["product_name"] == "TPU"
    assert result["filters"]["keyword"] == "YL000098"
    assert result["columns"][0]["fieldname"] == "material_code"
    assert "derived_json" in EXTRA_ITEM_FIELDS


def test_excel_columns_include_spec_model_after_product_name() -> None:
    fieldnames = [column["fieldname"] for column in EXCEL_COLUMNS]
    spec_column = next(column for column in EXCEL_COLUMNS if column["fieldname"] == "spec_model")
    quantity_column = next(column for column in EXCEL_COLUMNS if column["fieldname"] == "quantity")
    unit_column = next(column for column in EXCEL_COLUMNS if column["fieldname"] == "unit")
    total_unit_column = next(column for column in EXCEL_COLUMNS if column["fieldname"] == "total_unit_rmb")

    assert fieldnames.index("spec_model") == fieldnames.index("product_name") + 1
    assert fieldnames.index("unit") == fieldnames.index("quantity") + 1
    assert "Especificación / Modelo" in spec_column["label"]
    assert quantity_column["label"] == "采购数量"
    assert unit_column["label"] == "单位"
    assert total_unit_column["label"] == "综合单价 RMB"


def test_sea_air_express_share_same_item_columns() -> None:
    fieldnames = [column["fieldname"] for column in EXCEL_COLUMNS]

    assert fieldnames[:8] == [
        "material_code",
        "product_name",
        "spec_model",
        "unit_price",
        "purchase_currency",
        "quantity",
        "unit",
        "goods_value",
    ]
    assert fieldnames == [column["fieldname"] for column in EXCEL_COLUMNS]
    assert {"spec_model", "product_name_es", "unit", "purchase_currency"}.issubset(set(EXTRA_ITEM_FIELDS + fieldnames))


def test_get_batch_list_defaults_to_recent_days_without_classic_samples(monkeypatch) -> None:
    from overseas_costing.services import batch_service

    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            return [
                {
                    "name": "BATCH-RECENT",
                    "batch_no": "202608051608000144099",
                    "transport_mode": "SEA",
                    "source_created_at": "2026-08-05 16:08:00",
                    "source_approval_status": "RUNNING",
                    "extra_json": "{}",
                    "modified": "2026-08-05 16:08:00",
                }
            ]

    monkeypatch.setattr(batch_service, "frappe", FakeFrappe)
    monkeypatch.setattr(batch_service, "_recent_start", lambda recent_days: "2026-07-15 00:00:00")
    monkeypatch.setattr(batch_service, "_attach_batch_source_status", lambda items: items)
    monkeypatch.setattr(batch_service, "_attach_batch_calculation_snapshot", lambda items: items)

    result = get_batch_list({"transport_mode": "", "recent_days": 30})

    assert result["ok"] is True
    assert result["total"] == 1
    assert len(calls) == 1
    assert calls[0][1]["filters"] == [["source_created_at", ">=", "2026-07-15 00:00:00"]]
    assert all(not item.get("is_classic_sample") for item in result["items"])


def test_get_batch_list_keyword_can_find_history_batch_by_item_field(monkeypatch) -> None:
    from overseas_costing.services import batch_service

    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            if doctype == "Overseas Cost Item":
                return [{"batch": "HISTORY-BATCH"}]
            if doctype == "Overseas Cost Batch" and kwargs.get("filters") and ["name", "in", ["HISTORY-BATCH"]] in kwargs["filters"]:
                return [
                    {
                        "name": "HISTORY-BATCH",
                        "batch_no": "202606010001",
                        "transport_mode": "SEA",
                        "source_created_at": "2026-06-01 10:00:00",
                        "source_approval_status": "COMPLETED",
                        "extra_json": "{}",
                        "modified": "2026-06-01 10:00:00",
                    }
                ]
            return []

    monkeypatch.setattr(batch_service, "frappe", FakeFrappe)
    monkeypatch.setattr(batch_service, "_attach_batch_source_status", lambda items: items)
    monkeypatch.setattr(batch_service, "_attach_batch_calculation_snapshot", lambda items: items)

    result = get_batch_list({"transport_mode": "", "recent_days": 30, "keyword": "墨镜"})

    assert result["ok"] is True
    assert result["total"] == 1
    assert result["items"][0]["name"] == "HISTORY-BATCH"
    assert any(call[0] == "Overseas Cost Item" for call in calls)


def test_create_batch_dry_run_builds_manual_batch_and_version() -> None:
    result = create_batch(
        json.dumps(
            {
                "batch_no": "MANUAL-001",
                "customs_no": "26 16 1681 6000151",
                "waybill_no": "HPCU5155607",
                "transport_mode": "海运",
                "project_collection": "Yuewei",
                "source_dingtalk_url": "https://aflow.dingtalk.com/dingtalk/web/query/pchomepage.htm#/plainapproval?procInstId=PROC-MANUAL-001",
            },
            ensure_ascii=False,
        )
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["batch"]["batch_no"] == "MANUAL-001"
    assert result["batch"]["waybill_no"] == "HPCU5155607"
    assert result["batch"]["transport_mode"] == "SEA"
    assert result["batch"]["source_type"] == "manual"
    assert result["batch"]["source_instance_id"] == "PROC-MANUAL-001"
    assert result["version"]["version_code"] == "手工-MANUAL-001"
    assert result["version"]["is_current"] == 1


def test_create_batch_dry_run_requires_batch_no() -> None:
    result = create_batch({"transport_mode": "空运"})

    assert result["ok"] is False
    assert result["dry_run"] is True
    assert "批次号" in result["message"]


def test_normalize_limit_keeps_audit_queries_bounded() -> None:
    assert _normalize_limit("20") == 20
    assert _normalize_limit("bad") == 80
    assert _normalize_limit(999) == 300
    assert _normalize_limit(0) == 1


def test_get_audit_logs_dry_run_returns_stable_shape() -> None:
    result = get_audit_logs(batch_name="HPCU5155607", version_name="VERSION-001", limit=20)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["batch_name"] == "HPCU5155607"
    assert result["version_name"] == "VERSION-001"
    assert result["items"] == []
    assert result["total"] == 0


def test_build_export_xlsx_content_styles_and_freezes_header() -> None:
    content = _build_export_xlsx_content(
        columns=[
            {"excel_col": "A", "fieldname": "material_code", "label": "物料编码"},
            {"excel_col": "B", "fieldname": "product_name", "label": "产品名称"},
        ],
        rows=[["FL004106", "钢化膜"]],
    )

    workbook = load_workbook(BytesIO(content))
    sheet = workbook.active

    assert sheet.freeze_panes == "C2"
    assert sheet.auto_filter.ref == "A1:B2"
    assert sheet["A1"].value == "物料编码"
    assert sheet["A1"].fill.fgColor.rgb == "FFFFD966"
    assert sheet["A1"].font.sz == 8
    assert sheet["A1"].font.bold is False
    assert sheet["A1"].font.color.rgb == "FF000000"
    assert sheet["A1"].border.left.style == "thin"
    assert sheet["A1"].border.left.color.rgb == "FF000000"
    assert sheet["A2"].value == "FL004106"


def test_export_cell_value_hides_default_zero_cleaning_fee() -> None:
    column = {"fieldname": "limpieza_contenedor"}

    assert _export_cell_value({"limpieza_contenedor": 0}, {}, column) == ""
    assert _export_cell_value({"limpieza_contenedor": "0.00"}, {}, column) == ""
    assert _export_cell_value({"limpieza_contenedor": 25}, {}, column) == 25


def test_build_export_xlsx_content_merges_repeated_batch_level_cells() -> None:
    content = _build_export_xlsx_content(
        columns=[
            {"excel_col": "A", "fieldname": "material_code", "label": "物料编码"},
            {"excel_col": "I", "fieldname": "customs_no", "label": "报关单号"},
            {"excel_col": "J", "fieldname": "waybill_no", "label": "中国到墨西哥运单号"},
            {"excel_col": "K", "fieldname": "china_misc_rmb", "label": "中国运输及相关杂费 RMB"},
        ],
        rows=[
            ["FL001", "26 16 1681 6000151", "HPCU5155607", 0],
            ["FL001", "26 16 1681 6000151", "HPCU5155607", 0],
            ["FL002", "26 16 1681 6000151", "FSCU8486789", 0],
        ],
    )

    workbook = load_workbook(BytesIO(content))
    sheet = workbook.active
    merged_ranges = {str(cell_range) for cell_range in sheet.merged_cells.ranges}

    assert "A2:A3" not in merged_ranges
    assert "B2:B4" in merged_ranges
    assert "C2:C3" in merged_ranges
    assert "D2:D4" in merged_ranges
    assert sheet["B2"].alignment.horizontal == "center"
    assert sheet["B2"].alignment.vertical == "center"


def test_build_export_xlsx_content_expands_long_text_columns() -> None:
    content = _build_export_xlsx_content(
        columns=[
            {"excel_col": "BD", "fieldname": "project_collection", "label": "项目归集"},
            {"excel_col": "BE", "fieldname": "transport_mode", "label": "运输方式"},
        ],
        rows=[
            ["productos comerciales贸易产品", "海运"],
            ["YW OEM-Tablet平板", "海运"],
        ],
    )

    workbook = load_workbook(BytesIO(content))
    sheet = workbook.active

    assert sheet.column_dimensions["A"].width >= 36
    assert sheet.column_dimensions["B"].width >= 14
    assert sheet["A2"].alignment.wrap_text is True
    assert sheet["B2"].alignment.wrap_text is True
    assert sheet.row_dimensions[2].height >= 20


def test_build_export_xlsx_content_uses_reference_header_color_groups() -> None:
    content = _build_export_xlsx_content(
        columns=[
            {"excel_col": "N", "fieldname": "cc_rate", "label": "C.C税率"},
            {"excel_col": "X", "fieldname": "import_tax_total", "label": "IMPUESTOS合计清关税费"},
            {"excel_col": "AP", "fieldname": "mexico_customs_rmb", "label": "墨西哥清关费用 RMB"},
            {"excel_col": "AX", "fieldname": "freight_alloc_rmb", "label": "运输费用分摊 RMB"},
            {"excel_col": "BB", "fieldname": "total_cost_rmb", "label": "综合成本 RMB"},
        ],
        rows=[[0, 0, 0, 0, 0]],
    )

    workbook = load_workbook(BytesIO(content))
    sheet = workbook.active

    assert sheet["A1"].fill.fgColor.rgb == "FF0DF2DF"
    assert sheet["B1"].fill.fgColor.rgb == "FFD04FCA"
    assert sheet["C1"].fill.fgColor.rgb == "FFFCC102"
    assert sheet["D1"].fill.fgColor.rgb == "FFFFF3CE"
    assert sheet["E1"].fill.fgColor.rgb == "FF04B0F1"
    assert sheet["E1"].font.bold is True
    assert sheet["E1"].font.color.rgb == "FFFFFFFF"


def test_check_writeback_ready_dry_run_returns_blocking_reasons() -> None:
    result = check_writeback_ready(batch_name="HPCU5155607", version_name="VERSION-001")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["ready"] is False
    assert result["checks"]["batch_exists"] is False
    assert result["blocking_reasons"] == ["当前未连接 Frappe，不能执行真实回写检查。"]
    assert result["item_issue_examples"] == []


def test_build_writeback_readiness_allows_complete_confirmed_batch() -> None:
    result = _build_writeback_readiness(
        batch={
            "status": "Clean",
            "confirm_status": "Confirmed",
            "current_version": "VERSION-001",
            "item_count": 1,
            "actual_total_cost_rmb": 25,
        },
        resolved_version_name="VERSION-001",
        items=[
            {
                "row_no": 1,
                "material_code": "YL000001",
                "product_name": "太阳眼镜",
                "quantity": 2,
                "unit_price": 8,
                "purchase_currency": "RMB",
                "goods_value": 16,
                "total_unit_rmb": 12.5,
            }
        ],
    )

    assert result["ready"] is True
    assert result["blocking_reasons"] == []
    assert result["checks"]["has_items"] is True
    assert result["checks"]["items_have_unit_price"] is True


def test_build_writeback_readiness_blocks_incomplete_item_data() -> None:
    result = _build_writeback_readiness(
        batch={
            "status": "Dirty",
            "confirm_status": "Draft",
            "current_version": "",
            "item_count": 2,
            "estimated_total_cost_rmb": 0,
            "actual_total_cost_rmb": 0,
        },
        resolved_version_name=None,
        items=[
            {
                "row_no": 7,
                "material_code": "",
                "product_name": "保护膜",
                "quantity": 0,
                "unit_price": "",
                "purchase_currency": "",
                "goods_value": 0,
                "total_unit_rmb": 0,
            }
        ],
    )

    assert result["ready"] is False
    assert result["checks"]["has_current_version"] is False
    assert result["checks"]["has_dirty_data"] is True
    assert result["item_issue_counts"]["material_code"] == 1
    assert result["item_issue_counts"]["unit_price"] == 1
    assert result["item_issue_examples"][0]["row_no"] == 7
    assert "当前批次还没有确认。" in result["blocking_reasons"]
    assert "批次记录明细数为 2，实际查询到 1 条。" in result["warning_reasons"]


def test_hidden_approval_status_matches_revoked_dingtalk_statuses() -> None:
    assert is_hidden_approval_status("TERMINATED") is True
    assert is_hidden_approval_status("已撤销") is True
    assert is_hidden_approval_status("COMPLETED") is False
    assert is_hidden_approval_status("") is False


def test_build_batch_source_status_summarizes_oa_and_voucher_records() -> None:
    status = _build_batch_source_status(
        {
            "name": "BATCH-001",
            "batch_no": "FSCU8486789",
            "source_type": "oa_logistics",
            "source_approval_no": "202607010001",
            "source_attachment_count": 3,
        },
        [
            {"source_type": "OA", "attachment_type": "Packing List", "parse_status": "Queued"},
            {"source_type": "OA", "attachment_type": "Commercial Invoice", "parse_status": "Queued"},
            {
                "name": "ATT-OLD",
                "source_type": "Voucher",
                "attachment_type": "Tax Certificate",
                "parse_status": "Parsed",
                "modified": "2026-07-01 10:00:00",
                "mapped_result_json": json.dumps(
                    {
                        "status": "passed",
                        "status_label": "一致",
                        "voucher": {"paid_total_mxn": 100},
                        "system": {"system_import_tax_total_mxn": 100},
                        "difference": {"tax_total_diff_mxn": 0, "direction_label": "一致"},
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "name": "ATT-NEW",
                "file_name": "PD_MZ260108凭证.pdf",
                "source_type": "Voucher",
                "attachment_type": "Tax Certificate",
                "parse_status": "Parsed",
                "modified": "2026-07-20 10:00:00",
                "parse_result_json": json.dumps({"summary": {"paid_total_mxn": 129883}}, ensure_ascii=False),
                "mapped_result_json": json.dumps(
                    {
                        "status": "review",
                        "status_label": "需复核",
                        "system": {"system_import_tax_total_mxn": 130186},
                        "difference": {"tax_total_diff_mxn": -303, "direction_label": "凭证金额低于系统"},
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )

    assert status["has_oa_logistics"] is True
    assert status["source_no"] == "202607010001"
    assert status["oa_attachment_count"] == 3
    assert status["registered_attachment_count"] == 4
    assert status["packing_list_count"] == 1
    assert status["parsed_packing_list_count"] == 0
    assert status["tax_certificate_count"] == 2
    assert status["parsed_tax_certificate_count"] == 2
    assert status["latest_tax_certificate_reconciliation"] == {
        "name": "ATT-NEW",
        "file_name": "PD_MZ260108凭证.pdf",
        "modified": "2026-07-20 10:00:00",
        "status": "review",
        "status_label": "需复核",
        "manual_resolution_status_label": "",
        "paid_total_mxn": 129883,
        "system_tax_total_mxn": 130186,
        "tax_total_diff_mxn": -303,
        "direction_label": "凭证金额低于系统",
    }


def test_build_batch_source_status_exposes_quote_candidates_without_raw_oa_text() -> None:
    status = _build_batch_source_status(
        {
            "name": "BATCH-QUOTE-001",
            "extra_json": json.dumps(
                {
                    "source": "dingtalk_oa_logistics",
                    "logistics_quote_candidates": [
                        {
                            "carrier": "SISA",
                            "amount": 5730,
                            "currency": "RMB",
                            "volume_m3": 1.5,
                            "evidence_line": "合计价格：5730元",
                            "source_field": "物流报价",
                            "source_value": "不应暴露给前端的完整原文",
                        }
                    ],
                    "confirmed_logistics_quote": {
                        "carrier": "SISA",
                        "amount": 5730,
                        "currency": "RMB",
                    },
                },
                ensure_ascii=False,
            ),
        }
    )

    assert status["logistics_quote_candidate_count"] == 1
    assert status["logistics_quote_candidates"] == [
        {
            "carrier": "SISA",
            "amount": 5730,
            "currency": "RMB",
            "volume_m3": 1.5,
            "evidence_line": "合计价格：5730元",
            "source_field": "物流报价",
            "status": "待确认",
        }
    ]
    assert status["has_confirmed_logistics_quote"] is True
    assert "source_value" not in status["logistics_quote_candidates"][0]


def test_build_batch_source_status_exposes_logistics_text_summary() -> None:
    status = _build_batch_source_status(
        {
            "name": "BATCH-DHL-001",
            "source_type": "oa_logistics",
            "extra_json": json.dumps(
                {
                    "source": "dingtalk_oa_logistics",
                    "form_fields": {
                        "物流报价Cotización de logística": "DHL报价：\n50.22*1.3825*43.2+155*1.3825*1+155*1=3368.62678元",
                        "物流方式Camino Envío": "Express快递",
                        "预计发货日期Fecha de Pre-entrega": "2026/8/12",
                        "目标地区Países destinatarios": "MANZANILLO Mexico",
                        "重量Peso（KG）": "43.2",
                    },
                },
                ensure_ascii=False,
            ),
        }
    )

    assert status["logistics_text_summary"]["transport_mode"] == "EXPRESS"
    assert status["logistics_text_summary"]["logistics_quote_carrier"] == "DHL"
    assert status["logistics_text_summary"]["logistics_quote_amount"] == 3368.62678
    assert status["logistics_text_summary"]["pre_delivery_date"] == "2026/8/12"
    assert status["logistics_text_summary"]["destination"] == "MANZANILLO Mexico"
    assert "logistics_quote_text" not in status["logistics_text_summary"]
