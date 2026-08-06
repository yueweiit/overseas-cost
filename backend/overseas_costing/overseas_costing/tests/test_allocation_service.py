"""中文用途：AI 基础分摊填入服务测试。"""

import json
from unittest.mock import mock_open

from overseas_costing.services import allocation_service


def test_ai_allocation_suggestion_keeps_candidate_amount_and_enforces_transport_basis(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "summary": "海运费按体积更合理。",
                "rules": [
                    {
                        "rule_code": "china_ocean_usd",
                        "allocation_basis": "volume",
                        "reason": "海运柜货有体积数据，按空间占用分摊。",
                        "confidence": 0.82,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 20, "volume_m3": 3, "transport_mode": "SEA"},
            {"row_no": 2, "goods_value": 200, "gross_weight_kg": 10, "volume_m3": 7, "transport_mode": "SEA"},
        ],
        candidate_rules=[
            {
                "rule_code": "china_ocean_usd",
                "expense_category": "中国海运费",
                "allocation_basis": "gross_weight",
                "currency": "USD",
                "amount": 500,
                "is_enabled": 1,
            }
        ],
        context={"batch_name": "BATCH-001"},
    )

    assert result["ok"] is True
    assert result["source"] == "ai"
    assert result["rules"][0]["amount"] == 500
    assert result["rules"][0]["currency"] == "USD"
    assert result["rules"][0]["allocation_basis"] == "gross_weight"
    assert result["rules"][0]["is_ai_suggestion"] == 1
    assert "AI基础分摊填入" in result["rules"][0]["remark"]
    assert "默认先按毛重" in result["rules"][0]["remark"]


def test_ai_allocation_suggestion_skips_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {"api_key": "", "base_url": "https://example.test/v1", "model": "test-model", "timeout": 3},
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[],
        candidate_rules=[{"rule_code": "fee", "amount": 10, "currency": "RMB"}],
        context={},
    )

    assert result["ok"] is False
    assert result["action"] == "skipped"
    assert "未配置 AI 接口密钥" in result["reason"]


def test_ai_config_uses_deepseek_defaults_when_key_exists(monkeypatch) -> None:
    monkeypatch.setattr(allocation_service, "_conf_value", lambda _key: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("OVERSEAS_COST_AI_API_KEY", raising=False)
    monkeypatch.delenv("OVERSEAS_COST_AI_BASE_URL", raising=False)
    monkeypatch.delenv("OVERSEAS_COST_AI_MODEL", raising=False)

    config = allocation_service._ai_config()

    assert config["api_key"] == "test-key"
    assert config["base_url"] == "https://api.deepseek.com"
    assert config["model"] == "deepseek-v4-flash"


def test_ai_payload_and_rule_remark_expose_missing_basis_data(monkeypatch) -> None:
    captured_messages = []
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )

    def fake_call(_config, messages):
        captured_messages.extend(messages)
        return json.dumps(
            {
                "rules": [
                    {
                        "rule_code": "service_fee",
                        "allocation_basis": "gross_weight",
                        "reason": "服务费按重量分摊，毛重数据完整。",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(allocation_service, "_call_chat_completions", fake_call)
    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 20},
            {"row_no": 2, "goods_value": 100, "gross_weight_kg": 0},
        ],
        candidate_rules=[{"rule_code": "service_fee", "amount": 100, "currency": "RMB"}],
        context={},
    )

    prompt_payload = json.loads(captured_messages[1]["content"])["data"]
    assert prompt_payload["totals"]["missing_gross_weight_count"] == 1
    assert result["rules"][0]["basis_missing_count"] == 1
    assert "1 行缺少重量" in result["rules"][0]["remark"]
    assert "毛重数据完整" not in result["rules"][0]["remark"]


def test_ai_allocation_supports_chargeable_weight_when_gross_weight_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "rules": [
                    {
                        "rule_code": "china_to_mexico_freight_rmb",
                        "allocation_basis": "chargeable_weight",
                        "reason": "运输费按计费重分摊，重货和抛货取较大值。",
                        "confidence": 0.88,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 0, "volume_weight_kg": 35},
            {"row_no": 2, "goods_value": 100, "gross_weight_kg": 0, "volume_weight_kg": 20},
        ],
        candidate_rules=[{"rule_code": "china_to_mexico_freight_rmb", "amount": 100, "currency": "RMB"}],
        context={},
    )

    assert result["ok"] is True
    assert result["rules"][0]["allocation_basis"] == "chargeable_weight"
    assert "缺少计费重" not in result["rules"][0]["remark"]


def test_ai_transport_basis_is_enforced_to_confirmed_gross_weight_first(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "rules": [
                    {
                        "rule_code": "oa_sea_freight_rmb",
                        "allocation_basis": "gross_weight",
                        "reason": "海运费按毛重分摊。",
                        "confidence": 0.7,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 10, "volume_weight_kg": 35},
            {"row_no": 2, "goods_value": 100, "gross_weight_kg": 20, "volume_weight_kg": 0},
        ],
        candidate_rules=[{"rule_code": "oa_sea_freight_rmb", "amount": 100, "currency": "RMB"}],
        context={},
    )

    assert result["rules"][0]["allocation_basis"] == "gross_weight"
    assert "默认先按毛重" in result["rules"][0]["remark"]


def test_conf_value_reads_site_config_when_frappe_conf_is_stale(monkeypatch) -> None:
    class FakeFrappe:
        conf = {}

        @staticmethod
        def get_site_path(*parts):
            return "/fake-site/" + "/".join(parts)

    monkeypatch.setattr(allocation_service, "frappe", FakeFrappe)
    monkeypatch.setattr("builtins.open", mock_open(read_data='{"overseas_cost_ai_api_key":"file-key"}'))

    assert allocation_service._conf_value("overseas_cost_ai_api_key") == "file-key"
