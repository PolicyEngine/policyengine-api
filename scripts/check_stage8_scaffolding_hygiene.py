"""Reject staged one-off Supabase scaffolding and secret-shaped artifacts."""

from __future__ import annotations

from pathlib import PurePosixPath
import subprocess


PROHIBITED_PREFIXES = (
    ".agent-artifacts/",
    ".artifacts/",
    "supabase/",
)
PROHIBITED_SUFFIXES = (
    ".dump",
    ".key",
    ".pem",
    ".sql",
    ".sql.gz",
)
PROHIBITED_NAMES = {
    ".env",
    "bootstrap-payload.json",
    "scaffold-payload.json",
}
ONE_OFF_MARKERS = ("one-off", "one_off", "scratch")


def prohibited_staged_paths(paths: list[str]) -> list[str]:
    """Return obvious disposable or secret-shaped paths in stable order."""

    rejected: set[str] = set()
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        normalized = path.as_posix()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        lower = normalized.lower()
        if any(normalized.startswith(prefix) for prefix in PROHIBITED_PREFIXES):
            rejected.add(normalized)
        if lower.endswith(PROHIBITED_SUFFIXES):
            rejected.add(normalized)
        if path.name.lower() in PROHIBITED_NAMES:
            rejected.add(normalized)
        if any(marker in path.name.lower() for marker in ONE_OFF_MARKERS):
            rejected.add(normalized)
    return sorted(rejected)


def staged_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def main() -> None:
    rejected = prohibited_staged_paths(staged_paths())
    if rejected:
        formatted = "\n".join(f"- {path}" for path in rejected)
        raise SystemExit(
            "Stage 8 staged-file hygiene rejected one-off or secret-shaped "
            f"artifacts:\n{formatted}"
        )
    print("Stage 8 staged-file hygiene passed.")


if __name__ == "__main__":
    main()
