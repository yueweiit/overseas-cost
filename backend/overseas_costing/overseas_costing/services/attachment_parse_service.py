"""
中文用途：附件解析服务。

后续这里会接：
1. 凭证文件上传后的解析任务
2. OCR 识别
3. AI 字段抽取
4. 识别结果回填
"""

from __future__ import annotations


PACKING_LIST_TEMPLATE_STRATEGIES = {
    "mixed_workbook_router": "多 sheet 混合工作簿，先识别 sheet 类型再分别路由解析。",
    "sea_container_sheet": "海运装柜 / 装箱单模板，重点取物料编码、数量、毛重、体积。",
    "carton_packing_list": "彩盒 / 纸箱装箱单模板，重点取箱数、NW/GW、尺寸。",
    "express_item_list": "快递清单模板，重点取 SKU、数量、收件人、总重。",
}


def enqueue_parse_task(attachment_name: str) -> dict:
    return {
        "ok": True,
        "attachment_name": attachment_name,
        "queued": True,
        "message": "附件解析任务骨架已创建。",
    }


def build_packing_list_parse_task(
    *,
    batch_name: str,
    version_name: str | None = None,
    attachment_name: str | None = None,
    file_url: str | None = None,
    template_hint: str | None = None,
) -> dict:
    """构造装箱单解析任务的第一版描述。"""

    strategy = template_hint or "mixed_workbook_router"
    return {
        "batch_name": batch_name,
        "version_name": version_name,
        "attachment_name": attachment_name,
        "file_url": file_url,
        "template_hint": strategy,
        "parse_targets": [
            "actual_shipped_qty",
            "gross_weight_kg",
            "volume_m3",
            "volume_weight_kg",
            "chargeable_weight_kg",
        ],
        "parser_strategy": strategy,
        "parser_strategy_desc": PACKING_LIST_TEMPLATE_STRATEGIES.get(strategy, "待补充的模板策略。"),
        "needs_manual_review": True,
        "message": "一期先按多模板路由方式解析装箱单，识别后仍允许人工修正并留痕。",
    }
