#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "manifest.json"
DATES_FILE = REPO_ROOT / ".github" / "data" / "wallpaper-dates.json"
PINNED_FILE = REPO_ROOT / ".github" / "data" / "pinned-order.json"


def load_dates() -> dict[str, str]:
    """filename -> ISO-8601 date, maintained by generate_metadata.py.

    This file is committed fresh into every squash commit (see
    .github/workflows/generate-metadata.yml), so it survives the
    orphan-rewrite that makes real git history useless for figuring out
    when a file was actually added.
    """
    if not DATES_FILE.exists():
        return {}
    try:
        return json.loads(DATES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! could not read {DATES_FILE}: {e}", file=sys.stderr)
        return {}


def load_pinned() -> list[str]:
    """Ordered list of filenames to force to the top of the manifest,
    in the exact order given - manual override, bypasses date sorting
    entirely. Anything listed here that no longer exists on disk is
    silently skipped. Edit this file by hand (or from the shell) to
    reorder wallpapers without touching their real dates.
    """
    if not PINNED_FILE.exists():
        return []
    try:
        data = json.loads(PINNED_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            print(f"  ! {PINNED_FILE} should be a JSON array, ignoring", file=sys.stderr)
            return []
        return data
    except Exception as e:
        print(f"  ! could not read {PINNED_FILE}: {e}", file=sys.stderr)
        return []


def parse_ts(iso_date: str) -> float:
    return datetime.fromisoformat(iso_date).timestamp()


def main() -> int:
    files = sorted(
        p.name
        for p in REPO_ROOT.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )

    if not files:
        print("No image files found at repo root - refusing to write an "
              "empty manifest (this would wipe out the wallpaper list).",
              file=sys.stderr)
        return 1

    dates = load_dates()
    pinned = load_pinned()
    now = datetime.now(timezone.utc).astimezone().isoformat()

    file_set = set(files)
    pinned_entries = []
    seen = set()
    for name in pinned:
        if name in file_set and name not in seen:
            date = dates.get(name) or now
            pinned_entries.append({"filename": name, "date": date})
            seen.add(name)
        elif name not in file_set:
            print(f"  ! pinned filename {name!r} not found on disk, skipping", file=sys.stderr)

    dated, undated = [], []
    for name in files:
        if name in seen:
            continue  # already placed via pinned-order.json
        date = dates.get(name)
        (dated if date else undated).append({"filename": name, "date": date or now})
        if not date:
            print(f"  ! no cached date for {name!r}, treating as added now", file=sys.stderr)

    dated.sort(key=lambda e: parse_ts(e["date"]), reverse=True)  # newest first
    undated.sort(key=lambda e: e["filename"])                     # fallback: A-Z

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wallpapers": pinned_entries + dated + undated,
    }

    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(manifest['wallpapers'])} entries "
          f"({len(pinned_entries)} pinned, {len(dated)} dated, {len(undated)} undated) to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
