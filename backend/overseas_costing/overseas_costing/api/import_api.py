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
def list_manual_document_attachments(
    batch_name: str,
    logistics_type: str | None = None,
    limit: int | None = 200,
) -> dict:
    """查询人工上传的资料清单附件。"""

    return import_service.list_manual_document_attachments(
        batch_name=batch_name,
        logistics_type=logistics_type,
        limit=limit,
    )


@frappe.whitelist()
def register_manual_document_attachment(
    batch_name: str,
    logistics_type: str,
    slot_code: str,
    slot_label: str,
    attachment_type: str | None = None,
    file_url: str | None = None,
    file_name: str | None = None,
    version_name: str | None = None,
    remark: str | None = None,
    required=0,
) -> dict:
    """登记人工上传资料，只做归档和回溯，不触发字段解析。"""

    return import_service.register_manual_document_attachment(
        batch_name=batch_name,
        logistics_type=logistics_type,
        slot_code=slot_code,
        slot_label=slot_label,
        attachment_type=attachment_type,
        file_url=file_url,
        file_name=file_name,
        version_name=version_name,
        remark=remark,
        required=required,
    )


@frappe.whitelist()
def delete_manual_document_attachment(attachment_name: str) -> dict:
    """删除人工上传资料记录。"""

    return import_service.delete_manual_document_attachment(attachment_name=attachment_name)


@frappe.whitelist()
def parse_manual_document_attachments(
    batch_name: str,
    logistics_type: str | None = None,
    limit: int | None = 200,
    skip_parsed=1,
    recalculate=1,
) -> dict:
    """批量解析人工补传资料；仅可识别内容会写入，其他保留原件复核。"""

    skip_parsed_flag = str(skip_parsed or "").strip().lower() in ("1", "true", "yes", "y")
    recalculate_flag = str(recalculate or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.parse_manual_document_attachments(
        batch_name=batch_name,
        logistics_type=logistics_type,
        limit=limit,
        skip_parsed=skip_parsed_flag,
        recalculate=recalculate_flag,
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
def diagnose_oa_form_attachment_download(
    attachment_name: str,
    env_file: str | None = None,
    access_token: str | None = None,
) -> dict:
    """诊断钉钉发起表单附件自动下载链路，不保存文件。"""

    return import_service.diagnose_oa_form_attachment_download(
        attachment_name=attachment_name,
        env_file=env_file,
        access_token=access_token,
    )


@frappe.whitelist()
def preview_oa_source_attachment(attachment_name: str) -> dict:
    """识别已下载的 OA 附件内容，返回资料类型和字段候选，不写入核算明细。"""

    return import_service.preview_oa_source_attachment(attachment_name=attachment_name)


@frappe.whitelist()
def confirm_oa_source_attachment_type(
    attachment_name: str,
    confirmed_type: str,
    remark: str | None = None,
) -> dict:
    """保存人工确认的 OA 附件资料类型，不写入单价、货值或费用。"""

    return import_service.confirm_oa_source_attachment_type(
        attachment_name=attachment_name,
        confirmed_type=confirmed_type,
        remark=remark,
    )


@frappe.whitelist()
def preview_oa_purchase_order_match(
    attachment_name: str,
    version_name: str | None = None,
) -> dict:
    """预览采购订单附件与当前批次物料的匹配结果，不写入数据。"""

    return import_service.preview_oa_purchase_order_match(
        attachment_name=attachment_name,
        version_name=version_name,
    )


@frappe.whitelist()
def apply_oa_purchase_order_fillable_fields(
    attachment_name: str,
    version_name: str | None = None,
    recalculate_after_writeback=1,
) -> dict:
    """确认补入采购订单附件中匹配且为空的采购字段。"""

    recalculate_flag = str(recalculate_after_writeback or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.apply_oa_purchase_order_fillable_fields(
        attachment_name=attachment_name,
        version_name=version_name,
        recalculate_after_writeback=recalculate_flag,
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
def delete_tax_certificate_parse_records(
    batch_name: str | None = None,
    record_name: str | None = None,
    record_names_json: str | None = None,
) -> dict:
    """删除已保存的完税凭证解析记录。"""

    return import_service.delete_tax_certificate_parse_records(
        batch_name=batch_name,
        record_name=record_name,
        record_names_json=record_names_json,
    )


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
    recalculate_after_writeback=1,
) -> dict:
    """确认补入当前批次关联采购支出 OA 中可安全写入的采购字段。"""

    recalculate_flag = str(recalculate_after_writeback or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.apply_linked_purchase_expense_fillable_fields(
        batch_name=batch_name,
        version_name=version_name,
        env_file=env_file,
        linked_purchase_json=linked_purchase_json,
        purchase_summaries_json=purchase_summaries_json,
        recalculate_after_writeback=recalculate_flag,
    )


@frappe.whitelist()
def confirm_logistics_quote_candidate(
    batch_name: str,
    candidate_index: int,
    version_name: str | None = None,
    confirmation_note: str | None = None,
) -> dict:
    """人工确认一条物流报价候选后，生成对应的整票物流费用分摊规则。"""

    return import_service.confirm_logistics_quote_candidate(
        batch_name=batch_name,
        candidate_index=candidate_index,
        version_name=version_name,
        confirmation_note=confirmation_note,
    )


@frappe.whitelist()
def save_manual_logistics_quote(
    batch_name: str,
    amount,
    version_name: str | None = None,
    carrier: str | None = None,
    currency: str | None = "RMB",
    allocation_basis: str | None = "gross_weight",
    gross_weight_kg=None,
    chargeable_weight_kg=None,
    unit_freight_per_kg=None,
    billing_method: str | None = None,
    evidence_text: str | None = None,
    pre_delivery_date: str | None = None,
    destination: str | None = None,
    note: str | None = None,
) -> dict:
    """手工补录物流报价后，生成/更新对应的整票物流费用分摊规则。"""

    return import_service.save_manual_logistics_quote(
        batch_name=batch_name,
        version_name=version_name,
        carrier=carrier,
        amount=amount,
        currency=currency,
        allocation_basis=allocation_basis,
        gross_weight_kg=gross_weight_kg,
        chargeable_weight_kg=chargeable_weight_kg,
        unit_freight_per_kg=unit_freight_per_kg,
        billing_method=billing_method,
        evidence_text=evidence_text,
        pre_delivery_date=pre_delivery_date,
        destination=destination,
        note=note,
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
    recalculate_after_writeback=1,
) -> dict:
    """确认补入装箱单/物流附件中可安全写入的实际发货、重量、体积字段。"""

    recalculate_flag = str(recalculate_after_writeback or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.apply_packing_list_fillable_fields(
        batch_name=batch_name,
        attachment_name=attachment_name,
        file_url=file_url,
        version_name=version_name,
        template_hint=template_hint,
        sheet_rows_json=sheet_rows_json,
        recalculate_after_writeback=recalculate_flag,
    )


@frappe.whitelist()
def resolve_packing_list_conflict_row(
    batch_name: str,
    attachment_name: str | None,
    target_item_name: str,
    resolution_action: str,
    file_url: str | None = None,
    version_name: str | None = None,
    template_hint: str | None = None,
    sheet_rows_json: str | None = None,
    recalculate_after_writeback=1,
) -> dict:
    """保存单条装箱单差异处理结果。"""

    recalculate_flag = str(recalculate_after_writeback or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.resolve_packing_list_conflict_row(
        batch_name=batch_name,
        attachment_name=attachment_name,
        target_item_name=target_item_name,
        resolution_action=resolution_action,
        file_url=file_url,
        version_name=version_name,
        template_hint=template_hint,
        sheet_rows_json=sheet_rows_json,
        recalculate_after_writeback=recalculate_flag,
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
def parse_oa_source_attachments(
    batch_name: str | None = None,
    limit: int | None = 200,
    env_file: str | None = None,
    access_token: str | None = None,
    skip_parsed=1,
    recalculate=1,
) -> dict:
    """批量下载并解析钉钉发起附件；Excel 可回填，图片/PDF 等只保存识别快照。"""

    skip_parsed_flag = str(skip_parsed or "").strip().lower() in ("1", "true", "yes", "y")
    recalculate_flag = str(recalculate or "").strip().lower() in ("1", "true", "yes", "y")
    return import_service.parse_oa_source_attachments(
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
    target: str | None = None,
    batch_name: str | None = None,
    batch_no: str | None = None,
    source_approval_no: str | None = None,
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
        target=target or "",
        batch_name=batch_name or "",
        batch_no=batch_no or "",
        source_approval_no=source_approval_no or "",
        env_file=env_file,
        api_style=api_style,
        include_non_sea=include_non_sea_flag,
        access_token=access_token or "",
    )


@frappe.whitelist()
def pull_latest_oa_logistics_approvals(
    start: str | None = None,
    end: str | None = None,
    transport_modes: str | None = "ALL",
    limit: int | None = 80,
    env_file: str | None = None,
    api_style: str = "auto",
    list_api: str = "auto",
    access_token: str | None = None,
) -> dict:
    """手动拉取最近国际物流 OA 审批单，并保存/更新成本批次。"""

    from overseas_costing.scripts import import_oa_logistics

    try:
        normalized_limit = int(limit or 0) or None
    except (TypeError, ValueError):
        normalized_limit = 80
    if normalized_limit:
        normalized_limit = max(1, min(normalized_limit, 80))
    return import_oa_logistics.pull_latest_logistics_approvals_to_erp(
        start=start or "",
        end=end or "",
        transport_modes=transport_modes or "ALL",
        limit=normalized_limit,
        env_file=env_file,
        api_style=api_style or "auto",
        list_api=list_api or "auto",
        access_token=access_token or "",
    )


@frappe.whitelist()
def refresh_oa_logistics_detail(
    target: str,
    limit: int | None = 50,
    env_file: str | None = None,
    api_style: str = "auto",
    include_non_sea=0,
    access_token: str | None = None,
) -> dict:
    """按内部批次名、批次号或钉钉审批编号精准重拉一张国际物流 OA。"""

    from overseas_costing.scripts import import_oa_logistics

    include_non_sea_flag = str(include_non_sea or "").strip().lower() in ("1", "true", "yes", "y")
    return import_oa_logistics.refresh_oa_logistics_detail(
        target=target,
        limit=limit,
        env_file=env_file,
        api_style=api_style,
        include_non_sea=include_non_sea_flag,
        access_token=access_token or "",
    )


@frappe.whitelist()
def sync_existing_oa_finished_times(limit: int | None = 200) -> dict:
    """从已保存 OA 快照回填批次来源完成时间，仅补空值。"""

    from overseas_costing.scripts import import_oa_logistics

    return import_oa_logistics.sync_existing_oa_finished_times(limit=limit)


@frappe.whitelist()
def refresh_missing_oa_finished_times(
    limit: int | None = 200,
    env_file: str | None = None,
    api_style: str = "auto",
    access_token: str | None = None,
) -> dict:
    """回钉钉重拉详情，只补缺失的来源完成时间和审批状态。"""

    from overseas_costing.scripts import import_oa_logistics

    return import_oa_logistics.refresh_missing_oa_finished_times(
        limit=limit,
        env_file=env_file,
        api_style=api_style,
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
