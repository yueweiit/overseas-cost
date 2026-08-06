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
    assert first_item[5] == "钢化膜"
    assert first_item[7] is None
    assert first_item[11]["purchaseOrderNo"] == "202606220952000179521"
    assert first_item[11]["actualShippedQty"] == 500
    assert first_item[11]["volumeM3"] == 0.03528
    assert first_item[11]["sourceRemark"] == "买单；申报名称：钢化膜"


def test_parse_oa_attachment_detail_sheet_splits_group_total_price() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "5月指环扣双清"
    sheet.append(
        [
            "品目编码Item code",
            "中文品名 Chinese Name",
            "规格，型号，品牌 Specification, model, brand",
            "总个数 The total number of",
            "总毛重Gross weight",
            "总体积total capacity",
            "单价 unit price",
            "总价（RMB)",
            "出口方式",
        ]
    )
    sheet.append(["FL000429", "指环扣", "超队指环扣", 86400, 349.2, 0.36018, 0.619, 55710, "海运双清"])
    sheet.append(["FL000429", "指环扣", "超队指环扣", 3600, 14.5, 0.00864, None, None, "海运双清"])
    file_path = Path("tmp_group_price_attachment_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path)
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["parser"] == "oa_attachment_detail"
    assert summarize_excel_blocks(blocks) == {
        "block_count": 1,
        "item_count": 2,
        "batch_ids": ["5月指环扣双清-未关联采购单"],
    }
    first_item = blocks[0]["items"][0]
    second_item = blocks[0]["items"][1]
    assert first_item[2] == 0.619
    assert first_item[4] == pytest.approx(0.619 * 86400)
    assert second_item[2] == 0.619
    assert second_item[4] == pytest.approx(0.619 * 3600)
    assert second_item[11]["purchaseCurrency"] == "人民币RMB"


def test_parse_oa_attachment_detail_sheet_expands_merged_unit_price() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "5月指环扣双清"
    sheet.append(
        [
            "品目编码Item code",
            "中文品名 Chinese Name",
            "规格，型号，品牌 Specification, model, brand",
            "总个数 The total number of",
            "总毛重Gross weight",
            "总体积total capacity",
            "单价 unit price",
            "总价（RMB)",
            "出口方式",
        ]
    )
    sheet.append(["FL000429", "指环扣", "超队指环扣", 86400, 349.2, 0.36018, 0.619, 55710, "海运双清"])
    sheet.append(["FL000427", "指环扣", "亚克力指环扣", 3600, 14.5, 0.00864, None, None, "海运双清"])
    sheet.append(["FL000428", "指环扣", "透明指环扣", 72000, 291, 0.30015, None, None, "海运双清"])
    sheet.merge_cells("G2:G4")
    sheet.merge_cells("H2:H4")
    file_path = Path("tmp_merged_price_attachment_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path)
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["parser"] == "oa_attachment_detail"
    assert summarize_excel_blocks(blocks) == {
        "block_count": 1,
        "item_count": 3,
        "batch_ids": ["5月指环扣双清-未关联采购单"],
    }
    first_item, second_item, third_item = blocks[0]["items"]
    assert first_item[2] == 0.619
    assert first_item[4] == pytest.approx(0.619 * 86400)
    assert second_item[2] == 0.619
    assert second_item[4] == pytest.approx(0.619 * 3600)
    assert third_item[2] == 0.619
    assert third_item[4] == pytest.approx(0.619 * 72000)
    assert "合并单价按本行数量重算" in second_item[11]["sourceRemark"]


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


def test_parse_packing_list_without_price_headers_auto_detects_physical_fields() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "LX20260509001 CI&PL"
    sheet.append(["客户", "华峰"])
    sheet.append(["柜号", "FSCU8486789"])
    sheet.append(
        [
            "Item No.",
            "中文品名",
            "规格型号",
            "实际发货数量",
            "总毛重 G.W.(KG)",
            "总体积 CBM",
            "体积重 KG",
            "计费重 KG",
        ]
    )
    sheet.append(["YL000098", "TPU-HF-8695AU", "HF-8695AU", 5000, 1200, 19.0969, 3182.82, 3182.82])
    file_path = Path("tmp_packing_without_price_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path)
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["sourceSheet"] == "LX20260509001 CI&PL"
    assert meta["parser"] == "oa_attachment_detail"
    assert summarize_excel_blocks(blocks) == {
        "block_count": 1,
        "item_count": 1,
        "batch_ids": ["LX20260509001 CI&PL-未关联采购单"],
    }
    first_item = blocks[0]["items"][0]
    assert first_item[0] == "YL000098"
    assert first_item[1] == "TPU-HF-8695AU"
    assert first_item[3] == 5000
    assert first_item[11]["actualShippedQty"] == 5000
    assert first_item[11]["grossWeightKg"] == 1200
    assert first_item[11]["volumeM3"] == 19.0969
    assert first_item[11]["volumeWeightKg"] == 3182.82
    assert first_item[11]["chargeableWeightKg"] == 3182.82
    assert "purchaseCurrency" not in first_item[11]


def test_parse_sisa_warehouse_receipt_skips_image_column_and_allocates_box_totals() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "产品清单+派件信息"
    sheet.append(["SiSA墨西哥专线 海运进仓单"])
    sheet.append(["派件信息"])
    sheet.append(["客户", "西文名", "客户号", "货件号", "总箱数"])
    sheet.append(["凌翔电子", "LXDZ", "C0144", None, 10])
    sheet.append([])
    sheet.append(["产品清单"])
    sheet.append(
        [
            "产品图片",
            "箱号",
            "箱数",
            "型号",
            "品名",
            "报关单价\n（美元）",
            "单箱产品数",
            "总产品数",
            "长\n(cm)",
            "宽\n(cm)",
            "高\n(cm)",
            "体积/箱\n(cmb)",
            "总体积\n(cmb)",
            "毛重/箱\n(kg)",
            "总毛重\n(kg)",
            "备注",
        ]
    )
    sheet.append(
        [
            '=_xlfn.DISPIMG("ID_4BC568ED6C274B99BBC98F1EF3C7EB93",1)',
            "1号箱",
            1,
            "GJ003786",
            "灯管",
            7.7247191011236,
            8,
            8,
            130,
            36,
            68,
            None,
            0.31824,
            21,
            21,
            None,
        ]
    )
    sheet.append(
        [
            '=_xlfn.DISPIMG("ID_24CCFBB7860E47588117A94152CFFA90",1)',
            None,
            None,
            "FL002598",
            "灯管+连接线",
            6.53089887640449,
            30,
            30,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ]
    )
    long_model_name = "大面料（蓝色压花款 Apple iPad Air 13款的）"
    sheet.append([None, "2号箱", 1, long_model_name, "平板保护套配件", 10, 30, None, 35, 35, 35, None, None, 10, None, None])
    sheet.append(["Total", None, 2, None, None, None, None, 68, None, None, None, None, 0.361115, None, 31, None])
    file_path = Path("tmp_sisa_warehouse_receipt_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path, sheet_name="2026年YUEWEI")
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["sourceSheet"] == "产品清单+派件信息"
    assert meta["parser"] == "sisa_warehouse_receipt"
    assert "已自动识别" in meta["warning"]
    assert summarize_excel_blocks(blocks) == {
        "block_count": 1,
        "item_count": 3,
        "batch_ids": ["C0144"],
    }
    first_item, second_item, third_item = blocks[0]["items"]
    assert first_item[0] == "GJ003786"
    assert first_item[1] == "灯管"
    assert first_item[2] is None
    assert first_item[3] == 8
    assert first_item[4] is None
    assert first_item[11]["actualShippedQty"] == 8
    assert first_item[11]["grossWeightKg"] == pytest.approx(21 * 8 / 38)
    assert first_item[11]["volumeM3"] == pytest.approx(0.31824 * 8 / 38)
    assert "报关单价USD：7.724719" in first_item[11]["sourceRemark"]
    assert second_item[0] == "FL002598"
    assert second_item[1] == "灯管+连接线"
    assert second_item[11]["grossWeightKg"] == pytest.approx(21 * 30 / 38)
    assert second_item[11]["volumeM3"] == pytest.approx(0.31824 * 30 / 38)
    assert third_item[0] is None
    assert third_item[1] == "平板保护套配件"
    assert third_item[3] == 30
    assert third_item[11]["grossWeightKg"] == 10
    assert third_item[11]["volumeM3"] == pytest.approx(35 * 35 * 35 / 1_000_000)
    assert third_item[11]["specModel"] == long_model_name


def test_parse_ci_pl_workbook_merges_invoice_quantity_and_packing_weight() -> None:
    workbook = openpyxl.Workbook()
    ci = workbook.active
    ci.title = "CI"
    ci.append(["COMMERCIAL INVOICE", None, None, None, None])
    ci.append(["From", "ZHEJIANG HUAFON TPU CO.LTD", None, None, None])
    ci.append(["To", "YUEWEI S.A. DE C.V.", "C/I No.: HFZF25087160", None, None])
    ci.append([None, None, None, None, None])
    ci.append(["Article No", "Article Name", "Unit Price", "Quantity", "Amount"])
    ci.append([1, "TPU,Termoplástico poliuretano（热塑性聚氨酯（TPU HF-8695AU））", 3.05, 10000, 30500])
    ci.append([2, "TPU,Termoplástico poliuretano（热塑性聚氨酯（TPU HF-1190A-8））", 2.35, 15000, 35250])
    ci.append([None, "TOTAL:", None, 25000, 65750])

    pl = workbook.create_sheet("PL")
    pl.append(["PACKING LIST", None, None, None])
    pl.append(["Package List", None, None, None])
    pl.append(["Package No", "Article Name", "Dimension\n（M³）", "Weight\n(Kg)"])
    for index in range(1, 11):
        pl.append([index, "TPU,Termoplástico poliuretano（热塑性聚氨酯（TPU HF-8695AU））", 1.68, 1030])
    for index in range(11, 26):
        pl.append([index, "TPU,Termoplástico poliuretano（热塑性聚氨酯（TPU HF-1190A-8））", 1.68, 1030])
    pl.append([None, None, 42, 25750])

    file_path = Path("tmp_ci_pl_workbook_test.xlsx")
    try:
        workbook.save(file_path)
        workbook.close()

        meta, blocks = parse_yuewei_excel_workbook(file_path)
    finally:
        workbook.close()
        if file_path.exists():
            file_path.unlink()

    assert meta["sourceSheet"] == "CI+PL"
    assert meta["parser"] == "ci_pl_workbook"
    assert summarize_excel_blocks(blocks) == {
        "block_count": 1,
        "item_count": 2,
        "batch_ids": ["HFZF25087160"],
    }
    first_item = blocks[0]["items"][0]
    second_item = blocks[0]["items"][1]
    assert first_item[3] == 10000
    assert first_item[11]["specModel"] == "HF-8695AU"
    assert first_item[11]["actualShippedQty"] == 10000
    assert first_item[11]["grossWeightKg"] == 10300
    assert first_item[11]["volumeM3"] == 16.8
    assert second_item[11]["specModel"] == "HF-1190A-8"
    assert second_item[11]["grossWeightKg"] == 15450
    assert second_item[11]["volumeM3"] == 25.2


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
