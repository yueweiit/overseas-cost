"""中文用途：批次查询服务测试。"""

import json

from overseas_costing.services.batch_service import (
    _build_item_query_args,
    _normalize_item_query_filters,
    _normalize_limit,
    create_batch,
    get_audit_logs,
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


def test_hidden_approval_status_matches_revoked_dingtalk_statuses() -> None:
    assert is_hidden_approval_status("TERMINATED") is True
    assert is_hidden_approval_status("已撤销") is True
    assert is_hidden_approval_status("COMPLETED") is False
    assert is_hidden_approval_status("") is False
