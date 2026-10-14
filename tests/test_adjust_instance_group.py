from pathlib import Path

import yaml

from yc_snippets.adjust_instance_group import (
    GIB,
    YcCall,
    adjust_instance_group,
    get_argv,
    main,
    prepare_specification,
    update_argv,
)

GROUP = "cl1examplegroupid0001"
SPEC_TEXT = """\
id: cl1examplegroupid0001
folder_id: b1gfolder00000000000
created_at: "2025-06-26T14:26:22.849Z"
name: instance-group-example
description: Instance group for database example
labels:
  database: example
instance_template:
  platform_id: standard-v3
  resources_spec:
    memory: "68719476736"
    cores: "16"
    core_fraction: "100"
  metadata:
    user-data: keep-me
  boot_disk_spec:
    mode: READ_WRITE
scale_policy:
  fixed_scale:
    size: "3"
deploy_policy:
  max_deleting: "5"
  max_expansion: "10"
  startup_duration: 300s
  strategy: PROACTIVE
allocation_policy:
  zones:
    - zone_id: ru-central1-a
      instance_tags_pool:
        - keep-tag
    - zone_id: ru-central1-d
      instance_tags_pool:
        - zone-d-tag
load_balancer_state: {}
managed_instances_state:
  target_size: "3"
  running_actual_count: "7"
health_checks_spec:
  health_check_specs:
    - interval: 10s
      tcp_options:
        port: "2135"
service_account_id: aje1example0000000000
status: ACTIVE
application_load_balancer_state: {}
disable_zone_statuses:
  - zone_id: ru-central1-b
"""


def test_get_and_update_argv_match_the_cli():
    getter = get_argv("yc", GROUP)
    updater = update_argv("yc", GROUP, Path("group.yaml"))
    assert getter == ["yc", "compute", "instance-group", "get", "--full", GROUP]
    assert updater == [
        "yc",
        "compute",
        "instance-group",
        "update",
        GROUP,
        "--file",
        "group.yaml",
    ]
    assert "--token" not in getter
    assert "--async" not in updater


def test_prepare_sets_flavor_zone_and_size_and_drops_readonly_fields():
    prepared = prepare_specification(
        yaml.safe_load(SPEC_TEXT),
        zone="ru-central1-d",
        platform="standard-v4a",
        cores=8,
        memory_gb=32,
        size=6,
    )
    assert set(prepared) <= {
        "name",
        "description",
        "labels",
        "instance_template",
        "scale_policy",
        "deploy_policy",
        "allocation_policy",
        "health_checks_spec",
        "service_account_id",
    }
    for readonly in (
        "id",
        "folder_id",
        "created_at",
        "load_balancer_state",
        "managed_instances_state",
        "status",
        "application_load_balancer_state",
        "disable_zone_statuses",
    ):
        assert readonly not in prepared
    template = prepared["instance_template"]
    assert template["platform_id"] == "standard-v4a"
    assert template["resources_spec"]["cores"] == "8"
    assert template["resources_spec"]["memory"] == str(32 * GIB)
    assert template["resources_spec"]["memory"] == "34359738368"
    assert template["resources_spec"]["core_fraction"] == "100"
    assert template["metadata"]["user-data"] == "keep-me"
    assert template["boot_disk_spec"]["mode"] == "READ_WRITE"
    assert prepared["scale_policy"]["fixed_scale"]["size"] == "6"
    assert "auto_scale" not in prepared["scale_policy"]
    assert prepared["deploy_policy"]["max_expansion"] == "10"
    assert prepared["allocation_policy"]["zones"] == [
        {"zone_id": "ru-central1-d", "instance_tags_pool": ["zone-d-tag"]}
    ]
    assert prepared["health_checks_spec"]["health_check_specs"][0]["tcp_options"]["port"] == "2135"
    assert prepared["service_account_id"] == "aje1example0000000000"
    assert prepared["name"] == "instance-group-example"


def test_prepare_replaces_auto_scale_with_fixed_size():
    document = {
        "name": "group",
        "instance_template": {"platform_id": "standard-v3", "resources_spec": {"cores": 2, "memory": 2147483648}},
        "scale_policy": {"auto_scale": {"min_zone_size": 1, "max_size": 5}},
        "allocation_policy": {"zones": [{"zone_id": "ru-central1-a"}]},
    }
    prepared = prepare_specification(
        document,
        zone="ru-central1-b",
        platform="standard-v4a",
        cores=4,
        memory_gb=8,
        size=2,
    )
    assert prepared["scale_policy"] == {"fixed_scale": {"size": 2}}
    assert prepared["instance_template"]["resources_spec"]["memory"] == 8 * GIB
    assert prepared["allocation_policy"]["zones"] == [{"zone_id": "ru-central1-b"}]
    assert document["scale_policy"]["auto_scale"]["max_size"] == 5


def test_dry_run_prints_commands_and_does_not_call_yc(capsys, tmp_path):
    calls: list[list[str]] = []

    def run(argv, timeout):
        calls.append(list(argv))
        return YcCall(0, "", "")

    code = adjust_instance_group(
        group_id=GROUP,
        zone="ru-central1-d",
        platform="standard-v4a",
        cores=8,
        memory_gb=32,
        size=6,
        spec=tmp_path / "group.yaml",
        dry_run=True,
        run=run,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert calls == []
    assert f"compute instance-group get --full {GROUP}" in captured.out
    assert f"compute instance-group update {GROUP} --file " in captured.out
    assert not (tmp_path / "group.yaml").exists()


def test_apply_writes_spec_then_updates(tmp_path):
    spec = tmp_path / "nested" / "group.yaml"
    calls: list[list[str]] = []

    def run(argv, timeout):
        calls.append(list(argv))
        if argv[1:4] == ["compute", "instance-group", "get"]:
            return YcCall(0, SPEC_TEXT, "get stderr\n")
        return YcCall(0, "name: instance-group-example\n", "")

    code = main(
        [
            "--instance-group-id",
            GROUP,
            "--zone",
            "ru-central1-d",
            "--platform",
            "standard-v4a",
            "--cores",
            "8",
            "--memory-gb",
            "32",
            "--size",
            "6",
            "--spec",
            str(spec),
            "--yc",
            "yc-test",
        ],
        run=run,
    )
    assert code == 0
    assert calls[0][1:6] == ["compute", "instance-group", "get", "--full", GROUP]
    assert calls[1][1:5] == ["compute", "instance-group", "update", GROUP]
    assert calls[1][-2:] == ["--file", str(spec)]
    saved = yaml.safe_load(spec.read_text(encoding="utf-8"))
    assert saved["instance_template"]["platform_id"] == "standard-v4a"
    assert saved["scale_policy"]["fixed_scale"]["size"] == "6"
    assert "id" not in saved
    assert "managed_instances_state" not in saved


def test_get_failure_does_not_update(tmp_path):
    calls: list[list[str]] = []

    def run(argv, timeout):
        calls.append(list(argv))
        return YcCall(1, "", "denied\n")

    code = adjust_instance_group(
        group_id=GROUP,
        zone="ru-central1-d",
        platform="standard-v4a",
        cores=8,
        memory_gb=32,
        size=6,
        spec=tmp_path / "group.yaml",
        yc="yc",
        run=run,
    )
    assert code == 1
    assert len(calls) == 1
    assert not (tmp_path / "group.yaml").exists()


def test_rejects_bad_ids_and_secrets(capsys):
    code = main(
        [
            "--instance-group-id=--token",
            "--zone",
            "ru-central1-d",
            "--platform",
            "standard-v4a",
            "--cores",
            "8",
            "--memory-gb",
            "32",
            "--size",
            "6",
            "--spec",
            "group.yaml",
            "--dry-run",
        ]
    )
    assert code == 2
    assert "Некорректный идентификатор" in capsys.readouterr().err
