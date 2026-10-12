from yc_snippets.classify import RawListCommand, build_entries


def raw(argv: list[str], flags: list[str], description: str = "") -> RawListCommand:
    return RawListCommand(tuple(argv), description or argv[-2], tuple(flags))


def test_default_inventory_keeps_folder_resources_and_drops_secrets():
    entries = build_entries(
        [
            raw(["resource-manager", "cloud", "list"], ["--limit", "--organization-id"]),
            raw(["resource-manager", "folder", "list"], ["--limit"]),
            raw(["compute", "instance", "list"], ["--limit"], "List virtual machine instances"),
            raw(["compute", "zone", "list"], ["--limit"]),
            raw(["compute", "disk-type", "list"], ["--limit"]),
            raw(["lockbox", "secret", "list"], ["--limit"], "List secrets"),
            raw(["iot", "registry", "password", "list"], ["--registry-id"]),
            raw(["iam", "key", "list"], ["--service-account-id", "--limit"]),
            raw(["managed-postgresql", "cluster", "list"], ["--limit"]),
            raw(["managed-postgresql", "hosts", "list"], ["--cluster-id", "--cluster-name", "--limit"]),
            raw(["organization-manager", "user", "list"], ["--organization-id", "--limit"]),
            raw(["config", "list"], []),
            raw(["serverless", "trigger", "list"], ["--limit"]),
            raw(["serverless", "trigger", "v1", "list"], ["--limit"]),
            raw(["certificate-manager", "certificate", "list"], ["--limit", "--full"]),
            raw(["dns", "zone", "list"], ["--limit"], "List dns zones in folder."),
            raw(["managed-clickhouse", "version", "list"], ["--limit"], "List available ClickHouse versions."),
            raw(["managed-postgresql", "backup", "list"], ["--limit"], "List available backups"),
        ]
    )
    by_id = {entry.id: entry for entry in entries}

    assert "config" not in by_id
    assert by_id["compute.instance"].default is True
    assert by_id["compute.instance"].scope == "folder"
    assert by_id["lockbox.secret"].default is True
    assert by_id["lockbox.secret"].sensitivity == "none"
    assert by_id["resource-manager.cloud"].scope == "account"
    assert by_id["resource-manager.folder"].scope == "cloud"
    assert by_id["compute.zone"].kind == "reference"
    assert by_id["compute.zone"].default is False
    assert by_id["iot.registry.password"].sensitivity == "secret"
    assert by_id["iot.registry.password"].default is False
    assert by_id["iam.key"].scope == "parent"
    assert by_id["iam.key"].sensitivity == "credential"
    assert by_id["iam.key"].parent_command == "iam.service-account" or by_id["iam.key"].parent_flag == "--service-account-id"
    assert by_id["managed-postgresql.hosts"].scope == "parent"
    assert by_id["managed-postgresql.hosts"].parent_command == "managed-postgresql.cluster"
    assert by_id["managed-postgresql.hosts"].default is False
    assert by_id["organization-manager.user"].sensitivity == "pii"
    assert by_id["organization-manager.user"].default is False
    assert by_id["serverless.trigger"].default is True
    assert by_id["serverless.trigger.v1"].alias_of == "serverless.trigger"
    assert by_id["serverless.trigger.v1"].default is False
    assert by_id["certificate-manager.certificate"].sensitivity == "none"
    assert by_id["certificate-manager.certificate"].default is True
    assert by_id["dns.zone"].kind == "resource"
    assert by_id["dns.zone"].default is True
    assert by_id["managed-clickhouse.version"].kind == "reference"
    assert by_id["managed-clickhouse.version"].default is False
    assert by_id["managed-postgresql.backup"].default is True


def test_versioned_command_without_stable_alias_stays_addressable():
    entries = build_entries(
        [
            raw(["cloudrouter", "v1", "routing-instance", "list"], ["--folder-id", "--limit"]),
            raw(["cloudrouter", "v2", "peering", "list"], ["--folder-id", "--limit"]),
        ]
    )
    by_id = {entry.id: entry for entry in entries}
    assert by_id["cloudrouter.v2.peering"].alias_of is None
    assert by_id["cloudrouter.v2.peering"].default is True
    assert by_id["cloudrouter.v1.routing-instance"].default is True
