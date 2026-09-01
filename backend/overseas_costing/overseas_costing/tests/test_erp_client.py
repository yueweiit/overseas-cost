from __future__ import annotations

import io
import json
from urllib.error import HTTPError

from overseas_costing.services import erp_client


def test_get_erp_push_config_prefers_single_settings(monkeypatch) -> None:
    class FakeSettings:
        def get(self, fieldname, default=None):
            return {
                "enabled": 1,
                "base_url": "https://erp.example.com/api/resource",
                "target_doctype": "Overseas Cost Push",
                "http_method": "post",
                "timeout": 30,
                "payload_field": "payload_json",
                "field_map_json": "{\"name\": \"batch_name\"}",
            }.get(fieldname, default)

        @staticmethod
        def get_password(fieldname, raise_exception=False):
            assert fieldname == "authorization"
            return "token abc:def"

    class FakeDB:
        @staticmethod
        def exists(doctype, name):
            return doctype == "DocType" and name == "Overseas Cost ERP Settings"

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_single(doctype):
            assert doctype == "Overseas Cost ERP Settings"
            return FakeSettings()

    monkeypatch.setattr(erp_client, "frappe", FakeFrappe)
    monkeypatch.setattr(erp_client.os.environ, "get", lambda key, default=None: None)

    config = erp_client.get_erp_push_config()

    assert config["base_url"] == "https://erp.example.com/api/resource"
    assert config["authorization"] == "token abc:def"
    assert config["target_doctype"] == "Overseas Cost Push"
    assert config["push_mode"] == "standard_purchase"
    assert config["method"] == "POST"
    assert config["timeout"] == 30
    assert config["field_map"] == {"name": "batch_name"}
    assert config["payload_field"] == "payload_json"


def test_check_erp_connection_uses_get_without_writing(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "target_doctype": "Overseas Cost Push",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def read():
            return json.dumps({"data": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.check_erp_connection()

    assert result["ok"] is True
    assert captured == {
        "url": "https://erp.example.com/api/resource/Overseas%20Cost%20Push?limit_page_length=1",
        "method": "GET",
        "timeout": 30,
    }


def test_push_standard_purchase_flow_creates_item_and_purchase_order(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "company": "Empresas Mexico",
            "supplier": "Default Supplier",
            "cost_center": "Main - EM",
            "item_group": "Products",
            "stock_uom": "Nos",
            "default_currency": "CNY",
            "schedule_date": "2026-08-20",
            "target_doctype": "",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    captured = []

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        captured.append({"url": request.full_url, "method": request.get_method(), "body": body, "timeout": timeout})
        if request.get_method() == "GET" and "/Purchase%20Order?" in request.full_url:
            return FakeResponse({"data": []})
        if request.get_method() == "GET" and "/Item/YL000001" in request.full_url:
            raise HTTPError(request.full_url, 404, "Not Found", None, io.BytesIO(b"{}"))
        if request.get_method() == "POST" and request.full_url.endswith("/Item"):
            return FakeResponse({"data": {"name": "YL000001"}})
        if request.get_method() == "POST" and request.full_url.endswith("/Purchase%20Order"):
            return FakeResponse({"data": {"name": "PO-0001"}})
        raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.push_overseas_cost_payload(
        {
            "batch_no": "BATCH-001",
            "version_code": "V1",
            "subsidiary_code": "Empresas Mexico",
            "total_cost_rmb": 25,
            "items": [
                {
                    "material_code": "YL000001",
                    "material_name": "太阳眼镜",
                    "supplier": "HUAFON",
                    "purchase_currency": "RMB",
                    "source_quantity": 2,
                    "original_unit_price": 8,
                    "comprehensive_unit_price": 12.5,
                    "cost_formula": {
                        "goods_value": 16,
                        "total_cost": 25,
                        "allocated_logistics_cost": 6,
                    },
                    "expense_detail": {
                        "logistics": {"freight_alloc_rmb": 6},
                        "clearance_and_tax": {"clearance_alloc_rmb": 2, "tax_alloc_rmb": 1},
                    },
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["erp_target_doc"] == "PO-0001"
    item_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Item"))
    po_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Purchase%20Order"))
    assert item_body["item_code"] == "YL000001"
    assert item_body["custom_overseas_supplier"] == "HUAFON"
    assert item_body["custom_overseas_comprehensive_unit_price"] == 12.5
    assert po_body["company"] == "Empresas Mexico"
    assert po_body["supplier"] == "HUAFON"
    assert po_body["custom_overseas_supplier_source"] == "item"
    assert po_body["currency"] == "CNY"
    assert po_body["items"][0]["rate"] == 8
    assert po_body["items"][0]["custom_overseas_comprehensive_amount"] == 25
    assert po_body["items"][0]["custom_overseas_freight_alloc_amount"] == 6
    assert po_body["items"][0]["custom_overseas_clearance_alloc_amount"] == 2
    assert po_body["items"][0]["custom_overseas_tax_alloc_amount"] == 1
    assert po_body["items"][0]["custom_overseas_cost_center"] == "Main - EM"
    assert all("valuation_rate" not in (row["body"] or {}) for row in captured)


def test_purchase_order_item_reconciles_displayed_cost_amounts() -> None:
    row = erp_client._build_purchase_order_item(
        {
            "material_code": "YL000001",
            "cost_formula": {"goods_value": 107968.413496, "total_cost": 146743.38825},
            "expense_detail": {
                "logistics": {"freight_alloc_rmb": 9619.873947},
                "clearance_and_tax": {"clearance_alloc_rmb": 29155.100807, "tax_alloc_rmb": 0},
            },
        },
        {"batch_no": "BATCH-001"},
        {"stock_uom": "Nos"},
        "2026-09-01",
    )

    assert row["custom_overseas_comprehensive_amount"] == 146743.39
    assert row["custom_overseas_clearance_alloc_amount"] == 29155.11
    assert sum(
        row[fieldname]
        for fieldname in (
            "custom_overseas_original_amount",
            "custom_overseas_freight_alloc_amount",
            "custom_overseas_clearance_alloc_amount",
            "custom_overseas_tax_alloc_amount",
        )
    ) == row["custom_overseas_comprehensive_amount"]


def test_standard_purchase_flow_uses_default_supplier_when_item_suppliers_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "company": "Empresas Mexico",
            "supplier": "Default Supplier",
            "cost_center": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "default_currency": "CNY",
            "schedule_date": "2026-08-20",
            "target_doctype": "",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    captured = []

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        captured.append({"url": request.full_url, "method": request.get_method(), "body": body})
        if request.get_method() == "GET" and "/Purchase%20Order?" in request.full_url:
            return FakeResponse({"data": []})
        if request.get_method() == "GET" and "/Item/" in request.full_url:
            raise HTTPError(request.full_url, 404, "Not Found", None, io.BytesIO(b"{}"))
        if request.get_method() == "POST" and request.full_url.endswith("/Item"):
            return FakeResponse({"data": {"name": body["item_code"]}})
        if request.get_method() == "POST" and request.full_url.endswith("/Purchase%20Order"):
            return FakeResponse({"data": {"name": "PO-0002"}})
        raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.push_overseas_cost_payload(
        {
            "batch_no": "BATCH-002",
            "version_code": "V1",
            "subsidiary_code": "Empresas Mexico",
            "items": [
                {"material_code": "A001", "material_name": "A", "supplier": "Supplier A", "source_quantity": 1, "original_unit_price": 1},
                {"material_code": "B001", "material_name": "B", "supplier": "Supplier B", "source_quantity": 1, "original_unit_price": 1},
            ],
        }
    )

    po_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Purchase%20Order"))
    assert result["ok"] is True
    assert po_body["supplier"] == "Default Supplier"
    assert po_body["custom_overseas_supplier_source"] == "config"


def test_validate_payload_for_push_blocks_missing_supplier_in_standard_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "supplier": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "timeout": 30,
            "target_doctype": "",
            "method": "POST",
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    result = erp_client.validate_payload_for_push({"items": [{"material_code": "A001"}]})

    assert result["ok"] is False
    assert result["config_ready"] is False
    assert "缺少默认供应商配置" in result["blocking_reasons"]
    assert result["request"]["authorization_configured"] is True


def test_validate_payload_for_push_accepts_payload_supplier_in_standard_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "supplier": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "timeout": 30,
            "target_doctype": "",
            "method": "POST",
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    result = erp_client.validate_payload_for_push({"supplier": "HUAFON", "items": [{"material_code": "A001"}]})

    assert result["ok"] is True
    assert result["config_ready"] is True
    assert result["blocking_reasons"] == []


def test_normalize_currency_accepts_historical_chinese_labels() -> None:
    assert erp_client._normalize_currency("人民币RMB") == "CNY"
    assert erp_client._normalize_currency("美元 USD") == "USD"
    assert erp_client._normalize_currency("墨西哥比索MXN") == "MXN"
