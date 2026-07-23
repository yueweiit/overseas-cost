"""
中文用途：字段映射工具文件。

当前重点解决：
1. OA 国际物流单 -> 系统字段映射
2. 采购支出 OA -> 采购单价 / 币种 / 货值映射
3. 装箱单 / Packing List -> 实际发货数量与重量体积映射
4. 多来源字段统一收口
"""

from __future__ import annotations


TRANSPORT_MODE_MAP = {
    "SEA": "SEA",
    "AIR": "AIR",
    "EXPRESS": "EXPRESS",
    "海运": "SEA",
    "海运整柜": "SEA",
    "contenedor marítimo海运整柜": "SEA",
    "contenedor maritimo海运整柜": "SEA",
    "空运": "AIR",
    "air": "AIR",
    "correo express快递": "EXPRESS",
    "快递": "EXPRESS",
    "express": "EXPRESS",
}

EXCEL_BLOCK_FIELD_MAP = {
    "sourceSheet": "source_sheet",
    "sourceRange": "source_range",
    "projectCollection": "project_collection",
    "customsNo": "customs_no",
    "waybillNo": "waybill_no",
    "chinaMiscRmb": "china_misc_rmb",
    "chinaMiscMxn": "china_misc_mxn",
    "oceanUsd": "china_ocean_usd",
    "remark": "source_remark",
}

EXCEL_EXTRA_FIELD_MAP = {
    "sourceRow": "excel_row_no",
    "sourceDocNo": "source_doc_no",
    "purchaseOrderNo": "purchase_order_no",
    "purchaseCurrency": "purchase_currency",
    "productNameEs": "product_name_es",
    "specModel": "spec_model",
    "unit": "unit",
    "actualShippedQty": "actual_shipped_qty",
    "volumeM3": "volume_m3",
    "volumeWeightKg": "volume_weight_kg",
    "chargeableWeightKg": "chargeable_weight_kg",
    "sourceRemark": "source_remark",
    "ccRate": "cc_rate",
    "ccAntiDumping": "cc_anti_dumping",
    "igiRate": "igi_rate",
    "igiAmount": "igi_amount",
    "ivaRate": "iva_rate",
    "ivaAmount": "iva_amount",
    "dta": "dta",
    "prvDuty": "prv_duty",
    "prvIva": "prv_iva",
    "importTaxTotal": "import_tax_total",
    "revalidacion": "revalidacion",
    "maniobras": "maniobras",
    "muellaje": "muellaje",
    "entregaMercancia": "entrega_mercancia",
    "previo": "previo",
    "serviceAA": "service_aa",
    "almacenajes": "almacenajes",
    "reconocimientoAduanero": "reconocimiento_aduanero",
    "honorarios": "honorarios",
    "complementoManiobras": "complemento_maniobras",
    "desconsolidacion": "desconsolidacion",
    "maniobraFalso": "maniobra_falso",
    "arrastre": "arrastre",
    "patioRegulador": "patio_regulador",
    "entregaVacio": "entrega_vacio",
    "limpiezaContenedor": "limpieza_contenedor",
    "mexicoCustomsMxn": "mexico_customs_mxn",
    "mexicoCustomsRmb": "mexico_customs_rmb",
    "mexicoCustomsUsd": "mexico_customs_usd",
    "mexicoInlandMxn": "mexico_inland_mxn",
    "mexicoMiscMxn": "mexico_misc_mxn",
    "mexicoInlandMiscRmb": "mexico_inland_misc_rmb",
    "chinaToMexicoFreightRmb": "china_to_mexico_freight_rmb",
    "grossWeightKg": "gross_weight_kg",
    "weightRatio": "weight_ratio",
    "freightAllocRmb": "freight_alloc_rmb",
    "freightAllocMxn": "freight_alloc_mxn",
    "totalLogisticsMxn": "total_logistics_mxn",
    "allocPriceMxn": "alloc_price_mxn",
    "totalCostRmb": "total_cost_rmb",
    "totalUnitRmb": "total_unit_rmb",
}


def _first_value(row: dict, *keys: str):
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _clean_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


def normalize_transport_mode(value):
    """把多语言物流方式归一成系统枚举。"""

    cleaned = _clean_text(value)
    if not cleaned:
        return None

    normalized = str(cleaned).replace("（", "(").replace("）", ")").strip()
    if normalized in TRANSPORT_MODE_MAP:
        return TRANSPORT_MODE_MAP[normalized]

    lowered = normalized.lower()
    for key, target in TRANSPORT_MODE_MAP.items():
        if key.lower() == lowered:
            return target

    if "海运" in normalized or "marít" in normalized or "marit" in lowered:
        return "SEA"
    if "空运" in normalized or "air" in lowered:
        return "AIR"
    if "快递" in normalized or "express" in lowered or "correo" in lowered:
        return "EXPRESS"
    return None


def map_oa_row_to_item(row: dict) -> dict:
    """把 OA 国际物流单一行基础字段映射为系统明细结构。"""

    return {
        "material_code": _first_value(row, "物料编码 Código de material", "物料编码", "material_code"),
        "product_name": _first_value(
            row,
            "物料名称（中文）Nombre del material (chino)",
            "物料名称（中文）",
            "物料名称",
            "产品名称",
            "product_name",
        ),
        "product_name_es": _first_value(
            row,
            "物料名称（西语）Nombre del material (español)",
            "物料名称（西语）",
            "product_name_es",
        ),
        "spec_model": _first_value(row, "规格型号Especificación / Modelo", "规格型号", "spec_model"),
        "unit": _first_value(row, "单位Unidad", "单位", "unit"),
        "recipient": _first_value(row, "收件人Destinatario", "收件人", "recipient"),
        "category": _first_value(row, "物料类别TIPO", "大类", "category"),
        "project_collection": _first_value(row, "项目proyecto", "项目", "project_collection"),
        "quantity": _first_value(row, "数量Cantidad", "数量", "quantity"),
        "gross_weight_kg": _first_value(row, "重量Peso（KG）", "重量", "gross_weight_kg"),
        "waybill_no": _first_value(
            row,
            "柜号/单号Número DE Logística",
            "柜号/单号",
            "运单号",
            "waybill_no",
        ),
        "transport_mode": normalize_transport_mode(
            _first_value(row, "物流方式Camino Envío", "物流方式", "transport_mode")
        ),
        "source_remark": _first_value(row, "备注otro", "备注", "source_remark"),
        "source_type": "OA_LOGISTICS",
    }


def map_purchase_expense_row_to_item(row: dict) -> dict:
    """把采购支出 OA 明细行映射为采购价格来源字段。"""

    return {
        "material_code": _first_value(row, "物品编码Código", "物料编码", "material_code"),
        "product_name": _first_value(row, "物品名称Nombre del artículo", "物料名称", "product_name"),
        "spec_model": _first_value(row, "物品规格Especificacion", "规格型号", "spec_model"),
        "quantity": _first_value(row, "数量Cantidad", "数量", "quantity"),
        "unit": _first_value(row, "单位Unidad", "单位", "unit"),
        "unit_price": _first_value(row, "单价Precio", "采购单价", "unit_price"),
        "goods_value": _first_value(row, "总金额Monto Total", "总货值", "goods_value"),
        "purchase_currency": _first_value(row, "币种Moneda", "采购币种", "purchase_currency"),
        "source_type": "PURCHASE_EXPENSE_OA",
    }


def map_packing_list_row_to_item(row: dict) -> dict:
    """把装箱单 / Packing List 行映射为实际发货与物理属性字段。"""

    return {
        "material_code": _first_value(row, "物料编码", "物品编码", "SKU", "code", "material_code"),
        "product_name": _first_value(row, "物料名称", "品名", "material", "product_name"),
        "spec_model": _first_value(row, "规格型号", "规格", "model", "spec_model"),
        "actual_shipped_qty": _first_value(
            row,
            "实际发货数量",
            "发货数量",
            "数量",
            "qty",
            "actual_shipped_qty",
        ),
        "gross_weight_kg": _first_value(
            row,
            "毛重KG",
            "毛重",
            "箱重",
            "gross_weight_kg",
            "box_weight",
        ),
        "volume_m3": _first_value(row, "体积m3", "体积", "volume_m3"),
        "volume_weight_kg": _first_value(row, "体积重KG", "体积重", "volume_weight_kg"),
        "chargeable_weight_kg": _first_value(row, "计费重KG", "计费重", "chargeable_weight_kg"),
        "hs_code": _first_value(row, "海关分类编码", "HS CODE", "hs_code"),
        "source_type": "PACKING_LIST",
    }


def map_yuewei_excel_block_item_to_item(block: dict, item_row, row_index: int | None = None) -> dict:
    """Map one row from the Yuewei Excel block JSON used by the demo/importer."""

    item = item_row if isinstance(item_row, list) else []
    extra = item[11] if len(item) > 11 and isinstance(item[11], dict) else {}
    mapped = {
        "row_no": row_index,
        "material_code": item[0] if len(item) > 0 else None,
        "product_name": item[1] if len(item) > 1 else None,
        "unit_price": item[2] if len(item) > 2 else None,
        "quantity": item[3] if len(item) > 3 else None,
        "goods_value": item[4] if len(item) > 4 else None,
        "import_name": item[5] if len(item) > 5 else None,
        "hs_code": item[6] if len(item) > 6 else None,
        "category": item[7] if len(item) > 7 else None,
        "alloc_price_mxn": item[8] if len(item) > 8 else None,
        "total_unit_rmb": item[9] if len(item) > 9 else None,
        "goods_value_ratio": item[10] if len(item) > 10 else None,
        "transport_mode": normalize_transport_mode(extra.get("transportMode") or block.get("transportMode")),
        "source_type": extra.get("sourceType") or block.get("sourceType") or "EXCEL_MAIN",
    }

    legacy_excel_a = extra.get("excelA")
    if not mapped["material_code"] and legacy_excel_a:
        mapped["material_code"] = legacy_excel_a

    shared_cost_fields = {"chinaMiscRmb", "chinaMiscMxn", "oceanUsd"}
    for source_field, target_field in EXCEL_BLOCK_FIELD_MAP.items():
        if source_field in shared_cost_fields and row_index not in (None, 1):
            continue
        value = block.get(source_field)
        if value not in (None, ""):
            mapped[target_field] = value

    for source_field, target_field in EXCEL_EXTRA_FIELD_MAP.items():
        value = extra.get(source_field)
        if value not in (None, ""):
            mapped[target_field] = value

    if mapped.get("row_no") is None and mapped.get("excel_row_no"):
        mapped["row_no"] = mapped["excel_row_no"]

    return mapped
