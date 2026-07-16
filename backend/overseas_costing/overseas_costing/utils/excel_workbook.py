"""中文用途：解析 Yuewei 成本总表 xlsx 为现有导入 block 结构。"""

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


def parse_yuewei_excel_workbook(file_path: str | Path, sheet_name: str = "2026年YUEWEI") -> tuple[dict, list[dict]]:
    """读取成本总表工作簿，返回与 excel-imported-blocks.js 兼容的 meta / blocks。"""

    if load_workbook is None:
        raise RuntimeError("解析 .xlsx 需要安装 openpyxl，请先安装后再导入真实 Excel。")

    path = Path(file_path).expanduser()
    workbook = load_workbook(path, data_only=True, read_only=False)
    try:
        if sheet_name not in workbook.sheetnames:
            available_sheets = "、".join(workbook.sheetnames)
            raise ValueError(f"工作簿中不存在工作表：{sheet_name}。当前文件包含：{available_sheets}")

        blocks = parse_yuewei_sheet(workbook[sheet_name], source_sheet=sheet_name)
        meta = {
            "sheetCount": len(workbook.sheetnames),
            "blockCount": len(blocks),
            "itemCount": sum(len(block.get("items") or []) for block in blocks),
            "sheets": list(workbook.sheetnames),
            "sourceFile": path.name,
            "sourceSheet": sheet_name,
        }
        return meta, blocks
    finally:
        workbook.close()


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
