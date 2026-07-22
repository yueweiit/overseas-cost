"""
中文用途：钉钉审批跳转工具测试。
"""

import json
import os
from pathlib import Path

from overseas_costing.utils.dingtalk import (
    build_desktop_approval_url,
    build_dingtalk_order_payload,
    build_mobile_approval_url,
    extract_dingtalk_instance_id,
)
from overseas_costing.scripts.import_oa_logistics import (
    DEFAULT_LOGISTICS_PROCESS_CODE,
    _merge_oa_extra_json,
    _sync_oa_form_attachments,
    _normalize_legacy_instance,
    build_oa_item_values_from_approval,
    build_batch_values_from_approval,
    build_purchase_expense_item_values_from_approval,
    extract_form_attachments,
    extract_oa_goods_rows,
    extract_form_fields,
    extract_linked_purchase_approvals,
    extract_purchase_expense_rows,
    is_hidden_approval_status,
    is_sea_approval,
    load_env_file,
    resolve_logistics_process_code,
    save_sea_approvals_to_erp,
    summarize_approval,
    summarize_purchase_approval,
)


def test_build_mobile_and_desktop_approval_url() -> None:
    mobile_url = build_mobile_approval_url("PROC-001")
    desktop_url = build_desktop_approval_url("PROC-001")

    assert "PROC-001" in mobile_url
    assert mobile_url.startswith("https://aflow.dingtalk.com/")
    assert desktop_url.startswith("dingtalk://dingtalkclient/page/link?url=")


def test_build_dingtalk_order_payload_prefers_desktop_protocol() -> None:
    payload = build_dingtalk_order_payload(
        batch_name="BATCH-001",
        approval_no="OA-20260709-001",
        instance_id="PROC-001",
        official_url="https://oa.dingtalk.com/approval/detail",
    )

    assert payload["approval_no"] == "OA-20260709-001"
    assert payload["instance_id"] == "PROC-001"
    assert payload["desktop_url"].startswith("dingtalk://")
    assert payload["open_url"] == payload["desktop_url"]
    assert payload["can_open"] is True


def test_build_dingtalk_order_payload_fallback_to_official_url() -> None:
    payload = build_dingtalk_order_payload(
        batch_name="BATCH-002",
        official_url="https://oa.dingtalk.com/approval/detail",
    )

    assert payload["desktop_url"] == ""
    assert payload["open_mode"] == "web_url"
    assert payload["open_url"] == "https://oa.dingtalk.com/approval/detail"


def test_extract_dingtalk_instance_id_from_pc_approval_url() -> None:
    url = (
        "https://aflow.dingtalk.com/dingtalk/web/query/pchomepage.htm?from=oflow&op=true"
        "#/plainapproval?procInstId=aR2wGNueQB-FVuGOgSAZdA04891770039043"
    )

    assert extract_dingtalk_instance_id(url) == "aR2wGNueQB-FVuGOgSAZdA04891770039043"


def test_build_dingtalk_order_payload_uses_proc_inst_id_from_official_url() -> None:
    official_url = (
        "https://aflow.dingtalk.com/dingtalk/web/query/pchomepage.htm"
        "#/plainapproval?procInstId=PROC-URL-001"
    )

    payload = build_dingtalk_order_payload(batch_name="BATCH-003", official_url=official_url)

    assert payload["instance_id"] == "PROC-URL-001"
    assert payload["open_mode"] == "desktop_protocol"
    assert payload["open_url"] == payload["desktop_url"]


def test_logistics_approval_summary_extracts_sea_trace_fields() -> None:
    instance = {
        "processInstanceId": "PROC-SEA-001",
        "businessId": "202607210001",
        "title": "国际物流 Logística Internacional",
        "status": "COMPLETED",
        "url": "https://aflow.dingtalk.com/dingtalk/web/query/pchomepage.htm#/plainapproval?procInstId=PROC-SEA-001",
        "formComponentValues": [
            {"name": "物流方式Camino Envío", "value": "海运"},
            {"name": "柜号/单号Número DE Logística", "value": "HPCU5155607"},
        ],
    }

    fields = extract_form_fields(instance)
    summary = summarize_approval(instance)

    assert is_sea_approval(fields) is True
    assert summary["source_instance_id"] == "PROC-SEA-001"
    assert summary["source_approval_no"] == "202607210001"
    assert summary["transport_mode_raw"] == "海运"
    assert summary["logistics_no"] == "HPCU5155607"
    assert summary["open_url"].startswith("dingtalk://")


def test_extract_linked_purchase_approvals_from_relate_field_ext_value() -> None:
    instance = {
        "processInstanceId": "PROC-SEA-001",
        "businessId": "202606101808000475588",
        "formComponentValues": [
            {
                "componentType": "RelateField",
                "name": "关联审批单Asociar órdenes de compra.",
                "value": (
                    '["采购支出 Gastos de compra enviado por Yadira Pérez Reyes",'
                    '"采购支出 Gastos de compra enviado por Yadira Pérez Reyes"]'
                ),
                "extValue": (
                    '{"list":['
                    '{"businessId":"202604300000000596348","procInstId":"5Qmu4-WKReWhGss44I3fyQ04891777478459"},'
                    '{"businessId":"202604150041000081318","procInstId":"xi3Aw3-rQDmc0H89KGjJmw04891776184868"}'
                    "]}"
                ),
            }
        ],
    }

    linked = extract_linked_purchase_approvals(instance)
    summary = summarize_approval(instance)

    assert len(linked) == 2
    assert linked[0]["approval_no"] == "202604300000000596348"
    assert linked[0]["source_instance_id"] == "5Qmu4-WKReWhGss44I3fyQ04891777478459"
    assert linked[0]["open_url"].startswith("dingtalk://")
    assert summary["linked_purchase_count"] == 2
    assert summary["linked_purchase_approvals"][1]["approval_no"] == "202604150041000081318"


def test_extract_form_attachments_ignores_comment_attachments() -> None:
    instance = {
        "processInstanceId": "PROC-SEA-ATTACH",
        "businessId": "202607220001",
        "formComponentValues": [
            {
                "componentType": "DDAttachment",
                "name": "Adjunto物品清单/运费报价等附件信息",
                "value": json.dumps(
                    [
                        {
                            "fileName": "2026.7.3DHL快递清单.xlsx",
                            "fileId": "FILE-001",
                            "spaceId": "SPACE-001",
                            "fileSize": 2048,
                        },
                        {
                            "fileName": "7月份燃油附加费.png",
                            "fileId": "FILE-002",
                            "spaceId": "SPACE-001",
                        },
                    ],
                    ensure_ascii=False,
                ),
            }
        ],
        "comments": [
            {
                "attachments": [
                    {"fileName": "评论里的凭证.pdf", "fileId": "COMMENT-FILE-001"},
                ]
            }
        ],
    }

    attachments = extract_form_attachments(instance)
    summary = summarize_approval(instance)
    values = build_batch_values_from_approval(
        {
            **summary,
            "transport_mode_raw": "contenedor marítimo海运整柜",
            "logistics_no": "TCLU1234567",
        }
    )
    extra = json.loads(values["extra_json"])

    assert len(attachments) == 2
    assert attachments[0]["file_name"] == "2026.7.3DHL快递清单.xlsx"
    assert attachments[0]["attachment_type"] == "Packing List"
    assert attachments[1]["attachment_type"] == "Logistics Bill"
    assert "评论里的凭证.pdf" not in [row["file_name"] for row in attachments]
    assert summary["oa_form_attachment_count"] == 2
    assert values["source_attachment_count"] == 2
    assert extra["oa_form_attachments"][0]["file_id"] == "FILE-001"


def test_extract_purchase_expense_rows_keeps_first_non_empty_currency() -> None:
    instance = {
        "processInstanceId": "PROC-PURCHASE-001",
        "businessId": "202604150041000081318",
        "title": "采购支出 Gastos de compra enviado por Yadira Pérez Reyes",
        "status": "RUNNING",
        "formComponentValues": [
            {"componentType": "DDSelectField", "name": "币种Moneda", "value": "人民币RMB"},
            {
                "componentType": "TableField",
                "name": "需求明细Desglose de los gastos",
                "value": json.dumps(
                    [
                        {
                            "rowValue": [
                                {"label": "物品名称Nombre del artículo", "value": "TPU原料 HF-8695AU"},
                                {"label": "物品编码Código", "value": "YL000097"},
                                {"label": "物品规格Especificacion", "value": "HF-8695AU"},
                                {"label": "数量Cantidad", "value": "10000"},
                                {"label": "单位Unidad", "value": "KG"},
                                {"label": "单价Precio", "value": "2.2"},
                                {"label": "总金额Monto Total", "value": "22000"},
                            ],
                            "rowNumber": "TableField_119WFD19L8R40_1",
                        }
                    ],
                    ensure_ascii=False,
                ),
            },
            {"componentType": "DDSelectField", "name": "币种Moneda", "value": None},
        ],
    }

    fields = extract_form_fields(instance)
    rows = extract_purchase_expense_rows(instance)
    mapped_items = build_purchase_expense_item_values_from_approval(instance)
    summary = summarize_purchase_approval(instance)

    assert fields["币种Moneda"] == "人民币RMB"
    assert rows[0]["币种Moneda"] == "人民币RMB"
    assert mapped_items[0]["material_code"] == "YL000097"
    assert mapped_items[0]["unit_price"] == 2.2
    assert mapped_items[0]["goods_value"] == 22000
    assert mapped_items[0]["purchase_currency"] == "人民币RMB"
    assert summary["detail_row_count"] == 1
    assert summary["mapped_preview_items"][0]["product_name"] == "TPU原料 HF-8695AU"


def test_legacy_dingtalk_instance_is_normalized_for_summary() -> None:
    legacy = _normalize_legacy_instance(
        {
            "business_id": "202607210002",
            "status": "COMPLETED",
            "form_component_values": [{"name": "物流方式Camino Envío", "value": "SEA"}],
        },
        "PROC-OLD-001",
    )
    summary = summarize_approval(legacy)

    assert legacy["processInstanceId"] == "PROC-OLD-001"
    assert summary["source_instance_id"] == "PROC-OLD-001"
    assert summary["source_approval_no"] == "202607210002"
    assert is_sea_approval(summary["form_fields"]) is True


def test_load_env_file_keeps_existing_values_by_default(monkeypatch) -> None:
    env_file = Path.cwd() / ".tmp_dingtalk_env_test"
    env_file.write_text("DINGTALK_PROCESS_CODE=FROM_FILE\nDINGTALK_LIST_API=old\n", encoding="utf-8")
    monkeypatch.setenv("DINGTALK_PROCESS_CODE", "EXISTING")

    try:
        load_env_file(str(env_file))
    finally:
        env_file.unlink(missing_ok=True)

    assert os.environ["DINGTALK_PROCESS_CODE"] == "EXISTING"
    assert os.environ["DINGTALK_LIST_API"] == "old"


def test_logistics_process_code_does_not_use_budget_process_env(monkeypatch) -> None:
    monkeypatch.setenv("DINGTALK_PROCESS_CODE", "PROC-BUDGET-001")
    monkeypatch.delenv("DINGTALK_LOGISTICS_PROCESS_CODE", raising=False)

    assert resolve_logistics_process_code() == DEFAULT_LOGISTICS_PROCESS_CODE

    monkeypatch.setenv("DINGTALK_LOGISTICS_PROCESS_CODE", "PROC-LOGISTICS-ENV")

    assert resolve_logistics_process_code() == "PROC-LOGISTICS-ENV"
    assert resolve_logistics_process_code("PROC-CLI") == "PROC-CLI"


def test_build_batch_values_from_oa_logistics_approval() -> None:
    values = build_batch_values_from_approval(
        {
            "source_approval_no": "202601291020000337788",
            "source_instance_id": "PROC-SEA-TRACE",
            "approval_title": "国际物流 Logística Internacional",
            "approval_status": "COMPLETED",
            "originator_userid": "USER-001",
            "originator_dept_id": "DEPT-001",
            "create_time": "2026-01-29T10:20Z",
            "finish_time": "2026-04-21T17:16Z",
            "transport_mode_raw": "contenedor marítimo海运整柜",
            "logistics_no": "HPCU5155607",
            "form_fields": {
                "Adjunto物品清单/运费报价等附件信息": [
                    {"fileName": "2026.1.29装箱单.xlsx", "fileId": "209810480976"}
                ]
            },
        }
    )

    assert values["batch_no"] == "HPCU5155607"
    assert values["waybill_no"] == "HPCU5155607"
    assert values["container_no"] == "HPCU5155607"
    assert values["transport_mode"] == "SEA"
    assert values["source_type"] == "oa_logistics"
    assert values["source_approval_no"] == "202601291020000337788"
    assert values["source_instance_id"] == "PROC-SEA-TRACE"
    assert values["source_attachment_count"] == 1
    assert values["source_created_at"] == "2026-01-29 10:20:00"


def test_build_batch_values_keeps_linked_purchase_approvals_in_extra_json() -> None:
    values = build_batch_values_from_approval(
        {
            "source_approval_no": "202606101808000475588",
            "source_instance_id": "PROC-SEA-TRACE",
            "approval_status": "COMPLETED",
            "transport_mode_raw": "contenedor marítimo海运整柜",
            "logistics_no": "FSCU8486789",
            "linked_purchase_approvals": [
                {
                    "approval_no": "202604300000000596348",
                    "source_instance_id": "5Qmu4-WKReWhGss44I3fyQ04891777478459",
                }
            ],
            "form_fields": {},
        }
    )

    extra = json.loads(values["extra_json"])

    assert extra["linked_purchase_approvals"][0]["approval_no"] == "202604300000000596348"


def test_merge_oa_extra_json_preserves_existing_excel_payload() -> None:
    merged = _merge_oa_extra_json(
        json.dumps({"source": "excel", "sourceSheet": "2026年YUEWEI"}, ensure_ascii=False),
        json.dumps(
            {
                "source": "dingtalk_oa_logistics",
                "transport_mode_raw": "海运",
                "linked_purchase_approvals": [{"approval_no": "202604300000000596348"}],
            },
            ensure_ascii=False,
        ),
    )

    payload = json.loads(merged)

    assert payload["source"] == "excel"
    assert payload["sourceSheet"] == "2026年YUEWEI"
    assert payload["oa_logistics_trace"]["linked_purchase_approvals"][0]["approval_no"] == "202604300000000596348"


def test_extract_oa_goods_rows_and_build_item_values() -> None:
    approval = {
        "source_approval_no": "202606101808000475588",
        "source_instance_id": "PROC-SEA-FORM",
        "transport_mode_raw": "contenedor marítimo海运整柜",
        "logistics_no": "FSCU8486789",
        "form_fields": {
            "项目proyecto": "YW ODM",
            "物料类别TIPO": "material物料",
            "货物信息Bienes": [
                {
                    "rowValue": [
                        {"label": "物料编码 Código de material", "value": "YL000097"},
                        {"label": "物料名称（中文）Nombre del material (chino)", "value": "TPU原料 HF-8695AU"},
                        {"label": "物料名称（西语）Nombre del material (español)", "value": "Elastómero de poliuretano termoplástico"},
                        {"label": "规格型号Especificación / Modelo", "value": "HF-8695AU"},
                        {"label": "数量Cantidad", "value": "10000"},
                        {"label": "单位Unidad", "value": "KG"},
                        {"label": "收件人Destinatario", "value": "Alfredo Garcia Cardenas"},
                    ],
                    "rowNumber": "TableField_1",
                }
            ],
        },
    }

    rows = extract_oa_goods_rows(approval)
    items = build_oa_item_values_from_approval(approval)

    assert rows[0]["项目proyecto"] == "YW ODM"
    assert items[0]["material_code"] == "YL000097"
    assert items[0]["product_name"] == "TPU原料 HF-8695AU"
    assert items[0]["product_name_es"] == "Elastómero de poliuretano termoplástico"
    assert items[0]["spec_model"] == "HF-8695AU"
    assert items[0]["quantity"] == 10000
    assert items[0]["unit"] == "KG"
    assert items[0]["recipient"] == "Alfredo Garcia Cardenas"
    assert items[0]["waybill_no"] == "FSCU8486789"
    assert items[0]["source_doc_no"] == "202606101808000475588"
    assert items[0]["parse_status"] == "SUCCESS"


def test_save_sea_approvals_to_erp_dry_run_returns_trace_preview() -> None:
    result = save_sea_approvals_to_erp(
        {
            "items": [
                {
                    "source_approval_no": "202601291020000337788",
                    "source_instance_id": "PROC-SEA-TRACE",
                    "approval_status": "COMPLETED",
                    "transport_mode_raw": "contenedor marítimo海运整柜",
                    "logistics_no": "HPCU5155607",
                    "form_fields": {},
                }
            ]
        }
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["valid_count"] == 1
    assert result["items"][0]["batch_no"] == "HPCU5155607"


def test_sync_oa_form_attachments_creates_attachment_records(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    inserted_attachments = []
    inserted_audits = []

    class FakeDoc:
        def __init__(self, payload):
            self.payload = dict(payload)
            self.__dict__.update(payload)
            self.name = payload.get("name") or f"DOC-{len(inserted_attachments) + len(inserted_audits) + 1}"

        def insert(self, **_kwargs):
            if self.payload.get("doctype") == "Overseas Cost Attachment":
                self.name = f"ATTACH-{len(inserted_attachments) + 1}"
                self.payload["name"] = self.name
                inserted_attachments.append(self.payload)
            elif self.payload.get("doctype") == "Overseas Cost Audit Log":
                self.name = f"AUDIT-{len(inserted_audits) + 1}"
                self.payload["name"] = self.name
                inserted_audits.append(self.payload)
            return self

        def save(self, **_kwargs):
            return self

    class FakeDB:
        @staticmethod
        def get_value(*_args, **_kwargs):
            return None

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_doc(*args):
            if len(args) == 1 and isinstance(args[0], dict):
                return FakeDoc(args[0])
            raise AssertionError(args)

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)

    result = _sync_oa_form_attachments(
        batch_name="BATCH-001",
        version_name="VER-001",
        approval_item={
            "source_approval_no": "202607220001",
            "source_instance_id": "PROC-SEA-ATTACH",
            "oa_form_attachments": [
                {
                    "source_field": "Adjunto物品清单/运费报价等附件信息",
                    "component_type": "DDAttachment",
                    "file_id": "FILE-001",
                    "space_id": "SPACE-001",
                    "file_name": "2026.7.3DHL快递清单.xlsx",
                    "file_ext": "xlsx",
                    "file_url": "",
                    "attachment_type": "Packing List",
                    "raw": {"fileName": "2026.7.3DHL快递清单.xlsx", "fileId": "FILE-001"},
                }
            ],
        },
    )

    assert result["created_count"] == 1
    assert inserted_attachments[0]["batch"] == "BATCH-001"
    assert inserted_attachments[0]["version"] == "VER-001"
    assert inserted_attachments[0]["source_type"] == "OA"
    assert inserted_attachments[0]["attachment_type"] == "Packing List"
    assert inserted_attachments[0]["file_name"] == "2026.7.3DHL快递清单.xlsx"
    assert inserted_attachments[0]["parse_status"] == "Queued"
    assert "FILE-001" in inserted_attachments[0]["source_doc_no"]
    assert json.loads(inserted_attachments[0]["parse_result_json"])["comment_attachments_included"] is False
    assert inserted_audits[0]["field_name"] == "oa_form_attachments"


def test_revoked_approval_is_skipped_when_saving_oa_trace() -> None:
    assert is_hidden_approval_status("TERMINATED") is True

    result = save_sea_approvals_to_erp(
        {
            "items": [
                {
                    "source_approval_no": "202601121441000259291",
                    "source_instance_id": "PROC-REVOKED",
                    "approval_status": "TERMINATED",
                    "transport_mode_raw": "doble despacho en aduana para transporte marítimo海运双清",
                    "logistics_no": "",
                    "form_fields": {},
                }
            ]
        }
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["valid_count"] == 0
    assert result["skipped_count"] == 1
    assert result["skipped_items"][0]["reason"] == "审批单已撤销或终止，不进入成本表格"
