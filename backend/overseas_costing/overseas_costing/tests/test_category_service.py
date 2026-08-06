"""中文用途：商品业务归类服务测试。"""

import json

from overseas_costing.services import category_service
from overseas_costing.services.category_service import preview_batch_categories


def test_preview_batch_categories_suggests_explicit_sunglasses_business_category() -> None:
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
    assert item["suggested_business_category"] == "太阳眼镜"
    assert item["business_category"] == "太阳眼镜"
    assert item["match_type"] == "explicit_business_alias"
    assert item["needs_review"] is True
    assert item["affects_customs_fields"] is False
    assert item["affects_tax_rate"] is False
    assert "不覆盖海关进口名称" in item["calculation_policy"]


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
    assert item["suggested_business_category"] == ""
    assert item["business_category"] == ""
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
    assert result["summary"]["business_category_candidate_count"] == 0


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
    assert item["hs_code"] == "3909500000"
    assert item["affects_customs_fields"] is False
    assert item["affects_tax_rate"] is False


def test_preview_batch_categories_uses_ai_for_business_category(monkeypatch) -> None:
    monkeypatch.setattr(
        category_service.allocation_service,
        "_ai_config",
        lambda: {"api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model", "timeout": 3},
    )
    monkeypatch.setattr(
        category_service.allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "items": [
                    {
                        "item_name": "ITEM-001",
                        "action": "classify",
                        "suggested_business_category": "太阳眼镜",
                        "confidence": 0.86,
                        "reason": "英文名称 sun shade glasses 与太阳眼镜含义一致。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "name": "ITEM-001",
                    "material_code": "FL004118",
                    "product_name": "Anteojos de sol",
                    "import_name": "Sun shade eyewear",
                    "hs_code": "90041000",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["import_name"] == "Sun shade eyewear"
    assert item["hs_code"] == "90041000"
    assert item["suggested_business_category"] == "太阳眼镜"
    assert item["suggested_name"] == "太阳眼镜"
    assert item["match_type"] == "ai_business_category"
    assert item["needs_review"] is True
    assert item["ai_ready"] is True
    assert item["affects_customs_fields"] is False
    assert item["affects_tax_rate"] is False
    assert result["summary"]["ai_ready_count"] == 1
    assert result["summary"]["ai_business_category_count"] == 1
    assert result["summary"]["ai_normalization_count"] == 1


def test_preview_batch_categories_rejects_generic_ai_grouping(monkeypatch) -> None:
    monkeypatch.setattr(
        category_service.allocation_service,
        "_ai_config",
        lambda: {"api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model", "timeout": 3},
    )
    monkeypatch.setattr(
        category_service.allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "items": [
                    {
                        "item_name": "ITEM-002",
                        "action": "normalize",
                        "suggested_name": "包装材料",
                        "suggested_category": "包装材料",
                        "confidence": 0.93,
                        "reason": "包含袋子字段。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = preview_batch_categories(
        rows_json=json.dumps(
            [
                {
                    "name": "ITEM-002",
                    "material_code": "AB123",
                    "product_name": "宠物拾便袋",
                    "product_name_es": "Bolsas para Desechos de Mascotas",
                }
            ],
            ensure_ascii=False,
        )
    )

    item = result["items"][0]
    assert item["suggested_name"] == ""
    assert item["match_type"] == "no_action"
    assert item["no_action"] is True
    assert result["summary"]["ai_normalization_count"] == 0
