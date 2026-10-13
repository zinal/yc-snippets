import json

import pytest

from yc_snippets.plan import PlanError
from yc_snippets.ydb_export import (
    AuthError,
    YcCall,
    assert_export_argv,
    access_bindings_argv,
    active_profile,
    database_get_argv,
    export_databases,
    init_argv,
    login_with_federation,
    main,
    parse_id_lines,
)


def test_parse_keeps_region_cloud_and_database_and_skips_duplicates():
    refs, invalid = parse_id_lines(
        "\n".join(
            [
                "# comment",
                "/ru-central1/b1gcloud000000000000/etndb000000000000001",
                "",
                "/ru-central1/b1gcloud000000000000/etndb000000000000001",
                "not-a-path",
                "/ru-central1/b1gother000000000000/etndb000000000000002/",
            ]
        )
    )
    assert [(item.cloud_id, item.database_id) for item in refs] == [
        ("b1gcloud000000000000", "etndb000000000000001"),
        ("b1gother000000000000", "etndb000000000000002"),
    ]
    assert refs[0].region == "ru-central1"
    assert invalid[0]["line"] == 5


def test_profile_commands_are_allowed_and_token_commands_are_not():
    assert_export_argv(["yc", "config", "profile", "list"])
    assert_export_argv(["yc", "--profile", "ydb-export", "config", "get", "federation-id"])
    with pytest.raises(PlanError):
        assert_export_argv(["yc", "config", "get", "token"])
    with pytest.raises(PlanError):
        assert_export_argv(["yc", "config", "list"])


def test_init_argv_opens_browser_for_the_given_federation():
    argv = init_argv("yc", "ydb-export", "yc.yandex-team.federation")
    assert argv == ["yc", "--profile", "ydb-export", "init", "--federation-id=yc.yandex-team.federation"]
    assert "--no-browser" not in argv
    assert "--token" not in argv


def test_active_profile_reads_marker():
    assert active_profile("default\nydb-export ACTIVE\n") == "ydb-export"


def test_export_writes_database_rights_backups_and_linked_resources(tmp_path):
    refs, invalid = parse_id_lines("/ru-central1/b1gcloud000000000000/etndb000000000000001\n")
    calls = []

    def fake(argv, _timeout):
        calls.append(list(argv))
        text = " ".join(argv)
        if "database get" in text or argv[3:6] == ["ydb", "database", "get"]:
            return YcCall(
                0,
                json.dumps(
                    {
                        "id": "etndb000000000000001",
                        "name": "payments",
                        "status": "RUNNING",
                        "folder_id": "b1gfolder00000000000",
                        "network_id": "enpnetwork000000000",
                        "subnet_ids": ["e2subnet000000000001"],
                        "resource_preset_id": "medium",
                        "storage_config": {"storage_type_id": "ssd"},
                        "endpoint": "grpcs://ydb.serverless.yandexcloud.net:2135/?database=/ru-central1/b1gcloud000000000000/etndb000000000000001",
                    }
                ),
                "",
            )
        if "list-access-bindings" in text:
            return YcCall(0, json.dumps([{"role_id": "ydb.viewer", "subject": {"id": "ajeuser", "type": "userAccount"}}]), "")
        if "backup" in argv and "list" in argv:
            return YcCall(
                0,
                json.dumps(
                    [
                        {"id": "backup-1", "database_id": "etndb000000000000001", "status": "READY"},
                        {"id": "backup-2", "database_id": "other", "status": "READY"},
                    ]
                ),
                "",
            )
        if "resource-manager" in argv and "cloud" in argv:
            return YcCall(0, json.dumps({"id": "b1gcloud000000000000", "name": "prod"}), "")
        if "folder" in argv:
            return YcCall(0, json.dumps({"id": "b1gfolder00000000000", "name": "data"}), "")
        if "network" in argv:
            return YcCall(0, json.dumps({"id": "enpnetwork000000000", "name": "vpc"}), "")
        if "subnet" in argv:
            return YcCall(0, json.dumps({"id": "e2subnet000000000001", "zone_id": "ru-central1-a"}), "")
        if "resource-preset" in argv:
            return YcCall(0, json.dumps({"id": "medium", "cores": 2}), "")
        if "storage-type" in argv:
            return YcCall(0, json.dumps({"id": "ssd"}), "")
        return YcCall(1, "", "unexpected t1.secret")

    report = export_databases(refs, invalid, out_dir=tmp_path, yc="yc", profile="ydb-export", limit=1000, timeout=5, run=fake)
    assert report.failures == 0
    saved = json.loads((tmp_path / "databases" / "b1gcloud000000000000__etndb000000000000001.json").read_text())
    assert saved["database"]["name"] == "payments"
    assert saved["access_bindings"][0]["role_id"] == "ydb.viewer"
    assert [item["id"] for item in saved["backups"]] == ["backup-1"]
    assert saved["cloud"]["name"] == "prod"
    assert saved["folder"]["name"] == "data"
    assert saved["related"]["network"]["enpnetwork000000000"]["name"] == "vpc"
    assert saved["related"]["subnet"]["e2subnet000000000001"]["zone_id"] == "ru-central1-a"
    assert saved["related"]["resource_preset"]["medium"]["cores"] == 2
    assert saved["related"]["storage_type"]["ssd"]["id"] == "ssd"
    assert saved["ok"] is True
    assert all("--token" not in call for call in calls)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["ok"] == 1
    assert summary["databases"][0]["status"] == "RUNNING"


def test_export_keeps_file_when_database_get_fails(tmp_path):
    refs, invalid = parse_id_lines("/ru-central1/b1gcloud000000000000/etndb000000000000001\n")

    def fake(argv, _timeout):
        if "database" in argv and "get" in argv:
            return YcCall(1, "", "PERMISSION_DENIED token t1.secretvalue")
        if "cloud" in argv:
            return YcCall(0, json.dumps({"id": "b1gcloud000000000000"}), "")
        return YcCall(1, "", "skipped")

    report = export_databases(refs, invalid, out_dir=tmp_path, yc="yc", profile="ydb-export", limit=10, timeout=5, run=fake)
    assert report.failures == 1
    saved = json.loads(next((tmp_path / "databases").iterdir()).read_text())
    assert saved["ok"] is False
    assert saved["database"] is None
    assert "t1.secretvalue" not in json.dumps(saved)


def test_login_refuses_noninteractive_terminal_and_restores_profile():
    calls = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if argv[1:4] == ["config", "profile", "list"]:
            return YcCall(0, "default ACTIVE\n", "")
        return YcCall(0, "", "")

    def inherit(argv):
        calls.append(list(argv))
        return 0

    with pytest.raises(AuthError, match="интерактивном"):
        login_with_federation(
            yc="yc",
            profile="ydb-export",
            federation_id="ajeexamplefederation",
            skip_init=False,
            run=run,
            inherit=inherit,
            stdin_is_tty=False,
        )
    assert ["yc", "config", "profile", "activate", "default"] in calls
    assert not any("--no-browser" in call or "--token" in call for call in calls)


def test_dotted_federation_id_passes_cli_checks(tmp_path, capsys):
    ids = tmp_path / "databases.txt"
    ids.write_text("/ru-central1/b1gcloud000000000000/etndb000000000000001\n", encoding="utf-8")
    code = main([str(ids), "--federation-id", "yc.yandex-team.federation", "--dry-run"])
    captured = capsys.readouterr()
    assert code == 0
    assert "недопустимые символы" not in captured.err


def test_skip_init_accepts_dotted_federation_id():
    calls = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if argv[1:4] == ["config", "profile", "list"]:
            return YcCall(0, "ydb-export ACTIVE\n", "")
        if argv[-1] == "federation-id":
            return YcCall(0, "yc.yandex-team.federation\n", "")
        if "whoami" in argv:
            return YcCall(0, json.dumps({"id": "ajeuser"}), "")
        return YcCall(1, "", "unexpected")

    login_with_federation(
        yc="yc",
        profile="ydb-export",
        federation_id="yc.yandex-team.federation",
        skip_init=True,
        run=run,
        inherit=lambda argv: calls.append(list(argv)) or 0,
        stdin_is_tty=False,
    )
    assert any(call[-1] == "federation-id" for call in calls)


def test_skip_init_checks_federation_without_opening_browser():
    calls = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if argv[1:4] == ["config", "profile", "list"]:
            return YcCall(0, "ydb-export ACTIVE\n", "")
        if argv[-1] == "federation-id":
            return YcCall(0, "ajeexamplefederation\n", "")
        if "whoami" in argv:
            return YcCall(0, json.dumps({"id": "ajeuser"}), "")
        return YcCall(1, "", "unexpected")

    login_with_federation(
        yc="yc",
        profile="ydb-export",
        federation_id="ajeexamplefederation",
        skip_init=True,
        run=run,
        inherit=lambda argv: calls.append(list(argv)) or 0,
        stdin_is_tty=False,
    )
    assert not any("init" in call for call in calls)
    assert access_bindings_argv("yc", "ydb-export", "etn", 1)[-4:] == ["--format", "json", "--limit", "1"]
    assert database_get_argv("yc", "ydb-export", "etn")[3:6] == ["ydb", "database", "get"]
