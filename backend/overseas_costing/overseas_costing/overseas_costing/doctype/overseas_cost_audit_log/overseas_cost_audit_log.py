"""
中文用途：海外成本审计日志控制器。

日志单用于记录：
1. 谁改了什么
2. 哪个版本被重算
3. 哪次回写被触发
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import AUDIT_ACTION_TYPES
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostAuditLog(Document):
    """海外成本审计日志。"""

    def validate(self) -> None:
        require_value(self.batch, "所属批次")
        if self.action_type:
            require_in(self.action_type, AUDIT_ACTION_TYPES, "动作类型")
