"""
中文用途：导入相关 API。

当前一期先占住两个入口：
1. 导入主表并生成批次
2. 上传附件并登记解析任务
"""

from __future__ import annotations

import frappe

from overseas_costing.services import import_service


@frappe.whitelist()
def import_main_excel(
    source_name: str,
    source_type: str = "excel",
    transport_mode: str = "SEA",
    source_sheet: str | None = None,
    project_collection: str | None = None,
    version_type: str = "Estimated",
    blocks_json: str | None = None,
    fx_usd_to_rmb: float | None = None,
    fx_rmb_to_mxn: float | None = None,
) -> dict:
    """导入主表并生成批次。"""

    return import_service.import_main_excel(
        source_name=source_name,
        source_type=source_type,
        transport_mode=transport_mode,
        source_sheet=source_sheet,
        project_collection=project_collection,
        version_type=version_type,
        blocks_json=blocks_json,
        fx_usd_to_rmb=fx_usd_to_rmb,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
    )


@frappe.whitelist()
def import_parsed_excel_blocks(
    source_name: str,
    blocks_json: str,
    source_sheet: str | None = None,
    transport_keyword: str = "",
    include_double_clear=0,
    batch_ids: str | None = None,
    limit: int | None = None,
    project_collection: str | None = None,
    version_type: str = "Estimated",
    fx_usd_to_rmb: float | None = None,
    fx_rmb_to_mxn: float | None = None,
) -> dict:
    """导入已解析 Excel block JSON，支持按一期范围筛选。"""

    return import_service.import_parsed_excel_blocks(
        source_name=source_name,
        blocks_json=blocks_json,
        source_sheet=source_sheet,
        transport_keyword=transport_keyword,
        include_double_clear=include_double_clear,
        batch_ids=batch_ids,
        limit=limit,
        project_collection=project_collection,
        version_type=version_type,
        fx_usd_to_rmb=fx_usd_to_rmb,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
    )


@frappe.whitelist()
def import_yuewei_excel_file(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    source_sheet: str | None = None,
    transport_keyword: str = "",
    include_double_clear=0,
    batch_ids: str | None = None,
    limit: int | None = None,
    project_collection: str | None = None,
    version_type: str = "Estimated",
    fx_usd_to_rmb: float | None = None,
    fx_rmb_to_mxn: float | None = None,
) -> dict:
    """导入真实 Yuewei 成本总表 xlsx 文件。"""

    return import_service.import_yuewei_excel_file(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        source_sheet=source_sheet,
        transport_keyword=transport_keyword,
        include_double_clear=include_double_clear,
        batch_ids=batch_ids,
        limit=limit,
        project_collection=project_collection,
        version_type=version_type,
        fx_usd_to_rmb=fx_usd_to_rmb,
        fx_rmb_to_mxn=fx_rmb_to_mxn,
    )


@frappe.whitelist()
def preview_yuewei_excel_file(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    source_sheet: str | None = None,
    transport_keyword: str = "",
    include_double_clear=1,
    batch_ids: str | None = None,
    limit: int | None = None,
) -> dict:
    """预览真实 xlsx 解析结果，不写入数据库。"""

    return import_service.preview_yuewei_excel_file(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        source_sheet=source_sheet,
        transport_keyword=transport_keyword,
        include_double_clear=include_double_clear,
        batch_ids=batch_ids,
        limit=limit,
    )


@frappe.whitelist()
def upload_attachment(batch_name: str, version_name: str | None = None, file_url: str | None = None) -> dict:
    """上传或登记附件，后续用于凭证解析。"""

    return import_service.upload_attachment(
        batch_name=batch_name,
        version_name=version_name,
        file_url=file_url,
    )


@frappe.whitelist()
def preview_tax_certificate_pdf(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
) -> dict:
    """预览解析进口完税凭证 PDF，不写入成本明细。"""

    return import_service.preview_tax_certificate_pdf(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        text=text,
    )


@frappe.whitelist()
def import_purchase_expense_oa(
    batch_name: str,
    source_instance_id: str | None = None,
    approval_no: str | None = None,
    official_url: str | None = None,
    version_name: str | None = None,
    detail_rows_json: str | None = None,
) -> dict:
    """从采购支出 OA 补采购单价、采购币种和货值来源。"""

    return import_service.import_purchase_expense_oa(
        batch_name=batch_name,
        source_instance_id=source_instance_id,
        approval_no=approval_no,
        official_url=official_url,
        version_name=version_name,
        detail_rows_json=detail_rows_json,
    )


@frappe.whitelist()
def parse_packing_list_attachment(
    batch_name: str,
    attachment_name: str | None = None,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
) -> dict:
    """解析装箱单附件，补实际发货数量、重量和体积相关字段。"""

    return import_service.parse_packing_list_attachment(
        batch_name=batch_name,
        attachment_name=attachment_name,
        file_url=file_url,
        version_name=version_name,
        template_hint=template_hint,
        sheet_rows_json=sheet_rows_json,
    )
