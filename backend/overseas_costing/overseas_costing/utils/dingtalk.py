"""
中文用途：钉钉审批跳转工具。

当前主要解决两件事：
1. 统一生成钉钉审批移动端链接和 PC 客户端唤起链接
2. 把批次里的审批编号、实例 ID、官方链接整理成前端可直接使用的跳转载荷
"""

from __future__ import annotations

from urllib.parse import quote

MOBILE_APPROVAL_URL_TEMPLATE = (
    "https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm"
    "?showmenu=false&dd_progress=false#/approval?procInstId={instance_id}"
)

DESKTOP_PROTOCOL_URL_TEMPLATE = (
    "dingtalk://dingtalkclient/page/link?url={encoded_mobile_url}&pc_slide=true"
)


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def build_mobile_approval_url(instance_id: str | None) -> str:
    """生成钉钉移动审批页链接。"""

    normalized = _clean(instance_id)
    if not normalized:
        return ""
    return MOBILE_APPROVAL_URL_TEMPLATE.format(instance_id=normalized)


def build_desktop_approval_url(instance_id: str | None) -> str:
    """生成唤起 PC 钉钉客户端的协议链接。"""

    mobile_url = build_mobile_approval_url(instance_id)
    if not mobile_url:
        return ""
    return DESKTOP_PROTOCOL_URL_TEMPLATE.format(encoded_mobile_url=quote(mobile_url, safe=""))


def build_dingtalk_order_payload(
    *,
    batch_name: str | None = None,
    approval_no: str | None = None,
    instance_id: str | None = None,
    official_url: str | None = None,
) -> dict:
    """整理成前端可直接使用的钉钉原单跳转信息。"""

    approval_no = _clean(approval_no)
    instance_id = _clean(instance_id)
    official_url = _clean(official_url)
    mobile_url = build_mobile_approval_url(instance_id)
    desktop_url = build_desktop_approval_url(instance_id)
    open_url = desktop_url or official_url

    if desktop_url:
        open_mode = "desktop_protocol"
    elif official_url:
        open_mode = "web_url"
    else:
        open_mode = "unavailable"

    return {
        "batch_name": _clean(batch_name),
        "approval_no": approval_no,
        "instance_id": instance_id,
        "official_url": official_url,
        "mobile_url": mobile_url,
        "desktop_url": desktop_url,
        "open_url": open_url,
        "open_mode": open_mode,
        "can_open": bool(open_url),
    }
