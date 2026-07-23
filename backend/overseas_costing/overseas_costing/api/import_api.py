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
def list_oa_form_attachments(batch_name: str, limit: int | None = 50) -> dict:
    """查询钉钉发起表单附件记录；评论附件本阶段不纳入。"""

    return import_service.list_oa_form_attachments(
        batch_name=batch_name,
        limit=limit,
    )


@frappe.whitelist()
def download_oa_form_attachment(
    attachment_name: str,
    env_file: str | None = None,
    access_token: str | None = None,
) -> dict:
    """下载钉钉发起表单附件到系统文件，评论附件本阶段不处理。"""

    return import_service.download_oa_form_attachment(
        attachment_name=attachment_name,
        env_file=env_file,
        access_token=access_token,
    )


@frappe.whitelist()
def preview_tax_certificate_pdf(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
    batch_name: str | None = None,
) -> dict:
    """预览解析进口完税凭证 PDF，不写入成本明细。"""

    return import_service.preview_tax_certificate_pdf(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        text=text,
        batch_name=batch_name,
    )


@frappe.whitelist()
def save_tax_certificate_parse_result(
    source_name: str | None = None,
    file_path: str | None = None,
    file_url: str | None = None,
    text: str | None = None,
    batch_name: str | None = None,
) -> dict:
    """保存进口完税凭证 PDF 解析结果，不写入成本明细。"""

    return import_service.save_tax_certificate_parse_result(
        source_name=source_name,
        file_path=file_path,
        file_url=file_url,
        text=text,
        batch_name=batch_name,
    )


@frappe.whitelist()
def list_tax_certificate_parse_records(batch_name: str | None = None, limit: int | None = 20) -> dict:
    """查询已保存完税凭证解析记录摘要。"""

    return import_service.list_tax_certificate_parse_records(
        batch_name=batch_name,
        limit=limit,
    )


@frappe.whitelist()
def get_tax_certificate_parse_record(record_name: str | None = None) -> dict:
    """查询单条完税凭证解析记录详情。"""

    return import_service.get_tax_certificate_parse_record(record_name=record_name)


@frappe.whitelist()
def resolve_tax_certificate_reconciliation(
    record_name: str | None = None,
    resolution_action: str | None = None,
    adjusted_tax_total_mxn: float | str | None = None,
    remark: str | None = None,
) -> dict:
    """保存完税凭证差异人工处理结果，不写入成本字段。"""

    return import_service.resolve_tax_certificate_reconciliation(
        record_name=record_name,
        resolution_action=resolution_action,
        adjusted_tax_total_mxn=adjusted_tax_total_mxn,
        remark=remark,
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
def preview_linked_purchase_expense_oa(
    batch_name: str,
    version_name: str | None = None,
    env_file: str | None = None,
    linked_purchase_json: str | None = None,
    purchase_summaries_json: str | None = None,
) -> dict:
    """预览当前批次关联采购支出 OA 能补哪些采购价格字段，不写入数据。"""

    return import_service.preview_linked_purchase_expense_oa(
        batch_name=batch_name,
        version_name=version_name,
        env_file=env_file,
        linked_purchase_json=linked_purchase_json,
        purchase_summaries_json=purchase_summaries_json,
    )


@frappe.whitelist()
def apply_linked_purchase_expense_fillable_fields(
    batch_name: str,
    version_name: str | None = None,
    env_file: str | None = None,
    linked_purchase_json: str | None = None,
    purchase_summaries_json: str | None = None,
) -> dict:
    """确认补入当前批次关联采购支出 OA 中可安全写入的采购字段。"""

    return import_service.apply_linked_purchase_expense_fillable_fields(
        batch_name=batch_name,
        version_name=version_name,
        env_file=env_file,
        linked_purchase_json=linked_purchase_json,
        purchase_summaries_json=purchase_summaries_json,
    )


@frappe.whitelist()
def preview_packing_list_attachment(
    batch_name: str,
    attachment_name: str | None = None,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
) -> dict:
    """预览装箱单/物流附件可补哪些实际发货、重量、体积字段，不写入数据。"""

    return import_service.preview_packing_list_attachment(
        batch_name=batch_name,
        attachment_name=attachment_name,
        file_url=file_url,
        version_name=version_name,
        template_hint=template_hint,
        sheet_rows_json=sheet_rows_json,
    )


@frappe.whitelist()
def apply_packing_list_fillable_fields(
    batch_name: str,
    attachment_name: str | None = None,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
) -> dict:
    """确认补入装箱单/物流附件中可安全写入的实际发货、重量、体积字段。"""

    return import_service.apply_packing_list_fillable_fields(
        batch_name=batch_name,
        attachment_name=attachment_name,
        file_url=file_url,
        version_name=version_name,
        template_hint=template_hint,
        sheet_rows_json=sheet_rows_json,
    )


@frappe.whitelist()
def parse_oa_packing_list_attachments(
    batch_name: str | None = None,
    limit: int | None = 200,
    env_file: str | None = None,
    access_token: str | None = None,
    skip_parsed=1,
    recalculate=1,
) -> dict:
    """批量下载并解析钉钉发起附件里的 Excel 装箱单，写入可补字段。"""

    skip_parsed_flag = str(skip_parsed or "").strip().lower() in ("1", "true", "yes", "y")
    recalculate_flag = str(recalculate or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.parse_oa_packing_list_attachments(
        batch_name=batch_name,
        limit=limit,
        env_file=env_file,
        access_token=access_token,
        skip_parsed=skip_parsed_flag,
        recalculate=recalculate_flag,
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


@frappe.whitelist()
def refresh_existing_oa_logistics_details(
    limit: int | None = 200,
    env_file: str | None = None,
    api_style: str = "auto",
    include_non_sea=0,
    access_token: str | None = None,
) -> dict:
    """重拉已有国际物流 OA 批次详情，并自动同步关联采购支出字段。"""

    from overseas_costing.scripts import import_oa_logistics

    include_non_sea_flag = str(include_non_sea or "").strip().lower() in ("1", "true", "yes", "y")
    return import_oa_logistics.refresh_existing_oa_logistics_details(
        limit=limit,
        env_file=env_file,
        api_style=api_style,
        include_non_sea=include_non_sea_flag,
        access_token=access_token or "",
    )


@frappe.whitelist()
def sync_purchase_expenses_from_process(
    process_code: str | None = None,
    start: str | None = None,
    end: str | None = None,
    env_file: str | None = None,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    batch_limit: int | None = 200,
    include_running=0,
    access_token: str | None = None,
) -> dict:
    """从采购支出 OA 流程批量拉单，并按物料编码/规格同步已有国际物流批次。"""

    from overseas_costing.scripts import import_oa_logistics

    include_running_flag = str(include_running or "").strip().lower() in ("1", "true", "yes", "y")
    return import_oa_logistics.sync_purchase_expenses_from_process(
        process_code=process_code or "",
        start=start or "",
        end=end or "",
        env_file=env_file,
        api_style=api_style,
        list_api=list_api,
        page_size=int(page_size or 20),
        max_pages=int(max_pages or 20),
        chunk_days=int(chunk_days or 30),
        limit=limit,
        batch_limit=batch_limit,
        include_running=include_running_flag,
        access_token=access_token or "",
    )


@frappe.whitelist()
def preview_purchase_expenses_from_process(
    process_code: str | None = None,
    start: str | None = None,
    end: str | None = None,
    env_file: str | None = None,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    batch_limit: int | None = 200,
    include_running=0,
    access_token: str | None = None,
) -> dict:
    """预览采购支出 OA 流程能匹配哪些已有国际物流批次，不写入数据。"""

    from overseas_costing.scripts import import_oa_logistics

    include_running_flag = str(include_running or "").strip().lower() in ("1", "true", "yes", "y")
    return import_oa_logistics.preview_purchase_expenses_from_process(
        process_code=process_code or "",
        start=start or "",
        end=end or "",
        env_file=env_file,
        api_style=api_style,
        list_api=list_api,
        page_size=int(page_size or 20),
        max_pages=int(max_pages or 20),
        chunk_days=int(chunk_days or 30),
        limit=limit,
        batch_limit=batch_limit,
        include_running=include_running_flag,
        access_token=access_token or "",
    )
