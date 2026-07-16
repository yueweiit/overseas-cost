"""
中文用途：基础参数校验工具。

当前先放轻量级校验函数，
后续前后端接口统一从这里复用。
"""

from __future__ import annotations


def require_value(value, field_label: str) -> None:
    if value in (None, ""):
        raise ValueError(f"{field_label} 不能为空")


def require_in(value: str, allowed: tuple[str, ...], field_label: str) -> None:
    if value not in allowed:
        raise ValueError(f"{field_label} 不合法，当前值：{value}")
