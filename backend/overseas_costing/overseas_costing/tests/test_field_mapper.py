"""
中文用途：字段映射工具测试。
"""

from overseas_costing.utils.field_mapper import (
    map_oa_row_to_item,
    map_packing_list_row_to_item,
    map_purchase_expense_row_to_item,
    normalize_business_type,
    normalize_transport_mode,
    normalize_unit,
)


def test_normalize_unit() -> None:
    assert normalize_unit("pieza") == "个"
    assert normalize_unit("Piezas") == "个"
    assert normalize_unit(" pcs ") == "个"
    assert normalize_unit("包") == "包"
    assert normalize_unit("") is None


def test_map_oa_row_to_item() -> None:
    row = {
        "物料编码 Código de material": "YL000097",
        "物料名称（中文）Nombre del material (chino)": "TPU原料",
        "物料类别TIPO": "树脂",
        "项目proyecto": "2026Yuewei",
        "数量Cantidad": 10000,
        "单位Unidad": "pieza",
        "重量Peso（KG）": 25750,
        "柜号/单号Número DE Logística": "HPCU5155607",
        "物流方式Camino Envío": "contenedor marítimo海运整柜",
        "备注otro": "汇率待确认",
    }
    mapped = map_oa_row_to_item(row)
    assert mapped["material_code"] == "YL000097"
    assert mapped["product_name"] == "TPU原料"
    assert mapped["category"] == "树脂"
    assert mapped["project_collection"] == "2026Yuewei"
    assert mapped["unit"] == "个"
    assert mapped["waybill_no"] == "HPCU5155607"
    assert mapped["transport_mode"] == "SEA"
    assert mapped["source_remark"] == "汇率待确认"


def test_map_oa_row_to_item_accepts_spaced_bilingual_headers() -> None:
    row = {
        "物料编码 Código de material": "GJ003865",
        "物料名称（中文） Nombre del material (chino)": "清洗篮",
        "物料名称（西语） Nombre del material (español)": "Dispositivo de teñido de fundas de móvil",
        "数量 Cantidad": 20,
        "单位 Unidad": "pieza",
        "收件人 Destinatario": "Alfredo Garcia Cardenas",
    }

    mapped = map_oa_row_to_item(row)

    assert mapped["material_code"] == "GJ003865"
    assert mapped["product_name"] == "清洗篮"
    assert mapped["product_name_es"] == "Dispositivo de teñido de fundas de móvil"
    assert mapped["quantity"] == 20
    assert mapped["unit"] == "个"
    assert mapped["recipient"] == "Alfredo Garcia Cardenas"


def test_map_oa_row_to_item_repairs_shifted_dingtalk_columns() -> None:
    row = {
        "物料编码 Código de material": "GJ003865",
        "物料名称（中文）Nombre del material (chino)": "清洗篮Dispositivo de teñido de fundas de móvil",
        "物料名称（西语）Nombre del material (español)": "33.5*31*20",
        "规格型号Especificación / Modelo": "20",
        "数量Cantidad": "pieza",
        "单位Unidad": "Alfredo Garcia Cardenas",
    }

    mapped = map_oa_row_to_item(row)

    assert mapped["material_code"] == "GJ003865"
    assert mapped["product_name"] == "清洗篮"
    assert mapped["product_name_es"] == "Dispositivo de teñido de fundas de móvil"
    assert mapped["spec_model"] == "33.5*31*20"
    assert mapped["quantity"] == "20"
    assert mapped["unit"] == "个"
    assert mapped["recipient"] == "Alfredo Garcia Cardenas"


def test_map_purchase_expense_row_to_item() -> None:
    row = {
        "物品编码Código": "FL004104",
        "物品名称Nombre del artículo": "包装袋",
        "物品规格Especificacion": "10*12cm*珠光膜阴阳骨袋",
        "数量Cantidad": 1000,
        "单位Unidad": "piezas",
        "单价Precio": 0.049,
        "总金额Monto Total": 49.0,
        "币种Moneda": "人民币RMB",
    }
    mapped = map_purchase_expense_row_to_item(row)
    assert mapped["material_code"] == "FL004104"
    assert mapped["unit"] == "个"
    assert mapped["unit_price"] == 0.049
    assert mapped["goods_value"] == 49.0
    assert mapped["purchase_currency"] == "人民币RMB"
    assert mapped["source_type"] == "PURCHASE_EXPENSE_OA"


def test_map_packing_list_row_to_item() -> None:
    row = {
        "物料编码": "CW000175",
        "物料名称": "仿真玉米",
        "规格型号": "仿真烤玉米乳胶材质",
        "实际发货数量": 400,
        "单位": "Pieza",
        "毛重KG": 32.5,
        "体积m3": 0.21,
        "体积重KG": 35.0,
        "计费重KG": 35.0,
        "单价": 1.2,
        "总价（RMB)": 480,
        "海关分类编码": "3926909090",
    }
    mapped = map_packing_list_row_to_item(row)
    assert mapped["material_code"] == "CW000175"
    assert mapped["unit"] == "个"
    assert mapped["actual_shipped_qty"] == 400
    assert mapped["gross_weight_kg"] == 32.5
    assert mapped["volume_m3"] == 0.21
    assert mapped["chargeable_weight_kg"] == 35.0
    assert mapped["unit_price"] == 1.2
    assert mapped["goods_value"] == 480
    assert mapped["purchase_currency"] == "人民币RMB"
    assert mapped["hs_code"] == "3926909090"


def test_normalize_transport_mode() -> None:
    assert normalize_transport_mode("contenedor marítimo海运整柜") == "SEA"
    assert normalize_transport_mode("correo express快递") == "EXPRESS"
    assert normalize_transport_mode("华峰正报") is None


def test_normalize_business_type_uses_explicit_business_type() -> None:
    assert normalize_business_type("SEA_DDP") == "SEA_DDP"
    assert normalize_business_type("空运 DDP（双清包税）") == "AIR_DDP"


def test_normalize_business_type_falls_back_to_legacy_transport_mode() -> None:
    assert normalize_business_type("", transport_mode="SEA") == "SEA_STANDARD"
    assert normalize_business_type("", transport_mode="AIR") == "AIR_STANDARD"
    assert normalize_business_type("", transport_mode="EXPRESS") == "EXPRESS"
