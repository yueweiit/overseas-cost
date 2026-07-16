"""
中文用途：海外成本版本单控制器。

版本单负责记录：
1. 暂估版 / 实际版 / 调整版
2. 汇率快照
3. 规则快照
4. 当前版本标记
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import VERSION_SOURCE_TYPES, VERSION_TYPES
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostVersion(Document):
    """海外成本版本单。"""

    def validate(self) -> None:
        require_value(self.batch, "所属批次")
        require_value(self.version_code, "版本编码")
        if self.version_type:
            require_in(self.version_type, VERSION_TYPES, "版本类型")
        if self.source_type:
            require_in(self.source_type, VERSION_SOURCE_TYPES, "版本来源类型")
