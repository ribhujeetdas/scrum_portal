from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_readme_first_install_contract_is_complete_and_resolvable():
    readme = (REPOSITORY_ROOT / "readme.md").read_text(encoding="utf-8")
    required_instructions = (
        "Python 3.12",
        "requirements-dev.txt",
        "SECRET_KEY",
        "FERNET_KEY",
        "scripts\\migrate_db.py",
        "scripts/database_configure.py",
        "scripts\\verify.py",
        "scripts/diagnose.py",
        "scripts\\run_server.py",
        "/health/ready",
        "/auth/signup",
        "git archive",
    )
    for instruction in required_instructions:
        assert instruction in readme

    relative_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme)
    missing = [
        target
        for target in relative_links
        if not target.startswith(("http://", "https://", "#"))
        and not (REPOSITORY_ROOT / target).is_file()
    ]
    assert missing == []


@pytest.mark.parametrize("lock_name", ["requirements.txt", "requirements-dev.txt"])
def test_shared_lock_guards_windows_only_dependency(lock_name):
    lock = (REPOSITORY_ROOT / lock_name).read_text(encoding="utf-8")

    assert 'pywin32==312 ; sys_platform == "win32"' in lock
    assert re.search(r"(?m)^pywin32==312 \\\s*$", lock) is None
