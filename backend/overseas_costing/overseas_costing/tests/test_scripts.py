"""中文用途：调试脚本测试。"""

from pathlib import Path

from overseas_costing.scripts import import_excel_workbook
from overseas_costing.scripts.recalculate_batch import recalculate, recalculate_from_env


def test_recalculate_script_delegates_to_service_in_dry_run() -> None:
    result = recalculate(batch_name="BATCH-001", version_name="VERSION-001")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["batch_name"] == "BATCH-001"
    assert result["version_name"] == "VERSION-001"
    assert "summary_snapshot" in result


def test_recalculate_script_reads_batch_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OVERSEAS_COST_BATCH", "BATCH-002")
    monkeypatch.setenv("OVERSEAS_COST_VERSION", "VERSION-002")

    result = recalculate_from_env()

    assert result["ok"] is True
    assert result["batch_name"] == "BATCH-002"
    assert result["version_name"] == "VERSION-002"


def test_recalculate_script_requires_batch_env(monkeypatch) -> None:
    monkeypatch.delenv("OVERSEAS_COST_BATCH", raising=False)

    result = recalculate_from_env()

    assert result["ok"] is False
    assert "OVERSEAS_COST_BATCH" in result["message"]


def test_import_excel_workbook_preview_from_env(monkeypatch) -> None:
    workbook_path = Path("attachment.xlsx")

    def fake_parse(path: Path, sheet_name: str | None = None):
        assert Path(path) == workbook_path
        assert sheet_name == "7月份钢化膜空运"
        return (
            {"sourceSheet": "7月份钢化膜空运", "parser": "oa_attachment_detail"},
            [
                {
                    "id": "PO-001",
                    "batchNo": "PO-001",
                    "sourceSheet": "7月份钢化膜空运",
                    "transportMode": "空运",
                    "items": [["FL004106", "钢化膜", 1.2, 500, 600]],
                }
            ],
        )

    monkeypatch.setattr(import_excel_workbook, "parse_yuewei_excel_workbook", fake_parse)
    monkeypatch.setattr(import_excel_workbook, "_resolve_file_path", lambda file_path=None: workbook_path)
    monkeypatch.setenv("OVERSEAS_COST_EXCEL_FILE", str(workbook_path))
    monkeypatch.setenv("OVERSEAS_COST_SOURCE_SHEET", "7月份钢化膜空运")
    monkeypatch.setenv("OVERSEAS_COST_TRANSPORT_KEYWORD", "空运")

    result = import_excel_workbook.preview_from_env()

    assert result["ok"] is True
    assert result["parser_meta"]["parser"] == "oa_attachment_detail"
    assert result["selected_summary"]["block_count"] == 1
    assert result["selected_summary"]["item_count"] == 1
    assert result["selection"]["include_double_clear"] is True


def test_import_excel_workbook_import_from_env(monkeypatch) -> None:
    workbook_path = Path("cost.xlsx")

    def fake_import(**kwargs):
        return {
            "ok": True,
            "source_name": kwargs["source_name"],
            "file_path": kwargs["file_path"],
            "source_sheet": kwargs["source_sheet"],
            "transport_keyword": kwargs["transport_keyword"],
            "limit": kwargs["limit"],
        }

    monkeypatch.setattr(import_excel_workbook, "import_yuewei_excel_file", fake_import)
    monkeypatch.setattr(import_excel_workbook, "_resolve_file_path", lambda file_path=None: workbook_path)
    monkeypatch.setenv("OVERSEAS_COST_EXCEL_FILE", str(workbook_path))
    monkeypatch.setenv("OVERSEAS_COST_SOURCE_NAME", "7月份钢化膜空运明细.xlsx")
    monkeypatch.setenv("OVERSEAS_COST_SOURCE_SHEET", "7月份钢化膜空运")
    monkeypatch.setenv("OVERSEAS_COST_TRANSPORT_KEYWORD", "空运")
    monkeypatch.setenv("OVERSEAS_COST_LIMIT", "2")

    result = import_excel_workbook.import_from_env()

    assert result["ok"] is True
    assert result["source_name"] == "7月份钢化膜空运明细.xlsx"
    assert result["source_sheet"] == "7月份钢化膜空运"
    assert result["transport_keyword"] == "空运"
    assert result["limit"] == 2
