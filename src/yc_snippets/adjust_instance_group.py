"""Корректировка одной инстанс-группы через YAML-спецификацию.

Алгоритм:

1. ``yc compute instance-group get --full <id>`` — описание группы в YAML.
2. В описании выставляются платформа, ядра, память, фиксированный размер и
   одна зона доступности. Поля ответа ``get``, которых нет в
   ``UpdateInstanceGroupRequest``, удаляются: иначе ``update --file`` отвечает
   ``unknown field found`` (``id``, ``folder_id``, ``load_balancer_state``,
   ``managed_instances_state``, а также ``created_at``, ``status``,
   ``application_load_balancer_state``, ``disable_zone_statuses``).
3. ``yc compute instance-group update <id> --file <spec>``. Флаг ``--async``
   не передаётся: CLI сам дожидается операции.

Память в параметре — гигабайты по 1024³ байт, как в выводе CLI:
32 ГБ записываются как ``34359738368``. Контракт:
https://github.com/yandex-cloud/cloudapi/blob/master/yandex/cloud/compute/v1/instancegroup/instance_group_service.proto
"""

from __future__ import annotations

import argparse
import copy
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from yc_snippets.plan import PlanError, assert_safe_argv

PROFILE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,49}$")
ZONE_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
PLATFORM_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
GIB = 1024**3
MAX_MEMORY_BYTES = 824633720832
MAX_FIXED_SIZE = 100

# Поля UpdateInstanceGroupRequest, которые можно оставить в --file.
# https://github.com/yandex-cloud/cloudapi/blob/master/yandex/cloud/compute/v1/instancegroup/instance_group_service.proto
UPDATE_FIELDS = frozenset(
    {
        "name",
        "description",
        "labels",
        "instance_template",
        "scale_policy",
        "deploy_policy",
        "allocation_policy",
        "health_checks_spec",
        "service_account_id",
        "load_balancer_spec",
        "variables",
        "deletion_protection",
        "application_load_balancer_spec",
        "auto_healing_policy",
    }
)


class UsageError(RuntimeError):
    pass


@dataclass(frozen=True)
class YcCall:
    returncode: int
    stdout: str
    stderr: str


YcRunner = Callable[[Sequence[str], float], YcCall]


def _global_flags(yc: str, profile: str | None, impersonate_service_account_id: str | None) -> list[str]:
    argv = [yc]
    if profile:
        argv.extend(["--profile", profile])
    if impersonate_service_account_id:
        argv.extend(["--impersonate-service-account-id", impersonate_service_account_id])
    return argv


def get_argv(
    yc: str,
    group_id: str,
    *,
    profile: str | None = None,
    impersonate_service_account_id: str | None = None,
) -> list[str]:
    argv = [
        *_global_flags(yc, profile, impersonate_service_account_id),
        "compute",
        "instance-group",
        "get",
        "--full",
        group_id,
    ]
    assert_safe_argv(argv)
    return argv


def update_argv(
    yc: str,
    group_id: str,
    spec: Path,
    *,
    profile: str | None = None,
    impersonate_service_account_id: str | None = None,
) -> list[str]:
    argv = [
        *_global_flags(yc, profile, impersonate_service_account_id),
        "compute",
        "instance-group",
        "update",
        group_id,
        "--file",
        str(spec),
    ]
    assert_safe_argv(argv)
    return argv


def _int64(previous: object, value: int) -> int | str:
    """Сохранить строковый int64 из вывода ``yc``, если поле уже было строкой."""

    if isinstance(previous, str):
        return str(value)
    return value


def prepare_specification(
    document: dict,
    *,
    zone: str,
    platform: str,
    cores: int,
    memory_gb: int,
    size: int,
) -> dict:
    """Вернуть спецификацию для ``update --file``. Исходный словарь не меняется."""

    if not isinstance(document, dict):
        raise UsageError("Описание инстанс-группы не является объектом YAML")
    prepared = copy.deepcopy({key: value for key, value in document.items() if key in UPDATE_FIELDS})

    template = prepared.get("instance_template")
    if not isinstance(template, dict):
        raise UsageError("В описании нет instance_template")
    template["platform_id"] = platform
    resources = template.get("resources_spec")
    if not isinstance(resources, dict):
        resources = {}
        template["resources_spec"] = resources
    resources["cores"] = _int64(resources.get("cores"), cores)
    resources["memory"] = _int64(resources.get("memory"), memory_gb * GIB)

    scale = prepared.get("scale_policy")
    if not isinstance(scale, dict):
        scale = {}
        prepared["scale_policy"] = scale
    # fixed_scale и auto_scale — взаимоисключающие ветви ScalePolicy.
    scale.pop("auto_scale", None)
    fixed = scale.get("fixed_scale")
    if not isinstance(fixed, dict):
        fixed = {}
        scale["fixed_scale"] = fixed
    fixed["size"] = _int64(fixed.get("size"), size)

    allocation = prepared.get("allocation_policy")
    if not isinstance(allocation, dict):
        allocation = {}
        prepared["allocation_policy"] = allocation
    zones = allocation.get("zones")
    selected: dict | None = None
    if isinstance(zones, list):
        for item in zones:
            if isinstance(item, dict) and item.get("zone_id") == zone:
                selected = item
                break
    if selected is None:
        selected = {"zone_id": zone}
    else:
        selected["zone_id"] = zone
    allocation["zones"] = [selected]
    return prepared


def load_specification(text: str) -> dict:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UsageError(f"Ответ yc не разбирается как YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise UsageError("Ответ yc не является объектом YAML")
    return document


def dump_specification(document: dict) -> str:
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1_000_000,
    )


def subprocess_yc(argv: Sequence[str], timeout: float) -> YcCall:
    assert_safe_argv(list(argv))
    try:
        completed = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return YcCall(124, "", f"таймаут {timeout} с")
    return YcCall(completed.returncode, completed.stdout, completed.stderr)


def _validate_args(
    *,
    group_id: str,
    zone: str,
    platform: str,
    cores: int,
    memory_gb: int,
    size: int,
    spec: Path,
    profile: str | None,
    impersonate_service_account_id: str | None,
) -> None:
    if not ID_RE.fullmatch(group_id):
        raise UsageError("Некорректный идентификатор инстанс-группы")
    if not ZONE_RE.fullmatch(zone):
        raise UsageError("Некорректная зона доступности")
    if not PLATFORM_RE.fullmatch(platform):
        raise UsageError("Некорректный platform_id")
    if cores < 1:
        raise UsageError("Количество ядер должно быть больше нуля")
    if memory_gb < 1 or memory_gb * GIB > MAX_MEMORY_BYTES:
        raise UsageError("Объём памяти вне диапазона ResourcesSpec")
    if size < 1 or size > MAX_FIXED_SIZE:
        raise UsageError("Целевое количество экземпляров должно быть от 1 до 100")
    if str(spec).startswith("-"):
        raise UsageError("Путь спецификации не должен начинаться с дефиса")
    if profile is not None and not PROFILE_RE.fullmatch(profile):
        raise UsageError("Имя профиля содержит недопустимые символы")
    if impersonate_service_account_id is not None and not ID_RE.fullmatch(impersonate_service_account_id):
        raise UsageError("Некорректный идентификатор сервисного аккаунта для имперсонации")


def adjust_instance_group(
    *,
    group_id: str,
    zone: str,
    platform: str,
    cores: int,
    memory_gb: int,
    size: int,
    spec: Path,
    yc: str = "yc",
    profile: str | None = None,
    impersonate_service_account_id: str | None = None,
    timeout: float = 3600,
    dry_run: bool = False,
    run: YcRunner = subprocess_yc,
) -> int:
    _validate_args(
        group_id=group_id,
        zone=zone,
        platform=platform,
        cores=cores,
        memory_gb=memory_gb,
        size=size,
        spec=spec,
        profile=profile,
        impersonate_service_account_id=impersonate_service_account_id,
    )
    getter = get_argv(
        yc,
        group_id,
        profile=profile,
        impersonate_service_account_id=impersonate_service_account_id,
    )
    updater = update_argv(
        yc,
        group_id,
        spec,
        profile=profile,
        impersonate_service_account_id=impersonate_service_account_id,
    )
    print(shlex.join(getter))
    print(shlex.join(updater))
    if dry_run:
        return 0

    fetched = run(getter, timeout)
    if fetched.stderr:
        print(fetched.stderr, file=sys.stderr, end="" if fetched.stderr.endswith("\n") else "\n")
    if fetched.returncode != 0:
        return fetched.returncode
    document = load_specification(fetched.stdout)
    prepared = prepare_specification(
        document,
        zone=zone,
        platform=platform,
        cores=cores,
        memory_gb=memory_gb,
        size=size,
    )
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(dump_specification(prepared), encoding="utf-8")

    updated = run(updater, timeout)
    if updated.stdout:
        print(updated.stdout, end="" if updated.stdout.endswith("\n") else "\n")
    if updated.stderr:
        print(updated.stderr, file=sys.stderr, end="" if updated.stderr.endswith("\n") else "\n")
    return updated.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adjust-instance-group",
        description=(
            "Скачать описание инстанс-группы, выставить платформу, ядра, память, "
            "фиксированный размер и одну зону, убрать readonly-поля и применить спецификацию."
        ),
    )
    parser.add_argument("--instance-group-id", required=True, help="Идентификатор инстанс-группы")
    parser.add_argument("--zone", required=True, help="Целевая зона доступности, например ru-central1-d")
    parser.add_argument("--platform", required=True, help="instance_template.platform_id")
    parser.add_argument("--cores", required=True, type=int, help="Число ядер")
    parser.add_argument(
        "--memory-gb",
        required=True,
        type=int,
        help="Объём памяти в гигабайтах по 1024³ байт",
    )
    parser.add_argument("--size", required=True, type=int, help="Целевое число экземпляров, scale_policy.fixed_scale.size")
    parser.add_argument("--spec", required=True, type=Path, help="Куда записать YAML для update --file")
    parser.add_argument("--yc", default="yc", help="Путь к бинарнику yc")
    parser.add_argument("--profile", help="Профиль yc. Без флага используется активный профиль")
    parser.add_argument(
        "--impersonate-service-account-id",
        help="Идентификатор сервисного аккаунта для имперсонации",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600,
        help="Таймаут одной команды yc, в секундах. По умолчанию 3600",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать команды get и update и не вызывать yc",
    )
    return parser


def main(argv: list[str] | None = None, *, run: YcRunner = subprocess_yc) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    yc = args.yc
    if yc == "yc":
        found = shutil.which("yc")
        if found is None and not args.dry_run:
            print("Не найден yc. Установите Yandex Cloud CLI.", file=sys.stderr)
            return 2
        yc = found or "yc"
    try:
        return adjust_instance_group(
            group_id=args.instance_group_id,
            zone=args.zone,
            platform=args.platform,
            cores=args.cores,
            memory_gb=args.memory_gb,
            size=args.size,
            spec=args.spec,
            yc=yc,
            profile=args.profile,
            impersonate_service_account_id=args.impersonate_service_account_id,
            timeout=args.timeout,
            dry_run=args.dry_run,
            run=run,
        )
    except (UsageError, PlanError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
