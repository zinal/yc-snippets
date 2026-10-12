"""Запуск заданий инвентаризации и запись конвертов с результатами."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from yc_snippets.catalog import Catalog
from yc_snippets.plan import (
    Discovery,
    Job,
    PlanError,
    Selection,
    Skip,
    build_argv,
    plan_jobs,
    select_commands,
)
from yc_snippets.redact import redact

YcRunner = Callable[[list[str], float], "YcResult"]


@dataclass(frozen=True)
class YcResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class RunReport:
    jobs: list[Job] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)
    ok: int = 0
    failed: int = 0
    resources_by_type: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)


def subprocess_yc(argv: list[str], timeout: float) -> YcResult:
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    return YcResult(completed.returncode, completed.stdout, completed.stderr)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_resources(stdout: str) -> tuple[list, dict | None]:
    if not stdout.strip():
        return [], None
    payload = json.loads(stdout)
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        lists = [value for value in payload.values() if isinstance(value, list)]
        if len(lists) == 1:
            return lists[0], payload
        return [], payload
    return [], None


def _output_path(out_dir: Path, job: Job) -> Path:
    if job.scope == "account" or not job.scope_id:
        return out_dir / "account" / f"{job.command_id}.json"
    if job.scope == "cloud":
        return out_dir / "clouds" / job.scope_id / f"{job.command_id}.json"
    if job.scope == "organization":
        return out_dir / "organizations" / job.scope_id / f"{job.command_id}.json"
    return out_dir / "folders" / job.scope_id / f"{job.command_id}.json"


def _load_json_array(result: YcResult, label: str) -> list[dict]:
    if result.returncode != 0:
        detail = redact(result.stderr).strip() or f"код {result.returncode}"
        raise PlanError(f"Не удалось получить {label}: {detail}")
    try:
        resources, _document = _parse_resources(result.stdout)
    except json.JSONDecodeError as exc:
        raise PlanError(f"Ответ {label} не является JSON") from exc
    if not isinstance(resources, list):
        raise PlanError(f"Ответ {label} не является списком")
    return [item for item in resources if isinstance(item, dict)]


def discover(
    catalog: Catalog,
    run_yc: YcRunner,
    *,
    cloud_id: str | None,
    profile: str | None,
    limit: int | None,
    impersonate_service_account_id: str | None,
    timeout: float,
    need_clouds: bool,
    need_folders: bool,
    need_organizations: bool,
) -> tuple[Discovery, list[str]]:
    clouds: list[dict] = []
    folders: list[dict] = []
    organizations: list[dict] = []
    problems: list[str] = []
    if need_clouds or need_folders:
        cloud_command = catalog.get("resource-manager.cloud")
        argv = build_argv(
            cloud_command,
            profile=profile,
            limit=limit,
            impersonate_service_account_id=impersonate_service_account_id,
        )
        clouds = _load_json_array(run_yc(argv, timeout), "список облаков")
        if cloud_id:
            clouds = [item for item in clouds if item.get("id") == cloud_id]
    if need_folders:
        folder_command = catalog.get("resource-manager.folder")
        for cloud in clouds:
            current_cloud_id = cloud.get("id")
            if not isinstance(current_cloud_id, str):
                continue
            argv = build_argv(
                folder_command,
                scope_id=current_cloud_id,
                profile=profile,
                limit=limit,
                impersonate_service_account_id=impersonate_service_account_id,
            )
            try:
                listed = _load_json_array(run_yc(argv, timeout), f"список каталогов облака {current_cloud_id}")
            except PlanError as exc:
                problems.append(str(exc))
                continue
            for folder in listed:
                folder.setdefault("cloud_id", current_cloud_id)
            folders.extend(listed)
    if need_organizations:
        org_command = catalog.get("organization-manager.organization")
        argv = build_argv(
            org_command,
            profile=profile,
            limit=limit,
            impersonate_service_account_id=impersonate_service_account_id,
        )
        try:
            organizations = _load_json_array(run_yc(argv, timeout), "список организаций")
        except PlanError as exc:
            problems.append(str(exc))
    return Discovery(clouds=tuple(clouds), folders=tuple(folders), organizations=tuple(organizations)), problems


def execute_jobs(
    jobs: list[Job],
    skips: list[Skip],
    *,
    out_dir: Path | None,
    run_yc: YcRunner,
    timeout: float,
    dry_run: bool,
) -> RunReport:
    report = RunReport(jobs=list(jobs), skips=list(skips))
    for job in jobs:
        if dry_run or job.placeholder:
            continue
        result = run_yc(list(job.argv), timeout)
        envelope: dict = {
            "id": job.command_id,
            "scope": job.scope,
            "scope_id": job.scope_id,
            "collected_at": _now(),
            "command": list(job.argv),
            "ok": result.returncode == 0,
        }
        if result.returncode == 0:
            try:
                resources, document = _parse_resources(result.stdout)
            except json.JSONDecodeError:
                envelope["ok"] = False
                envelope["error"] = "ответ не является JSON"
                envelope["stderr"] = redact(result.stdout)[:4000]
                report.failed += 1
                report.errors.append({"id": job.command_id, "scope_id": job.scope_id, "error": envelope["error"]})
            else:
                envelope["resources"] = resources
                if document is not None:
                    envelope["document"] = document
                report.ok += 1
                report.resources_by_type[job.command_id] = report.resources_by_type.get(job.command_id, 0) + len(resources)
        else:
            envelope["exit_code"] = result.returncode
            envelope["stderr"] = redact(result.stderr)[:4000]
            report.failed += 1
            report.errors.append(
                {
                    "id": job.command_id,
                    "scope_id": job.scope_id,
                    "exit_code": result.returncode,
                    "stderr": envelope["stderr"],
                }
            )
        if out_dir is not None:
            path = _output_path(out_dir, job)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if out_dir is not None and not dry_run:
        summary = {
            "collected_at": _now(),
            "ok": report.ok,
            "failed": report.failed,
            "skipped": [{"id": skip.command_id, "reason": skip.reason} for skip in report.skips],
            "resources_by_type": report.resources_by_type,
            "errors": report.errors,
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def needs_discovery(commands: list, *, folder_id: str | None, cloud_id: str | None, organization_id: str | None) -> tuple[bool, bool, bool]:
    need_clouds = any(command.scope == "cloud" and not cloud_id for command in commands)
    need_folders = any(command.scope == "folder" and not folder_id for command in commands)
    need_organizations = any(command.scope == "organization" and not organization_id for command in commands)
    return need_clouds or need_folders, need_folders, need_organizations
