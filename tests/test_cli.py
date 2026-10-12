import subprocess
import sys
from pathlib import Path

from yc_snippets.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_prints_folder_command(capsys, monkeypatch):
    monkeypatch.delenv("YC_PROFILE", raising=False)
    code = main(["inventory", "--dry-run", "--folder-id", "b1gfolder", "--only", "compute.instance", "--limit", "5"])
    captured = capsys.readouterr()
    assert code == 0
    assert "yc compute instance list --format json --folder-id b1gfolder --limit 5" in captured.out
    assert "--token" not in captured.out


def test_launcher_dry_run_from_checkout():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "yc-snippets"),
            "inventory",
            "--dry-run",
            "--folder-id",
            "b1gfolder",
            "--only",
            "compute.instance",
            "--limit",
            "5",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.returncode == 0
    assert "yc compute instance list --format json --folder-id b1gfolder --limit 5" in completed.stdout
    assert "--token" not in completed.stdout


def test_inventory_without_out_does_not_call_yc(capsys):
    code = main(["inventory", "--folder-id", "b1gfolder", "--only", "compute.instance"])
    captured = capsys.readouterr()
    assert code == 2
    assert "--out" in captured.err
