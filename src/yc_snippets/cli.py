"""Командная строка: каталог команд и инвентаризация через ``yc``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from yc_snippets.catalog import catalog_path, load_catalog, validate_catalog
from yc_snippets.plan import Selection, Skip, plan_jobs, select_commands
from yc_snippets.runner import discover, execute_jobs, needs_discovery, subprocess_yc


def _split_ids(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise SystemExit("--only не содержит ни одного идентификатора")
    return frozenset(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yc-snippets", description="Инвентаризация ресурсов Yandex Cloud через yc")
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog", help="Показать или проверить каталог команд")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    list_parser = catalog_sub.add_parser("list", help="Список команд каталога")
    list_parser.add_argument("--default", action="store_true", help="Только команды прогона по умолчанию")
    list_parser.add_argument("--scope", help="Фильтр области: account, cloud, folder, organization, parent")
    catalog_sub.add_parser("validate", help="Проверить каталог")
    show = catalog_sub.add_parser("show", help="Показать одну команду")
    show.add_argument("command_id")

    inventory = sub.add_parser("inventory", help="Собрать метаданные ресурсов")
    inventory.add_argument("--out", type=Path, help="Каталог для JSON-конвертов")
    inventory.add_argument("--dry-run", action="store_true", help="Напечатать команды yc и не вызывать их")
    inventory.add_argument("--folder-id", help="Собрать ресурсы одного каталога")
    inventory.add_argument("--cloud-id", help="Ограничить обход одним облаком")
    inventory.add_argument("--organization-id", help="Идентификатор организации для команд этой области")
    inventory.add_argument("--only", help="Идентификаторы команд через запятую")
    inventory.add_argument("--profile", help="Профиль yc. По умолчанию берётся YC_PROFILE, если она задана")
    inventory.add_argument("--limit", type=int, default=1000, help="--limit для команд, которые его поддерживают")
    inventory.add_argument("--timeout", type=float, default=120, help="Таймаут одной команды yc, в секундах")
    inventory.add_argument("--impersonate-service-account-id", help="Идентификатор сервисного аккаунта для имперсонации")
    inventory.add_argument("--include-operational", action="store_true", help="Добавить обслуживания и заморозки изменений")
    inventory.add_argument("--include-reference", action="store_true", help="Добавить справочники вроде зон и типов дисков")
    inventory.add_argument("--include-advisory", action="store_true", help="Добавить рекомендации Adviser")
    inventory.add_argument("--include-pii", action="store_true", help="Добавить пользователей и группы организации")
    inventory.add_argument("--include-credentials", action="store_true", help="Добавить метаданные ключей и сертификатов")
    inventory.add_argument(
        "--allow-secrets",
        action="store_true",
        help="Разрешить команды, которые могут вернуть секрет. Для обычной инвентаризации не нужно",
    )
    return parser


def _catalog_list(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    for command in catalog.commands:
        if args.default and not command.default:
            continue
        if args.scope and command.scope != args.scope:
            continue
        print(f"{command.id}\t{command.scope}\t{command.kind}\t{command.sensitivity}\t{command.description}")
    return 0


def _catalog_show(command_id: str) -> int:
    command = load_catalog().get(command_id)
    payload = command.to_json()
    for key, value in payload.items():
        print(f"{key}: {value}")
    return 0


def _catalog_validate() -> int:
    catalog = load_catalog()
    errors = validate_catalog(catalog)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"ok {len(catalog.commands)} commands {catalog_path()}")
    return 0


def _inventory(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    selection = Selection(
        only=_split_ids(args.only),
        include_operational=args.include_operational,
        include_reference=args.include_reference,
        include_advisory=args.include_advisory,
        include_pii=args.include_pii,
        include_credentials=args.include_credentials,
        allow_secrets=args.allow_secrets,
    )
    commands = select_commands(catalog.commands, selection)
    profile = args.profile or os.environ.get("YC_PROFILE") or None

    if args.dry_run:
        jobs, skips = plan_jobs(
            commands,
            folder_id=args.folder_id,
            cloud_id=args.cloud_id,
            organization_id=args.organization_id,
            profile=profile,
            limit=args.limit,
            impersonate_service_account_id=args.impersonate_service_account_id,
            placeholders=True,
        )
        for job in jobs:
            print(" ".join(job.argv))
        for skip in skips:
            print(f"skip {skip.command_id}: {skip.reason}", file=sys.stderr)
        return 0

    if shutil.which("yc") is None:
        print("Не найден yc. Установите Yandex Cloud CLI и повторите запуск.", file=sys.stderr)
        return 2
    if args.out is None:
        print("Для сбора нужен --out. Посмотреть команды можно через --dry-run.", file=sys.stderr)
        return 2

    need_clouds, need_folders, need_organizations = needs_discovery(
        commands,
        folder_id=args.folder_id,
        cloud_id=args.cloud_id,
        organization_id=args.organization_id,
    )
    found, problems = discover(
        catalog,
        subprocess_yc,
        cloud_id=args.cloud_id,
        profile=profile,
        limit=args.limit,
        impersonate_service_account_id=args.impersonate_service_account_id,
        timeout=args.timeout,
        need_clouds=need_clouds,
        need_folders=need_folders,
        need_organizations=need_organizations,
    )
    for problem in problems:
        print(problem, file=sys.stderr)
    jobs, skips = plan_jobs(
        commands,
        discovery=found,
        folder_id=args.folder_id,
        cloud_id=args.cloud_id,
        organization_id=args.organization_id,
        profile=profile,
        limit=args.limit,
        impersonate_service_account_id=args.impersonate_service_account_id,
        placeholders=False,
    )
    skips = [Skip("discovery", problem) for problem in problems] + skips
    report = execute_jobs(jobs, skips, out_dir=args.out, run_yc=subprocess_yc, timeout=args.timeout, dry_run=False)
    print(
        f"ok={report.ok} failed={report.failed} skipped={len(report.skips)} out={args.out}",
        file=sys.stderr,
    )
    if report.ok == 0 and report.failed > 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog" and args.catalog_command == "list":
            return _catalog_list(args)
        if args.command == "catalog" and args.catalog_command == "show":
            return _catalog_show(args.command_id)
        if args.command == "catalog" and args.catalog_command == "validate":
            return _catalog_validate()
        if args.command == "inventory":
            return _inventory(args)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.error(f"Неизвестная команда {args.command}")
    return 2
