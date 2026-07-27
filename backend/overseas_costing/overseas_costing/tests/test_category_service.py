"""中文用途：商品品类归类服务测试。"""

import json

from overseas_costing.services.category_service import preview_batch_categories


def test_preview_batch_categories_suggests_explicit_sunglasses_name_normalization() -> None:
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
    assert item["suggested_name"] == "太阳眼镜"
    assert item["match_type"] == "explicit_name_alias"
    assert item["needs_review"] is True


def test_preview_batch_categories_keeps_canonical_name_without_a_suggestion() -> None:
    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "material_code": "FL004112",
                    "product_name": "太阳眼镜",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["suggested_category"] == ""
    assert item["match_type"] == "no_action"
    assert item["no_action"] is True


def test_preview_batch_categories_keeps_ordinary_products_out_of_name_normalization() -> None:
    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "material_code": "AB123",
                    "product_name": "宠物拾便袋",
                    "product_name_es": "Bolsas para Desechos de Mascotas",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["suggested_category"] == ""
    assert item["match_type"] == "no_action"
    assert item["no_action"] is True
    assert result["summary"]["normalization_candidate_count"] == 0


def test_preview_batch_categories_does_not_classify_by_hs_code_only() -> None:
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
    assert item["suggested_category"] == ""
    assert item["match_type"] == "no_action"
