"""
中文用途：导入服务骨架测试。
"""

import json
import shutil
from pathlib import Path

import pytest

from overseas_costing.services import attachment_parse_service
from overseas_costing.services.attachment_parse_service import (
    _build_tax_certificate_manual_resolution,
    _build_tax_certificate_reconciliation,
    build_packing_list_parse_task,
)
from overseas_costing.services.import_service import (
    apply_linked_purchase_expense_fillable_fields,
    _coerce_item_numeric_defaults,
    _ensure_supported_excel_path,
    _get_linked_purchase_approvals_from_extra,
    _index_items,
    _match_item,
    _values_equal_for_import,
    get_tax_certificate_parse_record,
    import_main_excel,
    import_purchase_expense_oa,
    list_oa_form_attachments,
    list_tax_certificate_parse_records,
    parse_packing_list_attachment,
    parse_oa_packing_list_attachments,
    preview_packing_list_attachment,
    preview_linked_purchase_expense_oa,
    preview_tax_certificate_pdf,
    preview_yuewei_excel_file,
    save_tax_certificate_parse_result,
    apply_packing_list_fillable_fields,
    download_oa_form_attachment,
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


def test_get_linked_purchase_approvals_from_oa_trace_extra_json() -> None:
    linked = _get_linked_purchase_approvals_from_extra(
        (
            '{"source":"excel","oa_logistics_trace":{"linked_purchase_approvals":['
            '{"approval_no":"202604300000000596348","source_instance_id":"PROC-PURCHASE-001"}'
            "]}}"
        )
    )

    assert linked[0]["approval_no"] == "202604300000000596348"
    assert linked[0]["source_instance_id"] == "PROC-PURCHASE-001"


def test_purchase_item_match_rejects_same_code_with_different_spec() -> None:
    indexes = _index_items(
        [
            {
                "name": "ITEM-001",
                "material_code": "YL00060",
                "product_name": "TPU原料 HF-1190A-8",
                "spec_model": "HF-1190A-8",
            }
        ]
    )

    matched_by, candidates = _match_item(
        {"material_code": "YL00060", "product_name": "原料TPU", "spec_model": "HF-1190A-1"},
        indexes,
    )

    assert matched_by == "material_code"
    assert candidates == []


def test_purchase_item_match_trusts_unique_material_code_when_enabled() -> None:
    indexes = _index_items(
        [
            {
                "name": "ITEM-001",
                "material_code": "YL00060",
                "product_name": "TPU原料 HF-1190A-8",
                "spec_model": "HF-1190A-8",
            }
        ]
    )

    matched_by, candidates = _match_item(
        {"material_code": "YL00060", "product_name": "原料TPU", "spec_model": "HF-1190A-1"},
        indexes,
        trust_unique_material_code=True,
    )

    assert matched_by == "material_code"
    assert candidates[0]["name"] == "ITEM-001"


def test_preview_linked_purchase_expense_oa_matches_without_writing(monkeypatch) -> None:
    from overseas_costing.services import import_service

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Batch" and name_or_filters == "FSCU8486789":
                return {"name": "BATCH-DOC"} if as_dict else "BATCH-DOC"
            if doctype == "Overseas Cost Batch" and name_or_filters == "BATCH-DOC":
                if fields == ["current_version"]:
                    return {"current_version": "VER-DOC"}
                return {
                    "name": "BATCH-DOC",
                    "batch_no": "FSCU8486789",
                    "source_approval_no": "202606101808000475588",
                    "source_instance_id": "PROC-SEA",
                    "source_dingtalk_url": "",
                    "extra_json": (
                        '{"source":"dingtalk_oa_logistics","linked_purchase_approvals":['
                        '{"approval_no":"202604150041000081318","source_instance_id":"PROC-PURCHASE-001"}'
                        "]}"
                    ),
                }
            return None

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype == "Overseas Cost Item":
                return [
                    {
                        "name": "ITEM-001",
                        "row_no": 1,
                        "material_code": "YL000097",
                        "product_name": "TPU原料 HF-8695AU",
                        "spec_model": "HF-8695AU",
                        "unit_price": 0.0,
                        "purchase_currency": "",
                        "goods_value": 0.0,
                    },
                    {
                        "name": "ITEM-002",
                        "row_no": 2,
                        "material_code": "YL000058",
                        "product_name": "副牌PC透明 LUXI",
                        "spec_model": "LUXI",
                        "unit_price": 2.1,
                        "purchase_currency": "人民币RMB",
                        "goods_value": 100,
                    },
                ]
            return []

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)

    result = preview_linked_purchase_expense_oa(
        batch_name="FSCU8486789",
        purchase_summaries_json=(
            '[{"source_approval_no":"202604150041000081318","source_instance_id":"PROC-PURCHASE-001",'
            '"purchase_currency":"人民币RMB","mapped_preview_items":['
            '{"material_code":"YL000097","product_name":"TPU原料 HF-8695AU","spec_model":"HF-8695AU",'
            '"unit_price":2.9,"goods_value":29000,"purchase_currency":"人民币RMB","source_type":"PURCHASE_EXPENSE_OA"},'
            '{"material_code":"YL000058","product_name":"副牌PC透明 LUXI","spec_model":"副牌/高透PC/打暗甲PC用 LUXI",'
            '"unit_price":2.35,"goods_value":11750,"purchase_currency":"人民币RMB","source_type":"PURCHASE_EXPENSE_OA"}'
            "]}]"
        ),
    )

    assert result["ok"] is True
    assert result["linked_purchase_count"] == 1
    assert result["purchase_summaries"][0]["can_open"] is True
    assert result["purchase_summaries"][0]["open_url"].startswith("dingtalk://")
    assert result["writeback_preview"]["matched_count"] == 2
    assert result["writeback_preview"]["fillable_row_count"] == 1
    assert result["writeback_preview"]["writable_row_count"] == 2
    assert result["writeback_preview"]["conflict_row_count"] == 1
    first_changes = result["writeback_preview"]["matched_rows"][0]["business_changes"]
    second_changes = result["writeback_preview"]["matched_rows"][1]["business_changes"]
    assert {change["status"] for change in first_changes} == {"fillable"}
    assert {change["field_label"] for change in first_changes} >= {"单价Precio", "总金额Monto Total"}
    assert any(change["status"] == "conflict" for change in second_changes)


def test_apply_linked_purchase_expense_fillable_fields_writes_matched_conflicts(monkeypatch) -> None:
    from overseas_costing.services import import_service

    class FakeItemDoc:
        def __init__(self, **values):
            self.__dict__.update(values)
            self.save_count = 0

        def save(self, **_kwargs):
            self.save_count += 1

    class FakeAuditDoc:
        def __init__(self, payload):
            self.payload = payload
            self.name = f"AUDIT-{len(audit_payloads) + 1}"

        def insert(self, **_kwargs):
            audit_payloads.append(self.payload)
            return self

    items = {
        "ITEM-001": FakeItemDoc(
            name="ITEM-001",
            row_no=1,
            material_code="YL000097",
            product_name="TPU原料 HF-8695AU",
            spec_model="HF-8695AU",
            unit_price=0.0,
            purchase_currency="",
            goods_value=0.0,
        ),
        "ITEM-002": FakeItemDoc(
            name="ITEM-002",
            row_no=2,
            material_code="YL000058",
            product_name="副牌PC透明 LUXI",
            spec_model="LUXI",
            unit_price=2.1,
            purchase_currency="人民币RMB",
            goods_value=100,
        ),
    }
    batch_updates = {}
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Batch" and name_or_filters == "FSCU8486789":
                return {"name": "BATCH-DOC"} if as_dict else "BATCH-DOC"
            if doctype == "Overseas Cost Batch" and name_or_filters == "BATCH-DOC":
                if fields == ["current_version"]:
                    return {"current_version": "VER-DOC"}
                return {
                    "name": "BATCH-DOC",
                    "batch_no": "FSCU8486789",
                    "extra_json": (
                        '{"source":"dingtalk_oa_logistics","linked_purchase_approvals":['
                        '{"approval_no":"202604150041000081318","source_instance_id":"PROC-PURCHASE-001"}'
                        "]}"
                    ),
                }
            return None

        @staticmethod
        def set_value(doctype, name, fieldname, value, **_kwargs):
            batch_updates[(doctype, name, fieldname)] = value

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype != "Overseas Cost Item":
                return []
            return [
                {
                    "name": item.name,
                    "row_no": item.row_no,
                    "material_code": item.material_code,
                    "product_name": item.product_name,
                    "spec_model": item.spec_model,
                    "unit_price": item.unit_price,
                    "purchase_currency": item.purchase_currency,
                    "goods_value": item.goods_value,
                }
                for item in items.values()
            ]

        @staticmethod
        def get_doc(*args):
            if len(args) == 2 and args[0] == "Overseas Cost Item":
                return items[args[1]]
            if len(args) == 1 and isinstance(args[0], dict):
                return FakeAuditDoc(args[0])
            raise AssertionError(args)

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)

    result = apply_linked_purchase_expense_fillable_fields(
        batch_name="FSCU8486789",
        purchase_summaries_json=(
            '[{"source_approval_no":"202604150041000081318","source_instance_id":"PROC-PURCHASE-001",'
            '"purchase_currency":"人民币RMB","mapped_preview_items":['
            '{"material_code":"YL000097","product_name":"TPU原料 HF-8695AU","spec_model":"HF-8695AU",'
            '"unit_price":2.9,"goods_value":29000,"purchase_currency":"人民币RMB","source_type":"PURCHASE_EXPENSE_OA"},'
            '{"material_code":"YL000058","product_name":"副牌PC透明 LUXI","spec_model":"LUXI",'
            '"unit_price":2.35,"goods_value":11750,"purchase_currency":"人民币RMB","source_type":"PURCHASE_EXPENSE_OA"}'
            "]}]"
        ),
    )

    assert result["ok"] is True
    assert result["updated_count"] == 2
    assert result["changed_field_count"] == 5
    assert items["ITEM-001"].unit_price == 2.9
    assert items["ITEM-001"].purchase_currency == "人民币RMB"
    assert items["ITEM-001"].goods_value == 29000
    assert items["ITEM-002"].unit_price == 2.35
    assert items["ITEM-002"].goods_value == 11750
    assert batch_updates[("Overseas Cost Batch", "BATCH-DOC", "status")] == "Dirty"
    assert commit_count["value"] == 1
    assert len(audit_payloads) == 5


def test_apply_linked_purchase_expense_aggregates_duplicate_target_rows(monkeypatch) -> None:
    from overseas_costing.services import import_service

    class FakeItemDoc:
        def __init__(self, **values):
            self.__dict__.update(values)
            self.save_count = 0

        def save(self, **_kwargs):
            self.save_count += 1

    item = FakeItemDoc(
        name="ITEM-001",
        row_no=1,
        material_code="YL00060",
        product_name="TPU原料 HF-1190A-8",
        spec_model="HF-1190A-8",
        quantity=15000,
        unit_price=0.0,
        purchase_currency="",
        goods_value=0.0,
    )
    batch_updates = {}
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeAuditDoc:
        def __init__(self, payload):
            self.payload = payload
            self.name = f"AUDIT-{len(audit_payloads) + 1}"

        def insert(self, **_kwargs):
            audit_payloads.append(self.payload)
            return self

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Batch" and name_or_filters == "FSCU8486789":
                return {"name": "BATCH-DOC"} if as_dict else "BATCH-DOC"
            if doctype == "Overseas Cost Batch" and name_or_filters == "BATCH-DOC":
                if fields == ["current_version"]:
                    return {"current_version": "VER-DOC"}
                return {
                    "name": "BATCH-DOC",
                    "batch_no": "FSCU8486789",
                    "extra_json": (
                        '{"source":"dingtalk_oa_logistics","linked_purchase_approvals":['
                        '{"approval_no":"202604300000000596348","source_instance_id":"PROC-PURCHASE-001"}'
                        "]}"
                    ),
                }
            return None

        @staticmethod
        def set_value(doctype, name, fieldname, value, **_kwargs):
            batch_updates[(doctype, name, fieldname)] = value

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype != "Overseas Cost Item":
                return []
            return [
                {
                    "name": item.name,
                    "row_no": item.row_no,
                    "material_code": item.material_code,
                        "product_name": item.product_name,
                        "spec_model": item.spec_model,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "purchase_currency": item.purchase_currency,
                        "goods_value": item.goods_value,
                }
            ]

        @staticmethod
        def get_doc(*args):
            if len(args) == 2 and args[0] == "Overseas Cost Item":
                return item
            if len(args) == 1 and isinstance(args[0], dict):
                return FakeAuditDoc(args[0])
            raise AssertionError(args)

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)

    result = apply_linked_purchase_expense_fillable_fields(
        batch_name="FSCU8486789",
        purchase_summaries_json=(
            '[{"source_approval_no":"202604300000000596348","source_instance_id":"PROC-PURCHASE-001",'
                '"purchase_currency":"美元Dólar","mapped_preview_items":['
                '{"material_code":"YL00060","product_name":"原料TPU","spec_model":"HF-1190A-1",'
                '"quantity":5000,"unit_price":2.35,"goods_value":11750,"purchase_currency":"美元Dólar","source_type":"PURCHASE_EXPENSE_OA"},'
                '{"material_code":"YL00060","product_name":"原料TPU","spec_model":"HF-1190A-1",'
                '"quantity":10500,"unit_price":2.2,"goods_value":23100,"purchase_currency":"美元Dólar","source_type":"PURCHASE_EXPENSE_OA"}'
                "]}]"
            ),
        )

    assert result["ok"] is True
    assert result["updated_count"] == 1
    assert result["skipped_count"] == 0
    assert item.unit_price == pytest.approx((34850 / 15500) * import_service.DEFAULT_FX_USD_TO_RMB)
    assert item.purchase_currency == "美元Dólar"
    assert item.goods_value == pytest.approx((34850 / 15500) * import_service.DEFAULT_FX_USD_TO_RMB * 15000)
    assert batch_updates[("Overseas Cost Batch", "BATCH-DOC", "status")] == "Dirty"
    assert commit_count["value"] == 1
    assert len(audit_payloads) == 3


def test_list_oa_form_attachments_returns_structured_records(monkeypatch) -> None:
    from overseas_costing.services import import_service

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fieldname=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Batch" and name_or_filters == "FSCU8486789":
                return {"name": "BATCH-DOC"} if as_dict else "BATCH-DOC"
            return None

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype != "Overseas Cost Attachment":
                return []
            return [
                {
                    "name": "ATTACH-001",
                    "batch": "BATCH-DOC",
                    "version": "VER-DOC",
                    "source_type": "OA",
                    "attachment_type": "Packing List",
                    "source_doc_no": "202607220001::FILE-001",
                    "file_name": "装箱单.xlsx",
                    "file_url": "",
                    "parse_status": "Queued",
                    "parse_result_json": attachment_parse_service._json_dumps(
                        {
                            "source_field": "Adjunto物品清单/运费报价等附件信息",
                            "file_id": "FILE-001",
                            "space_id": "SPACE-001",
                            "file_ext": "xlsx",
                            "comment_attachments_included": False,
                        }
                    ),
                    "mapped_result_json": attachment_parse_service._json_dumps(
                        {"parse_targets": ["actual_shipped_qty", "gross_weight_kg", "volume_m3"]}
                    ),
                    "remark": "钉钉发起表单附件已登记，等待下载和解析；评论附件暂不导入。",
                }
            ]

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)

    result = list_oa_form_attachments(batch_name="FSCU8486789")

    assert result["ok"] is True
    assert result["comment_attachments_included"] is False
    assert result["total"] == 1
    assert result["items"][0]["file_name"] == "装箱单.xlsx"
    assert result["items"][0]["file_id"] == "FILE-001"
    assert result["items"][0]["can_download"] is True
    assert result["items"][0]["parse_targets"] == ["actual_shipped_qty", "gross_weight_kg", "volume_m3"]


def test_download_oa_form_attachment_saves_file_url_and_keeps_trace(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics
    from overseas_costing.services import import_service

    commit_count = {"value": 0}

    class FakeAttachmentDoc:
        name = "ATTACH-001"
        source_type = "OA"
        attachment_type = "Packing List"
        file_name = "packing.xlsx"
        file_url = ""
        parse_status = "Queued"
        remark = ""
        parse_result_json = json.dumps(
            {
                "source": "dingtalk_oa_form_attachment",
                "instance_id": "PROC-SEA-001",
                "file_id": "FILE-001",
                "space_id": "SPACE-001",
                "raw_attachment": {"fileName": "packing.xlsx", "fileId": "FILE-001"},
            },
            ensure_ascii=False,
        )

        def save(self, **_kwargs):
            return self

    attachment_doc = FakeAttachmentDoc()

    class FakeDB:
        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_doc(*args):
            if args == ("Overseas Cost Attachment", "ATTACH-001"):
                return attachment_doc
            raise AssertionError(args)

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)
    monkeypatch.setattr(import_service, "_resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setattr(import_oa_logistics, "load_env_file", lambda _path: _path)
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN-001")
    monkeypatch.setattr(
        import_oa_logistics,
        "get_process_attachment_download_url",
        lambda **_kwargs: {"download_uri": "https://download.example.com/packing.xlsx"},
    )
    monkeypatch.setattr(
        import_service,
        "_fetch_dingtalk_attachment_content",
        lambda _download_uri: (
            b"excel-bytes",
            {
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content_length": 11,
            },
        ),
    )
    monkeypatch.setattr(
        import_service,
        "_save_content_as_frappe_file",
        lambda **_kwargs: {"file_url": "/private/files/packing.xlsx"},
    )

    result = download_oa_form_attachment("ATTACH-001")
    updated_snapshot = json.loads(attachment_doc.parse_result_json)

    assert result["ok"] is True
    assert result["downloaded"] is True
    assert result["file_url"] == "/private/files/packing.xlsx"
    assert attachment_doc.file_url == "/private/files/packing.xlsx"
    assert attachment_doc.parse_status == "Queued"
    assert updated_snapshot["download"]["file_id"] == "FILE-001"
    assert commit_count["value"] == 1


def test_save_large_content_as_private_file_registers_file_doc(monkeypatch) -> None:
    from overseas_costing.services import import_service

    inserted_docs: list[dict] = []
    site_root = Path("tmp_large_file_test_site").resolve()
    if site_root.exists():
        shutil.rmtree(site_root)

    class FakeFileDoc:
        def __init__(self, payload):
            self.payload = payload
            self.file_url = payload["file_url"]

        def insert(self, **_kwargs):
            inserted_docs.append(self.payload)
            return self

    class FakeFrappe:
        @staticmethod
        def get_site_path(*parts):
            return str(site_root.joinpath(*parts))

        @staticmethod
        def get_doc(payload):
            return FakeFileDoc(payload)

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)

    try:
        result = import_service._save_large_content_as_private_file(
            file_name='CI&PL:测试?.xlsx',
            content=b"large-excel-bytes",
            attached_to_name="ATTACH-001",
        )

        assert result.file_url.startswith("/private/files/")
        assert (site_root / "private" / "files" / Path(result.file_url).name).read_bytes() == b"large-excel-bytes"
        assert inserted_docs[0]["doctype"] == "File"
        assert inserted_docs[0]["attached_to_doctype"] == "Overseas Cost Attachment"
        assert inserted_docs[0]["attached_to_name"] == "ATTACH-001"
        assert ":" not in inserted_docs[0]["file_name"]
        assert "?" not in inserted_docs[0]["file_name"]
    finally:
        if site_root.exists():
            shutil.rmtree(site_root)


def test_parse_oa_packing_list_attachments_only_handles_excel_packing_lists(monkeypatch) -> None:
    from overseas_costing.services import import_service

    rows = [
        {
            "name": "ATTACH-XLSX",
            "batch": "BATCH-DOC",
            "version": "VER-DOC",
            "source_type": "OA",
            "attachment_type": "Packing List",
            "source_doc_no": "OA-001::FILE-XLSX",
            "file_name": "CI&PL.xlsx",
            "file_url": "",
            "parse_status": "Queued",
            "parse_result_json": json.dumps({"file_id": "FILE-XLSX", "file_ext": "xlsx"}, ensure_ascii=False),
            "mapped_result_json": json.dumps({"parse_targets": ["actual_shipped_qty", "gross_weight_kg"]}, ensure_ascii=False),
        },
        {
            "name": "ATTACH-PDF",
            "batch": "BATCH-DOC",
            "version": "VER-DOC",
            "source_type": "OA",
            "attachment_type": "Packing List",
            "source_doc_no": "OA-001::FILE-PDF",
            "file_name": "装箱单.pdf",
            "file_url": "",
            "parse_status": "Queued",
            "parse_result_json": json.dumps({"file_id": "FILE-PDF", "file_ext": "pdf"}, ensure_ascii=False),
            "mapped_result_json": json.dumps({"parse_targets": ["actual_shipped_qty"]}, ensure_ascii=False),
        },
        {
            "name": "ATTACH-PARSED",
            "batch": "BATCH-DOC",
            "version": "VER-DOC",
            "source_type": "OA",
            "attachment_type": "Packing List",
            "source_doc_no": "OA-001::FILE-PARSED",
            "file_name": "已解析装箱单.xlsx",
            "file_url": "/private/files/parsed.xlsx",
            "parse_status": "Parsed",
            "parse_result_json": json.dumps({"file_id": "FILE-PARSED", "file_ext": "xlsx"}, ensure_ascii=False),
            "mapped_result_json": json.dumps({"parse_targets": ["actual_shipped_qty"]}, ensure_ascii=False),
        },
    ]

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **_kwargs):
            assert doctype == "Overseas Cost Attachment"
            return rows

    download_calls: list[str] = []
    parse_calls: list[dict] = []

    def fake_download(attachment_name, **_kwargs):
        download_calls.append(attachment_name)
        return {
            "ok": True,
            "downloaded": True,
            "attachment_name": attachment_name,
            "file_url": "/private/files/CI&PL.xlsx",
            "message": "已下载",
        }

    def fake_apply(**kwargs):
        parse_calls.append(kwargs)
        return {
            "ok": True,
            "batch_doc_name": kwargs["batch_name"],
            "version_name": kwargs["version_name"],
            "updated_count": 2,
            "changed_field_count": 4,
            "skipped_count": 0,
            "conflict_row_count": 0,
            "unmatched_count": 1,
            "ambiguous_count": 0,
            "attachment_marked_parsed": True,
            "message": "已解析",
        }

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)
    monkeypatch.setattr(import_service, "download_oa_form_attachment", fake_download)
    monkeypatch.setattr(import_service, "apply_packing_list_fillable_fields", fake_apply)

    result = parse_oa_packing_list_attachments(recalculate=False)

    assert result["ok"] is True
    assert result["scanned_count"] == 3
    assert result["downloaded_count"] == 1
    assert result["parsed_count"] == 1
    assert result["updated_count"] == 2
    assert result["changed_field_count"] == 4
    assert result["skipped_count"] == 2
    assert download_calls == ["ATTACH-XLSX"]
    assert parse_calls[0]["attachment_name"] == "ATTACH-XLSX"
    assert any(item["attachment_name"] == "ATTACH-PDF" and item["action"] == "skipped" for item in result["items"])


def test_parse_oa_packing_list_attachments_summarizes_dingtalk_permission_error(monkeypatch) -> None:
    from overseas_costing.services import import_service

    rows = [
        {
            "name": "ATTACH-XLSX",
            "batch": "BATCH-DOC",
            "version": "VER-DOC",
            "source_type": "OA",
            "attachment_type": "Packing List",
            "source_doc_no": "OA-001::FILE-XLSX",
            "file_name": "CI&PL.xlsx",
            "file_url": "",
            "parse_status": "Queued",
            "parse_result_json": json.dumps({"file_id": "FILE-XLSX", "file_ext": "xlsx"}, ensure_ascii=False),
            "mapped_result_json": json.dumps({"parse_targets": ["actual_shipped_qty"]}, ensure_ascii=False),
        }
    ]

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **_kwargs):
            assert doctype == "Overseas Cost Attachment"
            return rows

    def fake_download(_attachment_name, **_kwargs):
        return {
            "ok": False,
            "message": "钉钉接口 HTTP 403：AccessTokenPermissionDenied，应用尚未开通所需的权限：[Workflow.Instance.Write]",
        }

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)
    monkeypatch.setattr(import_service, "download_oa_form_attachment", fake_download)

    result = parse_oa_packing_list_attachments(recalculate=False)

    assert result["ok"] is False
    assert result["failed_count"] == 1
    assert result["permission_blocked_count"] == 1
    assert result["permission_scopes"] == ["Workflow.Instance.Write"]
    assert result["items"][0]["error_type"] == "dingtalk_permission"
    assert "缺少 Workflow.Instance.Write 权限" in result["message"]


def test_parse_oa_packing_list_attachments_stops_repeated_downloads_after_permission_error(monkeypatch) -> None:
    from overseas_costing.services import import_service

    rows = [
        {
            "name": "ATTACH-XLSX-1",
            "batch": "BATCH-DOC",
            "version": "VER-DOC",
            "source_type": "OA",
            "attachment_type": "Packing List",
            "file_name": "CI&PL-1.xlsx",
            "file_url": "",
            "parse_status": "Queued",
            "parse_result_json": json.dumps({"file_id": "FILE-1", "file_ext": "xlsx"}, ensure_ascii=False),
            "mapped_result_json": json.dumps({"parse_targets": ["actual_shipped_qty"]}, ensure_ascii=False),
        },
        {
            "name": "ATTACH-XLSX-2",
            "batch": "BATCH-DOC",
            "version": "VER-DOC",
            "source_type": "OA",
            "attachment_type": "Packing List",
            "file_name": "CI&PL-2.xlsx",
            "file_url": "",
            "parse_status": "Queued",
            "parse_result_json": json.dumps({"file_id": "FILE-2", "file_ext": "xlsx"}, ensure_ascii=False),
            "mapped_result_json": json.dumps({"parse_targets": ["actual_shipped_qty"]}, ensure_ascii=False),
        },
    ]

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **_kwargs):
            assert doctype == "Overseas Cost Attachment"
            return rows

    download_calls: list[str] = []

    def fake_download(attachment_name, **_kwargs):
        download_calls.append(attachment_name)
        return {
            "ok": False,
            "message": "钉钉接口 HTTP 403：AccessTokenPermissionDenied，应用尚未开通所需的权限：[Workflow.Instance.Write]",
        }

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)
    monkeypatch.setattr(import_service, "download_oa_form_attachment", fake_download)

    result = parse_oa_packing_list_attachments(recalculate=False)

    assert download_calls == ["ATTACH-XLSX-1"]
    assert result["failed_count"] == 1
    assert result["permission_blocked_count"] == 2
    assert result["items"][1]["action"] == "blocked"
    assert result["items"][1]["error_type"] == "dingtalk_permission"
    assert "暂不重复请求下载" in result["items"][1]["reason"]


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


def test_preview_packing_list_attachment_resolves_file_url_by_keyword(monkeypatch) -> None:
    from overseas_costing.services import import_service

    calls: list[dict] = []

    def fake_resolve_excel_file_path(**kwargs):
        calls.append(kwargs)
        return Path("packing.xlsx")

    def fake_parse(_path):
        return (
            {"sourceSheet": "CI&PL", "parser": "oa_attachment_detail"},
            [
                {
                    "id": "PO-001",
                    "sourceSheet": "CI&PL",
                    "sourceTemplate": "oa_attachment_detail",
                    "items": [
                        [
                            "YL000098",
                            "TPU",
                            None,
                            5000,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            None,
                            {"actualShippedQty": 5000, "grossWeightKg": 1200},
                        ]
                    ],
                }
            ],
        )

    monkeypatch.setattr(import_service, "_resolve_excel_file_path", fake_resolve_excel_file_path)
    monkeypatch.setattr(import_service, "parse_yuewei_excel_workbook", fake_parse)

    result = preview_packing_list_attachment(batch_name="BATCH-002", file_url="/private/files/packing.xlsx")

    assert result["ok"] is True
    assert calls == [{"file_url": "/private/files/packing.xlsx"}]
    assert result["mapped_preview_items"][0]["actual_shipped_qty"] == 5000


def test_apply_packing_list_fillable_fields_skips_conflicts(monkeypatch) -> None:
    from overseas_costing.services import import_service

    class FakeItemDoc:
        def __init__(self, **values):
            self.__dict__.update(values)
            self.save_count = 0

        def save(self, **_kwargs):
            self.save_count += 1

    class FakeAuditDoc:
        def __init__(self, payload):
            self.payload = payload
            self.name = f"AUDIT-{len(audit_payloads) + 1}"

        def insert(self, **_kwargs):
            audit_payloads.append(self.payload)
            return self

    items = {
        "ITEM-001": FakeItemDoc(
            name="ITEM-001",
            row_no=1,
            material_code="CW000175",
            product_name="钢化膜",
            spec_model="透明",
            actual_shipped_qty=0,
            gross_weight_kg=0,
            volume_m3=0,
            volume_weight_kg=0,
            chargeable_weight_kg=0,
        ),
        "ITEM-002": FakeItemDoc(
            name="ITEM-002",
            row_no=2,
            material_code="CW000176",
            product_name="钢化膜",
            spec_model="磨砂",
            actual_shipped_qty=200,
            gross_weight_kg=10,
            volume_m3=0.2,
            volume_weight_kg=0,
            chargeable_weight_kg=0,
        ),
    }
    batch_updates = {}
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Batch" and name_or_filters == "BATCH-PACKING":
                if fields == ["current_version"]:
                    return {"current_version": "VER-PACKING"}
                return {"name": "BATCH-PACKING"} if as_dict else "BATCH-PACKING"
            return None

        @staticmethod
        def set_value(doctype, name, fieldname, value, **_kwargs):
            batch_updates[(doctype, name, fieldname)] = value

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype != "Overseas Cost Item":
                return []
            return [
                {
                    "name": item.name,
                    "row_no": item.row_no,
                    "material_code": item.material_code,
                    "product_name": item.product_name,
                    "spec_model": item.spec_model,
                    "actual_shipped_qty": item.actual_shipped_qty,
                    "gross_weight_kg": item.gross_weight_kg,
                    "volume_m3": item.volume_m3,
                    "volume_weight_kg": item.volume_weight_kg,
                    "chargeable_weight_kg": item.chargeable_weight_kg,
                }
                for item in items.values()
            ]

        @staticmethod
        def get_doc(*args):
            if len(args) == 2 and args[0] == "Overseas Cost Item":
                return items[args[1]]
            if len(args) == 1 and isinstance(args[0], dict):
                return FakeAuditDoc(args[0])
            raise AssertionError(args)

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)
    rows_json = (
        '[{"物料编码":"CW000175","物料名称":"钢化膜","规格型号":"透明","实际发货数量":400,"毛重KG":32.5,"体积m3":0.21},'
        '{"物料编码":"CW000176","物料名称":"钢化膜","规格型号":"磨砂","实际发货数量":220,"毛重KG":12,"体积m3":0.22}]'
    )

    preview = preview_packing_list_attachment(
        batch_name="BATCH-PACKING",
        attachment_name="packing.xlsx",
        sheet_rows_json=rows_json,
    )
    result = apply_packing_list_fillable_fields(
        batch_name="BATCH-PACKING",
        attachment_name="ATT-PACKING",
        sheet_rows_json=rows_json,
    )

    assert preview["writeback_preview"]["fillable_row_count"] == 1
    assert preview["writeback_preview"]["conflict_row_count"] == 1
    assert result["ok"] is True
    assert result["updated_count"] == 1
    assert items["ITEM-001"].actual_shipped_qty == 400
    assert items["ITEM-001"].gross_weight_kg == 32.5
    assert items["ITEM-001"].volume_m3 == 0.21
    assert items["ITEM-002"].actual_shipped_qty == 200
    assert items["ITEM-002"].gross_weight_kg == 10
    assert batch_updates[("Overseas Cost Batch", "BATCH-PACKING", "status")] == "Dirty"
    assert batch_updates[("Overseas Cost Attachment", "ATT-PACKING", "parse_status")] == "Parsed"
    assert result["attachment_marked_parsed"] is True
    assert commit_count["value"] == 1
    assert len(audit_payloads) == 3


def test_apply_packing_list_duplicate_rows_matches_by_quantity(monkeypatch) -> None:
    from overseas_costing.services import import_service

    class FakeItemDoc:
        def __init__(self, **values):
            self.__dict__.update(values)

        def save(self, **_kwargs):
            return self

    class FakeAuditDoc:
        def __init__(self, payload):
            self.payload = payload

        def insert(self, **_kwargs):
            audit_payloads.append(self.payload)
            return self

    items = {
        "ITEM-ROW-2": FakeItemDoc(
            name="ITEM-ROW-2",
            row_no=2,
            material_code="",
            product_name="超队指环扣",
            spec_model="",
            quantity=86400,
            actual_shipped_qty=0,
            gross_weight_kg=0,
            volume_m3=0,
            volume_weight_kg=0,
            chargeable_weight_kg=0,
        ),
        "ITEM-ROW-3": FakeItemDoc(
            name="ITEM-ROW-3",
            row_no=3,
            material_code="",
            product_name="超队指环扣",
            spec_model="",
            quantity=3600,
            actual_shipped_qty=0,
            gross_weight_kg=0,
            volume_m3=0,
            volume_weight_kg=0,
            chargeable_weight_kg=0,
        ),
    }
    batch_updates = {}
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Batch" and name_or_filters == "BATCH-PACKING":
                if fields == ["current_version"]:
                    return {"current_version": "VER-PACKING"}
                return {"name": "BATCH-PACKING"} if as_dict else "BATCH-PACKING"
            return None

        @staticmethod
        def set_value(doctype, name, fieldname, value, **_kwargs):
            batch_updates[(doctype, name, fieldname)] = value

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype == "Overseas Cost Version":
                return []
            if doctype != "Overseas Cost Item":
                return []
            return [
                {
                    "name": item.name,
                    "row_no": item.row_no,
                    "material_code": item.material_code,
                    "product_name": item.product_name,
                    "spec_model": item.spec_model,
                    "quantity": item.quantity,
                    "actual_shipped_qty": item.actual_shipped_qty,
                    "gross_weight_kg": item.gross_weight_kg,
                    "volume_m3": item.volume_m3,
                    "volume_weight_kg": item.volume_weight_kg,
                    "chargeable_weight_kg": item.chargeable_weight_kg,
                }
                for item in items.values()
            ]

        @staticmethod
        def get_doc(*args):
            if len(args) == 2 and args[0] == "Overseas Cost Item":
                return items[args[1]]
            if len(args) == 1 and isinstance(args[0], dict):
                return FakeAuditDoc(args[0])
            raise AssertionError(args)

    monkeypatch.setattr(import_service, "frappe", FakeFrappe)
    rows_json = (
        '[{"物料名称":"超队指环扣","数量":86400,"毛重KG":19.4,"体积m3":0.02001},'
        '{"物料名称":"超队指环扣","数量":3600,"毛重KG":14.5,"体积m3":0.00864}]'
    )

    preview = preview_packing_list_attachment(
        batch_name="BATCH-PACKING",
        attachment_name="packing.xlsx",
        sheet_rows_json=rows_json,
    )
    result = apply_packing_list_fillable_fields(
        batch_name="BATCH-PACKING",
        attachment_name="ATT-PACKING",
        sheet_rows_json=rows_json,
    )

    assert preview["writeback_preview"]["matched_count"] == 2
    assert preview["writeback_preview"]["ambiguous_count"] == 0
    assert preview["writeback_preview"]["fillable_row_count"] == 2
    assert result["ok"] is True
    assert result["updated_count"] == 2
    assert items["ITEM-ROW-2"].actual_shipped_qty == 86400
    assert items["ITEM-ROW-2"].gross_weight_kg == 19.4
    assert items["ITEM-ROW-3"].actual_shipped_qty == 3600
    assert items["ITEM-ROW-3"].gross_weight_kg == 14.5
    assert batch_updates[("Overseas Cost Attachment", "ATT-PACKING", "mapped_result_json")]
    assert commit_count["value"] == 1
    assert len(audit_payloads) == 6


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


def test_save_tax_certificate_parse_result_updates_version_fx_from_voucher(monkeypatch) -> None:
    version_row = {"fx_usd_to_rmb": 0, "fx_rmb_to_mxn": 2.6, "remark": ""}
    batch_updates = {}
    attachment_payloads = []
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeDoc:
        def __init__(self, payload):
            self.__dict__.update(payload)
            self.payload = payload
            self.name = payload.get("name") or f"DOC-{len(attachment_payloads) + len(audit_payloads) + 1}"

        def insert(self, **_kwargs):
            if self.payload.get("doctype") == "Overseas Cost Attachment":
                attachment_payloads.append(self.payload)
            elif self.payload.get("doctype") == "Overseas Cost Audit Log":
                audit_payloads.append(self.payload)
            return self

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Version" and name_or_filters == "VER-001":
                if as_dict:
                    return dict(version_row)
                return version_row.get(fields)
            return None

        @staticmethod
        def set_value(doctype, name, fieldname, value=None, **_kwargs):
            if doctype == "Overseas Cost Version" and name == "VER-001":
                updates = fieldname if isinstance(fieldname, dict) else {fieldname: value}
                version_row.update(updates)
            else:
                batch_updates[(doctype, name, json.dumps(fieldname, ensure_ascii=False, default=str))] = value

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeFrappe:
        db = FakeDB()

        class local:
            site = "development.localhost"

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, filters=None, fields=None, **_kwargs):
            if doctype == "Overseas Cost Batch":
                values = {
                    "name": "BATCH-001",
                    "batch_no": "HPCU5155607",
                    "customs_no": "26 16 1681 6000151",
                    "waybill_no": "HPCU5155607",
                    "container_no": "HPCU5155607",
                    "current_version": "VER-001",
                    "item_count": 2,
                    "total_goods_value": 0,
                    "estimated_total_cost_rmb": 0,
                    "actual_total_cost_rmb": 0,
                }
                if filters and any(value in {"26 16 1681 6000151", "HPCU5155607", "BATCH-001"} for value in filters.values()):
                    return [values]
                return []
            if doctype == "Overseas Cost Item":
                return []
            if doctype == "Overseas Cost Attachment":
                return []
            return []

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

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

    monkeypatch.setattr(attachment_parse_service, "frappe", FakeFrappe)

    result = attachment_parse_service.save_tax_certificate_parse_result(
        source_name="PD_MZ260108.pdf",
        text=sample_text,
        batch_name="HPCU5155607",
    )

    assert result["ok"] is True
    assert result["saved"] is True
    assert result["fx_sync"]["action"] == "updated"
    assert version_row["fx_usd_to_rmb"] == pytest.approx(17.7957 / 2.6)
    assert "PD_MZ260108.pdf" in version_row["remark"]
    assert batch_updates[("Overseas Cost Batch", "BATCH-001", '"status"')] == "Dirty"
    assert len(attachment_payloads) == 1
    assert len(audit_payloads) == 1
    assert audit_payloads[0]["field_name"] == "fx_usd_to_rmb"
    assert commit_count["value"] == 1


def test_list_tax_certificate_parse_records_returns_empty_without_frappe() -> None:
    result = list_tax_certificate_parse_records(batch_name="HPCU5155607")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["items"] == []


def test_get_tax_certificate_parse_record_requires_frappe_context() -> None:
    result = get_tax_certificate_parse_record(record_name="ATT-001")

    assert result["ok"] is False
    assert result["dry_run"] is True
    assert result["record_name"] == "ATT-001"


def test_tax_certificate_record_summary_extracts_business_fields() -> None:
    row = {
        "name": "ATT-001",
        "batch": "BATCH-001",
        "version": "VER-001",
        "source_doc_no": "26 16 1681 6000151",
        "file_name": "PD_MZ260108凭证.pdf",
        "file_url": "/private/files/PD_MZ260108凭证.pdf",
        "parse_status": "Parsed",
        "modified": "2026-07-20 10:00:00",
        "parse_result_json": attachment_parse_service._json_dumps(
            {
                "summary": {"item_count": 22, "declared_item_count": 22, "paid_total_mxn": 129883},
                "header": {"pedimento_no": "26 16 1681 6000151", "container_no": "HPCU5155607", "payment_date": "01/04/2026"},
                "validation": {"status": "passed", "status_label": "通过"},
            }
        ),
        "mapped_result_json": attachment_parse_service._json_dumps(
            {
                "status": "review",
                "status_label": "需复核",
                "batch": {"name": "BATCH-001", "batch_no": "HPCU5155607", "customs_no": "26 16 1681 6000151"},
                "system": {"system_import_tax_total_mxn": 130186},
                "difference": {"tax_total_diff_mxn": -303, "direction_label": "凭证金额低于系统"},
                "review_count": 1,
                "passed_count": 3,
            }
        ),
    }

    result = attachment_parse_service._build_tax_certificate_record_summary(row)

    assert result["name"] == "ATT-001"
    assert result["customs_no"] == "26 16 1681 6000151"
    assert result["container_no"] == "HPCU5155607"
    assert result["paid_total_mxn"] == 129883
    assert result["system_tax_total_mxn"] == 130186
    assert result["tax_total_diff_mxn"] == -303
    assert result["reconciliation_status_label"] == "需复核"


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


def test_tax_certificate_manual_resolution_can_use_voucher_total() -> None:
    result = _build_tax_certificate_manual_resolution(
        mapped_result={
            "voucher": {"paid_total_mxn": 129883},
            "system": {"system_import_tax_total_mxn": 130186},
            "difference": {"tax_total_diff_mxn": -303},
        },
        resolution_action="use_voucher",
        remark="按正式完税凭证处理",
        operator_name="tester",
    )

    assert result["ok"] is True
    resolution = result["resolution"]
    assert resolution["action_label"] == "按凭证金额为准"
    assert resolution["final_tax_total_mxn"] == 129883
    assert resolution["final_diff_vs_system_mxn"] == -303
    assert resolution["final_diff_vs_voucher_mxn"] == 0


def test_tax_certificate_manual_resolution_requires_adjusted_amount() -> None:
    result = _build_tax_certificate_manual_resolution(
        mapped_result={
            "voucher": {"paid_total_mxn": 129883},
            "system": {"system_import_tax_total_mxn": 130186},
            "difference": {"tax_total_diff_mxn": -303},
        },
        resolution_action="manual_adjust",
    )

    assert result["ok"] is False
    assert "手工调整" in result["message"]


def test_tax_certificate_manual_resolution_requires_exception_remark() -> None:
    result = _build_tax_certificate_manual_resolution(
        mapped_result={
            "voucher": {"paid_total_mxn": 129883},
            "system": {"system_import_tax_total_mxn": 130186},
            "difference": {"tax_total_diff_mxn": -303},
        },
        resolution_action="mark_exception",
    )

    assert result["ok"] is False
    assert "异常原因" in result["message"]


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
