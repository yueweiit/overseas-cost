from overseas_costing.services.profit_service import calculate_profit_row, calculate_profit_rows


def test_calculate_profit_row_uses_comprehensive_cost_and_other_expense() -> None:
    result = calculate_profit_row(
        {
            "sales_quantity": 10,
            "sales_unit_price": 30,
            "sales_currency": "USD",
            "sales_fx_rate": 7,
            "total_unit_rmb": 150,
            "other_sales_expense_rmb": 20,
        }
    )

    assert result["sales_amount"] == 300
    assert result["sales_amount_rmb"] == 2100
    assert result["sales_cost_rmb"] == 1500
    assert result["gross_profit_rmb"] == 600
    assert result["profit_rmb"] == 580
    assert result["profit_margin"] == 27.619048
    assert result["profit_status"] == "CALCULATED"


def test_profit_summary_stays_pending_when_sales_data_is_missing() -> None:
    rows, summary = calculate_profit_rows(
        [
            {"sales_quantity": 0, "sales_unit_price": 0, "total_unit_rmb": 10},
            {"sales_quantity": 2, "sales_unit_price": 20, "sales_currency": "RMB", "total_unit_rmb": 10},
        ]
    )

    assert rows[0]["profit_status_label"] == "待补销售数据"
    assert summary["item_count"] == 2
    assert summary["calculated_count"] == 1
    assert summary["pending_count"] == 1
    assert summary["sales_amount_rmb"] == 40
    assert summary["profit_rmb"] == 20
    assert summary["status"] == "PENDING"
