"""Reject repository paths that are unsafe for legacy Windows ZIP extraction."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
import subprocess
import sys


MAX_REPOSITORY_PATH = 60
MAX_COMPONENT_LENGTH = 60
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
INVALID_COMPONENT = re.compile(r'[<>:"\\|?*]')


def tracked_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def path_problems(path: str) -> list[str]:
    problems: list[str] = []
    if len(path) > MAX_REPOSITORY_PATH:
        problems.append(
            f"repository-relative length {len(path)} exceeds {MAX_REPOSITORY_PATH}"
        )
    for component in PurePosixPath(path).parts:
        if len(component) > MAX_COMPONENT_LENGTH:
            problems.append(
                f"component length {len(component)} exceeds {MAX_COMPONENT_LENGTH}: {component}"
            )
        if component.endswith((" ", ".")):
            problems.append(f"component ends with a space or period: {component}")
        if INVALID_COMPONENT.search(component):
            problems.append(f"component contains a Windows-invalid character: {component}")
        stem = component.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            problems.append(f"component uses a Windows-reserved name: {component}")
    return problems


def main() -> int:
    paths = tracked_paths()
    failures = [
        (path, problem)
        for path in paths
        for problem in path_problems(path)
    ]
    if failures:
        for path, problem in failures:
            print(f"WINDOWS_PATH_ERROR {path}: {problem}", file=sys.stderr)
        return 1
    longest = max(paths, key=len, default="")
    print(
        f"WINDOWS_PATHS_OK files={len(paths)} "
        f"max_relative_length={len(longest)} path={longest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
