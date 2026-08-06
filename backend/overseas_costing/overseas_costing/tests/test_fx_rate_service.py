"""
中文用途：付款日汇率服务测试。
"""

import json

import pytest

from overseas_costing.services import fx_rate_service


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def close(self):
        pass


def test_normalize_payment_date_accepts_tax_certificate_date() -> None:
    assert fx_rate_service.normalize_payment_date("01/04/2026") == "2026-04-01"
    assert fx_rate_service.normalize_payment_date("2026-08-04") == "2026-08-04"


def test_resolve_fx_rate_date_prefers_real_payment_date() -> None:
    result = fx_rate_service.resolve_fx_rate_date(
        payment_date="01/04/2026",
        approval_finished_at="2026-04-21 17:16:00",
    )

    assert result["ok"] is True
    assert result["normalized_date"] == "2026-04-01"
    assert result["date_source"] == "payment_date"
    assert result["date_source_label"] == "真实付款日"
    assert result["is_estimated_rate"] is False


def test_build_fx_context_for_costing_uses_approval_finished_at_as_estimate() -> None:
    def fake_opener(request, timeout):
        if "currency=USD" in request.full_url:
            return FakeResponse({"currency": "USD", "rateDate": "2026-04-21", "cnyPerUnit": 6.9})
        if "currency=MXN" in request.full_url:
            return FakeResponse({"currency": "MXN", "rateDate": "2026-04-21", "cnyPerUnit": 0.38})
        return FakeResponse({"error": "rate_not_found", "message": "数据库中没有对应汇率"})

    result = fx_rate_service.build_fx_context_for_costing(
        payment_date="",
        approval_finished_at="2026-04-21 17:16:00",
        endpoint="http://fx.example.test/api/fx-rate",
        opener=fake_opener,
    )

    assert result["ok"] is True
    assert result["normalized_payment_date"] == ""
    assert result["normalized_approval_finished_at"] == "2026-04-21"
    assert result["normalized_fx_rate_date"] == "2026-04-21"
    assert result["fx_date_source"] == "approval_finished_at"
    assert result["fx_date_source_label"] == "付款审批完成日（暂估）"
    assert result["is_estimated_rate"] is True
    assert result["fx_usd_to_rmb"] == pytest.approx(6.9)
    assert result["fx_rmb_to_mxn"] == pytest.approx(1 / 0.38)


def test_fetch_cny_rate_uses_currency_and_payment_date() -> None:
    requested_urls = []

    def fake_opener(request, timeout):
        requested_urls.append(request.full_url)
        assert timeout == 8
        return FakeResponse(
            {
                "currency": "USD",
                "rateDate": "2026-08-04",
                "cnyPerUnit": 6.76,
                "sourceUrl": "https://example.test/fx",
                "fetchedAt": "2026-08-03 16:05:01",
            }
        )

    result = fx_rate_service.fetch_cny_rate(
        currency="美元USD",
        payment_date="2026-08-04",
        endpoint="http://fx.example.test/api/fx-rate",
        opener=fake_opener,
    )

    assert result["ok"] is True
    assert result["currency"] == "USD"
    assert result["requested_date"] == "2026-08-04"
    assert result["cny_per_unit"] == pytest.approx(6.76)
    assert "currency=USD" in requested_urls[0]
    assert "date=2026-08-04" in requested_urls[0]


def test_build_fx_context_from_payment_date_maps_legacy_version_fields() -> None:
    def fake_opener(request, timeout):
        if "currency=USD" in request.full_url:
            return FakeResponse({"currency": "USD", "rateDate": "2026-08-04", "cnyPerUnit": 6.8})
        if "currency=MXN" in request.full_url:
            return FakeResponse({"currency": "MXN", "rateDate": "2026-08-04", "cnyPerUnit": 0.4})
        return FakeResponse({"error": "rate_not_found", "message": "数据库中没有对应汇率"})

    result = fx_rate_service.build_fx_context_from_payment_date(
        "2026-08-04",
        endpoint="http://fx.example.test/api/fx-rate",
        opener=fake_opener,
    )

    assert result["ok"] is True
    assert result["fx_usd_to_rmb"] == pytest.approx(6.8)
    assert result["fx_mxn_to_rmb"] == pytest.approx(0.4)
    assert result["fx_rmb_to_mxn"] == pytest.approx(2.5)
    assert result["rate_snapshots"]["USD"]["rate_date"] == "2026-08-04"


def test_fetch_cny_rate_reports_missing_payment_date() -> None:
    result = fx_rate_service.fetch_cny_rate(currency="USD", payment_date="")

    assert result["ok"] is False
    assert result["action"] == "missing_payment_date"
