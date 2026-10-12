"""Загрузка каталога команд инвентаризации."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from yc_snippets.classify import CatalogEntry

SCOPES = frozenset({"account", "cloud", "folder", "organization", "parent"})
KINDS = frozenset({"advisory", "operational", "reference", "resource"})
SENSITIVITIES = frozenset({"credential", "none", "pii", "secret"})
FORBIDDEN_ARGV = frozenset({"--service-account-key", "--token", "payload"})

DATA_PATH = Path(__file__).resolve().parent / "data" / "inventory.json"


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Catalog:
    source: dict
    commands: tuple[CatalogEntry, ...]

    def by_id(self) -> dict[str, CatalogEntry]:
        return {command.id: command for command in self.commands}

    def get(self, command_id: str) -> CatalogEntry:
        try:
            return self.by_id()[command_id]
        except KeyError as exc:
            raise CatalogError(f"В каталоге нет команды {command_id}") from exc


def catalog_path() -> Path:
    return DATA_PATH


def _entry_from_json(raw: dict) -> CatalogEntry:
    missing = [name for name in ("id", "description", "argv", "scope", "kind", "sensitivity", "default", "flags") if name not in raw]
    if missing:
        raise CatalogError(f"У команды не хватает полей {missing}: {raw.get('id')}")
    argv = tuple(raw["argv"])
    if not argv or argv[-1] != "list":
        raise CatalogError(f"{raw['id']}: argv должен заканчиваться на list")
    if any(part in FORBIDDEN_ARGV for part in argv):
        raise CatalogError(f"{raw['id']}: команда содержит запрещённый аргумент")
    if argv[0] == "config":
        raise CatalogError(f"{raw['id']}: yc config list печатает секреты профиля и не входит в каталог")
    if raw["scope"] not in SCOPES:
        raise CatalogError(f"{raw['id']}: неизвестная область {raw['scope']}")
    if raw["kind"] not in KINDS:
        raise CatalogError(f"{raw['id']}: неизвестный вид {raw['kind']}")
    if raw["sensitivity"] not in SENSITIVITIES:
        raise CatalogError(f"{raw['id']}: неизвестная чувствительность {raw['sensitivity']}")
    if raw["sensitivity"] == "secret" and raw["default"]:
        raise CatalogError(f"{raw['id']}: секретная команда не может быть включена по умолчанию")
    return CatalogEntry(
        id=raw["id"],
        description=raw["description"],
        argv=argv,
        scope=raw["scope"],
        kind=raw["kind"],
        sensitivity=raw["sensitivity"],
        default=bool(raw["default"]),
        flags=tuple(raw["flags"]),
        parent_flag=raw.get("parent_flag"),
        parent_command=raw.get("parent_command"),
        alias_of=raw.get("alias_of"),
    )


def load_catalog(path: Path | None = None) -> Catalog:
    catalog_file = path or catalog_path()
    payload = json.loads(catalog_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "commands" not in payload:
        raise CatalogError("Каталог должен быть объектом с полем commands")
    commands = tuple(_entry_from_json(item) for item in payload["commands"])
    ids = [command.id for command in commands]
    if len(ids) != len(set(ids)):
        raise CatalogError("Идентификаторы команд в каталоге должны быть уникальными")
    return Catalog(source=dict(payload.get("source") or {}), commands=commands)


def validate_catalog(catalog: Catalog) -> list[str]:
    """Проверить согласованность ссылок. Пустой список означает, что каталог годится."""

    errors: list[str] = []
    known = {command.id for command in catalog.commands}
    for command in catalog.commands:
        if command.alias_of and command.alias_of not in known:
            errors.append(f"{command.id}: alias_of указывает на неизвестную команду {command.alias_of}")
        if command.alias_of and command.default:
            errors.append(f"{command.id}: устаревшая версия команды не должна быть включена по умолчанию")
        if command.parent_command and command.parent_command not in known:
            errors.append(f"{command.id}: parent_command указывает на неизвестную команду {command.parent_command}")
        if command.scope == "parent" and command.default:
            errors.append(f"{command.id}: вложенная команда не выполняется без идентификатора родителя")
        if command.default and command.sensitivity != "none":
            errors.append(f"{command.id}: команда по умолчанию должна иметь sensitivity=none")
        if command.default and command.kind != "resource":
            errors.append(f"{command.id}: по умолчанию собираются только ресурсы")
        if "--token" in command.flags or "--service-account-key" in command.flags:
            errors.append(f"{command.id}: флаг аутентификации нельзя сохранять в каталоге")
    return errors
