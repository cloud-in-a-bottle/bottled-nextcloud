"""Unit checks for hooks/before-starting/00-openhost-finish-upgrade.sh, run against a fake ``php``: no container."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "before-starting" / "00-openhost-finish-upgrade.sh"

FAKE_PHP = """#!/bin/bash
# Called as: php /var/www/html/occ <args...>
shift
echo "$*" >> "$FAKE_OCC_LOG"
case "$*" in
    *status*) [[ "$FAKE_STATUS_RC" == 0 ]] && printf '%s' "$FAKE_STATUS"; exit "$FAKE_STATUS_RC" ;;
    upgrade) exit "$FAKE_UPGRADE_RC" ;;
    "maintenance:mode --off") exit 0 ;;
esac
"""

# Hooks run as root in some setups, where they go through runuser; pass straight through to the fake php.
FAKE_RUNUSER = """#!/bin/bash
while [[ "$1" != "--" ]]; do shift; done
shift
exec "$@"
"""


def _run_hook(tmp_path: Path, status: str, status_rc: int = 0, upgrade_rc: int = 0) -> tuple[int, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("php", FAKE_PHP), ("runuser", FAKE_RUNUSER)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "occ.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_OCC_LOG": str(log),
        "FAKE_STATUS": status,
        "FAKE_STATUS_RC": str(status_rc),
        "FAKE_UPGRADE_RC": str(upgrade_rc),
    }
    result = subprocess.run(["bash", str(HOOK)], env=env, capture_output=True, text=True, timeout=30)
    return result.returncode, log.read_text().splitlines()


def _upgrades(calls: list[str]) -> int:
    return sum(1 for call in calls if call == "upgrade")


def test_up_to_date_instance_is_left_alone(tmp_path: Path) -> None:
    rc, calls = _run_hook(tmp_path, '{"installed":true,"maintenance":false,"needsDbUpgrade":false}')
    assert rc == 0
    assert _upgrades(calls) == 0


@pytest.mark.parametrize("prefix", ["", "Nextcloud or one of the apps require upgrade\n"])
def test_unfinished_upgrade_is_completed(tmp_path: Path, prefix: str) -> None:
    rc, calls = _run_hook(tmp_path, prefix + '{"installed":true,"maintenance":true,"needsDbUpgrade":true}')
    assert rc == 0
    assert _upgrades(calls) == 1
    assert calls[-1] == "maintenance:mode --off"


def test_maintenance_without_pending_upgrade_is_left_on(tmp_path: Path) -> None:
    rc, calls = _run_hook(tmp_path, '{"installed":true,"maintenance":true,"needsDbUpgrade":false}')
    assert rc == 0
    assert _upgrades(calls) == 0
    assert "maintenance:mode --off" not in calls


def test_failed_upgrade_fails_the_boot(tmp_path: Path) -> None:
    rc, calls = _run_hook(tmp_path, '{"installed":true,"needsDbUpgrade":true}', upgrade_rc=1)
    assert rc != 0
    assert _upgrades(calls) == 1
    assert "maintenance:mode --off" not in calls


@pytest.mark.parametrize(("status", "status_rc"), [("", 1), ("not json", 0)])
def test_unreadable_status_does_not_block_the_boot(tmp_path: Path, status: str, status_rc: int) -> None:
    rc, calls = _run_hook(tmp_path, status, status_rc=status_rc)
    assert rc == 0
    assert _upgrades(calls) == 0
