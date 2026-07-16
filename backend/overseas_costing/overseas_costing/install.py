"""
中文用途：应用安装初始化文件。

当前只放一个最小 after_install 钩子占位，
后续可在这里补：
1. 初始化系统配置
2. 初始化默认分摊规则
3. 初始化状态字典
"""

from __future__ import annotations


def after_install() -> None:
    """中文用途：Frappe 安装 app 后的初始化入口。"""

