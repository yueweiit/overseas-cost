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
    _recalculate_after_purchase_sync,
    _sync_oa_form_attachments,
    _sync_oa_logistics_allocation_rule,
    _sync_linked_purchase_fields,
    _normalize_legacy_instance,
    build_oa_item_values_from_approval,
    build_batch_values_from_approval,
    build_purchase_expense_item_values_from_approval,
    extract_logistics_fee_from_approval,
    extract_logistics_quote_candidates_from_approval,
    extract_logistics_text_summary_from_approval,
    extract_form_attachments,
    extract_oa_goods_rows,
    extract_form_fields,
    extract_linked_purchase_approvals,
    extract_purchase_expense_rows,
    get_access_token,
    get_process_attachment_download_url,
    is_completed_approval_status,
    is_hidden_approval_status,
    is_sea_approval,
    load_env_file,
    refresh_missing_oa_finished_times,
    refresh_oa_logistics_detail,
    resolve_logistics_process_code,
    resolve_purchase_process_code,
    refresh_existing_oa_logistics_details,
    pull_purchase_expense_approvals,
    preview_purchase_expenses_from_process,
    save_sea_approvals_to_erp,
    sync_existing_oa_finished_times,
    sync_purchase_expenses_from_process,
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


def test_get_process_attachment_download_url_uses_process_instance_and_file_id(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return {"result": {"downloadUri": "https://download.example.com/packing.xlsx"}}

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)

    result = get_process_attachment_download_url(
        token="TOKEN-001",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        user_id="USER-001",
        api_style="new",
    )

    assert result["download_uri"] == "https://download.example.com/packing.xlsx"
    assert calls[0]["method"] == "POST"
    assert calls[0]["token"] == "TOKEN-001"
    assert calls[0]["payload"] == {"processInstanceId": "PROC-SEA-001", "fileId": "FILE-001"}


def test_get_process_attachment_download_url_uses_legacy_api_for_legacy_credentials(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return {"errcode": 0, "result": {"download_uri": "https://download.example.com/packing.xlsx"}}

    monkeypatch.delenv("DINGTALK_CORP_ID", raising=False)
    monkeypatch.delenv("DINGTALK_CLIENT_ID", raising=False)
    monkeypatch.setenv("DINGTALK_APP_KEY", "legacy-app-key")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "legacy-app-secret")
    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)

    result = get_process_attachment_download_url(
        token="TOKEN-001",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        user_id="USER-001",
    )

    assert result["api_style"] == "legacy"
    assert result["download_uri"] == "https://download.example.com/packing.xlsx"
    assert "/topapi/processinstance/file/url/get?access_token=TOKEN-001" in calls[0]["url"]
    assert calls[0]["api_style"] == "legacy"
    assert calls[0]["payload"] == {
        "request": {
            "process_instance_id": "PROC-SEA-001",
            "file_id": "FILE-001",
        },
    }


def test_get_process_attachment_download_url_legacy_does_not_require_user_id(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return {"errcode": 0, "result": {"downloadUri": "https://download.example.com/no-user.xlsx"}}

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)

    result = get_process_attachment_download_url(
        token="TOKEN-001",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        api_style="legacy",
    )

    assert result["download_uri"] == "https://download.example.com/no-user.xlsx"
    assert "user_id" not in calls[0]["payload"]["request"]


def test_get_process_attachment_download_url_uses_legacy_dentry_auth_before_new_fallback(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "/topapi/processinstance/file/url/get" in url and len([call for call in calls if "/topapi/processinstance/file/url/get" in call["url"]]) == 1:
            return {"errcode": 60121, "errmsg": "找不到该用户", "success": False}
        if "/topapi/processinstance/cspace/info" in url:
            return {"errcode": 0, "result": {"space_id": "764607503"}}
        if "/topapi/process/dentry/auth" in url:
            return {"errcode": 0, "result": True}
        if "/topapi/processinstance/file/url/get" in url:
            return {"errcode": 0, "result": {"downloadUri": "https://download.example.com/legacy-auth.xlsx"}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)

    result = get_process_attachment_download_url(
        token="LEGACY-TOKEN",
        process_instance_id="PROC-SEA-001",
        file_id="207632357484",
        user_id="03435534375526711913",
        api_style="legacy",
    )

    assert result["download_uri"] == "https://download.example.com/legacy-auth.xlsx"
    assert result["fallback_api"] == "legacy_dentry_auth_then_file_url"
    auth_call = next(call for call in calls if "/topapi/process/dentry/auth" in call["url"])
    assert auth_call["payload"] == {
        "request": {
            "file_infos": [
                {
                    "file_id": 207632357484,
                    "space_id": 764607503,
                }
            ],
            "userid": "03435534375526711913",
        }
    }


def test_get_process_attachment_download_url_falls_back_to_storage_download(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "/topapi/processinstance/file/url/get" in url:
            return {"errcode": 60121, "errmsg": "找不到该用户", "success": False}
        if "/topapi/processinstance/cspace/info" in url:
            return {"errcode": 0, "result": {"space_id": "SPACE-001"}}
        if "/topapi/process/dentry/auth" in url:
            raise RuntimeError("legacy auth failed")
        if "/topapi/v2/user/get" in url:
            return {"errcode": 0, "result": {"unionid": "UNION-001"}}
        if "/v1.0/workflow/processInstances/spaces/files/authDownload" in url:
            raise RuntimeError("noPermission")
        if "/v1.0/storage/spaces/SPACE-001/dentries/FILE-001/downloadInfos/query" in url:
            return {
                "headerSignatureInfo": {
                    "resourceUrls": ["https://download.example.com/storage.xlsx"],
                    "headers": {"x-acs-signature": "SIG-001"},
                }
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "NEW-TOKEN")

    result = get_process_attachment_download_url(
        token="LEGACY-TOKEN",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        user_id="USER-001",
        corp_id="ding-corp-001",
        api_style="legacy",
    )

    assert result["download_uri"] == "https://download.example.com/storage.xlsx"
    assert result["download_headers"] == {"x-acs-signature": "SIG-001"}
    assert result["space_id"] == "SPACE-001"
    assert result["fallback_api"] == "storage_dentry_download_info"
    assert [call["payload"] for call in calls[:4]] == [
        {"request": {"process_instance_id": "PROC-SEA-001", "file_id": "FILE-001"}},
        {"process_instance_id": "PROC-SEA-001", "file_id": "FILE-001", "user_id": "USER-001"},
        {"request": {"file_infos": [{"file_id": "FILE-001", "space_id": "SPACE-001"}], "userid": "USER-001"}},
        {"userid": "USER-001", "language": "zh_CN"},
    ]
    assert any("/v1.0/workflow/processInstances/spaces/files/authDownload" in call["url"] for call in calls)
    assert any("unionId=UNION-001" in call["url"] for call in calls)


def test_get_process_attachment_download_url_uses_new_auth_before_storage(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "/topapi/processinstance/file/url/get" in url:
            return {"errcode": 60121, "errmsg": "找不到该用户", "success": False}
        if "/topapi/processinstance/cspace/info" in url:
            return {"errcode": 0, "result": {"space_id": "SPACE-001"}}
        if "/topapi/v2/user/get" in url:
            return {"errcode": 0, "result": {"unionid": "UNION-001"}}
        if "/v1.0/workflow/processInstances/spaces/files/authDownload" in url:
            return {"result": {"success": True}}
        if "/v1.0/workflow/processInstances/spaces/files/urls/download" in url:
            return {"result": {"downloadUri": "https://download.example.com/auth.xlsx"}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "NEW-TOKEN")

    result = get_process_attachment_download_url(
        token="LEGACY-TOKEN",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        user_id="USER-001",
        corp_id="ding-corp-001",
        api_style="legacy",
    )

    assert result["download_uri"] == "https://download.example.com/auth.xlsx"
    assert result["fallback_api"] == "new_auth_then_approval_download"
    auth_call = next(call for call in calls if "/v1.0/workflow/processInstances/spaces/files/authDownload" in call["url"])
    assert auth_call["payload"]["fileInfos"] == [{"spaceId": "SPACE-001", "fileId": "FILE-001"}]


def test_get_process_attachment_download_url_keeps_new_auth_file_id_as_string(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "/topapi/processinstance/file/url/get" in url:
            return {"errcode": 60121, "errmsg": "找不到该用户", "success": False}
        if "/topapi/processinstance/cspace/info" in url:
            return {"errcode": 0, "result": {"space_id": "764607503"}}
        if "/topapi/process/dentry/auth" in url:
            raise RuntimeError("legacy auth failed")
        if "/topapi/v2/user/get" in url:
            return {"errcode": 0, "result": {"unionid": "UNION-001"}}
        if "/v1.0/workflow/processInstances/spaces/files/authDownload" in url:
            return {"result": {"success": True}}
        if "/v1.0/workflow/processInstances/spaces/files/urls/download" in url:
            return {"result": {"downloadUri": "https://download.example.com/auth.xlsx"}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "NEW-TOKEN")

    result = get_process_attachment_download_url(
        token="LEGACY-TOKEN",
        process_instance_id="PROC-SEA-001",
        file_id="207632357484",
        user_id="03435534375526711913",
        corp_id="ding-corp-001",
        api_style="legacy",
    )

    auth_call = next(call for call in calls if "/v1.0/workflow/processInstances/spaces/files/authDownload" in call["url"])
    assert result["download_uri"] == "https://download.example.com/auth.xlsx"
    assert auth_call["payload"]["fileInfos"] == [{"spaceId": 764607503, "fileId": "207632357484"}]


def test_get_process_attachment_download_url_resolves_storage_dentry_by_file_name(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "/topapi/processinstance/file/url/get" in url:
            return {"errcode": 60121, "errmsg": "找不到该用户", "success": False}
        if "/topapi/processinstance/cspace/info" in url:
            return {"errcode": 0, "result": {"space_id": "SPACE-001"}}
        if "/topapi/v2/user/get" in url:
            return {"errcode": 0, "result": {"unionid": "UNION-001"}}
        if "/v1.0/workflow/processInstances/spaces/files/authDownload" in url:
            raise RuntimeError("noPermission")
        if "/v1.0/storage/spaces/SPACE-001/dentries/FILE-001/downloadInfos/query" in url:
            raise RuntimeError("permissionDenied")
        if "/v1.0/storage/spaces/SPACE-001/dentries?" in url:
            return {"dentries": [{"id": "DENTRY-002", "name": "packing.xlsx"}]}
        if "/v1.0/storage/spaces/SPACE-001/dentries/DENTRY-002/downloadInfos/query" in url:
            return {
                "headerSignatureInfo": {
                    "resourceUrls": ["https://download.example.com/resolved.xlsx"],
                    "headers": {"x-acs-signature": "RESOLVED-SIG"},
                }
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "NEW-TOKEN")

    result = get_process_attachment_download_url(
        token="LEGACY-TOKEN",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        file_name="packing.xlsx",
        user_id="USER-001",
        corp_id="ding-corp-001",
        api_style="legacy",
    )

    assert result["download_uri"] == "https://download.example.com/resolved.xlsx"
    assert result["download_headers"] == {"x-acs-signature": "RESOLVED-SIG"}
    assert result["fallback_api"] == "storage_dentry_list_then_download_info"
    assert any("/v1.0/storage/spaces/SPACE-001/dentries/FILE-001/downloadInfos/query" in call["url"] for call in calls)
    assert any("/v1.0/storage/spaces/SPACE-001/dentries?" in call["url"] for call in calls)
    assert any("/v1.0/storage/spaces/SPACE-001/dentries/DENTRY-002/downloadInfos/query" in call["url"] for call in calls)


def test_get_process_attachment_download_url_falls_back_to_thumbnail(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    calls = []

    def fake_request_json(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "/topapi/processinstance/file/url/get" in url:
            return {"errcode": 60121, "errmsg": "找不到该用户", "success": False}
        if "/topapi/processinstance/cspace/info" in url:
            return {"errcode": 0, "result": {"space_id": "SPACE-001"}}
        if "/topapi/process/dentry/auth" in url:
            raise RuntimeError("legacy auth failed")
        if "/topapi/v2/user/get" in url:
            return {"errcode": 0, "result": {"unionid": "UNION-001"}}
        if "/v1.0/workflow/processInstances/spaces/files/authDownload" in url:
            raise RuntimeError("noPermission")
        if "/v1.0/storage/spaces/SPACE-001/dentries/FILE-001/downloadInfos/query" in url:
            raise RuntimeError("permissionDenied")
        if "/v1.0/storage/spaces/SPACE-001/dentries?" in url:
            raise RuntimeError("list noPermission")
        if "/v1.0/storage/spaces/SPACE-001/thumbnails/query" in url:
            return {
                "resultItems": [
                    {
                        "dentryId": "FILE-001",
                        "thumbnail": {"url": "https://download.example.com/thumb.png"},
                    }
                ]
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "NEW-TOKEN")

    result = get_process_attachment_download_url(
        token="LEGACY-TOKEN",
        process_instance_id="PROC-SEA-001",
        file_id="FILE-001",
        file_name="报价.png",
        user_id="USER-001",
        corp_id="ding-corp-001",
        api_style="legacy",
    )

    assert result["download_uri"] == "https://download.example.com/thumb.png"
    assert result["download_headers"] == {}
    assert result["fallback_api"] == "storage_thumbnail_query"
    thumbnail_call = next(call for call in calls if "/v1.0/storage/spaces/SPACE-001/thumbnails/query" in call["url"])
    assert "unionId=UNION-001" in thumbnail_call["url"]
    assert thumbnail_call["payload"]["dentryIds"] == ["FILE-001"]


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


def test_extract_logistics_fee_from_approval_only_reads_explicit_amount() -> None:
    fee = extract_logistics_fee_from_approval(
        {
            "form_fields": {
                "物流费用": "900",
                "币种Moneda": "美元Dólar",
                "物流报价Cotización de logística": "40HQ / 900美金",
            }
        }
    )

    assert fee["amount"] == 900
    assert fee["currency"] == "USD"
    assert fee["source_field"] == "物流费用"

    quote_fee = extract_logistics_fee_from_approval(
        {
            "form_fields": {
                "物流报价Cotización de logística": "货物预估方数：1.5方\n1.SISA报价：3720/立方\n合计价格：5730元\n2.大墨仓报价：2900/立方\n合计价格：4350元"
            }
        }
    )

    assert quote_fee == {}

    candidates = extract_logistics_quote_candidates_from_approval(
        {
            "form_fields": {
                "物流报价Cotización de logística": "货物预估方数：1.5方\n1.SISA报价：3720/立方\n合计价格：5730元\n2.大墨仓报价：2900/立方\n合计价格：4350元"
            }
        }
    )

    assert candidates == [
        {
            "carrier": "SISA",
            "amount": 5730,
            "currency": "RMB",
            "volume_m3": 1.5,
            "source_field": "物流报价Cotización de logística",
            "source_value": "货物预估方数：1.5方\n1.SISA报价：3720/立方\n合计价格：5730元\n2.大墨仓报价：2900/立方\n合计价格：4350元",
            "evidence_line": "合计价格：5730元",
            "evidence_line_no": 3,
            "status": "待确认",
        },
        {
            "carrier": "大墨仓",
            "amount": 4350,
            "currency": "RMB",
            "volume_m3": 1.5,
            "source_field": "物流报价Cotización de logística",
            "source_value": "货物预估方数：1.5方\n1.SISA报价：3720/立方\n合计价格：5730元\n2.大墨仓报价：2900/立方\n合计价格：4350元",
            "evidence_line": "合计价格：4350元",
            "evidence_line_no": 5,
            "status": "待确认",
        },
    ]


def test_extract_logistics_quote_candidates_reads_formula_amount_line() -> None:
    candidates = extract_logistics_quote_candidates_from_approval(
        {
            "form_fields": {
                "物流报价Cotización de logística": (
                    "DHL报价：\n"
                    "运费=4075*（1+燃油附加费）+重量+155*（1+燃油附加费）+超过25kg的箱数+附加费\n"
                    "50.22*1.3825*33.2+155*1.3825*1+155*1=2674.33528元\n"
                    "每kg单价：80.5522674元"
                )
            }
        }
    )

    assert candidates == [
        {
            "carrier": "DHL",
            "amount": 2674.33528,
            "currency": "RMB",
            "volume_m3": None,
            "source_field": "物流报价Cotización de logística",
            "source_value": (
                "DHL报价：\n"
                "运费=4075*（1+燃油附加费）+重量+155*（1+燃油附加费）+超过25kg的箱数+附加费\n"
                "50.22*1.3825*33.2+155*1.3825*1+155*1=2674.33528元\n"
                "每kg单价：80.5522674元"
            ),
            "evidence_line": "50.22*1.3825*33.2+155*1.3825*1+155*1=2674.33528元",
            "evidence_line_no": 3,
            "status": "待确认",
        }
    ]


def test_extract_logistics_text_summary_reads_dhl_express_text_block() -> None:
    summary = extract_logistics_text_summary_from_approval(
        {
            "form_fields": {
                "物流报价Cotización de logística": (
                    "DHL报价：\n"
                    "运费=4075*（1+燃油附加费）*重量+155*（1+燃油附加费）*超过25kg的箱数+附加费*重量*附加费25折+超过25kg搬运费*超重箱数\n"
                    "50.22*1.3825*43.2+155*1.3825*1+155*1=3368.62678元\n"
                    "每kg单价：77.9774717592593元（含超重费用1箱）"
                ),
                "物流方式Camino Envío": "Express快递",
                "预计发货日期Fecha de Pre-entrega": "2026/8/12",
                "目标地区Países destinatarios": "MANZANILLO Mexico",
                "重量Peso（KG）": "43.2",
            }
        }
    )

    assert summary["transport_mode"] == "EXPRESS"
    assert summary["transport_mode_raw"] == "Express快递"
    assert summary["pre_delivery_date"] == "2026/8/12"
    assert summary["destination"] == "MANZANILLO Mexico"
    assert summary["gross_weight_kg"] == 43.2
    assert summary["logistics_quote_carrier"] == "DHL"
    assert summary["logistics_quote_amount"] == 3368.62678
    assert summary["logistics_quote_currency"] == "RMB"
    assert "50.22*1.3825*43.2" in summary["logistics_quote_evidence"]
    assert not summary.get("ai_used")


def test_extract_logistics_text_summary_uses_ai_fallback_without_overwriting_rule_values(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    monkeypatch.setattr(import_oa_logistics, "_runtime_config_bool", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        import_oa_logistics,
        "_call_ai_logistics_text_summary",
        lambda source_text, base_summary: {
            "transport_mode": "EXPRESS",
            "transport_mode_raw": "Express快递",
            "destination": "MANZANILLO Mexico",
            "gross_weight_kg": 43.2,
            "logistics_quote_amount": 9999,
            "logistics_quote_currency": "RMB",
            "logistics_quote_carrier": "DHL",
            "logistics_quote_evidence": "AI返回的金额不应覆盖规则金额",
            "ai_used": True,
            "ai_model": "deepseek-test",
            "ai_confidence": 0.76,
            "ai_reason": "字段名不规范，使用 AI 兜底识别。",
        },
    )

    summary = extract_logistics_text_summary_from_approval(
        {
            "form_fields": {
                "物流报价Cotización de logística": (
                    "DHL报价：\n"
                    "50.22*1.3825*43.2+155*1.3825*1+155*1=3368.62678元\n"
                    "每kg单价：77.9774717592593元"
                ),
                "业务备注": "目的地 MANZANILLO Mexico，重量 43.2KG，物流方式 Express快递",
            }
        }
    )

    assert summary["logistics_quote_amount"] == 3368.62678
    assert summary["logistics_quote_evidence"].startswith("50.22*1.3825*43.2")
    assert summary["transport_mode"] == "EXPRESS"
    assert summary["destination"] == "MANZANILLO Mexico"
    assert summary["gross_weight_kg"] == 43.2
    assert summary["ai_used"] is True
    assert summary["ai_model"] == "deepseek-test"


def test_extract_logistics_quote_candidates_reads_direct_40hq_quote_lines() -> None:
    candidates = extract_logistics_quote_candidates_from_approval(
        {
            "form_fields": {
                "物流报价Cotización de logística": (
                    "本周报价：\n"
                    "华运PIL：6050USD/40HQ+杂费\n"
                    "登泰PIL：5850USD/40HQ+杂费\n"
                    "彩虹捷运PIL：5850USD/40HQ+杂费\n"
                    "飞力达PIL：5850USD/40HQ+杂费\n"
                    "建议选择飞力达，可以借用货代仓库装柜"
                )
            }
        }
    )

    assert [(item["carrier"], item["amount"], item["currency"], item["remark"]) for item in candidates] == [
        ("华运PIL", 6050.0, "USD", "/40HQ+杂费"),
        ("登泰PIL", 5850.0, "USD", "/40HQ+杂费"),
        ("彩虹捷运PIL", 5850.0, "USD", "/40HQ+杂费"),
        ("飞力达PIL", 5850.0, "USD", "/40HQ+杂费"),
    ]
    assert all(item["status"] == "待确认" for item in candidates)


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


def test_extract_linked_purchase_approvals_from_nested_relate_payload() -> None:
    instance = {
        "processInstanceId": "PROC-SEA-NESTED",
        "formComponentValues": [
            {
                "componentType": "RelateField",
                "name": "Asocar órdenes de compra",
                "value": json.dumps(["采购支出 Gastos de compra enviado por Yadira"], ensure_ascii=False),
                "extValue": json.dumps(
                    {
                        "data": {
                            "list": [
                                {
                                    "businessId": "202604300000000596348",
                                    "url": "https://aflow.dingtalk.com/#/approval?procInstId=PROC-PURCHASE-NESTED",
                                    "title": "采购支出 Gastos de compra",
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    }

    linked = extract_linked_purchase_approvals(instance)

    assert len(linked) == 1
    assert linked[0]["approval_no"] == "202604300000000596348"
    assert linked[0]["source_instance_id"] == "PROC-PURCHASE-NESTED"


def test_extract_linked_purchase_approvals_from_top_level_related_payload() -> None:
    instance = {
        "processInstanceId": "PROC-SEA-RELATED",
        "processInstanceTitle": "国际物流 Logística Internacional",
        "formComponentValues": [],
        "relatedProcessInstances": [
            {
                "businessId": "202604150041000081318",
                "processInstanceId": "PROC-PURCHASE-TOP",
                "processInstanceTitle": "采购支出 Gastos de Compra",
                "url": "https://aflow.dingtalk.com/#/approval?procInstId=PROC-PURCHASE-TOP",
            },
            {
                "businessId": "202604150041000000000",
                "processInstanceId": "PROC-LOGISTICS-TOP",
                "processInstanceTitle": "国际物流 Logística Internacional",
            },
        ],
    }

    linked = extract_linked_purchase_approvals(instance)

    assert len(linked) == 1
    assert linked[0]["approval_no"] == "202604150041000081318"
    assert linked[0]["source_instance_id"] == "PROC-PURCHASE-TOP"


def test_extract_form_attachments_ignores_comment_attachments() -> None:
    instance = {
        "processInstanceId": "PROC-SEA-ATTACH",
        "businessId": "202607220001",
        "formComponentValues": [
            {
                "componentType": "DepartmentField",
                "name": "业务主体Entidad comercial",
                "extValue": json.dumps(
                    {"deptName": "YW MOLDES MX模具", "itemId": "1089528309", "name": "YW MOLDES MX模具"},
                    ensure_ascii=False,
                ),
            },
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
    env_file.write_text(
        "DINGTALK_PROCESS_CODE=FROM_FILE\nDINGTALK_LIST_API=old\nDINGTALK_APPKEY=APPKEY\nDINGTALK_APPSECRET=APPSECRET\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DINGTALK_PROCESS_CODE", "EXISTING")
    monkeypatch.delenv("DINGTALK_APP_KEY", raising=False)
    monkeypatch.delenv("DINGTALK_APP_SECRET", raising=False)

    try:
        load_env_file(str(env_file))
    finally:
        env_file.unlink(missing_ok=True)

    assert os.environ["DINGTALK_PROCESS_CODE"] == "EXISTING"
    assert os.environ["DINGTALK_LIST_API"] == "old"
    assert os.environ["DINGTALK_APP_KEY"] == "APPKEY"
    assert os.environ["DINGTALK_APP_SECRET"] == "APPSECRET"


def test_logistics_process_code_does_not_use_budget_process_env(monkeypatch) -> None:
    monkeypatch.setenv("DINGTALK_PROCESS_CODE", "PROC-BUDGET-001")
    monkeypatch.delenv("DINGTALK_LOGISTICS_PROCESS_CODE", raising=False)

    assert resolve_logistics_process_code() == DEFAULT_LOGISTICS_PROCESS_CODE

    monkeypatch.setenv("DINGTALK_LOGISTICS_PROCESS_CODE", "PROC-LOGISTICS-ENV")

    assert resolve_logistics_process_code() == "PROC-LOGISTICS-ENV"
    assert resolve_logistics_process_code("PROC-CLI") == "PROC-CLI"


def test_purchase_process_code_requires_purchase_specific_env(monkeypatch) -> None:
    monkeypatch.setenv("DINGTALK_PROCESS_CODE", "PROC-BUDGET-001")
    monkeypatch.delenv("DINGTALK_PURCHASE_PROCESS_CODE", raising=False)
    monkeypatch.delenv("DINGTALK_PURCHASE_EXPENSE_PROCESS_CODE", raising=False)
    monkeypatch.delenv("DINGTALK_PROCESS_CODES", raising=False)

    assert resolve_purchase_process_code() == ""

    monkeypatch.setenv("DINGTALK_PURCHASE_PROCESS_CODE", "PROC-PURCHASE-ENV")

    assert resolve_purchase_process_code() == "PROC-PURCHASE-ENV"
    assert resolve_purchase_process_code("PROC-PURCHASE-CLI") == "PROC-PURCHASE-CLI"

    monkeypatch.delenv("DINGTALK_PURCHASE_PROCESS_CODE", raising=False)
    monkeypatch.setenv("DINGTALK_PROCESS_CODES", '["PROC-OPERATION","PROC-PURCHASE-LIST"]')

    assert resolve_purchase_process_code() == "PROC-PURCHASE-LIST"


def test_purchase_process_code_reads_frappe_site_config(monkeypatch) -> None:
    from types import SimpleNamespace

    from overseas_costing.scripts import import_oa_logistics

    monkeypatch.delenv("DINGTALK_PURCHASE_PROCESS_CODE", raising=False)
    monkeypatch.delenv("DINGTALK_PURCHASE_EXPENSE_PROCESS_CODE", raising=False)
    monkeypatch.delenv("DINGTALK_PROCESS_CODES", raising=False)
    monkeypatch.setattr(
        import_oa_logistics,
        "frappe",
        SimpleNamespace(conf={"overseas_costing_dingtalk_purchase_process_code": "PROC-PURCHASE-SITE"}),
    )

    assert resolve_purchase_process_code() == "PROC-PURCHASE-SITE"


def test_get_access_token_reads_legacy_credentials_from_frappe_site_config(monkeypatch) -> None:
    from types import SimpleNamespace

    from overseas_costing.scripts import import_oa_logistics

    captured = {}

    def fake_request_json(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {"errcode": 0, "access_token": "SITE-TOKEN"}

    monkeypatch.delenv("DINGTALK_APP_KEY", raising=False)
    monkeypatch.delenv("DINGTALK_APP_SECRET", raising=False)
    monkeypatch.delenv("DINGTALK_APPKEY", raising=False)
    monkeypatch.delenv("DINGTALK_APPSECRET", raising=False)
    monkeypatch.delenv("DINGTALK_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(import_oa_logistics, "_request_json", fake_request_json)
    monkeypatch.setattr(
        import_oa_logistics,
        "frappe",
        SimpleNamespace(
            conf={
                "overseas_costing_dingtalk_app_key": "SITE-APP-KEY",
                "overseas_costing_dingtalk_app_secret": "SITE-APP-SECRET",
            }
        ),
    )

    assert get_access_token(api_style="legacy") == "SITE-TOKEN"
    assert "appkey=SITE-APP-KEY" in captured["url"]
    assert "appsecret=SITE-APP-SECRET" in captured["url"]


def test_completed_approval_status_filters_running() -> None:
    assert is_completed_approval_status("COMPLETED") is True
    assert is_completed_approval_status("审批通过") is True
    assert is_completed_approval_status("RUNNING") is False
    assert is_completed_approval_status("TERMINATED") is False


def test_pull_purchase_expense_approvals_reads_process_details(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    monkeypatch.setenv("DINGTALK_PURCHASE_PROCESS_CODE", "PROC-PURCHASE")
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN")
    monkeypatch.setattr(import_oa_logistics, "list_process_instance_ids", lambda **_kwargs: ["PROC-PURCHASE-001"])

    def fake_get_process_instance_detail(**_kwargs):
        return {
            "processInstanceId": "PROC-PURCHASE-001",
            "businessId": "202604150041000081318",
            "title": "采购支出 Gastos de Compra",
            "status": "COMPLETED",
            "formComponentValues": [
                {"componentType": "TextField", "name": "币种Moneda", "value": "人民币RMB"},
                {
                    "componentType": "TableField",
                    "name": "需求明细",
                    "value": json.dumps(
                        [
                            {
                                "rowValue": [
                                    {"label": "物品编码Código", "value": "YL000097"},
                                    {"label": "物品名称Nombre del artículo", "value": "TPU原料"},
                                    {"label": "数量Cantidad", "value": "10000"},
                                    {"label": "单价Precio", "value": "2.9"},
                                    {"label": "总金额Monto Total", "value": "29000"},
                                ]
                            }
                        ],
                        ensure_ascii=False,
                    ),
                },
            ],
        }

    monkeypatch.setattr(import_oa_logistics, "get_process_instance_detail", fake_get_process_instance_detail)

    result = pull_purchase_expense_approvals(process_code="", start="2026-04-01", end="2026-04-30")

    assert result["ok"] is True
    assert result["process_code"] == "PROC-PURCHASE"
    assert result["detail_count"] == 1
    assert result["items"][0]["detail_row_count"] == 1
    assert result["items"][0]["mapped_preview_items"][0]["material_code"] == "YL000097"
    assert result["items"][0]["mapped_preview_items"][0]["unit_price"] == 2.9


def test_extract_purchase_expense_rows_from_plain_text_detail() -> None:
    instance = {
        "formComponentValues": [
            {"componentType": "TextField", "name": "币种Moneda", "value": "人民币RMB"},
            {
                "componentType": "TextareaField",
                "name": "采购明细",
                "value": (
                    "物品编码Código: YL000097 物品名称Nombre del artículo: TPU原料 "
                    "物品规格Especificacion: 25KG 数量Cantidad: 10000 单价Precio: 2.9 总金额Monto Total: 29000\n"
                    "FL004104 包装袋 1000 0.049 49"
                ),
            },
        ]
    }

    rows = extract_purchase_expense_rows(instance)
    mapped = build_purchase_expense_item_values_from_approval(instance)

    assert len(rows) == 2
    assert rows[0]["物品编码Código"] == "YL000097"
    assert rows[0]["币种Moneda"] == "人民币RMB"
    assert mapped[0]["unit_price"] == 2.9
    assert mapped[1]["material_code"] == "FL004104"
    assert mapped[1]["product_name"] == "包装袋"
    assert mapped[1]["goods_value"] == 49


def test_pull_purchase_expense_approvals_skips_running_by_default(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    monkeypatch.setenv("DINGTALK_PURCHASE_PROCESS_CODE", "PROC-PURCHASE")
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN")
    monkeypatch.setattr(import_oa_logistics, "list_process_instance_ids", lambda **_kwargs: ["PROC-PURCHASE-RUNNING"])
    monkeypatch.setattr(
        import_oa_logistics,
        "get_process_instance_detail",
        lambda **_kwargs: {
            "processInstanceId": "PROC-PURCHASE-RUNNING",
            "businessId": "202604150041000081318",
            "title": "采购支出 Gastos de Compra",
            "status": "RUNNING",
            "formComponentValues": [],
        },
    )

    result = pull_purchase_expense_approvals(process_code="", start="2026-04-01", end="2026-04-30")

    assert result["detail_count"] == 0
    assert result["skipped_count"] == 1
    assert result["skipped_items"][0]["reason"] == "采购支出审批未完成"


def test_sync_purchase_expenses_from_process_requires_process_code(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    monkeypatch.delenv("DINGTALK_PURCHASE_PROCESS_CODE", raising=False)
    monkeypatch.delenv("DINGTALK_PURCHASE_EXPENSE_PROCESS_CODE", raising=False)
    monkeypatch.setattr(import_oa_logistics, "frappe", object())
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")

    result = sync_purchase_expenses_from_process(start="2026-04-01", end="2026-04-30")

    assert result["ok"] is False
    assert "DINGTALK_PURCHASE_PROCESS_CODE" in result["message"]


def test_preview_purchase_expenses_from_process_matches_existing_batches(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics
    from overseas_costing.services import import_service

    class FakeFrappe:
        @staticmethod
        def get_all(*_args, **_kwargs):
            return [
                {"name": "BATCH-FSCU", "batch_no": "FSCU8486789", "current_version": "VER-FSCU"},
                {"name": "BATCH-HPCU", "batch_no": "HPCU5155607", "current_version": "VER-HPCU"},
            ]

    purchase_summary = {
        "source_approval_no": "202604150041000081318",
        "source_instance_id": "PROC-PURCHASE-001",
        "approval_title": "采购支出 Gastos de Compra",
        "detail_row_count": 1,
        "purchase_currency": "人民币RMB",
        "mapped_preview_items": [{"material_code": "YL000097", "unit_price": 2.9}],
    }
    preview_calls: list[dict] = []

    def fake_pull_purchase_expense_approvals(**_kwargs):
        return {"ok": True, "detail_count": 1, "items": [purchase_summary], "skipped_items": []}

    def fake_preview_linked_purchase_expense_oa(**kwargs):
        preview_calls.append(kwargs)
        if kwargs["batch_name"] == "BATCH-FSCU":
            return {
                "writeback_preview": {
                    "matched_count": 1,
                    "writable_row_count": 1,
                    "fillable_row_count": 1,
                    "conflict_row_count": 0,
                    "same_row_count": 0,
                    "unmatched_count": 0,
                    "ambiguous_count": 0,
                    "matched_rows": [
                        {
                            "target_row_no": 1,
                            "target_material_code": "YL000097",
                            "target_product_name": "TPU原料",
                            "target_spec_model": "",
                            "mapped_row": {"material_code": "YL000097", "unit_price": 2.9},
                            "business_changes": [
                                {"fieldname": "purchase_unit_price", "new_value": 2.9, "status": "fillable"}
                            ],
                        }
                    ],
                }
            }
        return {
            "writeback_preview": {
                "matched_count": 0,
                "writable_row_count": 0,
                "fillable_row_count": 0,
                "conflict_row_count": 0,
                "same_row_count": 0,
                "unmatched_count": 1,
                "ambiguous_count": 0,
                "matched_rows": [],
            }
        }

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe())
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setenv("DINGTALK_PURCHASE_PROCESS_CODE", "PROC-PURCHASE")
    monkeypatch.setattr(import_oa_logistics, "pull_purchase_expense_approvals", fake_pull_purchase_expense_approvals)
    monkeypatch.setattr(import_service, "preview_linked_purchase_expense_oa", fake_preview_linked_purchase_expense_oa)

    result = preview_purchase_expenses_from_process(start="2026-04-01", end="2026-04-30")

    assert result["ok"] is True
    assert result["matched_batch_count"] == 1
    assert result["writable_batch_count"] == 1
    assert result["writable_row_count"] == 1
    assert result["purchase_summary_count"] == 1
    assert result["mapped_purchase_row_count"] == 1
    assert result["pull"]["items"][0]["can_open"] is True
    assert result["mapped_purchase_rows"][0]["source_approval_no"] == "202604150041000081318"
    assert result["items"][0]["batch_no"] == "FSCU8486789"
    assert len(preview_calls) == 2
    assert preview_calls[0]["purchase_summaries_json"]


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
                        {"label": "物料编码 Código de material", "value": "物料编码"},
                        {"label": "物料名称（中文）Nombre del material (chino)", "value": "物料名称中文"},
                        {"label": "物料名称（西语）Nombre del material (español)", "value": "物料名称西语"},
                        {"label": "规格型号Especificación / Modelo", "value": "规格型号"},
                        {"label": "数量Cantidad", "value": "数量"},
                        {"label": "单位Unidad", "value": "单位"},
                        {"label": "收件人Destinatario", "value": "收货人"},
                    ],
                    "rowNumber": "TableField_HEADER",
                },
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

    assert len(rows) == 1
    assert len(items) == 1
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


def test_extract_oa_goods_text_rows_and_skip_summary() -> None:
    approval = {
        "source_approval_no": "202601121522000486665",
        "source_instance_id": "PROC-SEA-TEXT",
        "transport_mode_raw": "海运",
        "logistics_no": "202601121522000486665",
        "form_fields": {
            "货物信息Bienes": """
                GJ003786-灯管-8pcs
                FL002598-灯管+连接线-30pcs
                热熔胶--100pcs
                合计47件，重量470.71kg，体积：1.53方
            """,
        },
    }

    rows = extract_oa_goods_rows(approval)
    items = build_oa_item_values_from_approval(approval)

    assert len(rows) == 3
    assert rows[0]["material_code"] == "GJ003786"
    assert rows[0]["product_name"] == "灯管"
    assert rows[0]["quantity"] == "8"
    assert rows[0]["unit"] == "个"
    assert rows[1]["material_code"] == "FL002598"
    assert rows[1]["product_name"] == "灯管+连接线"
    assert "material_code" not in rows[2]
    assert rows[2]["product_name"] == "热熔胶"
    assert rows[2]["quantity"] == "100"
    assert [item["quantity"] for item in items] == [8.0, 30.0, 100.0]
    assert items[2]["material_code"] is None


def test_build_oa_item_values_allocates_header_weight_by_quantity() -> None:
    approval = {
        "source_approval_no": "202608111418000558262",
        "source_instance_id": "PROC-EXPRESS-WEIGHT",
        "transport_mode_raw": "Express快递",
        "form_fields": {
            "重量Peso（KG）": "33.2",
            "货物信息Bienes": [
                {
                    "rowValue": [
                        {"label": "物料编码 Código de material", "value": "MHA101290"},
                        {"label": "物料名称（中文）Nombre del material (chino)", "value": "超队TPU模具"},
                        {"label": "规格型号Especificación / Modelo", "value": "Honor X8D 4G"},
                        {"label": "数量Cantidad", "value": "1"},
                    ],
                    "rowNumber": "ROW-1",
                },
                {
                    "rowValue": [
                        {"label": "物料编码 Código de material", "value": "MHA201290"},
                        {"label": "物料名称（中文）Nombre del material (chino)", "value": "超队PC模具"},
                        {"label": "规格型号Especificación / Modelo", "value": "Honor X8D 4G"},
                        {"label": "数量Cantidad", "value": "1"},
                    ],
                    "rowNumber": "ROW-2",
                },
            ],
        },
    }

    items = build_oa_item_values_from_approval(approval)

    assert [item["material_code"] for item in items] == ["MHA101290", "MHA201290"]
    assert [item["gross_weight_kg"] for item in items] == [16.6, 16.6]


def test_build_oa_item_values_keeps_spec_model_for_air_approval() -> None:
    approval = {
        "source_approval_no": "202608140001",
        "source_instance_id": "PROC-AIR-SPEC",
        "transport_mode_raw": "空运",
        "logistics_no": "AIR-001",
        "form_fields": {
            "货物信息Bienes": [
                {
                    "rowValue": [
                        {"label": "物料编码 Código de material", "value": "AIR001"},
                        {"label": "物料名称（中文）Nombre del material (chino)", "value": "空运测试物料"},
                        {"label": "物料名称（西语）Nombre del material (español)", "value": "Material de prueba"},
                        {"label": "规格型号Especificación / Modelo", "value": "AIR-SPEC-01"},
                        {"label": "数量Cantidad", "value": "3"},
                        {"label": "单位Unidad", "value": "pieza"},
                    ],
                    "rowNumber": "ROW-1",
                }
            ],
        },
    }

    items = build_oa_item_values_from_approval(approval)

    assert len(items) == 1
    assert items[0]["transport_mode"] == "AIR"
    assert items[0]["spec_model"] == "AIR-SPEC-01"
    assert items[0]["unit"] == "个"
    assert items[0]["waybill_no"] == "AIR-001"


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


def test_transport_mode_follows_camino_envio_value() -> None:
    sea_double_clear = build_batch_values_from_approval(
        {
            "source_approval_no": "202601301527000335149",
            "source_instance_id": "PROC-SEA-DOUBLE-CLEAR",
            "approval_status": "RUNNING",
            "transport_mode_raw": "doble despacho en aduana para transporte marítimo海运双清",
            "logistics_no": "",
            "form_fields": {},
        }
    )
    express = build_batch_values_from_approval(
        {
            "source_approval_no": "202601300932000271071",
            "source_instance_id": "PROC-EXPRESS",
            "approval_status": "COMPLETED",
            "transport_mode_raw": "correo express快递",
            "logistics_no": "",
            "form_fields": {},
        }
    )

    assert sea_double_clear["transport_mode"] == "SEA"
    assert express["transport_mode"] == "EXPRESS"


def test_existing_oa_batch_refreshes_transport_mode(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    set_values = []
    audits = []

    class FakeMeta:
        @staticmethod
        def has_field(_fieldname):
            return True

    class FakeDB:
        @staticmethod
        def get_value(doctype, filters, fieldname=None, as_dict=False):
            if doctype == "Overseas Cost Batch" and filters == "BATCH-001" and fieldname == "current_version":
                return "VER-001"
            if doctype == "Overseas Cost Batch" and filters == "BATCH-001" and isinstance(fieldname, list):
                current = {name: "" for name in fieldname}
                current["transport_mode"] = "SEA"
                return current if as_dict else current
            return None

        @staticmethod
        def set_value(doctype, name, values, update_modified=False):
            set_values.append(
                {
                    "doctype": doctype,
                    "name": name,
                    "values": dict(values),
                    "update_modified": update_modified,
                }
            )

    class FakeDoc:
        def __init__(self, payload):
            self.payload = payload

        def insert(self, **_kwargs):
            audits.append(self.payload)
            return self

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_meta(_doctype):
            return FakeMeta()

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)

    result = import_oa_logistics._update_oa_trace_batch("BATCH-001", {"transport_mode": "EXPRESS"})

    assert result["action"] == "updated"
    assert result["changed_fields"] == ["transport_mode"]
    assert set_values[0]["values"] == {"transport_mode": "EXPRESS"}
    assert audits[0]["field_name"] == "oa_logistics_trace"


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


def test_sync_linked_purchase_fields_applies_existing_import_service(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics
    from overseas_costing.services import import_service

    calls = []

    def fake_apply_linked_purchase_expense_fillable_fields(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "updated_count": 2,
            "changed_field_count": 6,
            "skipped_count": 0,
            "unmatched_count": 0,
            "ambiguous_count": 0,
            "message": "采购字段已同步",
        }

    monkeypatch.setattr(import_oa_logistics, "frappe", object())
    monkeypatch.setattr(import_service, "apply_linked_purchase_expense_fillable_fields", fake_apply_linked_purchase_expense_fillable_fields)

    result = _sync_linked_purchase_fields(
        batch_name="BATCH-001",
        version_name="VER-001",
        approval_item={
            "linked_purchase_approvals": [
                {"approval_no": "202604300000000596348", "source_instance_id": "PROC-PURCHASE-001"}
            ]
        },
    )

    assert result["ok"] is True
    assert result["action"] == "synced"
    assert result["updated_count"] == 2
    assert result["changed_field_count"] == 6
    assert calls[0]["batch_name"] == "BATCH-001"
    assert calls[0]["version_name"] == "VER-001"
    assert "202604300000000596348" in calls[0]["linked_purchase_json"]


def test_sync_oa_logistics_allocation_rule_creates_rule_and_recalculates(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    inserted_rules = []
    recalculate_calls = []

    class FakeDoc:
        def __init__(self, payload):
            self.payload = dict(payload)
            self.name = payload.get("name") or f"RULE-{len(inserted_rules) + 1}"

        def insert(self, **_kwargs):
            self.name = f"RULE-{len(inserted_rules) + 1}"
            self.payload["name"] = self.name
            inserted_rules.append(self.payload)
            return self

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Allocation Rule":
                return None
            return None

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

    def fake_recalculate_batch(**kwargs):
        recalculate_calls.append(kwargs)
        return {"ok": True, "summary_snapshot": {"total_cost_rmb": 1234}}

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)
    monkeypatch.setattr("overseas_costing.services.calculate_service.recalculate_batch", fake_recalculate_batch)

    rule_result = _sync_oa_logistics_allocation_rule(
        batch_name="BATCH-001",
        version_name="VER-001",
        approval_item={
            "logistics_fee": {
                "amount": "900",
                "currency": "美元Dólar",
                "source_label": "物流费用",
                "source_field": "物流费用",
                "source_value": "900",
            }
        },
    )
    recalc_result = _recalculate_after_purchase_sync(
        batch_name="BATCH-001",
        version_name="VER-001",
        purchase_sync={"ok": True, "updated_count": 0},
        logistics_fee_sync=rule_result,
    )

    assert rule_result["action"] == "created"
    assert rule_result["rule"]["rule_code"] == "oa_logistics_freight"
    assert rule_result["rule"]["amount"] == 900
    assert inserted_rules[0]["currency"] == "USD"
    assert recalc_result["action"] == "recalculated"
    assert recalculate_calls == [{"batch_name": "BATCH-001", "version_name": "VER-001"}]


def test_sync_express_single_quote_creates_freight_rule(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    inserted_rules = []

    class FakeDoc:
        def __init__(self, payload):
            self.payload = dict(payload)
            self.name = payload.get("name") or f"RULE-{len(inserted_rules) + 1}"

        def insert(self, **_kwargs):
            self.name = f"RULE-{len(inserted_rules) + 1}"
            self.payload["name"] = self.name
            inserted_rules.append(self.payload)
            return self

    class FakeDB:
        @staticmethod
        def get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
            if doctype == "Overseas Cost Allocation Rule":
                return None
            return None

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)

    rule_result = _sync_oa_logistics_allocation_rule(
        batch_name="202608131523000315085",
        version_name="VER-EXPRESS",
        approval_item={
            "transport_mode": "EXPRESS",
            "transport_mode_raw": "Express快递",
            "logistics_quote_candidates": extract_logistics_quote_candidates_from_approval(
                {
                    "form_fields": {
                        "物流报价Cotización de logística": (
                            "DHL报价：\n"
                            "运费=4075*（1+燃油附加费）+重量+155*（1+燃油附加费）+超过25kg的箱数+附加费\n"
                            "50.22*1.3975*43.2KG+155*1.3975*1+155*1=3403.49434元\n"
                            "每kg单价：78.7845912元"
                        )
                    }
                }
            ),
        },
    )

    assert rule_result["action"] == "created"
    assert rule_result["rule"]["amount"] == 3403.49434
    assert rule_result["rule"]["currency"] == "RMB"
    assert rule_result["rule"]["rule_code"] == "oa_logistics_freight"
    assert inserted_rules[0]["expense_category"] == "国际物流费用"


def test_refresh_existing_oa_logistics_details_repulls_missing_trace(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    detail_calls = []
    save_calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype != "Overseas Cost Batch":
                return []
            return [
                {
                    "name": "BATCH-OLD",
                    "batch_no": "HPCU5155607",
                    "waybill_no": "HPCU5155607",
                    "current_version": "VER-OLD",
                    "source_approval_no": "202607010001",
                    "source_instance_id": "PROC-SEA-OLD",
                    "source_dingtalk_url": "",
                    "extra_json": "{}",
                },
                {
                    "name": "BATCH-MISSING-ID",
                    "batch_no": "NO-ID",
                    "waybill_no": "",
                    "current_version": "VER-MISSING",
                    "source_approval_no": "",
                    "source_instance_id": "",
                    "source_dingtalk_url": "",
                    "extra_json": "{}",
                },
                {
                    "name": "BATCH-REVOKED",
                    "batch_no": "REVOKED",
                    "waybill_no": "REVOKED",
                    "current_version": "VER-REVOKED",
                    "source_approval_no": "202607010002",
                    "source_instance_id": "PROC-REVOKED",
                    "source_dingtalk_url": "",
                    "extra_json": "{}",
                },
            ]

    def fake_get_process_instance_detail(**kwargs):
        detail_calls.append(kwargs)
        return {"processInstanceId": kwargs["process_instance_id"]}

    def fake_summarize_approval(detail, **_kwargs):
        instance_id = detail["processInstanceId"]
        if instance_id == "PROC-REVOKED":
            return {
                "source_instance_id": instance_id,
                "source_approval_no": "202607010002",
                "approval_status": "TERMINATED",
                "form_fields": {"物流方式": "海运"},
                "transport_mode_raw": "海运",
                "logistics_no": "REVOKED",
            }
        return {
            "source_instance_id": instance_id,
            "source_approval_no": "202607010001",
            "approval_status": "COMPLETED",
            "form_fields": {"物流方式": "海运"},
            "transport_mode_raw": "海运",
            "logistics_no": "HPCU5155607",
            "linked_purchase_approvals": [
                {"approval_no": "202604300000000596348", "source_instance_id": "PROC-PURCHASE-001"}
            ],
            "oa_form_attachments": [],
        }

    def fake_save_sea_approvals_to_erp(result):
        save_calls.append(result)
        return {
            "ok": True,
            "created_count": 0,
            "updated_count": 1,
            "unchanged_count": 0,
            "skipped_count": 0,
            "items": [
                {
                    "batch_name": "BATCH-OLD",
                    "purchase_sync": {
                        "ok": True,
                        "linked_purchase_count": 1,
                        "updated_count": 2,
                        "changed_field_count": 6,
                    },
                    "attachment_sync": {"attachment_count": 0},
                }
            ],
            "skipped_items": [],
        }

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN")
    monkeypatch.setattr(import_oa_logistics, "get_process_instance_detail", fake_get_process_instance_detail)
    monkeypatch.setattr(import_oa_logistics, "summarize_approval", fake_summarize_approval)
    monkeypatch.setattr(import_oa_logistics, "save_sea_approvals_to_erp", fake_save_sea_approvals_to_erp)

    result = refresh_existing_oa_logistics_details(limit=50)

    assert result["ok"] is True
    assert result["scanned_count"] == 3
    assert result["detail_count"] == 1
    assert result["saved_count"] == 1
    assert result["purchase_updated_count"] == 2
    assert result["purchase_changed_field_count"] == 6
    assert {call["process_instance_id"] for call in detail_calls} == {"PROC-SEA-OLD", "PROC-REVOKED"}
    assert len(save_calls) == 1
    assert save_calls[0]["items"][0]["source_instance_id"] == "PROC-SEA-OLD"
    assert save_calls[0]["items"][0]["linked_purchase_approvals"][0]["source_instance_id"] == "PROC-PURCHASE-001"
    assert result["skipped_count"] == 2
    assert {item["batch_name"] for item in result["skipped_items"]} == {"BATCH-MISSING-ID", "BATCH-REVOKED"}


def test_refresh_existing_oa_logistics_details_can_target_one_batch(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    query_calls = []
    detail_calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            query_calls.append((doctype, kwargs))
            return [
                {
                    "name": "BATCH-TARGET",
                    "batch_no": "2k3o4tgh3e",
                    "waybill_no": "2k3o4tgh3e",
                    "current_version": "VER-TARGET",
                    "source_approval_no": "202608051608000144099",
                    "source_instance_id": "PROC-TARGET",
                    "source_dingtalk_url": "",
                    "extra_json": "{}",
                }
            ]

    def fake_get_process_instance_detail(**kwargs):
        detail_calls.append(kwargs)
        return {"processInstanceId": kwargs["process_instance_id"]}

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN")
    monkeypatch.setattr(import_oa_logistics, "get_process_instance_detail", fake_get_process_instance_detail)
    monkeypatch.setattr(
        import_oa_logistics,
        "summarize_approval",
        lambda detail, **_kwargs: {
            "source_instance_id": detail["processInstanceId"],
            "source_approval_no": "202608051608000144099",
            "approval_status": "COMPLETED",
            "form_fields": {"物流方式": "海运"},
            "transport_mode_raw": "海运",
            "logistics_no": "2k3o4tgh3e",
        },
    )
    monkeypatch.setattr(
        import_oa_logistics,
        "save_sea_approvals_to_erp",
        lambda result: {
            "ok": True,
            "created_count": 0,
            "updated_count": 1,
            "unchanged_count": 0,
            "skipped_count": 0,
            "items": [],
            "skipped_items": [],
        },
    )

    result = import_oa_logistics.refresh_existing_oa_logistics_details(
        batch_no="2k3o4tgh3e",
        source_approval_no="202608051608000144099",
    )

    assert result["ok"] is True
    assert result["target"] == {
        "target": "",
        "batch_name": "",
        "batch_no": "2k3o4tgh3e",
        "source_approval_no": "202608051608000144099",
    }
    assert query_calls[0][0] == "Overseas Cost Batch"
    assert query_calls[0][1]["filters"]["source_type"] == "oa_logistics"
    assert query_calls[0][1]["or_filters"] == [
        {"batch_no": "2k3o4tgh3e"},
        {"source_approval_no": "202608051608000144099"},
    ]
    assert [call["process_instance_id"] for call in detail_calls] == ["PROC-TARGET"]


def test_refresh_oa_logistics_detail_matches_target_across_identifiers(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    query_calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            query_calls.append((doctype, kwargs))
            return []

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN")

    result = refresh_oa_logistics_detail("202608051608000144099", limit=10)

    assert result["ok"] is True
    assert result["target"]["target"] == "202608051608000144099"
    assert query_calls[0][1]["filters"] == {"source_type": "oa_logistics"}
    assert query_calls[0][1]["or_filters"] == [
        {"name": "202608051608000144099"},
        {"batch_no": "202608051608000144099"},
        {"source_approval_no": "202608051608000144099"},
    ]


def test_sync_existing_oa_finished_times_backfills_only_empty(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    rows = [
        {
            "name": "BATCH-MISSING-FINISH",
            "batch_no": "HPCU5155607",
            "source_approval_no": "202601291020000337788",
            "source_instance_id": "PROC-SEA-TRACE",
            "source_finished_at": "",
            "extra_json": json.dumps(
                {
                    "source": "dingtalk_oa_logistics",
                    "finish_time": "2026-04-21T17:16Z",
                    "source_instance_id": "PROC-SEA-TRACE",
                },
                ensure_ascii=False,
            ),
        },
        {
            "name": "BATCH-HAS-FINISH",
            "batch_no": "FSCU8486789",
            "source_approval_no": "202607010001",
            "source_instance_id": "PROC-HAS-FINISH",
            "source_finished_at": "2026-07-01 09:30:00",
            "extra_json": json.dumps(
                {
                    "source": "dingtalk_oa_logistics",
                    "finish_time": "2026-07-01T09:30Z",
                    "source_instance_id": "PROC-HAS-FINISH",
                },
                ensure_ascii=False,
            ),
        },
        {
            "name": "BATCH-NO-SNAPSHOT-FINISH",
            "batch_no": "NO-FINISH",
            "source_approval_no": "202607010002",
            "source_instance_id": "PROC-NO-FINISH",
            "source_finished_at": "",
            "extra_json": json.dumps({"source": "dingtalk_oa_logistics"}, ensure_ascii=False),
        },
    ]
    set_values = []
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeDB:
        @staticmethod
        def set_value(doctype, name, fieldname, value=None, **kwargs):
            set_values.append(
                {
                    "doctype": doctype,
                    "name": name,
                    "fieldname": fieldname,
                    "value": value,
                    "update_modified": kwargs.get("update_modified"),
                }
            )

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeDoc:
        def __init__(self, payload):
            self.payload = payload

        def insert(self, **_kwargs):
            audit_payloads.append(self.payload)
            return self

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype == "Overseas Cost Batch":
                return rows
            return []

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)

    result = sync_existing_oa_finished_times(limit=50)

    assert result["ok"] is True
    assert result["scanned_count"] == 3
    assert result["updated_count"] == 1
    assert result["skipped_count"] == 2
    assert set_values == [
        {
            "doctype": "Overseas Cost Batch",
            "name": "BATCH-MISSING-FINISH",
            "fieldname": "source_finished_at",
            "value": "2026-04-21 17:16:00",
            "update_modified": False,
        }
    ]
    assert audit_payloads[0]["field_name"] == "source_finished_at"
    assert "暂估汇率" in audit_payloads[0]["action_remark"]
    assert commit_count["value"] == 1
    assert result["items"][0]["source_finished_at"] == "2026-04-21 17:16:00"
    assert {item["batch_name"] for item in result["skipped_items"]} == {"BATCH-HAS-FINISH", "BATCH-NO-SNAPSHOT-FINISH"}


def test_refresh_missing_oa_finished_times_only_updates_finish_fields(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    rows = [
        {
            "name": "BATCH-MISSING-FINISH",
            "batch_no": "HPCU5155607",
            "source_approval_no": "202601291020000337788",
            "source_instance_id": "PROC-SEA-TRACE",
            "source_dingtalk_url": "",
            "source_approval_status": "",
            "source_finished_at": "",
            "extra_json": json.dumps({"source": "dingtalk_oa_logistics"}, ensure_ascii=False),
        },
        {
            "name": "BATCH-NO-FINISH",
            "batch_no": "NO-FINISH",
            "source_approval_no": "202607010001",
            "source_instance_id": "PROC-NO-FINISH",
            "source_dingtalk_url": "",
            "source_approval_status": "",
            "source_finished_at": "",
            "extra_json": json.dumps({"source": "dingtalk_oa_logistics"}, ensure_ascii=False),
        },
    ]
    detail_calls = []
    set_values = []
    audit_payloads = []
    commit_count = {"value": 0}

    class FakeDB:
        @staticmethod
        def set_value(doctype, name, fieldname, value=None, **kwargs):
            set_values.append(
                {
                    "doctype": doctype,
                    "name": name,
                    "fieldname": fieldname,
                    "value": value,
                    "update_modified": kwargs.get("update_modified"),
                }
            )

        @staticmethod
        def commit():
            commit_count["value"] += 1

    class FakeDoc:
        def __init__(self, payload):
            self.payload = payload

        def insert(self, **_kwargs):
            audit_payloads.append(self.payload)
            return self

    class FakeFrappe:
        db = FakeDB()

        class session:
            user = "tester@example.com"

        @staticmethod
        def get_all(doctype, **kwargs):
            assert kwargs["filters"] == {"source_type": "oa_logistics", "source_finished_at": ["in", ["", None]]}
            if doctype == "Overseas Cost Batch":
                return rows
            return []

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

    def fake_get_process_instance_detail(**kwargs):
        detail_calls.append(kwargs)
        return {"processInstanceId": kwargs["process_instance_id"]}

    def fake_summarize_approval(detail, **_kwargs):
        if detail["processInstanceId"] == "PROC-NO-FINISH":
            return {
                "source_instance_id": "PROC-NO-FINISH",
                "source_approval_no": "202607010001",
                "source_dingtalk_url": "",
                "approval_status": "RUNNING",
                "finish_time": "",
            }
        return {
            "source_instance_id": "PROC-SEA-TRACE",
            "source_approval_no": "202601291020000337788",
            "source_dingtalk_url": "https://aflow.dingtalk.com/example",
            "approval_status": "COMPLETED",
            "finish_time": "2026-04-21T17:16Z",
        }

    monkeypatch.setattr(import_oa_logistics, "frappe", FakeFrappe)
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setattr(import_oa_logistics, "get_access_token", lambda **_kwargs: "TOKEN")
    monkeypatch.setattr(import_oa_logistics, "get_process_instance_detail", fake_get_process_instance_detail)
    monkeypatch.setattr(import_oa_logistics, "summarize_approval", fake_summarize_approval)

    result = refresh_missing_oa_finished_times(limit=50)

    assert result["ok"] is True
    assert result["scanned_count"] == 2
    assert result["updated_count"] == 1
    assert result["skipped_count"] == 1
    assert {call["process_instance_id"] for call in detail_calls} == {"PROC-SEA-TRACE", "PROC-NO-FINISH"}
    assert set_values[0]["doctype"] == "Overseas Cost Batch"
    assert set_values[0]["name"] == "BATCH-MISSING-FINISH"
    assert set_values[0]["fieldname"]["source_finished_at"] == "2026-04-21 17:16:00"
    assert set_values[0]["fieldname"]["source_approval_status"] == "COMPLETED"
    assert "extra_json" in set_values[0]["fieldname"]
    assert set_values[0]["update_modified"] is False
    assert audit_payloads[0]["field_name"] == "source_finished_at"
    assert "暂估汇率" in audit_payloads[0]["action_remark"]
    assert commit_count["value"] == 1


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
