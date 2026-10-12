from yc_snippets.catalog import load_catalog, validate_catalog


def test_shipped_catalog_matches_yc_snapshot():
    catalog = load_catalog()
    assert catalog.source["interface"] == "yc"
    assert catalog.source["version"]
    assert validate_catalog(catalog) == []

    instance = catalog.get("compute.instance")
    assert instance.default is True
    assert instance.scope == "folder"
    assert instance.argv == ("compute", "instance", "list")

    assert catalog.get("resource-manager.cloud").scope == "account"
    assert catalog.get("resource-manager.folder").scope == "cloud"
    assert catalog.get("lockbox.secret").default is True
    assert "payload" not in catalog.get("lockbox.secret").argv

    hosts = catalog.get("managed-postgresql.hosts")
    assert hosts.scope == "parent"
    assert hosts.default is False
    assert hosts.parent_command == "managed-postgresql.cluster"
    assert hosts.parent_flag == "--cluster-id"

    assert catalog.get("compute.zone").kind == "reference"
    assert catalog.get("dns.zone").kind == "resource"
    assert catalog.get("dns.zone").default is True
    assert catalog.get("managed-clickhouse.version").kind == "reference"
    assert catalog.get("managed-clickhouse.version").default is False
    assert catalog.get("organization-manager.user").sensitivity == "pii"
    assert all(command.argv[0] != "config" for command in catalog.commands)
    assert all("payload" not in command.argv for command in catalog.commands)
    assert any(command.default for command in catalog.commands)
