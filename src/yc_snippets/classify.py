"""Классификация команд ``yc ... list`` для каталога инвентаризации.

Правила сознательно консервативные: в прогон по умолчанию попадают только
метаданные созданных ресурсов. Справочники, операции, персональные данные и
команды, которые читают секреты, в каталоге есть, но выключены.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERSION_RE = re.compile(r"^v\d+(?:alpha|beta)?$")

REFERENCE_TAILS = frozenset(
    {
        "access-policy-template",
        "configuration",
        "disk-type",
        "drill-type",
        "hardware-pool",
        "host-type",
        "partner",
        "point-of-presence",
        "rental-period",
        "resource-preset",
        "role",
        "runtime",
        "standard-image",
        "storage-type",
        "version",
    }
)

OPERATIONAL_TAILS = frozenset(
    {
        "change-freeze",
        "execution",
        "issue",
        "maintenance",
        "synchronization-session",
    }
)

SECRET_TAILS = frozenset(
    {
        "oauth-client-secret",
        "password",
        "payload",
        "refresh-token",
    }
)

CREDENTIAL_TAILS = frozenset(
    {
        "access-key",
        "api-key",
        "certificate",
        "federated-credential",
        "key",
        "signature-certificate",
        "user-ssh-key",
    }
)

# Флаг родителя → последний сегмент id команды, которая перечисляет родителей.
PARENT_ID_FLAGS = {
    "--application-id": "application",
    "--broker-id": "broker",
    "--cluster-id": "cluster",
    "--config-id": "config",
    "--configuration-id": "configuration",
    "--container-id": "container",
    "--device-id": "device",
    "--federation-id": "federation",
    "--function-id": "function",
    "--http-router-id": "http-router",
    "--load-balancer-id": "load-balancer",
    "--oauth-client-id": "oauth-client",
    "--registry-id": "registry",
    "--repository-id": "repository",
    "--service-account-id": "service-account",
    "--subject-container-id": "subject-container",
    "--userpool-id": "userpool",
    "--workflow-id": "workflow",
    "--zone-id": "zone",
}

PARENT_FLAG_PRIORITY = (
    "--repository-id",
    "--application-id",
    "--device-id",
    "--broker-id",
    "--function-id",
    "--container-id",
    "--workflow-id",
    "--http-router-id",
    "--service-account-id",
    "--subject-container-id",
    "--cluster-id",
    "--registry-id",
    "--federation-id",
    "--userpool-id",
    "--load-balancer-id",
    "--oauth-client-id",
    "--configuration-id",
    "--config-id",
    "--zone-id",
)

# Флаги, которые сужают выборку, но не делают команду вложенной.
OPTIONAL_FILTERS = {
    "backup.backup": {"--archive-id", "--instance-id", "--type"},
    "backup.policy": {"--instance-id"},
    "backup.vm": {"--type"},
    "cdn.resource": {"--no-options"},
    "certificate-manager.certificate": {"--full"},
    "iot.device": {"--registry-id", "--registry-name"},
    "resource-manager.cloud": {"--organization-id"},
}

ACCOUNT_IDS = frozenset(
    {
        "organization-manager.organization",
        "resource-manager.cloud",
    }
)
CLOUD_IDS = frozenset({"resource-manager.folder"})

EXECUTABLE_SCOPES = frozenset({"account", "cloud", "folder", "organization"})


@dataclass(frozen=True)
class RawListCommand:
    argv: tuple[str, ...]
    description: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    description: str
    argv: tuple[str, ...]
    scope: str
    kind: str
    sensitivity: str
    default: bool
    flags: tuple[str, ...]
    parent_flag: str | None = None
    parent_command: str | None = None
    alias_of: str | None = None

    def to_json(self) -> dict:
        data = {
            "id": self.id,
            "description": self.description,
            "argv": list(self.argv),
            "scope": self.scope,
            "kind": self.kind,
            "sensitivity": self.sensitivity,
            "default": self.default,
            "flags": list(self.flags),
        }
        if self.parent_flag:
            data["parent_flag"] = self.parent_flag
        if self.parent_command:
            data["parent_command"] = self.parent_command
        if self.alias_of:
            data["alias_of"] = self.alias_of
        return data


def command_id(argv: tuple[str, ...]) -> str:
    body = argv[:-1] if argv and argv[-1] == "list" else argv
    return ".".join(body)


def strip_versions(cmd_id: str) -> str:
    return ".".join(part for part in cmd_id.split(".") if not VERSION_RE.match(part))


def _tail(cmd_id: str) -> str:
    return cmd_id.rsplit(".", 1)[-1]


def _version_key(part: str) -> tuple[int, int]:
    match = VERSION_RE.match(part)
    if not match:
        return (0, 0)
    number = int(part[1:]) if part[-1].isdigit() else int(re.match(r"^v(\d+)", part).group(1))
    stable = 1 if part[-1].isdigit() else 0
    return (number, stable)


def _sensitivity(cmd_id: str) -> str:
    if cmd_id == "certificate-manager.certificate":
        # ``list`` без ``--full`` возвращает метаданные сертификата, не ключ.
        return "none"
    parts = cmd_id.split(".")
    tail = parts[-1]
    if tail in SECRET_TAILS or "password" in parts:
        return "secret"
    if tail in CREDENTIAL_TAILS or any("certificate" in part or part.endswith("ssh-key") for part in parts):
        return "credential"
    if cmd_id.startswith("organization-manager.") and tail in {"group", "profile", "user"}:
        return "pii"
    return "none"


def _parent_flag(cmd_id: str, flags: tuple[str, ...]) -> str | None:
    optional = OPTIONAL_FILTERS.get(cmd_id, set())
    found = [flag for flag in PARENT_ID_FLAGS if flag in flags and flag not in optional]
    if found:
        for flag in PARENT_FLAG_PRIORITY:
            if flag in found:
                return flag
        return found[0]
    if "--id" in flags and cmd_id in {"cdn.origin", "organization-manager.idp.userpool.domain"}:
        return "--id"
    return None


def infer_parent_command(cmd_id: str, parent_flag: str | None, known_ids: set[str]) -> str | None:
    if parent_flag not in PARENT_ID_FLAGS:
        return None
    tail = PARENT_ID_FLAGS[parent_flag]
    parts = cmd_id.split(".")
    for end in range(len(parts) - 1, 0, -1):
        prefix = parts[:end]
        candidate = ".".join([*prefix, tail])
        if candidate in known_ids and candidate != cmd_id:
            return candidate
        joined = ".".join(prefix)
        if joined in known_ids and (joined == tail or joined.endswith("." + tail)):
            return joined
    return None


def _scope(cmd_id: str, flags: tuple[str, ...], parent_flag: str | None) -> str:
    if cmd_id.split(".", 1)[0] == "config":
        return "local"
    if cmd_id in ACCOUNT_IDS:
        return "account"
    if cmd_id in CLOUD_IDS:
        return "cloud"
    if parent_flag or cmd_id.startswith("quota-manager."):
        return "parent"
    if "--organization-id" in flags and cmd_id not in OPTIONAL_FILTERS:
        return "organization"
    return "folder"


def _is_reference(cmd_id: str, scope: str, description: str) -> bool:
    if scope == "parent":
        return False
    tail = _tail(cmd_id)
    if tail == "zone":
        # dns.zone — зона, которую создал пользователь. compute.zone и baremetal.zone — справочники.
        return not cmd_id.startswith("dns.")
    if tail in REFERENCE_TAILS or tail == "extension":
        return True
    text = description.lower()
    if text.startswith("list available ") and "in a folder" not in text and "backup" not in text:
        return True
    return False


def _kind(cmd_id: str, scope: str, description: str) -> str:
    if scope == "local":
        return "local"
    if cmd_id.startswith("adviser."):
        return "advisory"
    parts = cmd_id.split(".")
    tail = parts[-1]
    if tail in OPERATIONAL_TAILS or "maintenance" in parts or "change-freeze" in parts:
        return "operational"
    if _is_reference(cmd_id, scope, description):
        return "reference"
    return "resource"


def _canonical_ids(ids: list[str]) -> dict[str, str]:
    groups: dict[str, list[str]] = {}
    for cmd_id in ids:
        groups.setdefault(strip_versions(cmd_id), []).append(cmd_id)

    canonical: dict[str, str] = {}
    for stripped, group in groups.items():
        if stripped in group:
            chosen = stripped
        else:

            def score(item: str) -> tuple:
                versions = tuple(_version_key(part) for part in item.split(".") if VERSION_RE.match(part))
                return (versions or ((0, 0),), -item.count("."))

            chosen = max(group, key=score)
        for item in group:
            canonical[item] = chosen
    return canonical


def build_entries(raw_commands: list[RawListCommand]) -> list[CatalogEntry]:
    prelim = []
    for raw in raw_commands:
        if not raw.argv or raw.argv[-1] != "list":
            continue
        if "v0" in raw.argv:
            continue
        cmd_id = command_id(raw.argv)
        flags = tuple(dict.fromkeys(raw.flags))
        parent_flag = _parent_flag(cmd_id, flags)
        scope = _scope(cmd_id, flags, parent_flag)
        if scope == "local":
            continue
        kind = _kind(cmd_id, scope, raw.description)
        sensitivity = _sensitivity(cmd_id)
        prelim.append((raw, cmd_id, flags, parent_flag, scope, kind, sensitivity))

    known_ids = {item[1] for item in prelim}
    canonical = _canonical_ids(list(known_ids))
    entries: list[CatalogEntry] = []
    for raw, cmd_id, flags, parent_flag, scope, kind, sensitivity in prelim:
        chosen = canonical.get(cmd_id, cmd_id)
        alias_of = None if chosen == cmd_id else chosen
        parent_command = infer_parent_command(cmd_id, parent_flag, known_ids)
        default = (
            kind == "resource"
            and sensitivity == "none"
            and scope in EXECUTABLE_SCOPES
            and scope != "organization"
            and alias_of is None
        )
        entries.append(
            CatalogEntry(
                id=cmd_id,
                description=raw.description,
                argv=raw.argv,
                scope=scope,
                kind=kind,
                sensitivity=sensitivity,
                default=default,
                flags=flags,
                parent_flag=parent_flag,
                parent_command=parent_command,
                alias_of=alias_of,
            )
        )
    entries.sort(key=lambda entry: entry.id)
    return entries
