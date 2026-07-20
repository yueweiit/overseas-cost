"""中文用途：真实 xlsx 成本总表解析测试。"""

from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from overseas_costing.services.import_service import import_yuewei_excel_file
from overseas_costing.utils.excel_blocks import select_excel_blocks, summarize_excel_blocks
from overseas_costing.utils.excel_workbook import parse_yuewei_excel_workbook, parse_yuewei_sheet


def _build_sample_workbook():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "2026年YUEWEI"
    sheet.append(["物料编码", "产品名称", "单价", "数量", "总货值", "海关进口名称", "海关分类编码", "大类分类"])

    for cell_range in ("I2:I3", "J2:J3", "K2:K3", "L2:L3", "M2:M3", "AU2:AU3", "BD2:BD3", "BE2:BE3"):
        sheet.merge_cells(cell_range)

    sheet["I2"] = "26 16 1681 6000151"
    sheet["J2"] = "HPCU5155607"
    sheet["K2"] = 10157
    sheet["L2"] = 26408.2
    sheet["M2"] = 900
    sheet["AU2"] = 13976.3
    sheet["BD2"] = "原料采购"
    sheet["BE2"] = "海运"

    _write_item_row(sheet, 2, "YL000098", "TPU-HF-8695AU", 14.3575, 5000, 71787.5, 1200, 19.0969)
    _write_item_row(sheet, 3, "YL000058", "PC-LXTY1609T-11", 11.9167, 7000, 83417.09, 800, 22.1906)

    sheet["I4"] = "26 16 1681 6000999"
    sheet["J4"] = "MXT145414"
    sheet["K4"] = 300
    sheet["L4"] = 780
    sheet["M4"] = 0
    sheet["AU4"] = 1000
    sheet["BD4"] = "双清样本"
    sheet["BE4"] = "海运双清"
    _write_item_row(sheet, 4, "FL000027", "塑料包装袋", 0.03, 1000, 30, 10, 100)

    return workbook


def _write_item_row(sheet, row_no: int, code: str, name: str, price: float, qty: float, value: float, weight: float, ratio: float) -> None:
    values = {
        "A": code,
        "B": name,
        "C": price,
        "D": qty,
        "E": value,
        "F": "PLASTICO TPU EN FORMAS PRIMARIAS",
        "G": "39079101",
        "H": "00",
        "N": 0,
        "O": 0,
        "P": 0.05,
        "Q": 100,
        "R": 0.16,
        "S": 200,
        "T": ratio,
        "U": 10,
        "V": 2,
        "W": 0.32,
        "X": 312.32,
        "AO": 500,
        "AP": 192.31,
        "AQ": 26.79,
        "AV": weight,
        "AW": 60,
        "AX": 8385.78,
        "AY": 21803.03,
        "AZ": 22303.03,
        "BA": 4.4606,
        "BB": 80365.59,
        "BC": 16.0731,
    }
    for column, value in values.items():
        sheet[f"{column}{row_no}"] = value


def _build_oa_attachment_workbook():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "7月份钢化膜空运"
    sheet.append(
        [
            "对应钉钉采购订单号",
            "品目编码Item code",
            "品牌",
            "申报名称",
            "申报单位",
            "供应商supplier",
            "中文品名 Chinese Name",
            "是否开票/CI",
            "海关编码 Customs code",
            "英文品名 English product name",
            "西语品名 Spanish name",
            "规格，型号，品牌 Specification, model, brand",
            "长m",
            "宽m",
            "高m",
            "净重NW 件kg",
            "毛重GW 件kg",
            "单件CBM",
            "个数（每件）Number(Every)",
            "件数Number of pieces",
            "总个数 The total number of",
            "包装 Packing",
            "总净重",
            "总毛重Gross weight",
            "总体积total capacity",
            "单价 unit price",
            "总价（RMB)",
            "计划出货日期",
            "备注 Remarks",
            "出口方式",
            "项目归属",
        ]
    )
    sheet.append(
        [
            "202606220952000179521",
            "FL004106",
            "无品牌",
            "钢化膜",
            "个",
            "麒麟",
            "钢化膜",
            "否",
            "",
            "Tempered film",
            "Mica de celular",
            "GALAXY A07",
            0.49,
            0.36,
            0.2,
            12.9,
            13.4,
            0.03528,
            500,
            1,
            500,
            "纸箱+编织袋",
            12.9,
            13.4,
            0.03528,
            1.2,
            600,
            "2026-07-05",
            "买单",
            "空运双清包税",
            "贸易项目",
        ]
    )
    sheet.append(
        [
            "202606301549000536602",
            "FL004111",
            "无品牌",
            "太阳眼镜",
            "个",
            "线上",
            "太阳眼镜",
            "否",
            "",
            "sunglasses",
            "gafas de sol",
            "工业品电商",
            0.35,
            0.32,
            0.46,
            5.5,
            6,
            0.05152,
            5,
            1,
            5,
            "纸箱",
            5.5,
            6,
            0.05152,
            14.55,
            72.75,
            "2026-07-05",
            "买单",
            "空运双清包税",
            "TK项目",
        ]
    )
    sheet.append([None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, 19.4, 0.0868, 15.75, 672.75])
    return workbook


def _parse_sample_blocks() -> tuple[dict, list[dict]]:
    workbook = _build_sample_workbook()
    try:
        blocks = parse_yuewei_sheet(workbook["2026年YUEWEI"], source_sheet="2026年YUEWEI")
        meta = {
            "sourceSheet": "2026年YUEWEI",
            "blockCount": len(blocks),
            "itemCount": sum(len(block.get("items") or []) for block in blocks),
        }
        return meta, blocks
    finally:
        workbook.close()


def test_parse_yuewei_excel_workbook_expands_merged_batch_fields() -> None:
    meta, blocks = _parse_sample_blocks()

    assert meta["sourceSheet"] == "2026年YUEWEI"
    assert summarize_excel_blocks(blocks) == {
        "block_count": 2,
        "item_count": 3,
        "batch_ids": ["HPCU5155607", "MXT145414"],
    }
    assert blocks[0]["sourceRange"] == "2026年YUEWEI!2:3"
    assert blocks[0]["customsNo"] == "26 16 1681 6000151"
    assert blocks[0]["chinaMiscRmb"] == 10157
    assert blocks[0]["transportMode"] == "海运"
    assert blocks[0]["items"][1][0] == "YL000058"
    assert blocks[0]["items"][1][11]["chinaToMexicoFreightRmb"] == 13976.3


def test_parse_oa_attachment_detail_sheet_auto_detects_non_yuewei_sheet() -> None:
    workbook = _build_oa_attachment_workbook()
    file_path = Path("tmp_air_attachment_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path, sheet_name="2026年YUEWEI")
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["sourceSheet"] == "7月份钢化膜空运"
    assert meta["parser"] == "oa_attachment_detail"
    assert "已自动识别" in meta["warning"]
    assert summarize_excel_blocks(blocks) == {
        "block_count": 2,
        "item_count": 2,
        "batch_ids": ["202606220952000179521", "202606301549000536602"],
    }
    first_item = blocks[0]["items"][0]
    assert blocks[0]["transportMode"] == "空运双清包税"
    assert first_item[0] == "FL004106"
    assert first_item[2] == 1.2
    assert first_item[3] == 500
    assert first_item[4] == 600
    assert first_item[5] is None
    assert first_item[7] is None
    assert first_item[11]["purchaseOrderNo"] == "202606220952000179521"
    assert first_item[11]["actualShippedQty"] == 500
    assert first_item[11]["volumeM3"] == 0.03528
    assert first_item[11]["sourceRemark"] == "买单；申报名称：钢化膜"


def test_parse_oa_attachment_detail_sheet_ignores_cost_calculation_rows() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "华峰装柜"
    sheet.append(
        [
            "对应钉钉采购订单号",
            "品目编码Item code",
            "申报名称",
            "申报单位",
            "中文品名 Chinese Name",
            "总个数 The total number of",
            "单价 unit price",
            "总价（RMB)",
            "出口方式",
            "项目归属",
        ]
    )
    sheet.append(["202604150041000081318", "YL000098", "热塑性聚氨酯弹性体", "千克", "TPU", 10000, 3.05, 30500, "华峰正报", "亮甲2.0项目"])
    sheet.append(["费用支出明细", "人民币", "比索", "换算人民币支出", "占比", None, None, None, None, None])
    sheet.append(["海运费", 0, 0, None, None, None, None, None, None, None])
    file_path = Path("tmp_raw_material_attachment_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path)
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["sourceSheet"] == "华峰装柜"
    assert summarize_excel_blocks(blocks) == {
        "block_count": 1,
        "item_count": 1,
        "batch_ids": ["202604150041000081318"],
    }
    assert blocks[0]["transportMode"] == "海运"
    assert blocks[0]["items"][0][0] == "YL000098"


def test_select_parsed_workbook_blocks_excludes_double_clear_by_default() -> None:
    _meta, blocks = _parse_sample_blocks()

    selected = select_excel_blocks(blocks)
    selected_with_double_clear = select_excel_blocks(blocks, include_double_clear=1)

    assert [block["id"] for block in selected] == ["HPCU5155607"]
    assert [block["id"] for block in selected_with_double_clear] == ["HPCU5155607", "MXT145414"]


def test_import_yuewei_excel_file_returns_preview_without_frappe(monkeypatch) -> None:
    meta, blocks = _parse_sample_blocks()

    monkeypatch.setattr(
        "overseas_costing.services.import_service.parse_yuewei_excel_workbook",
        lambda _path, sheet_name="2026年YUEWEI": (meta, blocks),
    )
    monkeypatch.setattr(
        "overseas_costing.services.import_service._resolve_excel_file_path",
        lambda file_path=None, file_url=None: "sample.xlsx",
    )
    result = import_yuewei_excel_file(file_path=__file__, source_name="sample.xlsx")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["selected_summary"]["batch_ids"] == ["HPCU5155607"]
    assert result["preview_batches"][0]["mapped_preview_items"][0]["material_code"] == "YL000098"
