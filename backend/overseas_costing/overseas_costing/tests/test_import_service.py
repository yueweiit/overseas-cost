"""
中文用途：导入服务骨架测试。
"""

from pathlib import Path

from overseas_costing.services.attachment_parse_service import build_packing_list_parse_task
from overseas_costing.services.import_service import (
    _coerce_item_numeric_defaults,
    _ensure_supported_excel_path,
    _values_equal_for_import,
    import_main_excel,
    import_purchase_expense_oa,
    parse_packing_list_attachment,
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
