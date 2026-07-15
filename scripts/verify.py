from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, arguments: list[str]) -> dict[str, object]:
    started = time.perf_counter()
    completed = subprocess.run(
        arguments,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    duration = round(time.perf_counter() - started, 3)
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    result = {
        "name": name,
        "command": arguments,
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "output": output[-12000:],
    }
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"{status} {name} ({duration:.3f}s)")
    if completed.returncode and output:
        print(output[-4000:])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Scrum Portal quality gate.")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip dependency audit and coverage while iterating locally.",
    )
    args = parser.parse_args()

    python = sys.executable
    commands = [
        ("compile", [python, "-m", "compileall", "-q", "app", "scripts", "tests", "wsgi.py"]),
        ("lint", [python, "-m", "ruff", "check", "."]),
        ("format", [python, "-m", "ruff", "format", "--check", "."]),
        (
            "types",
            [
                python,
                "-m",
                "mypy",
                "app/core",
                "app/features/automation/sprint_viewer/metrics.py",
            ],
        ),
        ("security", [python, "-m", "bandit", "-q", "-r", "app", "-c", "pyproject.toml"]),
    ]
    if args.fast:
        commands.append(("tests", [python, "-m", "pytest", "-q"]))
    else:
        commands.extend(
            [
                (
                    "dependency_audit",
                    [python, "-m", "pip_audit", "-r", "requirements.txt"],
                ),
                (
                    "tests_with_coverage",
                    [
                        python,
                        "-m",
                        "pytest",
                        "-q",
                        "--cov=app",
                        "--cov-report=term-missing",
                        "--cov-fail-under=55",
                    ],
                ),
            ]
        )
    commands.append(("smoke", [python, "scripts/smoke_check.py"]))

    results = [_run(name, command) for name, command in commands]
    passed = all(item["exit_code"] == 0 for item in results)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "passed": passed,
        "fast": args.fast,
        "checks": results,
    }
    report_dir = REPOSITORY_ROOT / "artifacts" / "verification"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "latest.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"REPORT {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
