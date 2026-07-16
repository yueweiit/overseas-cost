"""
中文用途：汇率工具测试。
"""

from overseas_costing.utils.currency import convert_amount, round_money


def test_round_money() -> None:
    assert round_money(12.3456) == 12.35


def test_convert_amount() -> None:
    assert convert_amount(100, 7.2) == 720.0
