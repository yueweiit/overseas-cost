"""中文用途：附件内容识别与分类测试。"""

from pathlib import Path

from overseas_costing.services import attachment_parse_service
from overseas_costing.services.attachment_parse_service import (
    _has_meaningful_document_text,
    classify_source_document_text,
    extract_pdf_text_with_method,
    extract_source_document_field_candidates,
    parse_purchase_order_text,
    preview_source_document,
)


def test_classify_customs_declaration_before_price_document() -> None:
    text = "中华人民共和国海关出口货物报关单 3909500000 单价/总价/币制 1.8800 中国 6016.00 美元"

    classification = classify_source_document_text(text, source_name="供应商底单.pdf")
    fields = extract_source_document_field_candidates(text, classification_code=classification["code"])

    assert classification["code"] == "customs_declaration"
    assert fields["hs_codes"] == ["3909500000"]
    assert fields["unit_price_candidate"] == 1.88
    assert fields["goods_value_candidate"] == 6016
    assert fields["currencies"] == ["USD"]


def test_classify_purchase_price_document_requires_goods_and_price_fields() -> None:
    text = "物料编码 Material Code: FL000778\n单价 Precio: 12.5 USD\n总金额 Amount: 250 USD"

    classification = classify_source_document_text(text, source_name="采购发票.pdf")

    assert classification["code"] == "purchase_price_document"


def test_classify_logistics_quote_without_treating_it_as_purchase_price() -> None:
    text = "物流报价 Cotizacion de logistica\n海运费 2900 元/方\n合计 4350 元"

    classification = classify_source_document_text(text, source_name="物流报价.png")

    assert classification["code"] == "logistics_quote"


def test_classify_mexico_pedimento_as_tax_certificate() -> None:
    text = """
PEDIMENTO
NUM. PEDIMENTO: 26 16 1681 6000151
ADUANA E/S: 160
IMPORTE PAGADO: $ 129,883.00
"""

    classification = classify_source_document_text(text, source_name="PD_MZ260108凭证.pdf")
    fields = extract_source_document_field_candidates(text, classification_code=classification["code"])

    assert classification["code"] == "tax_certificate"
    assert fields["pedimento_no_candidate"] == "26 16 1681 6000151"
    assert fields["paid_total_mxn_candidate"] == 129883


def test_sync_tax_certificate_identity_fills_empty_batch_and_item_customs_numbers(monkeypatch) -> None:
    updates = []

    class FakeDB:
        @staticmethod
        def set_value(*args, **kwargs):
            updates.append((args, kwargs))

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(doctype, filters=None, **_kwargs):
            assert doctype == "Overseas Cost Item"
            assert filters == {"batch": "BATCH-001", "version": "VER-001"}
            return [
                {"name": "ITEM-EMPTY", "customs_no": ""},
                {"name": "ITEM-KEEP", "customs_no": "26 16 1681 6000001"},
            ]

    monkeypatch.setattr(attachment_parse_service, "frappe", FakeFrappe)
    monkeypatch.setattr(attachment_parse_service, "_insert_fx_sync_audit_log", lambda **_kwargs: None)

    result = attachment_parse_service._sync_tax_certificate_identity(
        parsed={"header": {"pedimento_no": "26 16 1681 6000151"}},
        batch={"name": "BATCH-001", "current_version": "VER-001", "customs_no": ""},
        source_name="PD_MZ260108凭证.pdf",
    )

    assert result == {
        "action": "updated",
        "customs_no": "26 16 1681 6000151",
        "batch_updated": True,
        "item_updated_count": 1,
    }
    assert updates[0][0] == ("Overseas Cost Batch", "BATCH-001", "customs_no", "26 16 1681 6000151")
    assert updates[1][0] == ("Overseas Cost Item", "ITEM-EMPTY", "customs_no", "26 16 1681 6000151")


def test_sync_saved_tax_certificate_identity_reuses_parsed_snapshot(monkeypatch) -> None:
    commit_count = {"value": 0}

    class FakeDB:
        @staticmethod
        def get_value(doctype, name, _fields, as_dict=False):
            assert doctype == "Overseas Cost Batch"
            assert name == "BATCH-001"
            assert as_dict is True
            return {"name": "BATCH-001", "current_version": "VER-001", "customs_no": ""}

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

    monkeypatch.setattr(attachment_parse_service, "frappe", FakeFrappe)
    monkeypatch.setattr(attachment_parse_service, "_has_frappe_db_context", lambda: True)
    monkeypatch.setattr(
        attachment_parse_service,
        "_query_tax_certificate_attachment_records",
        lambda **_kwargs: [
            {
                "name": "ATT-001",
                "batch": "BATCH-001",
                "file_name": "PD_MZ260108凭证.pdf",
                "parse_result_json": '{"header": {"pedimento_no": "26 16 1681 6000151"}}',
            }
        ],
    )
    monkeypatch.setattr(attachment_parse_service, "_sync_tax_certificate_identity", lambda **_kwargs: {"action": "updated"})

    result = attachment_parse_service.sync_saved_tax_certificate_identity()

    assert result["updated_count"] == 1
    assert result["conflict_count"] == 0
    assert result["skipped_count"] == 0
    assert commit_count["value"] == 1


def test_parse_purchase_order_extracts_only_complete_price_lines() -> None:
    text = """
PURCHASE ORDER NO: PO2026050901
Supplier (China): ZHEJIANG HUAFON TPU CO LTD
Buyer (Wevice): YUEWEISA DE CV
Currency: USD
S890 TPU raw material 1200 0.619 742.80
ME230 Packing bag 500 0.12 60.00
S891 Incomplete row 100 0.35
"""

    classification = classify_source_document_text(text, source_name="PO2026050901（已盖章签字）.pdf")
    parsed = parse_purchase_order_text(text, source_name="PO2026050901（已盖章签字）.pdf")

    assert classification["code"] == "purchase_order"
    assert parsed["purchase_order_no"] == "PO2026050901"
    assert parsed["supplier"] == "ZHEJIANG HUAFON TPU CO LTD"
    assert parsed["buyer"] == "YUEWEISA DE CV"
    assert parsed["currency"] == "USD"
    assert len(parsed["line_items"]) == 2
    assert parsed["line_items"][0]["material_code"] == "S890"
    assert parsed["line_items"][0]["unit_price"] == 0.619
    assert parsed["line_items"][0]["goods_value"] == 742.8


def test_page_markers_do_not_count_as_pdf_text_layer() -> None:
    assert _has_meaningful_document_text("--- Page 1 ---\n--- Page 2 ---\n--- Page 3 ---\n--- Page 4 ---\n--- Page 5 ---") is False


def test_extract_pdf_text_prefers_layout_preserving_output(monkeypatch) -> None:
    monkeypatch.setattr(attachment_parse_service, "_resolve_pdf_file_path", lambda **_kwargs: Path("采购订单.pdf"))
    monkeypatch.setattr(
        attachment_parse_service,
        "_extract_pdf_layout_text",
        lambda _path: "--- Page 1 ---\nPURCHASE ORDER NO: PO2026072401\nAB123 商品 100 2.5 250",
    )

    text, method = extract_pdf_text_with_method(file_path="采购订单.pdf")

    assert method == "pdf_layout_text"
    assert "AB123" in text


def test_preview_source_document_supports_docx_and_txt(monkeypatch) -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>PURCHASE ORDER NO: PO2026072401</w:t></w:r></w:p>
        <w:p><w:r><w:t>Currency: USD</w:t></w:r></w:p>
        <w:p><w:r><w:t>AB123 商品 100 2.5 250</w:t></w:r></w:p>
      </w:body>
    </w:document>"""

    class FakeDocxArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, name):
            assert name == "word/document.xml"
            return document_xml.encode("utf-8")

    monkeypatch.setattr(attachment_parse_service.zipfile, "ZipFile", lambda _path: FakeDocxArchive())

    extracted_docx_text = attachment_parse_service._extract_docx_text(Path("采购订单.docx"))

    assert "PO2026072401" in extracted_docx_text

    monkeypatch.setattr(attachment_parse_service, "_resolve_source_file_path", lambda **_kwargs: Path("采购订单.docx"))
    monkeypatch.setattr(attachment_parse_service, "_extract_docx_text", lambda _path: extracted_docx_text)

    docx_result = preview_source_document(file_path="采购订单.docx")

    assert docx_result["extraction_method"] == "word_docx"
    assert docx_result["classification"]["code"] == "purchase_order"
    assert docx_result["purchase_order"]["purchase_order_no"] == "PO2026072401"
    assert docx_result["purchase_order"]["line_items"][0]["material_code"] == "AB123"

    monkeypatch.setattr(attachment_parse_service, "_resolve_source_file_path", lambda **_kwargs: Path("采购价格.txt"))
    monkeypatch.setattr(
        attachment_parse_service,
        "_extract_plain_text_file",
        lambda _path: "物料编码：CD456\n单价：12.5 USD\n金额：1250 USD",
    )

    text_result = preview_source_document(file_path="采购价格.txt")

    assert text_result["extraction_method"] == "txt_text"
    assert text_result["classification"]["code"] == "purchase_price_document"
