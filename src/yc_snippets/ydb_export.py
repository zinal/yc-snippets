"""Выгрузка метаданных конкретных баз YDB по файлу путей.

Путь базы в Yandex Cloud имеет вид ``/ru-central1/<cloud-id>/<database-id>``.
Скрипт не читает таблицы и не запрашивает токен: вход в федерацию выполняет
``yc init`` в текущем терминале и открывает браузер.
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

from yc_snippets.plan import PlanError, assert_safe_argv
from yc_snippets.redact import redact

PATH_RE = re.compile(r"^/(?P<region>[^/]+)/(?P<cloud_id>[^/]+)/(?P<database_id>[^/]+)/?$")
PROFILE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
FEDERATION_PROPERTY = "federation-id"

SCALAR_LINKS = {
    "network_id": "network",
    "networkId": "network",
    "resource_preset_id": "resource_preset",
    "resourcePresetId": "resource_preset",
    "storage_type_id": "storage_type",
    "storageTypeId": "storage_type",
}
LIST_LINKS = {
    "subnet_ids": "subnet",
    "subnetIds": "subnet",
    "security_group_ids": "security_group",
    "securityGroupIds": "security_group",
}
GET_ARGV = {
    "cloud": ("resource-manager", "cloud", "get"),
    "folder": ("resource-manager", "folder", "get"),
    "network": ("vpc", "network", "get"),
    "subnet": ("vpc", "subnet", "get"),
    "security_group": ("vpc", "security-group", "get"),
    "resource_preset": ("ydb", "resource-preset", "get"),
    "storage_type": ("ydb", "storage-type", "get"),
}


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseRef:
    source: str
    region: str
    cloud_id: str
    database_id: str
    line_no: int


@dataclass(frozen=True)
class YcCall:
    returncode: int
    stdout: str
    stderr: str


YcRunner = Callable[[Sequence[str], float], YcCall]
InheritRunner = Callable[[Sequence[str]], int]


@dataclass
class ExportReport:
    written: list[Path] = field(default_factory=list)
    failures: int = 0
    invalid: int = 0


def parse_database_path(value: str) -> tuple[str, str, str] | None:
    match = PATH_RE.fullmatch(value.strip())
    if not match:
        return None
    return match.group("region"), match.group("cloud_id"), match.group("database_id")


def parse_id_lines(text: str) -> tuple[list[DatabaseRef], list[dict]]:
    """Разобрать файл. Повтор той же базы не запускает вторую выгрузку."""

    found: list[DatabaseRef] = []
    invalid: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_database_path(line)
        if parsed is None:
            invalid.append({"line": line_no, "value": line, "error": "ожидался путь /<region>/<cloud-id>/<database-id>"})
            continue
        region, cloud_id, database_id = parsed
        key = (cloud_id, database_id)
        if key in seen:
            continue
        seen.add(key)
        found.append(DatabaseRef(line, region, cloud_id, database_id, line_no))
    return found, invalid


def profile_names(listing: str) -> list[str]:
    names = []
    for line in listing.splitlines():
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def active_profile(listing: str) -> str | None:
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "ACTIVE":
            return parts[0]
    return None


def validate_name(value: str, pattern: re.Pattern[str], title: str) -> str:
    if not pattern.fullmatch(value):
        raise AuthError(f"{title} содержит недопустимые символы: {value}")
    return value


def init_argv(yc: str, profile: str, federation_id: str) -> list[str]:
    argv = [yc, "--profile", profile, "init", f"--federation-id={federation_id}"]
    assert_export_argv(argv)
    return argv


def assert_export_argv(argv: Sequence[str]) -> None:
    """Запретить чтение токена и ``yc config list``, но оставить команды профиля."""

    items = list(argv)
    if any(item in {"--token", "--service-account-key", "payload"} for item in items):
        raise PlanError("Команда запрашивает секрет: " + " ".join(items))
    if "config" in items:
        if "token" in items or "service-account-key" in items:
            raise PlanError("Команда запрашивает секрет профиля: " + " ".join(items))
        if "list" in items and "profile" not in items:
            raise PlanError("yc config list печатает секреты профиля")
        action_at = items.index("config") + 1
        action = items[action_at] if action_at < len(items) else ""
        if action == "profile" or (action == "get" and FEDERATION_PROPERTY in items):
            return
        raise PlanError("Эта команда yc config не используется выгрузкой YDB")
    assert_safe_argv(items)


def database_get_argv(yc: str, profile: str, database_id: str) -> list[str]:
    return [yc, "--profile", profile, "ydb", "database", "get", "--id", database_id, "--format", "json"]


def access_bindings_argv(yc: str, profile: str, database_id: str, limit: int) -> list[str]:
    return [
        yc,
        "--profile",
        profile,
        "ydb",
        "database",
        "list-access-bindings",
        "--id",
        database_id,
        "--format",
        "json",
        "--limit",
        str(limit),
    ]


def backup_list_argv(yc: str, profile: str, folder_id: str, limit: int) -> list[str]:
    return [
        yc,
        "--profile",
        profile,
        "ydb",
        "backup",
        "list",
        "--folder-id",
        folder_id,
        "--format",
        "json",
        "--limit",
        str(limit),
    ]


def linked_get_argv(yc: str, profile: str, kind: str, resource_id: str) -> list[str]:
    group = GET_ARGV[kind]
    return [yc, "--profile", profile, *group, "--id", resource_id, "--format", "json"]


def federation_get_argv(yc: str, profile: str) -> list[str]:
    argv = [yc, "--profile", profile, "config", "get", FEDERATION_PROPERTY]
    assert_export_argv(argv)
    return argv


def whoami_argv(yc: str, profile: str) -> list[str]:
    return [yc, "--profile", profile, "iam", "whoami", "--format", "json"]


def collect_links(value: object, found: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    links = found if found is not None else {kind: set() for kind in GET_ARGV}
    if isinstance(value, dict):
        for key, item in value.items():
            kind = SCALAR_LINKS.get(key)
            if kind and isinstance(item, str) and item:
                links[kind].add(item)
            list_kind = LIST_LINKS.get(key)
            if list_kind and isinstance(item, list):
                for entry in item:
                    if isinstance(entry, str) and entry:
                        links[list_kind].add(entry)
            else:
                collect_links(item, links)
    elif isinstance(value, list):
        for item in value:
            collect_links(item, links)
    return links


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_json(stdout: str) -> object:
    if not stdout.strip():
        return None
    return json.loads(stdout)


def _as_list(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        lists = [item for item in payload.values() if isinstance(item, list)]
        if len(lists) == 1:
            return lists[0]
    return []


def _database_field(database: dict, *names: str) -> str | None:
    for name in names:
        value = database.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _backup_database_id(backup: dict) -> str | None:
    return _database_field(backup, "database_id", "databaseId")


def subprocess_yc(argv: Sequence[str], timeout: float) -> YcCall:
    assert_export_argv(argv)
    completed = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    return YcCall(completed.returncode, completed.stdout, completed.stderr)


def inherit_yc(argv: Sequence[str]) -> int:
    assert_export_argv(argv)
    completed = subprocess.run(list(argv), check=False)
    return completed.returncode


class Cache:
    def __init__(self, yc: str, profile: str, limit: int, timeout: float, run: YcRunner):
        self.yc = yc
        self.profile = profile
        self.limit = limit
        self.timeout = timeout
        self.run = run
        self._values: dict[tuple[str, str], tuple[object | None, str | None]] = {}
        self._backups: dict[str, tuple[list, str | None, bool]] = {}

    def get(self, kind: str, resource_id: str) -> tuple[object | None, str | None]:
        key = (kind, resource_id)
        if key not in self._values:
            self._values[key] = self._call(linked_get_argv(self.yc, self.profile, kind, resource_id), f"{kind} {resource_id}")
        return self._values[key]

    def backups(self, folder_id: str, database_id: str) -> tuple[list, str | None, bool]:
        if folder_id not in self._backups:
            payload, error = self._call(
                backup_list_argv(self.yc, self.profile, folder_id, self.limit),
                f"backup list {folder_id}",
            )
            items = [item for item in _as_list(payload) if isinstance(item, dict)]
            truncated = error is None and len(items) >= self.limit
            self._backups[folder_id] = (items, error, truncated)
        items, error, truncated = self._backups[folder_id]
        selected = [item for item in items if _backup_database_id(item) == database_id]
        return selected, error, truncated

    def _call(self, argv: list[str], step: str) -> tuple[object | None, str | None]:
        assert_export_argv(argv)
        result = self.run(argv, self.timeout)
        if result.returncode != 0:
            detail = redact(result.stderr).strip() or f"код {result.returncode}"
            return None, f"{step}: {detail[:2000]}"
        try:
            return _parse_json(result.stdout), None
        except json.JSONDecodeError:
            return None, f"{step}: ответ не является JSON"


def export_databases(
    refs: Sequence[DatabaseRef],
    invalid: Sequence[dict],
    *,
    out_dir: Path,
    yc: str,
    profile: str,
    limit: int,
    timeout: float,
    run: YcRunner,
) -> ExportReport:
    cache = Cache(yc, profile, limit, timeout, run)
    out_dir.mkdir(parents=True, exist_ok=True)
    database_dir = out_dir / "databases"
    database_dir.mkdir(parents=True, exist_ok=True)
    report = ExportReport(invalid=len(invalid))
    summary_rows = []
    collected_at = _now()

    for index, ref in enumerate(refs, start=1):
        envelope, row = _export_one(ref, cache, collected_at)
        path = database_dir / f"{ref.cloud_id}__{ref.database_id}.json"
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row["file"] = str(path)
        summary_rows.append(row)
        report.written.append(path)
        if not envelope["ok"]:
            report.failures += 1
        state = "ok" if envelope["ok"] else "error"
        print(f"{index}/{len(refs)} {ref.database_id} {state}", file=sys.stderr)

    summary = {
        "collected_at": collected_at,
        "profile": profile,
        "databases": summary_rows,
        "invalid_lines": list(invalid),
        "ok": len(refs) - report.failures,
        "failed": report.failures,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _export_one(ref: DatabaseRef, cache: Cache, collected_at: str) -> tuple[dict, dict]:
    errors: list[dict] = []
    database, error = cache._call(
        database_get_argv(cache.yc, cache.profile, ref.database_id),
        "database get",
    )
    if error:
        errors.append({"step": "database", "message": error})
    if not isinstance(database, dict):
        database = None

    bindings_payload, bindings_error = cache._call(
        access_bindings_argv(cache.yc, cache.profile, ref.database_id, cache.limit),
        "access bindings",
    )
    bindings = [item for item in _as_list(bindings_payload) if isinstance(item, dict)] if bindings_error is None else []
    if bindings_error:
        errors.append({"step": "access_bindings", "message": bindings_error})
    bindings_truncated = bindings_error is None and len(bindings) >= cache.limit

    cloud, cloud_error = cache.get("cloud", ref.cloud_id)
    if cloud_error:
        errors.append({"step": "cloud", "message": cloud_error})
        cloud = None

    folder = None
    folder_id = _database_field(database, "folder_id", "folderId") if database else None
    backups: list = []
    backups_truncated = False
    warnings: list[str] = []
    if folder_id:
        folder, folder_error = cache.get("folder", folder_id)
        if folder_error:
            errors.append({"step": "folder", "message": folder_error})
            folder = None
        backups, backup_error, backups_truncated = cache.backups(folder_id, ref.database_id)
        if backup_error:
            errors.append({"step": "backups", "message": backup_error})
    elif database is not None:
        warnings.append("в описании базы нет folder_id, резервные копии каталога не запрашивались")

    related: dict[str, dict] = {kind: {} for kind in ("network", "subnet", "security_group", "resource_preset", "storage_type")}
    if database is not None:
        for kind, ids in collect_links(database).items():
            if kind in {"cloud", "folder"}:
                continue
            for resource_id in sorted(ids):
                payload, link_error = cache.get(kind, resource_id)
                if link_error:
                    errors.append({"step": kind, "id": resource_id, "message": link_error})
                elif isinstance(payload, dict):
                    related[kind][resource_id] = payload

    endpoint = _database_field(database, "endpoint") if database else None
    if bindings_truncated:
        warnings.append(f"список прав обрезан лимитом {cache.limit}")
    if backups_truncated:
        warnings.append(f"список резервных копий каталога обрезан лимитом {cache.limit}")
    if endpoint and f"/{ref.region}/{ref.cloud_id}/{ref.database_id}" not in endpoint:
        warnings.append("endpoint базы не содержит исходный путь")

    envelope = {
        "source": ref.source,
        "line": ref.line_no,
        "region": ref.region,
        "cloud_id": ref.cloud_id,
        "database_id": ref.database_id,
        "collected_at": collected_at,
        "ok": database is not None,
        "database": database,
        "access_bindings": bindings,
        "backups": backups,
        "cloud": cloud if isinstance(cloud, dict) else None,
        "folder": folder if isinstance(folder, dict) else None,
        "related": related,
        "warnings": warnings,
        "errors": errors,
    }
    row = {
        "database_id": ref.database_id,
        "cloud_id": ref.cloud_id,
        "region": ref.region,
        "name": _database_field(database, "name") if database else None,
        "status": _database_field(database, "status") if database else None,
        "folder_id": folder_id,
        "ok": envelope["ok"],
        "errors": [item["step"] for item in errors],
    }
    return envelope, row


def _capture(argv: Sequence[str], timeout: float = 30) -> YcCall:
    assert_export_argv(argv)
    completed = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    return YcCall(completed.returncode, completed.stdout, completed.stderr)


def login_with_federation(
    *,
    yc: str,
    profile: str,
    federation_id: str,
    skip_init: bool,
    run: YcRunner = _capture,
    inherit: InheritRunner = inherit_yc,
    stdin_is_tty: bool | None = None,
) -> None:
    """Открыть браузер через ``yc init`` для федерации и проверить профиль.

    ``skip_init`` повторяет выгрузку, пока IAM-токен федерации ещё жив.
    """

    validate_name(profile, PROFILE_RE, "Имя профиля")
    listing = run([yc, "config", "profile", "list"], 30)
    if listing.returncode != 0:
        detail = redact(listing.stderr).strip() or f"код {listing.returncode}"
        raise AuthError(f"Не удалось прочитать профили yc: {detail}")
    previous = active_profile(listing.stdout)
    names = profile_names(listing.stdout)
    try:
        if profile not in names:
            code = inherit([yc, "config", "profile", "create", profile])
            if code != 0:
                raise AuthError(f"Не удалось создать профиль {profile}")
        elif previous != profile:
            code = inherit([yc, "config", "profile", "activate", profile])
            if code != 0:
                raise AuthError(f"Не удалось активировать профиль {profile}")
        if not skip_init:
            interactive = sys.stdin.isatty() if stdin_is_tty is None else stdin_is_tty
            if not interactive:
                raise AuthError(
                    "Вход в федерацию открывает браузер и задаёт вопросы в терминале. "
                    "Запустите скрипт в интерактивном сеансе."
                )
            print(
                "\n".join(
                    [
                        f"Сейчас откроется браузер для входа в федерацию {federation_id}.",
                        "Когда CLI попросит, нажмите Enter. Затем выберите облако и каталог.",
                        "Токен в аргументы команд не передаётся.",
                        "",
                    ]
                ),
                file=sys.stderr,
            )
            code = inherit(init_argv(yc, profile, federation_id))
            if code != 0:
                raise AuthError(f"yc init завершился с кодом {code}")
        check = run(federation_get_argv(yc, profile), 30)
        actual = check.stdout.strip()
        if check.returncode != 0 or not actual:
            detail = redact(check.stderr).strip() or "federation-id пуст"
            raise AuthError(f"В профиле {profile} нет федерации: {detail}")
        if actual != federation_id:
            raise AuthError(f"Профиль {profile} входит в федерацию {actual}, а нужна {federation_id}")
        subject = run(whoami_argv(yc, profile), 60)
        if subject.returncode != 0:
            detail = redact(subject.stderr).strip() or f"код {subject.returncode}"
            raise AuthError(f"Аутентификация не подтвердилась: {detail}")
    finally:
        if previous and previous != profile:
            inherit([yc, "config", "profile", "activate", previous])


def _print_plan(refs: Sequence[DatabaseRef], profile: str, yc: str, limit: int) -> None:
    for ref in refs:
        print(f"# {ref.database_id}: cloud {ref.cloud_id}; folder, backups и связанные ресурсы читаются из database get")
        print(" ".join(database_get_argv(yc, profile, ref.database_id)))
        print(" ".join(access_bindings_argv(yc, profile, ref.database_id, limit)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export-ydb",
        description=(
            "Выгрузить метаданные баз YDB из файла путей /<region>/<cloud-id>/<database-id>. "
            "Содержимое таблиц не читается."
        ),
    )
    parser.add_argument("ids_file", type=Path, help="Текстовый файл, одна база на строку")
    parser.add_argument("--federation-id", required=True, help="Идентификатор федерации для входа через браузер")
    parser.add_argument("--out", type=Path, default=Path("out/ydb"), help="Каталог для JSON. По умолчанию out/ydb")
    parser.add_argument("--profile", default="ydb-export", help="Профиль yc. По умолчанию ydb-export")
    parser.add_argument("--yc", default="yc", help="Путь к бинарнику yc")
    parser.add_argument("--limit", type=int, default=1000, help="Лимит списка прав и резервных копий")
    parser.add_argument("--timeout", type=float, default=120, help="Таймаут одной команды yc, в секундах")
    parser.add_argument("--dry-run", action="store_true", help="Показать команды и не входить в федерацию")
    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="Не открывать браузер повторно, если профиль этой федерации уже инициализирован",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.ids_file.is_file():
        print(f"Файл не найден: {args.ids_file}", file=sys.stderr)
        return 2
    try:
        validate_name(args.profile, PROFILE_RE, "Имя профиля")
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.limit < 1:
        print("--limit должен быть больше нуля", file=sys.stderr)
        return 2
    refs, invalid = parse_id_lines(args.ids_file.read_text(encoding="utf-8"))
    for item in invalid:
        print(f"строка {item['line']}: {item['error']}: {item['value']}", file=sys.stderr)
    if not refs and invalid:
        return 1
    if not refs:
        print("В файле нет идентификаторов баз", file=sys.stderr)
        return 2
    yc = args.yc
    if yc == "yc":
        found = shutil.which("yc")
        if found is None and not args.dry_run:
            print("Не найден yc. Установите Yandex Cloud CLI.", file=sys.stderr)
            return 2
        yc = found or "yc"
    if args.dry_run:
        _print_plan(refs, args.profile, yc, args.limit)
        return 1 if invalid else 0
    try:
        login_with_federation(
            yc=yc,
            profile=args.profile,
            federation_id=args.federation_id,
            skip_init=args.skip_init,
        )
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = export_databases(
        refs,
        invalid,
        out_dir=args.out,
        yc=yc,
        profile=args.profile,
        limit=args.limit,
        timeout=args.timeout,
        run=subprocess_yc,
    )
    print(
        f"ok={len(refs) - report.failures} failed={report.failures} invalid={report.invalid} out={args.out}",
        file=sys.stderr,
    )
    if report.failures or report.invalid:
        return 1
    return 0
