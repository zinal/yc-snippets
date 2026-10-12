import json

from yc_snippets.catalog import Catalog
from yc_snippets.classify import CatalogEntry, RawListCommand, build_entries
from yc_snippets.plan import Selection, plan_jobs, select_commands
from yc_snippets.runner import YcResult, discover, execute_jobs


def test_execute_writes_envelopes_and_continues_after_error(tmp_path):
    entries = build_entries(
        [
            RawListCommand(("compute", "instance", "list"), "instances", ("--limit",)),
            RawListCommand(("vpc", "network", "list"), "networks", ("--limit",)),
        ]
    )
    commands = select_commands(entries, Selection())
    jobs, skips = plan_jobs(commands, placeholders=False, folder_id="b1gfolder", limit=None)
    calls = []

    def fake(argv, timeout):
        calls.append(argv)
        if "instance" in argv:
            return YcResult(0, json.dumps([{"id": "vm-1", "name": "web"}]), "")
        return YcResult(1, "", "PERMISSION_DENIED token t1.secretvalue")

    report = execute_jobs(jobs, skips, out_dir=tmp_path, run_yc=fake, timeout=5, dry_run=False)
    assert report.ok == 1
    assert report.failed == 1
    saved = json.loads((tmp_path / "folders" / "b1gfolder" / "compute.instance.json").read_text())
    assert saved["resources"][0]["id"] == "vm-1"
    assert "--token" not in saved["command"]
    error = json.loads((tmp_path / "folders" / "b1gfolder" / "vpc.network.json").read_text())
    assert "t1.secretvalue" not in error["stderr"]
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["resources_by_type"]["compute.instance"] == 1
    assert calls


def test_discover_skips_a_cloud_whose_folder_list_failed():
    def entry(argv: tuple[str, ...], scope: str) -> CatalogEntry:
        return CatalogEntry(
            id=".".join(argv[:-1]),
            description="",
            argv=argv,
            scope=scope,
            kind="resource",
            sensitivity="none",
            default=True,
            flags=("--limit",),
        )

    catalog = Catalog(
        source={},
        commands=(
            entry(("resource-manager", "cloud", "list"), "account"),
            entry(("resource-manager", "folder", "list"), "cloud"),
        ),
    )

    def fake(argv, _timeout):
        if argv[1:4] == ["resource-manager", "cloud", "list"]:
            return YcResult(0, json.dumps([{"id": "cloud-a"}, {"id": "cloud-b"}]), "")
        if "cloud-a" in argv:
            return YcResult(1, "", "PERMISSION_DENIED t1.secret")
        return YcResult(0, json.dumps([{"id": "folder-b"}]), "")

    found, problems = discover(
        catalog,
        fake,
        cloud_id=None,
        profile=None,
        limit=None,
        impersonate_service_account_id=None,
        timeout=5,
        need_clouds=True,
        need_folders=True,
        need_organizations=False,
    )
    assert [folder["id"] for folder in found.folders] == ["folder-b"]
    assert found.folders[0]["cloud_id"] == "cloud-b"
    assert len(problems) == 1
    assert "t1.secret" not in problems[0]
