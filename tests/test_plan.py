import pytest

from yc_snippets.classify import RawListCommand, build_entries
from yc_snippets.plan import Discovery, PlanError, Selection, plan_jobs, select_commands


def _commands():
    raws = [
        RawListCommand(("resource-manager", "cloud", "list"), "clouds", ("--limit",)),
        RawListCommand(("resource-manager", "folder", "list"), "folders", ("--limit",)),
        RawListCommand(("compute", "instance", "list"), "instances", ("--limit",)),
        RawListCommand(("vpc", "network", "list"), "networks", ("--limit",)),
        RawListCommand(("iot", "device", "password", "list"), "passwords", ("--device-id",)),
        RawListCommand(("managed-postgresql", "hosts", "list"), "hosts", ("--cluster-id", "--limit")),
        RawListCommand(("managed-postgresql", "cluster", "list"), "clusters", ("--limit",)),
    ]
    return build_entries(raws)


def test_dry_run_uses_placeholders_and_never_puts_token_on_argv():
    commands = select_commands(_commands(), Selection())
    jobs, skips = plan_jobs(commands, placeholders=True, profile="demo", limit=10)
    rendered = [" ".join(job.argv) for job in jobs]
    assert any("compute instance list" in line and "--folder-id $FOLDER_ID" in line for line in rendered)
    assert any("--cloud-id $CLOUD_ID" in line for line in rendered)
    assert any(line.startswith("yc resource-manager cloud list") for line in rendered)
    assert all("--token" not in line and "t1." not in line for line in rendered)
    assert all("--profile demo" in line for line in rendered)
    assert all("--limit 10" in line or "password" in line for line in rendered)
    assert not any(skip.command_id == "compute.instance" for skip in skips)


def test_explicit_folder_is_concrete_even_in_dry_run():
    commands = select_commands(_commands(), Selection(only=frozenset({"compute.instance"})))
    jobs, skips = plan_jobs(commands, placeholders=True, folder_id="b1gfolder")
    assert skips == []
    assert jobs[0].placeholder is False
    assert "--folder-id" in jobs[0].argv
    assert "b1gfolder" in jobs[0].argv
    assert "$FOLDER_ID" not in jobs[0].argv


def test_secret_command_requires_explicit_opt_in():
    with pytest.raises(PlanError):
        select_commands(_commands(), Selection(only=frozenset({"iot.device.password"})))
    chosen = select_commands(_commands(), Selection(only=frozenset({"iot.device.password"}), allow_secrets=True))
    assert chosen[0].sensitivity == "secret"


def test_discovered_folders_produce_one_job_each():
    commands = select_commands(_commands(), Selection(only=frozenset({"vpc.network"})))
    discovery = Discovery(folders=({"id": "folder-a", "cloud_id": "cloud-1"}, {"id": "folder-b", "cloud_id": "cloud-1"}))
    jobs, skips = plan_jobs(commands, discovery=discovery, placeholders=False)
    assert skips == []
    assert [job.scope_id for job in jobs] == ["folder-a", "folder-b"]


def test_parent_command_is_skipped_without_parent_id():
    commands = select_commands(_commands(), Selection(only=frozenset({"managed-postgresql.hosts"})))
    _jobs, skips = plan_jobs(commands, placeholders=False, folder_id="b1gfolder")
    assert skips[0].command_id == "managed-postgresql.hosts"
    assert "--cluster-id" in skips[0].reason
