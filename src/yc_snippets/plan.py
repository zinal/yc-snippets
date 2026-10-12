"""Построение безопасных argv для ``yc`` и списка заданий инвентаризации."""

from __future__ import annotations

from dataclasses import dataclass

from yc_snippets.classify import EXECUTABLE_SCOPES, CatalogEntry

FORBIDDEN_FLAGS = frozenset({"--service-account-key", "--token"})


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    only: frozenset[str] | None = None
    include_operational: bool = False
    include_reference: bool = False
    include_advisory: bool = False
    include_pii: bool = False
    include_credentials: bool = False
    allow_secrets: bool = False


@dataclass(frozen=True)
class Job:
    command_id: str
    argv: tuple[str, ...]
    scope: str
    scope_id: str | None
    placeholder: bool


@dataclass(frozen=True)
class Skip:
    command_id: str
    reason: str


@dataclass(frozen=True)
class Discovery:
    clouds: tuple[dict, ...] = ()
    folders: tuple[dict, ...] = ()
    organizations: tuple[dict, ...] = ()


def select_commands(commands: tuple[CatalogEntry, ...] | list[CatalogEntry], selection: Selection) -> list[CatalogEntry]:
    if selection.only is not None:
        known = {command.id: command for command in commands}
        missing = sorted(selection.only - known.keys())
        if missing:
            raise PlanError("В каталоге нет команд: " + ", ".join(missing))
        chosen = [known[command_id] for command_id in sorted(selection.only)]
    else:
        chosen = []
        for command in commands:
            if command.default:
                chosen.append(command)
                continue
            if command.alias_of:
                continue
            if selection.include_operational and command.kind == "operational" and command.sensitivity == "none":
                chosen.append(command)
            elif selection.include_reference and command.kind == "reference" and command.sensitivity == "none":
                chosen.append(command)
            elif selection.include_advisory and command.kind == "advisory" and command.sensitivity == "none":
                chosen.append(command)
            elif selection.include_pii and command.sensitivity == "pii":
                chosen.append(command)
            elif selection.include_credentials and command.sensitivity == "credential":
                chosen.append(command)
    if not selection.allow_secrets:
        blocked = [command.id for command in chosen if command.sensitivity == "secret"]
        if blocked and selection.only is not None:
            raise PlanError(
                "Команды читают секреты и не запускаются без --allow-secrets: " + ", ".join(blocked)
            )
        chosen = [command for command in chosen if command.sensitivity != "secret"]
    return chosen


def build_argv(
    command: CatalogEntry,
    *,
    scope_id: str | None = None,
    profile: str | None = None,
    limit: int | None = None,
    impersonate_service_account_id: str | None = None,
    extra_flag: tuple[str, str] | None = None,
) -> list[str]:
    argv = ["yc", *command.argv, "--format", "json"]
    if command.scope == "folder" and scope_id:
        argv.extend(["--folder-id", scope_id])
    elif command.scope == "cloud" and scope_id:
        argv.extend(["--cloud-id", scope_id])
    elif command.scope == "organization" and scope_id:
        argv.extend(["--organization-id", scope_id])
    elif command.scope == "parent" and extra_flag and scope_id:
        flag, _value_name = extra_flag
        argv.extend([flag, scope_id])
    if limit is not None and "--limit" in command.flags:
        argv.extend(["--limit", str(limit)])
    if profile:
        argv.extend(["--profile", profile])
    if impersonate_service_account_id:
        argv.extend(["--impersonate-service-account-id", impersonate_service_account_id])
    assert_safe_argv(argv)
    return argv


def assert_safe_argv(argv: list[str]) -> None:
    banned = FORBIDDEN_FLAGS.intersection(argv)
    if banned:
        raise PlanError("Нельзя передавать секреты аргументами yc: " + ", ".join(sorted(banned)))
    if "payload" in argv or (len(argv) > 1 and argv[1] == "config"):
        raise PlanError("Команда yc запрещена политикой инвентаризации: " + " ".join(argv))


def _ids(items: tuple[dict, ...] | list[dict], *, cloud_id: str | None = None) -> list[str]:
    result = []
    for item in items:
        if cloud_id and item.get("cloud_id") not in {None, cloud_id}:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            result.append(item_id)
    return result


def plan_jobs(
    commands: list[CatalogEntry],
    *,
    discovery: Discovery | None = None,
    folder_id: str | None = None,
    cloud_id: str | None = None,
    organization_id: str | None = None,
    profile: str | None = None,
    limit: int | None = 1000,
    impersonate_service_account_id: str | None = None,
    placeholders: bool = False,
) -> tuple[list[Job], list[Skip]]:
    """Собрать задания.

    ``placeholders=True`` используется сухим прогоном: вместо обхода облака
    подставляется один шаблонный идентификатор, и ``yc`` не вызывается.
    """

    found = discovery or Discovery()
    jobs: list[Job] = []
    skips: list[Skip] = []
    for command in commands:
        targets = _targets(
            command,
            found,
            folder_id=folder_id,
            cloud_id=cloud_id,
            organization_id=organization_id,
            placeholders=placeholders,
        )
        if not targets:
            skips.append(Skip(command.id, _skip_reason(command, folder_id, cloud_id, organization_id)))
            continue
        for scope_id, placeholder in targets:
            argv = build_argv(
                command,
                scope_id=None if placeholder and command.scope != "account" else scope_id,
                profile=profile,
                limit=limit,
                impersonate_service_account_id=impersonate_service_account_id,
            )
            if placeholder and command.scope == "folder":
                argv.extend(["--folder-id", "$FOLDER_ID"])
            elif placeholder and command.scope == "cloud":
                argv.extend(["--cloud-id", "$CLOUD_ID"])
            elif placeholder and command.scope == "organization":
                argv.extend(["--organization-id", "$ORGANIZATION_ID"])
            elif placeholder and command.scope == "parent" and command.parent_flag:
                argv.extend([command.parent_flag, "$PARENT_ID"])
            assert_safe_argv(argv)
            jobs.append(
                Job(
                    command_id=command.id,
                    argv=tuple(argv),
                    scope=command.scope,
                    scope_id=scope_id,
                    placeholder=placeholder,
                )
            )
    return jobs, skips


def _targets(
    command: CatalogEntry,
    discovery: Discovery,
    *,
    folder_id: str | None,
    cloud_id: str | None,
    organization_id: str | None,
    placeholders: bool,
) -> list[tuple[str | None, bool]]:
    if command.scope == "parent" or command.scope not in EXECUTABLE_SCOPES:
        if placeholders:
            return [("$PARENT_ID", True)]
        return []
    if command.scope == "account":
        return [(None, False)]
    if command.scope == "cloud":
        if cloud_id:
            return [(cloud_id, False)]
        ids = _ids(discovery.clouds)
        if ids:
            return [(item, False) for item in ids]
        return [("$CLOUD_ID", True)] if placeholders else []
    if command.scope == "folder":
        if folder_id:
            return [(folder_id, False)]
        ids = _ids(discovery.folders, cloud_id=cloud_id)
        if ids:
            return [(item, False) for item in ids]
        return [("$FOLDER_ID", True)] if placeholders else []
    if command.scope == "organization":
        if organization_id:
            return [(organization_id, False)]
        ids = _ids(discovery.organizations)
        if ids:
            return [(item, False) for item in ids]
        return [("$ORGANIZATION_ID", True)] if placeholders else []
    return []


def _skip_reason(command: CatalogEntry, folder_id: str | None, cloud_id: str | None, organization_id: str | None) -> str:
    if command.scope == "parent":
        parent = command.parent_command or "родительского ресурса"
        flag = command.parent_flag or "идентификатор родителя"
        return f"нужен {flag} из {parent}; вложенные ресурсы этим прогоном не собираются"
    if command.scope == "cloud" and not cloud_id:
        return "не найдено ни одного облака"
    if command.scope == "folder" and not folder_id:
        return "не найдено ни одного каталога"
    if command.scope == "organization" and not organization_id:
        return "не найдено ни одной организации"
    return "нет цели для команды"
