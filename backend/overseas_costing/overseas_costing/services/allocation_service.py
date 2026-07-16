"""
中文用途：分摊规则服务。

后续这里会集中承接：
1. 按货值分摊
2. 按重量分摊
3. 按体积分摊
4. 多费用池、多规则组合分摊
"""

from __future__ import annotations


def get_supported_allocation_bases() -> list[dict]:
    return [
        {"code": "goods_value", "label": "按货值分摊"},
        {"code": "gross_weight", "label": "按重量分摊"},
        {"code": "volume", "label": "按体积分摊"},
    ]
