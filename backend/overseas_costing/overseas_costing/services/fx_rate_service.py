"""
中文用途：按付款日查询汇率并生成可追溯快照。

当前汇率口径：
1. 人民币不需要外部汇率，固定 1。
2. 美元、墨西哥比索优先按真实付款日查询统一汇率接口。
3. 没有真实付款日时，按付款审批完成日暂估，后续拿到真实付款日再重算。
4. 查询不到时返回明确状态，不自动猜测或覆盖版本汇率。
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_FX_RATE_API_URL = "http://8.135.70.130:3003/api/fx-rate"
DEFAULT_TIMEOUT_SECONDS = 8

FX_DATE_SOURCE_PAYMENT = "payment_date"
FX_DATE_SOURCE_APPROVAL_FINISHED = "approval_finished_at"
FX_DATE_SOURCE_MISSING = "missing"

FX_DATE_SOURCE_LABELS = {
    FX_DATE_SOURCE_PAYMENT: "真实付款日",
    FX_DATE_SOURCE_APPROVAL_FINISHED: "付款审批完成日（暂估）",
    FX_DATE_SOURCE_MISSING: "未取得汇率日期",
}


def normalize_currency_code(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "CNY"
    compact = text.replace(" ", "").upper()
    lower = text.replace(" ", "").lower()
    if any(token in compact for token in ("RMB", "CNY")) or "人民币" in text:
        return "CNY"
    if "USD" in compact or "DÓLAR" in compact or "DOLAR" in compact or "美元" in text or "美金" in text:
        return "USD"
    if "MXN" in compact or "PESO" in compact or "比索" in text or "墨西哥" in text or "pesos" in lower:
        return "MXN"
    return compact


def normalize_payment_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[年月.]", "-", text).replace("日", "")
    text = re.sub(r"\s+", " ", text).strip()
    if " " in text:
        text = text.split(" ", 1)[0]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def resolve_fx_rate_date(*, payment_date=None, approval_finished_at=None) -> dict:
    """确定本次汇率查询应该使用的日期，并保留来源说明。"""

    raw_payment_date = str(payment_date or "").strip()
    normalized_payment_date = normalize_payment_date(payment_date)
    raw_approval_finished_at = str(approval_finished_at or "").strip()
    normalized_approval_finished_at = normalize_payment_date(approval_finished_at)

    if normalized_payment_date:
        return {
            "ok": True,
            "date": raw_payment_date,
            "normalized_date": normalized_payment_date,
            "date_source": FX_DATE_SOURCE_PAYMENT,
            "date_source_label": FX_DATE_SOURCE_LABELS[FX_DATE_SOURCE_PAYMENT],
            "is_estimated_rate": False,
            "payment_date": raw_payment_date,
            "normalized_payment_date": normalized_payment_date,
            "approval_finished_at": raw_approval_finished_at,
            "normalized_approval_finished_at": normalized_approval_finished_at,
            "message": "已按真实付款日查询汇率。",
        }

    if normalized_approval_finished_at:
        return {
            "ok": True,
            "date": raw_approval_finished_at,
            "normalized_date": normalized_approval_finished_at,
            "date_source": FX_DATE_SOURCE_APPROVAL_FINISHED,
            "date_source_label": FX_DATE_SOURCE_LABELS[FX_DATE_SOURCE_APPROVAL_FINISHED],
            "is_estimated_rate": True,
            "payment_date": raw_payment_date,
            "normalized_payment_date": "",
            "approval_finished_at": raw_approval_finished_at,
            "normalized_approval_finished_at": normalized_approval_finished_at,
            "message": "未识别到真实付款日，已按付款审批完成日暂估汇率。",
        }

    return {
        "ok": False,
        "date": "",
        "normalized_date": "",
        "date_source": FX_DATE_SOURCE_MISSING,
        "date_source_label": FX_DATE_SOURCE_LABELS[FX_DATE_SOURCE_MISSING],
        "is_estimated_rate": False,
        "payment_date": raw_payment_date,
        "normalized_payment_date": "",
        "approval_finished_at": raw_approval_finished_at,
        "normalized_approval_finished_at": "",
        "message": "缺少真实付款日和付款审批完成日，未自动查询汇率。",
    }


def _api_endpoint(endpoint: str | None = None) -> str:
    return str(endpoint or os.environ.get("OVERSEAS_COST_FX_RATE_API") or DEFAULT_FX_RATE_API_URL).strip()


def _read_json(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS, opener=None) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    open_fn = opener or urlopen
    response = None
    try:
        response = open_fn(request, timeout=timeout)
        raw = response.read()
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw or "{}")


def fetch_cny_rate(
    *,
    currency,
    payment_date,
    endpoint: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener=None,
) -> dict:
    """查询单个币种在付款日的人民币汇率。"""

    currency_code = normalize_currency_code(currency)
    requested_date = normalize_payment_date(payment_date)

    if currency_code == "CNY":
        return {
            "ok": True,
            "action": "resolved",
            "currency": "CNY",
            "requested_date": requested_date,
            "rate_date": requested_date,
            "cny_per_unit": 1.0,
            "source": "builtin:CNY",
            "source_url": "builtin:CNY",
            "fetched_at": None,
            "message": "人民币固定按 1 折算。",
        }
    if currency_code not in {"USD", "MXN"}:
        return {
            "ok": False,
            "action": "unsupported_currency",
            "currency": currency_code,
            "requested_date": requested_date,
            "message": f"暂不支持币种：{currency_code}",
        }
    if not requested_date:
        return {
            "ok": False,
            "action": "missing_payment_date",
            "currency": currency_code,
            "requested_date": "",
            "message": "缺少付款日，未自动查询汇率。",
        }

    query = urlencode({"currency": currency_code, "date": requested_date})
    base_url = _api_endpoint(endpoint)
    separator = "&" if "?" in base_url else "?"
    url = f"{base_url}{separator}{query}"

    try:
        payload = _read_json(url, timeout=timeout, opener=opener)
    except HTTPError as exc:
        return {
            "ok": False,
            "action": "http_error",
            "currency": currency_code,
            "requested_date": requested_date,
            "message": f"汇率接口 HTTP 错误：{exc.code}",
        }
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "action": "request_failed",
            "currency": currency_code,
            "requested_date": requested_date,
            "message": f"汇率接口请求失败：{exc}",
        }

    if payload.get("error"):
        return {
            "ok": False,
            "action": str(payload.get("error") or "rate_not_found"),
            "currency": currency_code,
            "requested_date": requested_date,
            "rate_date": payload.get("rateDate") or payload.get("date") or "",
            "source": "fx-rate-api",
            "source_url": "",
            "fetched_at": None,
            "raw": payload,
            "message": payload.get("message") or f"付款日 {requested_date} 没有 {currency_code} 汇率。",
        }

    cny_per_unit = payload.get("cnyPerUnit")
    if cny_per_unit is None:
        cny_per_unit = payload.get("rateToCny")
    try:
        cny_per_unit = float(cny_per_unit)
    except (TypeError, ValueError):
        cny_per_unit = 0.0
    if cny_per_unit <= 0:
        return {
            "ok": False,
            "action": "invalid_rate",
            "currency": currency_code,
            "requested_date": requested_date,
            "raw": payload,
            "message": f"汇率接口返回的 {currency_code} 汇率无效。",
        }

    return {
        "ok": True,
        "action": "resolved",
        "currency": currency_code,
        "requested_date": requested_date,
        "rate_date": payload.get("rateDate") or requested_date,
        "cny_per_unit": cny_per_unit,
        "usd_per_unit": payload.get("usdPerUnit"),
        "usd_cny": payload.get("usdCny"),
        "source": "fx-rate-api",
        "source_url": payload.get("sourceUrl") or "",
        "fetched_at": payload.get("fetchedAt"),
        "rate_text": payload.get("rateText") or "",
        "raw": payload,
        "message": payload.get("rateText") or f"已取得 {currency_code} 对人民币汇率。",
    }


def build_fx_context_from_payment_date(
    payment_date,
    *,
    endpoint: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener=None,
) -> dict:
    """按付款日查询 USD、MXN 汇率，并兼容现有版本汇率字段。"""

    normalized_date = normalize_payment_date(payment_date)
    snapshots: dict[str, dict] = {}
    errors: list[dict] = []
    context: dict = {
        "ok": True,
        "action": "resolved",
        "payment_date": str(payment_date or "").strip(),
        "normalized_payment_date": normalized_date,
        "source": "fx-rate-api",
        "rate_snapshots": snapshots,
        "errors": errors,
    }

    for currency_code in ("USD", "MXN"):
        snapshot = fetch_cny_rate(
            currency=currency_code,
            payment_date=normalized_date,
            endpoint=endpoint,
            timeout=timeout,
            opener=opener,
        )
        snapshots[currency_code] = snapshot
        if not snapshot.get("ok"):
            errors.append(
                {
                    "currency": currency_code,
                    "action": snapshot.get("action"),
                    "message": snapshot.get("message"),
                }
            )
            continue
        rate = float(snapshot.get("cny_per_unit") or 0)
        if currency_code == "USD":
            context["fx_usd_to_rmb"] = round(rate, 6)
        elif currency_code == "MXN" and rate:
            context["fx_mxn_to_rmb"] = round(rate, 6)
            context["fx_rmb_to_mxn"] = round(1 / rate, 6)

    if errors:
        context["ok"] = False
        context["action"] = "partial" if len(errors) < 2 else "failed"
        context["message"] = "部分付款日汇率缺失。" if len(errors) < 2 else "付款日汇率缺失。"
    else:
        context["message"] = "付款日汇率已取得。"
    return context


def build_fx_context_for_costing(
    *,
    payment_date=None,
    approval_finished_at=None,
    endpoint: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener=None,
) -> dict:
    """按成本核算口径查询汇率：真实付款日优先，审批完成日仅作暂估。"""

    resolved_date = resolve_fx_rate_date(
        payment_date=payment_date,
        approval_finished_at=approval_finished_at,
    )
    metadata = {
        "payment_date": str(payment_date or "").strip(),
        "approval_finished_at": str(approval_finished_at or "").strip(),
        "normalized_payment_date": resolved_date.get("normalized_payment_date") or "",
        "normalized_approval_finished_at": resolved_date.get("normalized_approval_finished_at") or "",
        "fx_rate_date": resolved_date.get("date") or "",
        "normalized_fx_rate_date": resolved_date.get("normalized_date") or "",
        "fx_date_source": resolved_date.get("date_source") or FX_DATE_SOURCE_MISSING,
        "fx_date_source_label": resolved_date.get("date_source_label") or FX_DATE_SOURCE_LABELS[FX_DATE_SOURCE_MISSING],
        "is_estimated_rate": bool(resolved_date.get("is_estimated_rate")),
        "rate_date_message": resolved_date.get("message") or "",
    }

    if not resolved_date.get("ok"):
        return {
            "ok": False,
            "action": "missing_fx_rate_date",
            "source": "fx-rate-api",
            "rate_snapshots": {},
            "errors": [],
            "message": resolved_date.get("message") or "缺少汇率日期，未自动查询汇率。",
            **metadata,
        }

    query_kwargs = {}
    if endpoint is not None:
        query_kwargs["endpoint"] = endpoint
    if timeout != DEFAULT_TIMEOUT_SECONDS:
        query_kwargs["timeout"] = timeout
    if opener is not None:
        query_kwargs["opener"] = opener
    context = build_fx_context_from_payment_date(resolved_date["normalized_date"], **query_kwargs)
    message = context.get("message") or ""
    if resolved_date.get("is_estimated_rate"):
        message = f"{resolved_date['message']} {message}".strip()
    else:
        message = f"{resolved_date['message']} {message}".strip()
    context.update(metadata)
    context["message"] = message
    return context
