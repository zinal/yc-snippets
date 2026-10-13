"""Инстанс-группы для баз, уже выгруженных ``scripts/export-ydb.py``.

Имя группы — ``instance-group-<database-id>``, каталог задаёт ``--folder-id``.
Список групп строится через ``build_argv`` из записи каталога
``compute.instance-group``. Полное описание и живой список машин — команды
справочника CLI, которых нет в каталоге ``list``:

- ``yc compute instance-group get --full``
- ``yc compute instance-group list-instances``

Справка: https://yandex.cloud/en/docs/compute/cli-ref/instance-group/get
и https://yandex.cloud/en/docs/compute/cli-ref/instance-group/list-instances.
Поля ``status`` и ``zone_id`` — из ``ManagedInstance`` в cloudapi.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from yc_snippets.catalog import load_catalog
from yc_snippets.plan import PlanError, assert_safe_argv, build_argv
from yc_snippets.redact import redact

PROFILE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
LIST_COMMAND = "compute.instance-group"
SIDECAR_SUFFIX = ".instance-group.json"


class UsageError(RuntimeError):
    pass


@dataclass(frozen=True)
class YcCall:
    returncode: int
    stdout: str
    stderr: str


YcRunner = Callable[[Sequence[str], float], YcCall]


@dataclass(frozen=True)
class DatabaseExport:
    path: Path
    database_id: str
    cloud_id: str | None
    source: str | None


@dataclass
class CollectReport:
    written: list[Path] = field(default_factory=list)
    failures: int = 0


def instance_group_name(database_id: str) -> str:
    return f"instance-group-{database_id}"


def sidecar_path(document: DatabaseExport) -> Path:
    return document.path.with_name(document.path.stem + SIDECAR_SUFFIX)


def list_argv(yc: str, profile: str, folder_id: str, limit: int) -> list[str]:
    """Список групп каталога. Аргументы берутся из записи ``compute.instance-group``."""

    command = load_catalog().get(LIST_COMMAND)
    argv = build_argv(command, scope_id=folder_id, profile=profile, limit=limit)
    argv[0] = yc
    return argv


def get_argv(yc: str, profile: str, folder_id: str, *, group_id: str | None = None, name: str | None = None) -> list[str]:
    argv = [yc, "--profile", profile, "--folder-id", folder_id, "compute", "instance-group", "get", "--full", "--format", "json"]
    if group_id:
        argv.extend(["--id", group_id])
    elif name:
        argv.extend(["--name", name])
    else:
        raise UsageError("Для instance-group get нужен id или имя")
    assert_safe_argv(argv)
    return argv


def instances_argv(
    yc: str,
    profile: str,
    folder_id: str,
    limit: int,
    *,
    group_id: str | None = None,
    name: str | None = None,
) -> list[str]:
    argv = [
        yc,
        "--profile",
        profile,
        "--folder-id",
        folder_id,
        "compute",
        "instance-group",
        "list-instances",
        "--format",
        "json",
        "--limit",
        str(limit),
    ]
    if group_id:
        argv.extend(["--id", group_id])
    elif name:
        argv.extend(["--name", name])
    else:
        raise UsageError("Для instance-group list-instances нужен id или имя")
    assert_safe_argv(argv)
    return argv


def database_directory(out_dir: Path) -> Path:
    nested = out_dir / "databases"
    if nested.is_dir():
        return nested
    return out_dir


def load_database_exports(out_dir: Path) -> tuple[list[DatabaseExport], list[str]]:
    """Прочитать конверты выгрузки YDB. Файлы групп пропускаются."""

    directory = database_directory(out_dir)
    if not directory.is_dir():
        raise UsageError(f"Каталог выгрузки не найден: {out_dir}")
    documents: list[DatabaseExport] = []
    problems: list[str] = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(SIDECAR_SUFFIX):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        database_id = payload.get("database_id") if isinstance(payload, dict) else None
        if not isinstance(database_id, str) or not database_id or database_id.startswith("-"):
            problems.append(f"{path.name}: нет database_id")
            continue
        cloud_id = payload.get("cloud_id")
        source = payload.get("source")
        documents.append(
            DatabaseExport(
                path,
                database_id,
                cloud_id if isinstance(cloud_id, str) else None,
                source if isinstance(source, str) else None,
            )
        )
    return documents, problems


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _field(payload: dict, *names: str) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _items(payload: object, *keys: str) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        lists = [value for value in payload.values() if isinstance(value, list)]
        if len(lists) == 1:
            return [item for item in lists[0] if isinstance(item, dict)]
    return []


def _truncated(payload: object, count: int, limit: int) -> bool:
    if isinstance(payload, dict):
        token = payload.get("next_page_token") or payload.get("nextPageToken")
        if isinstance(token, str) and token:
            return True
    return count >= limit


def placement(instances: Sequence[dict]) -> list[dict]:
    """Сгруппировать машины по ``zone_id`` из ответа ``list-instances``."""

    buckets: dict[str | None, list[dict]] = {}
    for item in instances:
        zone = _field(item, "zone_id", "zoneId")
        buckets.setdefault(zone, []).append(
            {
                "id": _field(item, "id"),
                "instance_id": _field(item, "instance_id", "instanceId"),
                "name": _field(item, "name"),
                "status": _field(item, "status"),
            }
        )
    rows = []
    for zone in sorted(buckets, key=lambda value: (value is None, value or "")):
        rows.append({"zone_id": zone, "count": len(buckets[zone]), "instances": buckets[zone]})
    return rows


def _call(run: YcRunner, argv: Sequence[str], timeout: float, step: str) -> tuple[object | None, str | None]:
    assert_safe_argv(list(argv))
    result = run(argv, timeout)
    if result.returncode != 0:
        detail = redact(result.stderr).strip() or f"код {result.returncode}"
        return None, f"{step}: {detail[:2000]}"
    if not result.stdout.strip():
        return None, f"{step}: пустой ответ"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, f"{step}: ответ не является JSON"


def _index_groups(items: Sequence[dict]) -> tuple[dict[str, dict], set[str]]:
    found: dict[str, dict] = {}
    duplicates: set[str] = set()
    for item in items:
        name = _field(item, "name")
        if not name:
            continue
        if name in found or name in duplicates:
            duplicates.add(name)
            found.pop(name, None)
            continue
        found[name] = item
    return found, duplicates


def _group_document(
    document: DatabaseExport,
    *,
    folder_id: str,
    collected_at: str,
    group: dict | None,
    instances: list[dict] | None,
    instances_truncated: bool,
    errors: list[dict],
    warnings: list[str],
    commands: dict[str, list[str]],
) -> dict:
    status = _field(group, "status") if group else None
    return {
        "database_file": document.path.name,
        "source": document.source,
        "database_id": document.database_id,
        "cloud_id": document.cloud_id,
        "folder_id": folder_id,
        "name": instance_group_name(document.database_id),
        "collected_at": collected_at,
        "ok": not errors and group is not None and instances is not None,
        "status": status,
        "instance_group": group,
        "instances": instances,
        "instances_truncated": instances_truncated,
        "placement": placement(instances or []),
        "warnings": warnings,
        "errors": errors,
        "commands": commands,
    }


def _check_identity(group: dict, *, folder_id: str, name: str) -> str | None:
    actual_folder = _field(group, "folder_id", "folderId")
    actual_name = _field(group, "name")
    if actual_folder and actual_folder != folder_id:
        return f"Группа {actual_name or name} лежит в каталоге {actual_folder}, а запрошен {folder_id}"
    if actual_name and actual_name != name:
        return f"Найдена группа {actual_name}, а нужна {name}"
    return None


def _read_one(
    document: DatabaseExport,
    *,
    folder_id: str,
    yc: str,
    profile: str,
    limit: int,
    timeout: float,
    run: YcRunner,
    groups: dict[str, dict],
    duplicates: set[str],
    list_truncated: bool,
    list_error: str | None,
) -> dict:
    name = instance_group_name(document.database_id)
    errors: list[dict] = []
    warnings: list[str] = []
    commands: dict[str, list[str]] = {}
    group: dict | None = None
    instances: list[dict] | None = None
    instances_truncated = False

    if name in duplicates:
        errors.append({"step": "list", "message": f"В каталоге {folder_id} несколько групп с именем {name}"})
    else:
        listed = groups.get(name)
        group_id = _field(listed, "id") if listed else None
        if listed and not group_id:
            errors.append({"step": "list", "message": f"У группы {name} в списке нет id"})
        elif listed or list_truncated or list_error:
            if list_error and not listed:
                warnings.append(list_error)
            getter = get_argv(yc, profile, folder_id, group_id=group_id, name=None if group_id else name)
            commands["get"] = getter
            payload, error = _call(run, getter, timeout, "instance-group get")
            if error:
                errors.append({"step": "get", "message": error})
            elif not isinstance(payload, dict):
                errors.append({"step": "get", "message": "instance-group get: ответ не является объектом"})
            else:
                group = payload
                mismatch = _check_identity(group, folder_id=folder_id, name=name)
                if mismatch:
                    errors.append({"step": "get", "message": mismatch})
                resolved = _field(group, "id") or group_id
                lister = instances_argv(yc, profile, folder_id, limit, group_id=resolved, name=None if resolved else name)
                commands["instances"] = lister
                listed_instances, instances_error = _call(run, lister, timeout, "instance-group list-instances")
                if instances_error:
                    errors.append({"step": "instances", "message": instances_error})
                else:
                    instances = _items(listed_instances, "instances")
                    instances_truncated = _truncated(listed_instances, len(instances), limit)
                    if instances_truncated:
                        warnings.append(f"список машин обрезан лимитом {limit}")
        else:
            errors.append({"step": "list", "message": f"В каталоге {folder_id} нет инстанс-группы {name}"})

    return _group_document(
        document,
        folder_id=folder_id,
        collected_at=_now(),
        group=group,
        instances=instances,
        instances_truncated=instances_truncated,
        errors=errors,
        warnings=warnings,
        commands=commands,
    )


def collect_instance_groups(
    documents: Sequence[DatabaseExport],
    *,
    folder_id: str,
    yc: str,
    profile: str,
    limit: int,
    timeout: float,
    run: YcRunner,
) -> CollectReport:
    report = CollectReport()
    list_command = list_argv(yc, profile, folder_id, limit)
    payload, list_error = _call(run, list_command, timeout, "instance-group list")
    groups: dict[str, dict] = {}
    duplicates: set[str] = set()
    list_truncated = False
    if list_error is None:
        items = _items(payload, "instance_groups", "instanceGroups")
        groups, duplicates = _index_groups(items)
        list_truncated = _truncated(payload, len(items), limit)
    for index, document in enumerate(documents, start=1):
        envelope = _read_one(
            document,
            folder_id=folder_id,
            yc=yc,
            profile=profile,
            limit=limit,
            timeout=timeout,
            run=run,
            groups=groups,
            duplicates=duplicates,
            list_truncated=list_truncated,
            list_error=list_error,
        )
        path = sidecar_path(document)
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.written.append(path)
        if not envelope["ok"]:
            report.failures += 1
        print(_progress(index, len(documents), document, envelope), file=sys.stderr)
    return report


def _progress(index: int, total: int, document: DatabaseExport, envelope: dict) -> str:
    prefix = f"{index}/{total} {document.database_id}"
    if envelope["ok"]:
        zones = " ".join(f"{row['zone_id']}={row['count']}" for row in envelope["placement"]) or "нет машин"
        return f"{prefix} ok {envelope['status']} {zones}"
    detail = envelope["errors"][0]["message"].replace("\n", " ") if envelope["errors"] else "ошибка"
    return f"{prefix} error: {detail[:300]}"


def print_plan(documents: Sequence[DatabaseExport], *, folder_id: str, yc: str, profile: str, limit: int) -> None:
    print(" ".join(list_argv(yc, profile, folder_id, limit)))
    for document in documents:
        name = instance_group_name(document.database_id)
        print(f"# {document.database_id}: {name}")
        print(" ".join(get_argv(yc, profile, folder_id, name=name)))
        print(" ".join(instances_argv(yc, profile, folder_id, limit, name=name)))


def subprocess_yc(argv: Sequence[str], timeout: float) -> YcCall:
    assert_safe_argv(list(argv))
    try:
        completed = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return YcCall(124, "", f"таймаут {timeout} с")
    return YcCall(completed.returncode, completed.stdout, completed.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export-instance-groups",
        description=(
            "По выгрузке баз YDB прочитать инстанс-группы instance-group-<database-id> "
            "в указанном каталоге и записать JSON рядом с описанием базы."
        ),
    )
    parser.add_argument("--folder-id", required=True, help="Каталог, в котором лежат инстанс-группы")
    parser.add_argument("--out", type=Path, default=Path("out/ydb"), help="Каталог выгрузки export-ydb. По умолчанию out/ydb")
    parser.add_argument("--profile", default="ydb-export", help="Профиль yc. По умолчанию ydb-export")
    parser.add_argument("--yc", default="yc", help="Путь к бинарнику yc")
    parser.add_argument("--limit", type=int, default=1000, help="Лимит списка групп и машин")
    parser.add_argument("--timeout", type=float, default=120, help="Таймаут одной команды yc, в секундах")
    parser.add_argument("--dry-run", action="store_true", help="Показать команды и не вызывать yc")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not PROFILE_RE.fullmatch(args.profile):
        print(f"Имя профиля содержит недопустимые символы: {args.profile}", file=sys.stderr)
        return 2
    if not args.folder_id or args.folder_id.startswith("-"):
        print("Нужен --folder-id", file=sys.stderr)
        return 2
    if args.limit < 1:
        print("--limit должен быть больше нуля", file=sys.stderr)
        return 2
    try:
        documents, problems = load_database_exports(args.out)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if not documents:
        print("В выгрузке нет описаний баз", file=sys.stderr)
        return 1 if problems else 2
    yc = args.yc
    if yc == "yc":
        found = shutil.which("yc")
        if found is None and not args.dry_run:
            print("Не найден yc. Установите Yandex Cloud CLI.", file=sys.stderr)
            return 2
        yc = found or "yc"
    if args.dry_run:
        try:
            print_plan(documents, folder_id=args.folder_id, yc=yc, profile=args.profile, limit=args.limit)
        except (PlanError, UsageError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 1 if problems else 0
    try:
        report = collect_instance_groups(
            documents,
            folder_id=args.folder_id,
            yc=yc,
            profile=args.profile,
            limit=args.limit,
            timeout=args.timeout,
            run=subprocess_yc,
        )
    except (PlanError, UsageError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"ok={len(documents) - report.failures} failed={report.failures} out={database_directory(args.out)}",
        file=sys.stderr,
    )
    if report.failures or problems:
        return 1
    return 0
