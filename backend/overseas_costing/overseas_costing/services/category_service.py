"""中文用途：商品品类归类预览服务。

第一版先做“规则优先 + AI 可接入”的建议结果，不直接回写商品明细。
后续接真实 AI 时，只替换 `_suggest_category` 的兜底分支即可。
"""

from __future__ import annotations

import json
import re
from typing import Any

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

STANDARD_CATEGORIES = [
    {
        "category": "太阳眼镜",
        "aliases": ("墨镜", "太阳镜", "太阳眼镜", "sunglasses", "gafas de sol", "lentes de sol"),
        "hs_prefixes": ("9004",),
    },
    {
        "category": "钢化膜",
        "aliases": ("钢化膜", "tempered film", "mica de celular", "screen protector", "protector de pantalla"),
        "hs_prefixes": (),
    },
    {
        "category": "服装",
        "aliases": ("衣服", "裤子", "上衣", "外套", "服装", "camiseta", "pantalon", "pantalón", "ropa"),
        "hs_prefixes": ("61", "62"),
    },
    {
        "category": "彩妆",
        "aliases": ("口红", "唇膏", "化妆品", "彩妆", "lipstick", "makeup", "cosmetic", "cosmetico", "cosmético"),
        "hs_prefixes": ("3304",),
    },
    {
        "category": "手机配件",
        "aliases": ("手机壳", "数据线", "充电器", "phone case", "cable", "charger", "funda"),
        "hs_prefixes": (),
    },
    {
        "category": "包装材料",
        "aliases": ("包装袋", "纸箱", "编织袋", "包装材料", "packing", "carton", "cartón", "bag", "bolsa"),
        "hs_prefixes": ("3923", "4819"),
    },
    {
        "category": "TPU原材料",
        "aliases": ("tpu", "热塑性聚氨酯", "聚氨酯", "poliuretano", "polyurethane"),
        "hs_prefixes": ("390950",),
    },
    {
        "category": "磁铁",
        "aliases": ("磁铁", "magnet", "imán", "iman"),
        "hs_prefixes": ("8505",),
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
        "taxonomy": [row["category"] for row in STANDARD_CATEGORIES],
        "message": "商品品类归类预览已生成。",
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
    suggestion = _suggest_category(row)
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


def _suggest_category(row: dict) -> dict:
    haystack = _category_haystack(row)
    hs_code = _normalize_hs_code(row.get("hs_code"))
    scored: list[dict[str, Any]] = []

    for definition in STANDARD_CATEGORIES:
        alias_hits = _alias_hits(haystack, definition.get("aliases") or ())
        hs_hit = bool(hs_code and any(hs_code.startswith(prefix) for prefix in definition.get("hs_prefixes") or ()))
        if not alias_hits and not hs_hit:
            continue

        confidence = 0.62
        reasons = []
        if alias_hits:
            confidence += min(0.28, 0.18 * len(alias_hits))
            reasons.append(f"命中关键词：{'、'.join(alias_hits[:3])}")
        if hs_hit:
            confidence += 0.2
            reasons.append(f"海关编码 {hs_code} 命中品类范围")
        confidence = min(0.98, round(confidence, 2))
        scored.append(
            {
                "suggested_category": definition["category"],
                "confidence": confidence,
                "reason": "；".join(reasons),
                "match_type": "rule_keyword_hs" if alias_hits and hs_hit else ("rule_hs" if hs_hit else "rule_keyword"),
            }
        )

    if scored:
        best = sorted(scored, key=lambda item: item["confidence"], reverse=True)[0]
        best["needs_review"] = best["confidence"] < 0.78
        best["ai_ready"] = False
        return best

    return {
        "suggested_category": "",
        "confidence": 0.0,
        "reason": "规则未命中，建议交给 AI 根据品名、规格、海关编码综合判断。",
        "match_type": "ai_pending",
        "needs_review": True,
        "ai_ready": True,
    }


def _category_haystack(row: dict) -> str:
    parts = [
        row.get("material_code"),
        row.get("product_name"),
        row.get("product_name_es"),
        row.get("import_name"),
        row.get("spec_model"),
        row.get("category"),
        row.get("source_doc_no"),
    ]
    return _normalize_text(" ".join(str(part) for part in parts if part not in (None, "")))


def _alias_hits(haystack: str, aliases: tuple[str, ...]) -> list[str]:
    hits = []
    for alias in aliases:
        normalized_alias = _normalize_text(alias)
        if normalized_alias and normalized_alias in haystack:
            hits.append(alias)
    return hits


def _normalize_text(value: str) -> str:
    text = str(value or "").lower()
    return re.sub(r"[\s\-_()/\\,，.。;；:：]+", "", text)


def _normalize_hs_code(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_limit(limit, default: int = 200, maximum: int = 1000) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _summarize_suggestions(items: list[dict]) -> dict:
    category_counts: dict[str, int] = {}
    needs_review_count = 0
    ai_ready_count = 0
    for item in items:
        category = item.get("suggested_category") or "未识别"
        category_counts[category] = category_counts.get(category, 0) + 1
        if item.get("needs_review"):
            needs_review_count += 1
        if item.get("ai_ready"):
            ai_ready_count += 1
    return {
        "item_count": len(items),
        "category_counts": category_counts,
        "needs_review_count": needs_review_count,
        "ai_ready_count": ai_ready_count,
    }
