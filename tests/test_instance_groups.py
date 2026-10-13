import json

from yc_snippets.catalog import load_catalog
from yc_snippets.instance_groups import (
    YcCall,
    collect_instance_groups,
    get_argv,
    instances_argv,
    list_argv,
    load_database_exports,
    main,
    placement,
)
from yc_snippets.plan import build_argv

FOLDER = "b1gfolder00000000000"
DATABASE = "etn89km63k1li33bga5p"
GROUP_NAME = f"instance-group-{DATABASE}"


def _write_export(directory, database_id=DATABASE, cloud_id="yc.searchapi.service-cloud"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cloud_id}__{database_id}.json"
    path.write_text(
        json.dumps(
            {
                "source": f"/ru-central1/{cloud_id}/{database_id}",
                "database_id": database_id,
                "cloud_id": cloud_id,
                "ok": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_list_argv_comes_from_the_catalog():
    command = load_catalog().get("compute.instance-group")
    expected = build_argv(command, scope_id=FOLDER, profile="ydb-export", limit=1000)
    assert list_argv("yc", "ydb-export", FOLDER, 1000) == expected
    assert "--token" not in expected


def test_get_and_instances_use_documented_flags():
    getter = get_argv("yc", "ydb-export", FOLDER, name=GROUP_NAME)
    listed = instances_argv("yc", "ydb-export", FOLDER, 1000, group_id="cl1group")
    assert getter == [
        "yc",
        "--profile",
        "ydb-export",
        "--folder-id",
        FOLDER,
        "compute",
        "instance-group",
        "get",
        "--full",
        "--format",
        "json",
        "--name",
        GROUP_NAME,
    ]
    assert listed[-4:] == ["--limit", "1000", "--id", "cl1group"]
    assert "--token" not in getter
    assert "--token" not in listed


def test_load_skips_instance_group_sidecars(tmp_path):
    export = _write_export(tmp_path / "databases")
    sidecar = export.with_name(export.stem + ".instance-group.json")
    sidecar.write_text(json.dumps({"database_id": "not-a-database", "name": "instance-group-not-a-database"}), encoding="utf-8")
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    documents, problems = load_database_exports(tmp_path)
    assert problems == []
    assert [item.database_id for item in documents] == [DATABASE]
    assert documents[0].cloud_id == "yc.searchapi.service-cloud"


def test_collect_writes_status_settings_instances_and_zones(tmp_path):
    export = _write_export(tmp_path / "databases")
    calls = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if argv[1:4] == ["compute", "instance-group", "list"]:
            return YcCall(0, json.dumps([{"id": "cl1group", "name": GROUP_NAME, "folder_id": FOLDER}]), "")
        if "get" in argv:
            return YcCall(
                0,
                json.dumps(
                    {
                        "id": "cl1group",
                        "folder_id": FOLDER,
                        "name": GROUP_NAME,
                        "status": "ACTIVE",
                        "instance_template": {"platform_id": "standard-v3", "metadata": {"user-data": "keep-me"}},
                        "scale_policy": {"fixed_scale": {"size": "2"}},
                        "allocation_policy": {"zones": [{"zone_id": "ru-central1-a"}, {"zone_id": "ru-central1-b"}]},
                        "service_account_id": "ajesa",
                    }
                ),
                "",
            )
        if "list-instances" in argv:
            return YcCall(
                0,
                json.dumps(
                    {
                        "instances": [
                            {
                                "id": "m2",
                                "instance_id": "fhm2",
                                "name": "vm-b",
                                "status": "STOPPED",
                                "zone_id": "ru-central1-b",
                            },
                            {
                                "id": "m1",
                                "instance_id": "fhm1",
                                "name": "vm-a",
                                "status": "RUNNING_ACTUAL",
                                "zone_id": "ru-central1-a",
                            },
                        ]
                    }
                ),
                "",
            )
        return YcCall(1, "", "unexpected")

    report = collect_instance_groups(
        load_database_exports(tmp_path)[0],
        folder_id=FOLDER,
        yc="yc",
        profile="ydb-export",
        limit=1000,
        timeout=5,
        run=run,
    )
    assert report.failures == 0
    saved_path = export.with_name(export.stem + ".instance-group.json")
    assert report.written == [saved_path]
    saved = json.loads(saved_path.read_text())
    assert saved["ok"] is True
    assert saved["status"] == "ACTIVE"
    assert saved["name"] == GROUP_NAME
    assert saved["instance_group"]["instance_template"]["metadata"]["user-data"] == "keep-me"
    assert saved["instance_group"]["scale_policy"]["fixed_scale"]["size"] == "2"
    assert [item["instance_id"] for item in saved["instances"]] == ["fhm2", "fhm1"]
    assert saved["placement"] == [
        {
            "zone_id": "ru-central1-a",
            "count": 1,
            "instances": [{"id": "m1", "instance_id": "fhm1", "name": "vm-a", "status": "RUNNING_ACTUAL"}],
        },
        {
            "zone_id": "ru-central1-b",
            "count": 1,
            "instances": [{"id": "m2", "instance_id": "fhm2", "name": "vm-b", "status": "STOPPED"}],
        },
    ]
    assert calls[0][:4] == ["yc", "compute", "instance-group", "list"]
    assert ["--id", "cl1group"] in [call[-2:] for call in calls]


def test_missing_group_is_saved_next_to_the_database_without_another_get(tmp_path):
    export = _write_export(tmp_path / "databases")
    calls = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if "list-instances" in argv:
            return YcCall(1, "", "should not list instances")
        if argv[1:4] == ["compute", "instance-group", "list"]:
            return YcCall(0, json.dumps([{"id": "other", "name": "instance-group-other"}]), "")
        return YcCall(1, "", "token t1.secretvalue")

    report = collect_instance_groups(
        load_database_exports(tmp_path)[0],
        folder_id=FOLDER,
        yc="yc",
        profile="ydb-export",
        limit=1000,
        timeout=5,
        run=run,
    )
    assert report.failures == 1
    saved = json.loads(export.with_name(export.stem + ".instance-group.json").read_text())
    assert saved["ok"] is False
    assert saved["instance_group"] is None
    assert saved["errors"][0]["message"] == f"В каталоге {FOLDER} нет инстанс-группы {GROUP_NAME}"
    assert "t1.secretvalue" not in json.dumps(saved)
    assert not any("get" in call for call in calls)


def test_get_error_is_redacted(tmp_path):
    _write_export(tmp_path / "databases")

    def run(argv, _timeout):
        if argv[1:4] == ["compute", "instance-group", "list"]:
            return YcCall(0, json.dumps([{"id": "cl1group", "name": GROUP_NAME}]), "")
        if "get" in argv:
            return YcCall(1, "", "PERMISSION_DENIED token t1.secretvalue")
        return YcCall(1, "", "should not list instances")

    collect_instance_groups(
        load_database_exports(tmp_path)[0],
        folder_id=FOLDER,
        yc="yc",
        profile="ydb-export",
        limit=1000,
        timeout=5,
        run=run,
    )
    text = next((tmp_path / "databases").glob("*.instance-group.json")).read_text()
    assert "t1.secretvalue" not in text
    assert "[REDACTED IAM TOKEN]" in text


def test_truncated_list_looks_up_the_group_by_name(tmp_path):
    _write_export(tmp_path / "databases")
    calls = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if argv[1:4] == ["compute", "instance-group", "list"]:
            return YcCall(0, json.dumps([{"id": "other", "name": "instance-group-other"}]), "")
        if "get" in argv:
            return YcCall(
                0,
                json.dumps({"id": "cl1group", "folder_id": FOLDER, "name": GROUP_NAME, "status": "STOPPED"}),
                "",
            )
        if "list-instances" in argv:
            return YcCall(0, json.dumps([{"id": "m1", "status": "RUNNING_ACTUAL", "zoneId": "ru-central1-d"}]), "")
        return YcCall(1, "", "unexpected")

    report = collect_instance_groups(
        load_database_exports(tmp_path)[0],
        folder_id=FOLDER,
        yc="yc",
        profile="ydb-export",
        limit=1,
        timeout=5,
        run=run,
    )
    assert report.failures == 0
    saved = json.loads(next((tmp_path / "databases").glob("*.instance-group.json")).read_text())
    assert saved["status"] == "STOPPED"
    assert saved["placement"][0]["zone_id"] == "ru-central1-d"
    assert any(call[call.index("--name") + 1] == GROUP_NAME for call in calls if "--name" in call)


def test_dry_run_prints_commands_without_calling_yc(tmp_path, capsys):
    _write_export(tmp_path / "databases")
    code = main(
        [
            "--folder-id",
            FOLDER,
            "--out",
            str(tmp_path),
            "--dry-run",
            "--yc",
            "yc",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "compute instance-group list" in captured.out
    assert f"--folder-id {FOLDER}" in captured.out
    assert f"--name {GROUP_NAME}" in captured.out
    assert "--full" in captured.out
    assert "list-instances" in captured.out
    assert "--token" not in captured.out
    assert list((tmp_path / "databases").glob("*.instance-group.json")) == []


def test_placement_groups_instances_by_zone():
    rows = placement(
        [
            {"zone_id": "ru-central1-b", "status": "STOPPED", "instance_id": "b"},
            {"zone_id": "ru-central1-b", "status": "RUNNING_ACTUAL", "instance_id": "b2"},
            {"zone_id": "ru-central1-a", "status": "RUNNING_ACTUAL", "instance_id": "a"},
        ]
    )
    assert [(row["zone_id"], row["count"]) for row in rows] == [("ru-central1-a", 1), ("ru-central1-b", 2)]
