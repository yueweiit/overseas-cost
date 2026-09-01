"""
中文用途：海外成本 ERP 对接设置。

这里保存 DeepLinkERP 推送所需的接口参数，避免把地址、token、目标单据写死在代码里。
"""

from __future__ import annotations

from frappe.model.document import Document


class OverseasCostERPSettings(Document):
    """海外成本 ERP 对接设置。"""

    pass
