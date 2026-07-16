"""
中文用途：海外成本明细行控制器。

明细行负责记录：
1. 物料编码、产品名称、单价、数量、总货值
2. 报关/运单维度字段
3. 税费、清关费、物流费、重量与分摊结果
4. 原始导入备注与 Excel 映射快照
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import TRANSPORT_MODES
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostItem(Document):
    """海外成本明细行。"""

    def validate(self) -> None:
        require_value(self.batch, "所属批次")
        require_value(self.version, "所属版本")
        if not self.material_code and not self.product_name:
            raise ValueError("物料编码和产品名称至少要有一个")
        if self.transport_mode:
            require_in(self.transport_mode, TRANSPORT_MODES, "运输方式")
