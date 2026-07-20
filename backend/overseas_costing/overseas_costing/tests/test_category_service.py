"""中文用途：商品品类归类服务测试。"""

import json

from overseas_costing.services.category_service import preview_batch_categories


def test_preview_batch_categories_classifies_sunglasses_aliases() -> None:
    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "material_code": "FL004111",
                    "product_name": "墨镜",
                    "product_name_es": "gafas de sol",
                    "import_name": "sunglasses",
                    "hs_code": "",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert result["ok"] is True
    assert item["suggested_category"] == "太阳眼镜"
    assert item["confidence"] >= 0.78
    assert item["needs_review"] is False


def test_preview_batch_categories_classifies_chinese_sunglasses_alias() -> None:
    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "material_code": "FL004112",
                    "product_name": "墨镜",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["suggested_category"] == "太阳眼镜"
    assert item["needs_review"] is False


def test_preview_batch_categories_marks_unknown_rows_ai_ready() -> None:
    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "material_code": "AB123",
                    "product_name": "新奇特商品",
                    "spec_model": "未知规格",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["suggested_category"] == ""
    assert item["match_type"] == "ai_pending"
    assert item["ai_ready"] is True
    assert result["summary"]["ai_ready_count"] == 1


def test_preview_batch_categories_uses_hs_code_for_tpu_material() -> None:
    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "material_code": "YL000098",
                    "product_name": "热塑性聚氨酯弹性体",
                    "hs_code": "3909500000",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["suggested_category"] == "TPU原材料"
    assert "3909500000" in item["reason"]
