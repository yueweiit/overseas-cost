"""
中文用途：导入服务骨架测试。
"""

from pathlib import Path

from overseas_costing.services import attachment_parse_service
from overseas_costing.services.attachment_parse_service import (
    _build_tax_certificate_reconciliation,
    build_packing_list_parse_task,
)
from overseas_costing.services.import_service import (
    _coerce_item_numeric_defaults,
    _ensure_supported_excel_path,
    _values_equal_for_import,
    import_main_excel,
    import_purchase_expense_oa,
    parse_packing_list_attachment,
    preview_tax_certificate_pdf,
    preview_yuewei_excel_file,
    save_tax_certificate_parse_result,
)


def test_import_purchase_expense_oa_returns_preview_and_dingtalk_payload() -> None:
    result = import_purchase_expense_oa(
        batch_name="BATCH-001",
        source_instance_id="PROC-001",
        approval_no="OA-001",
        official_url="https://oa.dingtalk.com/example",
        detail_rows_json=(
            '[{"物品编码Código":"FL004104","物品名称Nombre del artículo":"包装袋",'
            '"单价Precio":0.049,"总金额Monto Total":49,"币种Moneda":"人民币RMB"}]'
        ),
    )

    assert result["ok"] is True
    assert result["mapped_preview_count"] == 1
    assert result["mapped_preview_items"][0]["material_code"] == "FL004104"
    assert result["dingtalk_payload"]["instance_id"] == "PROC-001"
    assert "purchase_currency" in result["writeback_targets"]


def test_parse_packing_list_attachment_returns_parse_plan() -> None:
    result = parse_packing_list_attachment(
        batch_name="BATCH-002",
        attachment_name="packing-list.xlsx",
        template_hint="sea_container_sheet",
        sheet_rows_json=(
            '[{"物料编码":"CW000175","实际发货数量":400,"毛重KG":32.5,"体积m3":0.21}]'
        ),
    )

    assert result["ok"] is True
    assert result["mapped_preview_count"] == 1
    assert result["mapped_preview_items"][0]["actual_shipped_qty"] == 400
    assert result["parse_task"]["parser_strategy"] == "sea_container_sheet"


def test_preview_tax_certificate_pdf_extracts_pedimento_tax_summary_and_items() -> None:
    sample_text = """
Ped. 6000151
9 17.79570 23540.000 160
26  16  1681  6000151
A1
01/04/2026
DTA 0 5532 PRV 0 330
IVA/PRV 0 53 IVA 0 113244
IGI/IGE 0 10724
IMPORTE PAGADO:
$129,883
NUM. CFDI O DOCUMENTO EQUIVALENTE FECHA INCOTERM MONEDA FACT VAL. MON. FACT
COVE2680NE2K1
LX20251231001
31/12/2025 CIF USD 38,858.55
NO. (GUIA/ORDEN EMBARQUE)/ID: SZCN60111600 M
NUMERO / TIPO HPCU5155607 3
PEDIMENTO REF: MZ260108
39079101001 00 0 1 1 5,000.000 1 5,000.00000 CHN CHN
PLASTICO TPU EN FORMAS PRIMARIAS
IGI 0.00000 1 0 0
IVA 16.00000 1 0 32719
202871 40.57420202871
39232991005 01 0 1 6 512,000.000 1 896.00000 CHN CHN
BOLSAS DE PLASTICO
IGI 7.00000 1 0 2105
IVA 16.00000 1 0 5186
30068 0.0587330068
********* FIN DE PEDIMENTO NUM. TOTAL DE PARTIDAS: CLAVE PREVALIDADOR: 01002****** ****** *********
"""

    result = preview_tax_certificate_pdf(source_name="PD_MZ260108凭证.pdf", text=sample_text)

    assert result["ok"] is True
    assert result["header"]["pedimento_no"] == "26 16 1681 6000151"
    assert result["header"]["pedimento_short_no"] == "6000151"
    assert result["header"]["pedimento_ref"] == "MZ260108"
    assert result["header"]["container_no"] == "HPCU5155607"
    assert result["header"]["payment_date"] == "01/04/2026"
    assert result["header"]["exchange_rate"] == 17.7957
    assert result["tax_totals"]["dta_mxn"] == 5532
    assert result["tax_totals"]["iva_mxn"] == 113244
    assert result["summary"]["tax_total_sum_mxn"] == 129883
    assert result["summary"]["tax_total_matches_paid_total"] is True
    assert result["summary"]["declared_item_count"] == 2
    assert result["summary"]["validation_status"] == "passed"
    assert result["validation"]["status_label"] == "通过"
    assert result["summary"]["item_count"] == 2
    assert result["line_items"][0]["hs_code"] == "39079101"
    assert result["line_items"][0]["import_name"] == "PLASTICO TPU EN FORMAS PRIMARIAS"
    assert result["line_items"][0]["taxes"]["iva_amount_mxn"] == 32719
    assert result["reconciliation"]["status"] == "pending"
    assert result["reconciliation"]["voucher"]["paid_total_mxn"] == 129883


def test_preview_tax_certificate_pdf_flags_failed_validation_for_amount_mismatch() -> None:
    sample_text = """
Ped. 6000151
9 17.79570 23540.000 160
26  16  1681  6000151
01/04/2026
DTA 0 5532 PRV 0 330
IVA/PRV 0 53 IVA 0 113244
IGI/IGE 0 10724
IMPORTE PAGADO:
$129,884
NUMERO / TIPO HPCU5155607 3
PEDIMENTO REF: MZ260108
39079101001 00 0 1 1 5,000.000 1 5,000.00000 CHN CHN
PLASTICO TPU EN FORMAS PRIMARIAS
IGI 0.00000 1 0 0
IVA 16.00000 1 0 32719
202871 40.57420202871
********* FIN DE PEDIMENTO NUM. TOTAL DE PARTIDAS: CLAVE PREVALIDADOR: 01001****** ****** *********
"""

    result = preview_tax_certificate_pdf(source_name="bad-tax.pdf", text=sample_text)
    amount_check = next(check for check in result["validation"]["checks"] if check["code"] == "tax_total_matches_paid")

    assert result["summary"]["tax_total_sum_mxn"] == 129883
    assert result["summary"]["paid_total_mxn"] == 129884
    assert result["validation"]["status"] == "failed"
    assert result["summary"]["needs_manual_review"] is True
    assert amount_check["status"] == "failed"


def test_save_tax_certificate_parse_result_returns_dry_run_without_frappe() -> None:
    sample_text = """
Ped. 6000151
9 17.79570 23540.000 160
26  16  1681  6000151
01/04/2026
DTA 0 5532 PRV 0 330
IVA/PRV 0 53 IVA 0 113244
IGI/IGE 0 10724
IMPORTE PAGADO:
$129,883
NUMERO / TIPO HPCU5155607 3
PEDIMENTO REF: MZ260108
39079101001 00 0 1 1 5,000.000 1 5,000.00000 CHN CHN
PLASTICO TPU EN FORMAS PRIMARIAS
IGI 0.00000 1 0 0
IVA 16.00000 1 0 32719
202871 40.57420202871
********* FIN DE PEDIMENTO NUM. TOTAL DE PARTIDAS: CLAVE PREVALIDADOR: 01001****** ****** *********
"""

    result = save_tax_certificate_parse_result(
        source_name="PD_MZ260108凭证.pdf",
        text=sample_text,
        batch_name="HPCU5155607",
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["saved"] is False
    assert result["preview"]["header"]["pedimento_no"] == "26 16 1681 6000151"
    assert result["preview"]["reconciliation"]["voucher"]["paid_total_mxn"] == 129883


def test_tax_certificate_reconciliation_preview_calculates_difference_without_writeback() -> None:
    parsed = {
        "header": {
            "pedimento_no": "26 16 1681 6000151",
            "container_no": "HPCU5155607",
            "payment_date": "01/04/2026",
        },
        "summary": {
            "paid_total_mxn": 220,
            "tax_total_sum_mxn": 220,
            "item_count": 2,
            "declared_item_count": 2,
        },
        "validation": {"status": "passed", "status_label": "通过"},
    }
    result = _build_tax_certificate_reconciliation(
        parsed=parsed,
        batch={
            "name": "BATCH-001",
            "batch_no": "HPCU5155607",
            "customs_no": "26 16 1681 6000151",
            "waybill_no": "HPCU5155607",
            "item_count": 2,
        },
        items=[
            {"row_no": 1, "import_tax_total": 120, "hs_code": "39079101"},
            {"row_no": 2, "igi_amount": 30, "iva_amount": 40, "dta": 10, "hs_code": "39232991"},
        ],
    )

    assert result["status"] == "review"
    assert result["system"]["system_import_tax_total_mxn"] == 200
    assert result["difference"]["tax_total_diff_mxn"] == 20
    assert result["difference"]["direction_label"] == "凭证金额高于系统"
    assert result["message"].startswith("对比结果仅用于复核")


def test_tax_certificate_batch_lookup_prefers_voucher_header_over_requested_batch(monkeypatch) -> None:
    class FakeFrappe:
        @staticmethod
        def get_all(_doctype, filters=None, **_kwargs):
            if filters == {"customs_no": "26 16 1681 6000151"}:
                return [
                    {
                        "name": "BATCH-CUSTOMS",
                        "batch_no": "HPCU5155607",
                        "customs_no": "26 16 1681 6000151",
                        "waybill_no": "HPCU5155607",
                    }
                ]
            if filters == {"name": "CURRENT-BATCH"}:
                return [
                    {
                        "name": "CURRENT-BATCH",
                        "batch_no": "202606301549000536602",
                        "customs_no": "",
                        "waybill_no": "",
                    }
                ]
            return []

    monkeypatch.setattr(attachment_parse_service, "frappe", FakeFrappe)

    result = attachment_parse_service._find_tax_certificate_batch(
        {"pedimento_no": "26 16 1681 6000151", "container_no": "HPCU5155607"},
        batch_name="CURRENT-BATCH",
    )

    assert result["name"] == "BATCH-CUSTOMS"
    assert result["customs_no"] == "26 16 1681 6000151"


def test_build_packing_list_parse_task_defaults_to_multi_template_router() -> None:
    task = build_packing_list_parse_task(batch_name="BATCH-003")

    assert task["parser_strategy"] == "mixed_workbook_router"
    assert "volume_m3" in task["parse_targets"]


def test_import_main_excel_returns_yuewei_block_preview_without_frappe() -> None:
    result = import_main_excel(
        source_name="墨西哥进口物料综合成本核算.xlsx",
        source_sheet="2026年YUEWEI",
        blocks_json=(
            '[{"id":"HPCU5155607","sourceSheet":"2026年YUEWEI","sourceRange":"2026年YUEWEI!79:100",'
            '"customsNo":"26 16 1681 6000151","waybillNo":"HPCU5155607","transportMode":"海运",'
            '"items":[["YL000098","TPU-HF-8695AU",14.3575,5000,71787.5,'
            '"PLASTICO TPU EN FORMAS PRIMARIAS","39079101","00",null,null,null,{"grossWeightKg":1200}]]}]'
        ),
    )

    assert result["ok"] is True
    assert result["queued"] is False
    assert result["preview_batches"][0]["batch_no"] == "HPCU5155607"
    assert result["preview_batches"][0]["mapped_preview_items"][0]["material_code"] == "YL000098"
    assert result["preview_batches"][0]["mapped_preview_items"][0]["transport_mode"] == "SEA"


def test_coerce_item_numeric_defaults_keeps_formula_cache_blanks_importable() -> None:
    normalized = _coerce_item_numeric_defaults(
        {
            "material_code": "YL000098",
            "unit_price": None,
            "quantity": "",
            "goods_value": None,
            "gross_weight_kg": 1200,
        }
    )

    assert normalized["unit_price"] == 0
    assert normalized["quantity"] == 0
    assert normalized["goods_value"] == 0
    assert normalized["gross_weight_kg"] == 1200


def test_values_equal_for_import_treats_numeric_strings_as_same_value() -> None:
    assert _values_equal_for_import("2.60", 2.6) is True
    assert _values_equal_for_import("", None) is True
    assert _values_equal_for_import(" YL000098 ", "YL000098") is True
    assert _values_equal_for_import("2.61", 2.6) is False


def test_ensure_supported_excel_path_rejects_non_excel_suffix() -> None:
    xlsx_path = Path("成本表.xlsx")
    pdf_path = Path("成本表.pdf")

    assert _ensure_supported_excel_path(xlsx_path) == xlsx_path

    try:
        _ensure_supported_excel_path(pdf_path)
    except ValueError as exc:
        assert ".xlsx / .xlsm" in str(exc)
    else:
        raise AssertionError("PDF 文件不应通过 Excel 导入扩展名校验")


def test_preview_yuewei_excel_file_returns_selected_batches_without_import(monkeypatch) -> None:
    from overseas_costing.services import import_service

    def fake_parse(path: Path, sheet_name: str | None = None):
        assert path == Path("sample.xlsx")
        assert sheet_name is None
        return (
            {"sourceSheet": "7月份钢化膜空运", "parser": "oa_attachment_detail"},
            [
                {
                    "id": "PO-001",
                    "batchNo": "PO-001",
                    "sourceSheet": "7月份钢化膜空运",
                    "transportMode": "空运双清包税",
                    "items": [["FL004106", "钢化膜", 1.2, 500, 600]],
                }
            ],
        )

    monkeypatch.setattr(import_service, "_resolve_excel_file_path", lambda **_kwargs: Path("sample.xlsx"))
    monkeypatch.setattr(import_service, "parse_yuewei_excel_workbook", fake_parse)

    result = preview_yuewei_excel_file(file_url="/private/files/sample.xlsx")

    assert result["ok"] is True
    assert result["source_summary"]["block_count"] == 1
    assert result["selected_summary"]["block_count"] == 1
    assert result["selected_summary"]["item_count"] == 1
    assert result["preview_batches"][0]["batch_no"] == "PO-001"
