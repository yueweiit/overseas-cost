"""
中文用途：Frappe 页面后端入口文件。

当前先预留页面后端入口，
后续正式接入 ERP 时可从这里：
1. 提供页面上下文
2. 注册页面资源
3. 对接前端整表页面
"""

from __future__ import annotations


def get_context(context: dict) -> dict:
    context.update(
        {
            "page_title": "海外采购综合成本核算",
            "module_name": "Overseas Costing",
        }
    )
    return context
