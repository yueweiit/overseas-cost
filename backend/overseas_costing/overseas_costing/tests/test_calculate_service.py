"""中文用途：重算服务测试。"""

import json

from overseas_costing.services.calculate_service import (
    batch_update_items,
    calculate_item_rows,
    create_item,
    delete_batch,
    delete_item,
    update_item_field,
)


def test_calculate_item_rows_allocates_by_goods_value_and_weight() -> None:
    items = [
        {
            "name": "ITEM-1",
            "unit_price": 10,
            "quantity": 10,
            "goods_value": 100,
            "gross_weight_kg": 20,
            "mexico_customs_rmb": 10,
        },
        {
            "name": "ITEM-2",
            "unit_price": 5,
            "quantity": 20,
            "goods_value": 100,
            "gross_weight_kg": 30,
            "mexico_customs_rmb": 10,
        },
    ]
    rules = [
        {
            "rule_code": "china_misc_rmb",
            "allocation_basis": "goods_value",
            "currency": "RMB",
            "amount": 20,
            "is_enabled": 1,
        },
        {
            "rule_code": "china_to_mexico_freight_rmb",
            "allocation_basis": "gross_weight",
            "currency": "RMB",
            "amount": 50,
            "is_enabled": 1,
        },
    ]

    rows, summary = calculate_item_rows(items, rules, fx_rmb_to_mxn=2.6)

    assert summary["total_goods_value"] == 200
    assert summary["total_gross_weight_kg"] == 50
    assert rows[0]["goods_value_ratio"] == 50
    assert rows[0]["weight_ratio"] == 40
    assert rows[0]["freight_alloc_rmb"] == 20
    assert rows[1]["freight_alloc_rmb"] == 30
    assert rows[0]["total_cost_rmb"] == 140
    assert rows[0]["total_unit_rmb"] == 14


def test_update_item_field_dry_run_allows_editable_field_and_coerces_numeric_value() -> None:
    result = update_item_field(
        item_name="ITEM-1",
        fieldname="quantity",
        value="12.5",
        remark="修正装箱单数量",
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["changed"] is True
    assert result["value"] == 12.5
    assert result["manual_override_reason"] == "修正装箱单数量"


def test_update_item_field_dry_run_rejects_calculated_field_without_reason() -> None:
    result = update_item_field(
        item_name="ITEM-1",
        fieldname="total_cost_rmb",
        value="100",
    )

    assert result["ok"] is False
    assert result["edit_mode"] == "reason_required"
    assert "人工覆盖需要填写修改原因" in result["message"]


def test_update_item_field_dry_run_allows_special_override_with_reason() -> None:
    result = update_item_field(
        item_name="ITEM-1",
        fieldname="total_cost_rmb",
        value="100",
        manual_override_reason="财务手工确认",
    )

    assert result["ok"] is True
    assert result["edit_mode"] == "special_override"
    assert result["value"] == 100


def test_update_item_field_dry_run_rejects_readonly_calc_field() -> None:
    result = update_item_field(
        item_name="ITEM-1",
        fieldname="freight_alloc_rmb",
        value="10",
        remark="测试",
    )

    assert result["ok"] is False
    assert result["edit_mode"] == "readonly_calc"


def test_batch_update_items_dry_run_counts_success_and_errors() -> None:
    updates = json.dumps(
        [
            {"item_name": "ITEM-1", "field_name": "quantity", "field_value": "12"},
            {"item_name": "ITEM-2", "fieldname": "freight_alloc_rmb", "value": "1"},
        ],
        ensure_ascii=False,
    )

    result = batch_update_items(batch_name="BATCH-001", updates=updates)

    assert result["ok"] is False
    assert result["dry_run"] is True
    assert result["changed_count"] == 1
    assert result["error_count"] == 1
    assert result["results"][0]["ok"] is True
    assert result["results"][1]["edit_mode"] == "readonly_calc"


def test_create_item_dry_run_builds_insert_payload() -> None:
    result = create_item(
        batch_name="BATCH-001",
        version_name="VERSION-001",
        item_payload=json.dumps(
            {
                "material_code": "NEW-001",
                "product_name": "新增物料",
                "unit_price": "2.5",
                "quantity": "4",
                "transport_mode": "海运",
            },
            ensure_ascii=False,
        ),
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["item"]["material_code"] == "NEW-001"
    assert result["item"]["goods_value"] == 10
    assert result["item"]["transport_mode"] == "SEA"


def test_delete_item_dry_run_returns_preview() -> None:
    result = delete_item(item_name="ITEM-1", batch_name="BATCH-001", version_name="VERSION-001")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["item_name"] == "ITEM-1"


def test_delete_batch_dry_run_returns_preview() -> None:
    result = delete_batch(batch_name="BATCH-001")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["batch_name"] == "BATCH-001"
