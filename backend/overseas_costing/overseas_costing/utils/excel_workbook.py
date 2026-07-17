"""中文用途：解析成本总表/钉钉附件 xlsx 为现有导入 block 结构。"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover - 只在真实解析 xlsx 时才需要报错
    load_workbook = None


MAX_EXCEL_COLUMN = "BE"

ITEM_COLUMNS = ["A", "B", "C", "D", "E", "F", "G", "H", "BA", "BC", "T"]

EXTRA_COLUMN_MAP = {
    "N": "ccRate",
    "O": "ccAntiDumping",
    "P": "igiRate",
    "Q": "igiAmount",
    "R": "ivaRate",
    "S": "ivaAmount",
    "U": "dta",
    "V": "prvDuty",
    "W": "prvIva",
    "X": "importTaxTotal",
    "Y": "revalidacion",
    "Z": "maniobras",
    "AA": "muellaje",
    "AB": "entregaMercancia",
    "AC": "previo",
    "AD": "serviceAA",
    "AE": "almacenajes",
    "AF": "reconocimientoAduanero",
    "AG": "honorarios",
    "AH": "complementoManiobras",
    "AI": "desconsolidacion",
    "AJ": "maniobraFalso",
    "AK": "arrastre",
    "AL": "patioRegulador",
    "AM": "entregaVacio",
    "AN": "limpiezaContenedor",
    "AO": "mexicoCustomsMxn",
    "AP": "mexicoCustomsRmb",
    "AQ": "mexicoCustomsUsd",
    "AR": "mexicoInlandMxn",
    "AS": "mexicoMiscMxn",
    "AT": "mexicoInlandMiscRmb",
    "AU": "chinaToMexicoFreightRmb",
    "AV": "grossWeightKg",
    "AW": "weightRatio",
    "AX": "freightAllocRmb",
    "AY": "freightAllocMxn",
    "AZ": "totalLogisticsMxn",
    "BB": "totalCostRmb",
    "BD": "projectCollection",
    "BE": "transportMode",
}

BLOCK_COLUMN_MAP = {
    "customsNo": "I",
    "waybillNo": "J",
    "chinaMiscRmb": "K",
    "chinaMiscMxn": "L",
    "oceanUsd": "M",
    "mexicoInlandMxn": "AR",
    "mexicoMiscMxn": "AS",
    "mexicoInlandMiscRmb": "AT",
    "chinaToMexicoFreightRmb": "AU",
    "projectCollection": "BD",
    "transportMode": "BE",
}


def col_to_index(column: str) -> int:
    value = 0
    for char in column.upper():
        if not ("A" <= char <= "Z"):
            raise ValueError(f"非法 Excel 列名：{column}")
        value = value * 26 + ord(char) - ord("A") + 1
    return value


COL = {column: col_to_index(column) for column in set(ITEM_COLUMNS) | set(EXTRA_COLUMN_MAP) | set(BLOCK_COLUMN_MAP.values())}


def parse_yuewei_excel_workbook(file_path: str | Path, sheet_name: str | None = None) -> tuple[dict, list[dict]]:
    """读取工作簿，返回与 excel-imported-blocks.js 兼容的 meta / blocks。

    兼容两类来源：
    1. 早期 Yuewei 成本总表，按固定 A~BE 列位解析。
    2. 钉钉国际物流审批附件中的物料/装箱明细，按表头自动识别解析。
    """

    if load_workbook is None:
        raise RuntimeError("解析 .xlsx 需要安装 openpyxl，请先安装后再导入真实 Excel。")

    path = Path(file_path).expanduser()
    workbook = load_workbook(path, data_only=True, read_only=False)
    try:
        selected_sheet_name, parser_name, warning = _select_sheet(workbook, sheet_name)
        worksheet = workbook[selected_sheet_name]
        if parser_name == "oa_attachment_detail":
            blocks = parse_oa_attachment_detail_sheet(worksheet, source_sheet=selected_sheet_name)
        else:
            blocks = parse_yuewei_sheet(worksheet, source_sheet=selected_sheet_name)
        meta = {
            "sheetCount": len(workbook.sheetnames),
            "blockCount": len(blocks),
            "itemCount": sum(len(block.get("items") or []) for block in blocks),
            "sheets": list(workbook.sheetnames),
            "sourceFile": path.name,
            "sourceSheet": selected_sheet_name,
            "requestedSheet": (sheet_name or "").strip(),
            "parser": parser_name,
        }
        if warning:
            meta["warning"] = warning
        return meta, blocks
    finally:
        workbook.close()


def _select_sheet(workbook, sheet_name: str | None) -> tuple[str, str, str]:
    requested_sheet = (sheet_name or "").strip()
    available_sheets = list(workbook.sheetnames)

    if requested_sheet and requested_sheet in workbook.sheetnames:
        parser_name = _detect_sheet_parser(workbook[requested_sheet])
        return requested_sheet, parser_name, ""

    for candidate in available_sheets:
        parser_name = _detect_sheet_parser(workbook[candidate])
        if parser_name == "oa_attachment_detail":
            warning = ""
            if requested_sheet:
                warning = f"未找到工作表“{requested_sheet}”，已自动识别并使用“{candidate}”。"
            return candidate, parser_name, warning

    if requested_sheet:
        if len(available_sheets) == 1:
            only_sheet = available_sheets[0]
            parser_name = _detect_sheet_parser(workbook[only_sheet])
            return only_sheet, parser_name, f"未找到工作表“{requested_sheet}”，当前文件只有“{only_sheet}”，已自动使用该工作表。"
        available = "、".join(available_sheets)
        raise ValueError(f"工作簿中不存在工作表：{requested_sheet}。当前文件包含：{available}。也可以把工作表名称留空，由系统自动识别。")

    first_sheet = available_sheets[0]
    return first_sheet, _detect_sheet_parser(workbook[first_sheet]), ""


def _detect_sheet_parser(worksheet) -> str:
    return "oa_attachment_detail" if _find_oa_attachment_header(worksheet) else "yuewei_cost_workbook"


def parse_yuewei_sheet(worksheet, source_sheet: str | None = None) -> list[dict]:
    source_sheet = source_sheet or worksheet.title
    reader = MergedCellReader(worksheet)
    blocks: list[dict] = []
    current_key = ""
    current_rows: list[int] = []

    def flush_current() -> None:
        nonlocal current_key, current_rows
        if current_rows:
            blocks.append(_build_block(reader, source_sheet, current_rows))
        current_key = ""
        current_rows = []

    for row_no in range(1, worksheet.max_row + 1):
        if not _is_data_row(reader, row_no):
            flush_current()
            continue

        row_key = _block_key(reader, source_sheet, row_no)
        if current_rows and row_key != current_key:
            flush_current()

        current_key = row_key
        current_rows.append(row_no)

    flush_current()
    return blocks


def parse_oa_attachment_detail_sheet(worksheet, source_sheet: str | None = None) -> list[dict]:
    """解析国际物流审批附件里的物料/装箱明细表。

    这类附件通常以“对应钉钉采购订单号、品目编码、总个数、单价、总价、出口方式”
    等中文表头为主，不适合按 A~BE 固定列位读取。
    """

    source_sheet = source_sheet or worksheet.title
    header_row, header_map = _find_oa_attachment_header(worksheet) or (0, {})
    if not header_row:
        return []

    grouped_rows: dict[str, list[dict]] = {}
    row_ranges: dict[str, list[int]] = {}
    for row_no in range(header_row + 1, worksheet.max_row + 1):
        row = _read_attachment_row(worksheet, row_no, header_map)
        if not _is_attachment_data_row(row):
            continue

        group_key = str(row.get("purchase_order_no") or f"{source_sheet}-未关联采购单").strip()
        grouped_rows.setdefault(group_key, []).append(row)
        row_ranges.setdefault(group_key, []).append(row_no)

    blocks = []
    for group_key, rows in grouped_rows.items():
        row_numbers = row_ranges[group_key]
        first = rows[0]
        block = {
            "id": group_key,
            "batchNo": group_key,
            "sourceSheet": source_sheet,
            "sourceRange": f"{source_sheet}!{row_numbers[0]}:{row_numbers[-1]}",
            "sourceTemplate": "oa_attachment_detail",
            "sourceType": "OA_ATTACHMENT",
            "sourceDocNo": group_key,
            "transportMode": first.get("transport_mode") or _transport_from_sheet_name(source_sheet),
            "projectCollection": first.get("project_collection"),
            "remark": "国际物流审批附件明细",
            "items": [_build_attachment_item(row, source_sheet) for row in rows],
        }
        blocks.append(block)

    return blocks


class MergedCellReader:
    def __init__(self, worksheet):
        self.worksheet = worksheet
        self.max_col = col_to_index(MAX_EXCEL_COLUMN)
        self._merged_values: dict[tuple[int, int], Any] = {}
        for merged_range in worksheet.merged_cells.ranges:
            top_value = _normalize_cell_value(worksheet.cell(merged_range.min_row, merged_range.min_col).value)
            min_col = max(1, merged_range.min_col)
            max_col = min(self.max_col, merged_range.max_col)
            for row_no in range(merged_range.min_row, merged_range.max_row + 1):
                for col_no in range(min_col, max_col + 1):
                    self._merged_values[(row_no, col_no)] = top_value

    def value(self, row_no: int, column: str):
        col_no = COL.get(column) or col_to_index(column)
        value = _normalize_cell_value(self.worksheet.cell(row_no, col_no).value)
        if value not in (None, ""):
            return value
        return self._merged_values.get((row_no, col_no))


def _normalize_cell_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return value


def _is_data_row(reader: MergedCellReader, row_no: int) -> bool:
    values = [reader.value(row_no, column) for column in ("A", "B", "C", "D", "E", "F", "G", "H")]
    text = " ".join(str(value) for value in values if value not in (None, ""))
    if not text:
        return False
    if any(marker in text for marker in ("物料编码", "产品名称", "单价", "总货值", "海关进口名称")):
        return False
    return True


def _block_key(reader: MergedCellReader, source_sheet: str, row_no: int) -> str:
    waybill_no = reader.value(row_no, "J")
    customs_no = reader.value(row_no, "I")
    return str(waybill_no or customs_no or f"{source_sheet}!{row_no}").strip()


def _first_row_value(reader: MergedCellReader, rows: list[int], column: str):
    for row_no in rows:
        value = reader.value(row_no, column)
        if value not in (None, ""):
            return value
    return None


def _build_block(reader: MergedCellReader, source_sheet: str, rows: list[int]) -> dict:
    start_row = rows[0]
    end_row = rows[-1]
    block = {
        "id": _first_row_value(reader, rows, "J") or _first_row_value(reader, rows, "I") or f"{source_sheet}!{start_row}",
        "sourceSheet": source_sheet,
        "sourceRange": f"{source_sheet}!{start_row}:{end_row}",
        "items": [_build_item(reader, source_sheet, row_no) for row_no in rows],
    }

    for target_field, column in BLOCK_COLUMN_MAP.items():
        value = _first_row_value(reader, rows, column)
        if value not in (None, ""):
            block[target_field] = value

    if block.get("projectCollection") and not block.get("remark"):
        block["remark"] = block["projectCollection"]
    return block


def _build_item(reader: MergedCellReader, source_sheet: str, row_no: int) -> list:
    item = [reader.value(row_no, column) for column in ITEM_COLUMNS]
    extra = {
        "excelA": reader.value(row_no, "A"),
        "sourceSheet": source_sheet,
        "sourceRow": row_no,
    }

    for column, target_field in EXTRA_COLUMN_MAP.items():
        value = reader.value(row_no, column)
        if value not in (None, ""):
            extra[target_field] = value

    item.append(extra)
    return item


ATTACHMENT_HEADER_ALIASES = {
    "purchase_order_no": ("对应钉钉采购订单号", "采购订单号", "采购订单"),
    "material_code": ("品目编码", "物料编码", "itemcode"),
    "brand": ("品牌",),
    "import_name": ("申报名称",),
    "unit": ("申报单位", "单位"),
    "supplier": ("供应商", "supplier"),
    "product_name": ("中文品名", "chinesename", "物料名称", "品名"),
    "invoice_flag": ("是否开票", "ci"),
    "hs_code": ("海关编码", "customscode", "hscode"),
    "product_name_en": ("英文品名", "englishproductname"),
    "product_name_es": ("西语品名", "spanishname"),
    "spec_model": ("规格", "型号", "specificationmodelbrand"),
    "length_m": ("长m",),
    "width_m": ("宽m",),
    "height_m": ("高m",),
    "net_weight_each_kg": ("净重nw件kg",),
    "gross_weight_each_kg": ("毛重gw件kg",),
    "unit_cbm": ("单件cbm",),
    "qty_per_piece": ("个数每件", "numberevery"),
    "piece_count": ("件数", "numberofpieces"),
    "quantity": ("总个数", "totalnumberof"),
    "packing": ("包装", "packing"),
    "total_net_weight_kg": ("总净重",),
    "gross_weight_kg": ("总毛重", "grossweight"),
    "volume_m3": ("总体积", "totalcapacity"),
    "unit_price": ("单价", "unitprice"),
    "goods_value": ("总价", "总金额", "rmb"),
    "planned_ship_date": ("计划出货日期",),
    "source_remark": ("备注", "remarks"),
    "export_mode": ("出口方式",),
    "project_collection": ("项目归属", "项目"),
}


def _find_oa_attachment_header(worksheet) -> tuple[int, dict[str, int]] | None:
    for row_no in range(1, min(worksheet.max_row, 15) + 1):
        normalized_headers = {
            col_no: _normalize_header(worksheet.cell(row_no, col_no).value)
            for col_no in range(1, worksheet.max_column + 1)
        }
        field_map = _build_attachment_header_map(normalized_headers)
        required_hits = sum(1 for field in ("material_code", "quantity", "unit_price", "goods_value") if field in field_map)
        source_hits = sum(1 for field in ("purchase_order_no", "export_mode", "project_collection") if field in field_map)
        if "material_code" in field_map and required_hits >= 3 and source_hits >= 1:
            return row_no, field_map
    return None


def _build_attachment_header_map(normalized_headers: dict[int, str]) -> dict[str, int]:
    field_map: dict[str, int] = {}
    for fieldname, aliases in ATTACHMENT_HEADER_ALIASES.items():
        for col_no, header in normalized_headers.items():
            if not header:
                continue
            if any(_normalize_header(alias) in header for alias in aliases):
                field_map[fieldname] = col_no
                break
    return field_map


def _normalize_header(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", "").replace("\n", "").replace("\r", "")
    for char in (" ", "\t", "（", "）", "(", ")", "/", "\\", "-", "_"):
        text = text.replace(char, "")
    return text.strip().lower()


def _read_attachment_row(worksheet, row_no: int, header_map: dict[str, int]) -> dict:
    row = {"excel_row_no": row_no}
    for fieldname, col_no in header_map.items():
        row[fieldname] = _normalize_cell_value(worksheet.cell(row_no, col_no).value)
    export_mode = row.get("export_mode")
    row["transport_mode"] = export_mode or _transport_from_sheet_name(worksheet.title)
    return row


def _is_attachment_data_row(row: dict) -> bool:
    key_values = [
        row.get("purchase_order_no"),
        row.get("material_code"),
        row.get("product_name"),
        row.get("import_name"),
        row.get("quantity"),
        row.get("goods_value"),
    ]
    if not any(value not in (None, "") for value in key_values):
        return False
    if not any(row.get(field) not in (None, "") for field in ("material_code", "product_name", "import_name")):
        return False
    return True


def _transport_from_sheet_name(source_sheet: str) -> str:
    if "空运" in source_sheet:
        return "空运"
    if "快递" in source_sheet:
        return "快递"
    return "海运"


def _build_attachment_item(row: dict, source_sheet: str) -> list:
    quantity = row.get("quantity") or row.get("qty_per_piece")
    product_name = row.get("product_name") or row.get("import_name")
    category = row.get("import_name")
    extra = {
        "excelA": row.get("material_code"),
        "sourceSheet": source_sheet,
        "sourceRow": row.get("excel_row_no"),
        "sourceType": "OA_ATTACHMENT",
        "sourceDocNo": row.get("purchase_order_no"),
        "purchaseOrderNo": row.get("purchase_order_no"),
        "productNameEs": row.get("product_name_es"),
        "specModel": row.get("spec_model"),
        "unit": row.get("unit"),
        "actualShippedQty": quantity,
        "grossWeightKg": row.get("gross_weight_kg"),
        "volumeM3": row.get("volume_m3"),
        "projectCollection": row.get("project_collection"),
        "transportMode": row.get("transport_mode"),
        "purchaseCurrency": "RMB",
        "sourceRemark": row.get("source_remark"),
        "supplier": row.get("supplier"),
        "packing": row.get("packing"),
        "plannedShipDate": row.get("planned_ship_date"),
    }
    return [
        row.get("material_code"),
        product_name,
        row.get("unit_price"),
        quantity,
        row.get("goods_value"),
        row.get("import_name"),
        row.get("hs_code"),
        category,
        None,
        None,
        None,
        {key: value for key, value in extra.items() if value not in (None, "")},
    ]
