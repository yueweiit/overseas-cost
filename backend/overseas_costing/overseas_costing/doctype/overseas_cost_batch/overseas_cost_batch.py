"""
中文用途：海外成本批次主单控制器。

主单负责记录：
1. 批次号、报关单号、运单号、运输方式
2. OA / Excel 导入来源追溯信息
3. 当前版本、确认状态、回写状态
4. 汇总金额、重量、明细数量
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import (
    BATCH_CONFIRM_STATUSES,
    BATCH_SOURCE_TYPES,
    BATCH_STATUSES,
    BATCH_WRITEBACK_STATUSES,
    BUSINESS_TYPES,
    TRANSPORT_MODES,
)
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostBatch(Document):
    """海外成本批次主单。"""

    def validate(self) -> None:
        require_value(self.batch_no, "批次号")
        if self.transport_mode:
            require_in(self.transport_mode, TRANSPORT_MODES, "运输方式")
        if self.business_type:
            require_in(self.business_type, BUSINESS_TYPES, "业务类型")
        if self.source_type:
            require_in(self.source_type, BATCH_SOURCE_TYPES, "来源类型")
        if self.status:
            require_in(self.status, BATCH_STATUSES, "批次状态")
        if self.confirm_status:
            require_in(self.confirm_status, BATCH_CONFIRM_STATUSES, "确认状态")
        if self.writeback_status:
            require_in(self.writeback_status, BATCH_WRITEBACK_STATUSES, "回写状态")
