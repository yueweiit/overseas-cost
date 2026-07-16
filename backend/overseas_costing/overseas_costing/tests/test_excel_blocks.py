"""中文用途：Excel blocks 解析与筛选测试。"""

import json

from overseas_costing.utils.excel_blocks import (
    load_excel_blocks_js_text,
    select_excel_blocks,
    summarize_excel_blocks,
)


def test_load_excel_blocks_js_text() -> None:
    text = (
        'window.EXCEL_IMPORTED_META = {"blockCount":2};\n'
        'window.EXCEL_IMPORTED_BLOCKS = [{"id":"A","items":[[1]]},{"id":"B","items":[]}];'
    )

    meta, blocks = load_excel_blocks_js_text(text)

    assert meta["blockCount"] == 2
    assert [block["id"] for block in blocks] == ["A", "B"]


def test_select_excel_blocks_excludes_double_clear_by_default() -> None:
    blocks = [
        {"id": "DOUBLE", "sourceSheet": "2026年YUEWEI", "transportMode": "海运双清", "items": [[1]]},
        {"id": "SEA", "sourceSheet": "2026年YUEWEI", "transportMode": "海运", "items": [[1], [2]]},
        {"id": "AIR", "sourceSheet": "2026年YUEWEI", "transportMode": "空运", "items": [[1]]},
        {"id": "OLD", "sourceSheet": "2025年YUEWEI", "transportMode": "海运", "items": [[1]]},
    ]

    selected = select_excel_blocks(blocks)
    selected_with_double_clear = select_excel_blocks(blocks, include_double_clear=1)

    assert [block["id"] for block in selected] == ["SEA"]
    assert [block["id"] for block in selected_with_double_clear] == ["DOUBLE", "SEA"]
    assert summarize_excel_blocks(selected) == {
        "block_count": 1,
        "item_count": 2,
        "batch_ids": ["SEA"],
    }


def test_select_excel_blocks_supports_batch_ids_and_limit() -> None:
    blocks = [
        {"id": "A", "sourceSheet": "2026年YUEWEI", "transportMode": "海运", "items": []},
        {"id": "B", "sourceSheet": "2026年YUEWEI", "transportMode": "海运", "items": []},
    ]

    selected = select_excel_blocks(blocks, batch_ids="B,A", limit=1)

    assert json.dumps(selected, ensure_ascii=False)
    assert [block["id"] for block in selected] == ["A"]
