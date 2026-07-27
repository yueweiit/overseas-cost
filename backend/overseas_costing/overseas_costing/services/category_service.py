"""中文用途：商品名称归并预览服务。

只提示少量、证据明确的同义名称归并，例如“墨镜”统一为“太阳眼镜”。
普通商品不强行归类，也不直接回写商品明细。
"""

from __future__ import annotations

import json
import re

try:
    import frappe
except Exception:  # pragma: no cover - 本地无 Frappe 环境时保持可导入
    frappe = None


ITEM_FIELDS = [
    "name",
    "row_no",
    "material_code",
    "product_name",
    "product_name_es",
    "import_name",
    "spec_model",
    "hs_code",
    "category",
    "source_doc_no",
    "purchase_order_no",
]

NAME_NORMALIZATION_RULES = [
    {
        "canonical_name": "太阳眼镜",
        "aliases": ("墨镜", "太阳镜", "太阳眼镜", "sunglasses", "gafas de sol", "lentes de sol"),
    },
]


def preview_batch_categories(batch_name: str | None = None, version_name: str | None = None, rows_json: str | None = None, limit: int | str = 200) -> dict:
    """返回批次内商品的品类归类预览，不写库。"""

    items = _load_rows(rows_json)
    dry_run = frappe is None
    batch_doc_name = batch_name or ""
    resolved_version_name = version_name or ""

    if not items and frappe is not None:
        if not batch_name:
            return {"ok": False, "message": "缺少批次。", "items": [], "summary": {}}
        batch_doc_name = _resolve_batch_name(batch_name)
        if not batch_doc_name:
            return {"ok": False, "message": f"未找到批次：{batch_name}", "items": [], "summary": {}}
        resolved_version_name = _resolve_version_name(batch_doc_name, version_name)
        if not resolved_version_name:
            return {"ok": False, "message": "当前批次没有可归类版本。", "items": [], "summary": {}}
        items = _fetch_batch_items(batch_doc_name, resolved_version_name, _normalize_limit(limit))

    suggestions = [_build_preview_row(row) for row in items[: _normalize_limit(limit)]]
    summary = _summarize_suggestions(suggestions)
    return {
        "ok": True,
        "dry_run": dry_run,
        "batch_name": batch_doc_name,
        "version_name": resolved_version_name,
        "items": suggestions,
        "summary": summary,
        "taxonomy": [row["canonical_name"] for row in NAME_NORMALIZATION_RULES],
        "message": "商品名称归并预览已生成。",
    }


def _resolve_batch_name(batch_name: str) -> str | None:
    batch = frappe.db.get_value("Overseas Cost Batch", batch_name, ["name"], as_dict=True)
    if batch:
        return batch["name"]
    batch = frappe.db.get_value("Overseas Cost Batch", {"batch_no": batch_name}, ["name"], as_dict=True)
    if batch:
        return batch["name"]
    return None


def _resolve_version_name(batch_doc_name: str, version_name: str | None = None) -> str | None:
    if version_name:
        return version_name
    current_version = frappe.db.get_value("Overseas Cost Batch", batch_doc_name, "current_version")
    if current_version:
        return current_version
    rows = frappe.get_all(
        "Overseas Cost Version",
        filters={"batch": batch_doc_name},
        fields=["name"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return rows[0]["name"] if rows else None


def _fetch_batch_items(batch_doc_name: str, version_name: str, limit: int) -> list[dict]:
    return frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": version_name},
        fields=ITEM_FIELDS,
        order_by="row_no asc",
        limit_page_length=limit,
    )


def _load_rows(rows_json: str | None) -> list[dict]:
    if not rows_json:
        return []
    loaded = json.loads(rows_json) if isinstance(rows_json, str) else rows_json
    if isinstance(loaded, dict):
        loaded = [loaded]
    if not isinstance(loaded, list):
        raise ValueError("rows_json 必须是 JSON 对象或对象数组。")
    return [row for row in loaded if isinstance(row, dict)]


def _build_preview_row(row: dict) -> dict:
    suggestion = _suggest_name_normalization(row)
    return {
        "item_name": row.get("name") or "",
        "row_no": row.get("row_no") or "",
        "material_code": row.get("material_code") or "",
        "product_name": row.get("product_name") or "",
        "product_name_es": row.get("product_name_es") or "",
        "import_name": row.get("import_name") or "",
        "spec_model": row.get("spec_model") or "",
        "hs_code": row.get("hs_code") or "",
        "current_category": row.get("category") or "",
        **suggestion,
    }


def _suggest_name_normalization(row: dict) -> dict:
    name_fields = ("product_name", "product_name_es", "import_name", "spec_model")
    source_names = [str(row.get(field) or "").strip() for field in name_fields if str(row.get(field) or "").strip()]
    normalized_names = {_normalize_text(name) for name in source_names}

    for definition in NAME_NORMALIZATION_RULES:
        canonical_name = definition["canonical_name"]
        canonical_key = _normalize_text(canonical_name)
        alias_hits = _alias_hits(" ".join(source_names), definition.get("aliases") or ())
        if not alias_hits or canonical_key in normalized_names:
            continue
        return {
            "suggested_category": canonical_name,
            "suggested_name": canonical_name,
            "confidence": 0.95,
            "reason": f"命中同义名称：{'、'.join(alias_hits[:3])}；建议统一为“{canonical_name}”",
            "match_type": "explicit_name_alias",
            "needs_review": True,
            "ai_ready": False,
            "no_action": False,
        }

    return {
        "suggested_category": "",
        "suggested_name": "",
        "confidence": 0.0,
        "reason": "未发现需要统一名称的同义商品。",
        "match_type": "no_action",
        "needs_review": False,
        "ai_ready": False,
        "no_action": True,
    }


def _alias_hits(haystack: str, aliases: tuple[str, ...]) -> list[str]:
    normalized_haystack = _normalize_text(haystack)
    hits = []
    for alias in aliases:
        normalized_alias = _normalize_text(alias)
        if normalized_alias and normalized_alias in normalized_haystack:
            hits.append(alias)
    return hits


def _normalize_text(value: str) -> str:
    text = str(value or "").lower()
    return re.sub(r"[\s\-_()/\\,，.。;；:：]+", "", text)


def _normalize_limit(limit, default: int = 200, maximum: int = 1000) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _summarize_suggestions(items: list[dict]) -> dict:
    category_counts: dict[str, int] = {}
    needs_review_count = 0
    no_action_count = 0
    for item in items:
        category = item.get("suggested_name") or ""
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1
        if item.get("needs_review"):
            needs_review_count += 1
        if item.get("no_action"):
            no_action_count += 1
    return {
        "item_count": len(items),
        "category_counts": category_counts,
        "needs_review_count": needs_review_count,
        "normalization_candidate_count": needs_review_count,
        "no_action_count": no_action_count,
        "ai_ready_count": 0,
    }
