from overseas_costing.scripts import import_oa_logistics


def test_scheduled_pull_logistics_approvals_skips_without_credentials(monkeypatch) -> None:
    for key in (
        "DINGTALK_ACCESS_TOKEN",
        "DINGTALK_APP_KEY",
        "DINGTALK_APPKEY",
        "DINGTALK_APP_SECRET",
        "DINGTALK_APPSECRET",
        "DINGTALK_CORP_ID",
        "DINGTALK_CLIENT_ID",
        "DINGTALK_CLIENT_SECRET",
        "DINGTALK_ENV_FILE",
        "DINGTALK_SCHEDULE_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")

    result = import_oa_logistics.scheduled_pull_logistics_approvals()

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"]


def test_scheduled_pull_logistics_approvals_pulls_all_transport_modes(monkeypatch) -> None:
    pull_calls = []
    save_calls = []
    logged = []

    def fake_pull_logistics_approvals(**kwargs):
        pull_calls.append(kwargs)
        return {
            "ok": True,
            "transport_modes": ["SEA", "AIR", "EXPRESS"],
            "total_instance_count": 4,
            "detail_count": 4,
            "transport_counts": {"SEA": 2, "AIR": 1, "EXPRESS": 1},
            "filtered_count": 4,
            "items": [{"source_approval_no": "202601300932000271071"}],
        }

    def fake_save_sea_approvals_to_erp(result):
        save_calls.append(result)
        return {
            "ok": True,
            "created_count": 1,
            "updated_count": 2,
            "unchanged_count": 1,
            "skipped_count": 0,
            "message": "ok",
        }

    monkeypatch.setenv("DINGTALK_APP_KEY", "APP-KEY")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "APP-SECRET")
    monkeypatch.setenv("DINGTALK_SCHEDULE_PULL_START", "2026-01-01")
    monkeypatch.setenv("DINGTALK_SCHEDULE_PULL_END", "2026-07-29")
    monkeypatch.setenv("DINGTALK_SCHEDULE_TRANSPORT_MODES", "SEA,AIR,EXPRESS")
    monkeypatch.setenv("DINGTALK_SCHEDULE_LIMIT", "4")
    monkeypatch.setattr(import_oa_logistics, "resolve_dingtalk_env_file", lambda env_file=None: "")
    monkeypatch.setattr(import_oa_logistics, "pull_logistics_approvals", fake_pull_logistics_approvals)
    monkeypatch.setattr(import_oa_logistics, "save_sea_approvals_to_erp", fake_save_sea_approvals_to_erp)
    monkeypatch.setattr(import_oa_logistics, "_log_scheduled_pull_summary", lambda summary: logged.append(summary))

    result = import_oa_logistics.scheduled_pull_logistics_approvals()

    assert result["ok"] is True
    assert result["start"] == "2026-01-01"
    assert result["end"] == "2026-07-29"
    assert result["save"]["created_count"] == 1
    assert pull_calls[0]["transport_modes"] == "SEA,AIR,EXPRESS"
    assert pull_calls[0]["limit"] == 4
    assert pull_calls[0]["app_key"] == "APP-KEY"
    assert save_calls[0]["items"][0]["source_approval_no"] == "202601300932000271071"
    assert logged[0]["pull"]["transport_counts"] == {"SEA": 2, "AIR": 1, "EXPRESS": 1}
