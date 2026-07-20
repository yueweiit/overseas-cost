"""中文用途：商品品类归类 API。"""

from __future__ import annotations

import frappe

from overseas_costing.services import category_service


@frappe.whitelist()
def preview_batch_categories(batch_name: str | None = None, version_name: str | None = None, rows_json: str | None = None, limit: int | str = 200) -> dict:
    """返回商品品类归类预览，不写库。"""

    return category_service.preview_batch_categories(
        batch_name=batch_name,
        version_name=version_name,
        rows_json=rows_json,
        limit=limit,
    )
