"""
中文用途：汇率与金额处理工具。

后续汇率快照、币种换算、金额保留位数等通用逻辑尽量统一在这里处理。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def round_money(value: float | int | str, places: int = 2) -> float:
    quant = Decimal("1." + ("0" * places))
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def convert_amount(amount: float | int, rate: float | int, places: int = 2) -> float:
    return round_money(float(amount) * float(rate), places=places)
