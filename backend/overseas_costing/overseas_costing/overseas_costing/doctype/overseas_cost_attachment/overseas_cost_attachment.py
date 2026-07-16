"""
中文用途：海外成本附件单控制器。

附件单用于记录：
1. OA / Excel / 凭证来源
2. 附件地址
3. 解析状态
4. 解析结果
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.utils.validators import require_value


class OverseasCostAttachment(Document):
    """海外成本附件单。"""

    def validate(self) -> None:
        require_value(self.batch, "所属批次")
        require_value(self.source_type, "来源类型")
