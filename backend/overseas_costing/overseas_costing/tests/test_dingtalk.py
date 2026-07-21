"""
中文用途：钉钉审批跳转工具测试。
"""

from overseas_costing.utils.dingtalk import (
    build_desktop_approval_url,
    build_dingtalk_order_payload,
    build_mobile_approval_url,
    extract_dingtalk_instance_id,
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
