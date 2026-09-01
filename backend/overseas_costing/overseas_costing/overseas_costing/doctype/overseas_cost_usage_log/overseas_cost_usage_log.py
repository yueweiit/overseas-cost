"""
中文用途：海外成本使用记录控制器。

该日志用于回答交付后“采购人员有没有使用系统”。
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import USAGE_ACTION_TYPES, USAGE_STATUSES
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostUsageLog(Document):
    """海外成本使用记录。"""

    def validate(self) -> None:
        require_value(self.action_type, "动作类型")
        require_in(self.action_type, USAGE_ACTION_TYPES, "动作类型")
        if self.status:
            require_in(self.status, USAGE_STATUSES, "执行状态")
