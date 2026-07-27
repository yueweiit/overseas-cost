"""
中文用途：字段映射工具测试。
"""

from overseas_costing.utils.field_mapper import (
    map_oa_row_to_item,
    map_packing_list_row_to_item,
    map_purchase_expense_row_to_item,
    normalize_transport_mode,
)


def test_map_oa_row_to_item() -> None:
    row = {
        "物料编码 Código de material": "YL000097",
        "物料名称（中文）Nombre del material (chino)": "TPU原料",
        "物料类别TIPO": "树脂",
        "项目proyecto": "2026Yuewei",
        "数量Cantidad": 10000,
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
    assert mapped["waybill_no"] == "HPCU5155607"
    assert mapped["transport_mode"] == "SEA"
    assert mapped["source_remark"] == "汇率待确认"


def test_map_purchase_expense_row_to_item() -> None:
    row = {
        "物品编码Código": "FL004104",
        "物品名称Nombre del artículo": "包装袋",
        "物品规格Especificacion": "10*12cm*珠光膜阴阳骨袋",
        "数量Cantidad": 1000,
        "单位Unidad": "个",
        "单价Precio": 0.049,
        "总金额Monto Total": 49.0,
        "币种Moneda": "人民币RMB",
    }
    mapped = map_purchase_expense_row_to_item(row)
    assert mapped["material_code"] == "FL004104"
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
