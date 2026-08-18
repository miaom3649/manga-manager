#!/usr/bin/env python3
"""Print every UTF-8 project line containing a CJK unified ideograph."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKIPPED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".tools",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
SKIPPED_FILES = {PROJECT_ROOT / "src/hmanga/locales/zh-CN.json"}
DOCUMENT_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def should_skip(path: Path) -> bool:
    return (
        path in SKIPPED_FILES
        or path.suffix.casefold() in DOCUMENT_SUFFIXES
        or any(part in SKIPPED_DIRECTORIES for part in path.parts)
    )


def main() -> int:
    matches = 0
    matched_files: set[Path] = set()

    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file() or should_skip(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            # Images, archives and other binary/non-UTF-8 files are not source text.
            continue
        relative = path.relative_to(PROJECT_ROOT)
        for line_number, line in enumerate(lines, start=1):
            if CHINESE.search(line):
                print(f"{relative}:{line_number}: {line.strip()}")
                matches += 1
                matched_files.add(relative)

    print(f"\nFound {matches} matching lines in {len(matched_files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
