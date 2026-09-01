"""
中文用途：编辑、重算、版本切换相关 API。

当前一期重点接口：
1. 单字段编辑
2. 批量编辑
3. 重算
4. 更新分摊规则
5. 创建版本
6. 切换版本
"""

from __future__ import annotations

import frappe

from overseas_costing.services import calculate_service


@frappe.whitelist()
def update_item_field(
    item_name: str,
    fieldname: str,
    value: str,
    version_name: str | None = None,
    remark: str | None = None,
    manual_override_reason: str | None = None,
) -> dict:
    """更新单行明细中的某个字段。"""

    return calculate_service.update_item_field(
        item_name=item_name,
        fieldname=fieldname,
        value=value,
        version_name=version_name,
        remark=remark,
        manual_override_reason=manual_override_reason,
    )


@frappe.whitelist()
def batch_update_items(
    batch_name: str,
    updates: str,
    version_name: str | None = None,
    remark: str | None = None,
) -> dict:
    """批量更新批次明细字段。"""

    return calculate_service.batch_update_items(
        batch_name=batch_name,
        updates=updates,
        version_name=version_name,
        remark=remark,
    )


@frappe.whitelist()
def confirm_actual_shipped_qty_from_quantity(
    batch_name: str,
    version_name: str | None = None,
    remark: str | None = None,
) -> dict:
    """按采购数量批量确认缺失的实际发货数量。"""

    return calculate_service.confirm_actual_shipped_qty_from_quantity(
        batch_name=batch_name,
        version_name=version_name,
        remark=remark,
    )


@frappe.whitelist()
def create_item(
    batch_name: str,
    item_payload: str | None = None,
    version_name: str | None = None,
    remark: str | None = None,
) -> dict:
    """在当前批次版本下新增一条物料明细。"""

    return calculate_service.create_item(
        batch_name=batch_name,
        item_payload=item_payload,
        version_name=version_name,
        remark=remark,
    )


@frappe.whitelist()
def delete_item(
    item_name: str,
    batch_name: str | None = None,
    version_name: str | None = None,
    remark: str | None = None,
) -> dict:
    """删除一条物料明细，并写审计日志。"""

    return calculate_service.delete_item(
        item_name=item_name,
        batch_name=batch_name,
        version_name=version_name,
        remark=remark,
    )


@frappe.whitelist()
def delete_batch(batch_name: str, remark: str | None = None) -> dict:
    """删除一个批次及其关联明细、版本、规则、附件和修改记录。"""

    return calculate_service.delete_batch(batch_name=batch_name, remark=remark)


@frappe.whitelist()
def recalculate_batch(batch_name: str, version_name: str | None = None) -> dict:
    """触发整票重算。"""

    return calculate_service.recalculate_batch(batch_name=batch_name, version_name=version_name)


@frappe.whitelist()
def update_allocation_rule(batch_name: str, version_name: str, rule_payload: str) -> dict:
    """更新分摊规则。"""

    return calculate_service.update_allocation_rule(
        batch_name=batch_name,
        version_name=version_name,
        rule_payload=rule_payload,
    )


@frappe.whitelist()
def create_version(batch_name: str, source_version_name: str, version_type: str) -> dict:
    """基于现有版本创建新版本。"""

    return calculate_service.create_version(
        batch_name=batch_name,
        source_version_name=source_version_name,
        version_type=version_type,
    )


@frappe.whitelist()
def switch_version(batch_name: str, target_version_name: str) -> dict:
    """切换当前版本。"""

    return calculate_service.switch_version(
        batch_name=batch_name,
        target_version_name=target_version_name,
    )
