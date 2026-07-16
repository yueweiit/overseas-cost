"""
中文用途：版本服务。

后续这里主要负责：
1. 版本复制
2. 当前版本切换
3. 版本摘要快照
4. 暂估版 / 实际版 的生命周期管理
"""

from __future__ import annotations


def build_empty_summary_snapshot() -> dict:
    return {
        "total_goods_value": 0,
        "total_gross_weight_kg": 0,
        "total_logistics_cost_rmb": 0,
        "total_cost_rmb": 0,
        "item_count": 0,
    }
