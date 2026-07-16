"""
中文用途：海外成本分摊规则控制器。

分摊规则用于描述：
1. 某个费用池是什么
2. 该费用按什么维度分摊
3. 该规则当前是否启用
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import ALLOCATION_BASES
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostAllocationRule(Document):
    """海外成本分摊规则。"""

    def validate(self) -> None:
        require_value(self.batch, "所属批次")
        require_value(self.version, "所属版本")
        require_value(self.rule_code, "规则编码")
        if self.allocation_basis:
            require_in(self.allocation_basis, ALLOCATION_BASES, "分摊依据")
