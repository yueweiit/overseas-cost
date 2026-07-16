"""
中文用途：Frappe 桌面模块配置文件。

后续如果要在 ERP 桌面或模块页中展示“海外采购综合成本核算”，
可以从这里配置图标、标签和入口。
"""

from __future__ import annotations


def get_data() -> list[dict]:
    """返回桌面模块配置。"""

    return [
        {
            "module_name": "Overseas Costing",
            "type": "module",
            "label": "海外采购综合成本核算",
        }
    ]
