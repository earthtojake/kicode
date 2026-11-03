"""Fetch KiCad's license notices at one commit, for the wheel's dist-info/licenses. Standard library only.

    python scripts/kicad_licenses.py <commit> <out dir>

Writes every LICENSE* file at the top of KiCad's tree, and AUTHORS.txt, as they are at <commit>.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://gitlab.com/api/v4/projects/kicad%2Fcode%2Fkicad/repository"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "kicad-cli-bin"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main(commit: str, out: Path) -> int:
    tree = json.loads(fetch(f"{API}/tree?ref={commit}&per_page=100"))
    names = sorted(entry["name"] for entry in tree
                   if entry["type"] == "blob" and (entry["name"].startswith("LICENSE") or entry["name"] == "AUTHORS.txt"))
    if "LICENSE" not in names:
        raise SystemExit(f"no LICENSE at the top of KiCad's tree at {commit}")
    out.mkdir(parents=True, exist_ok=True)
    for name in names:
        (out / name).write_bytes(fetch(f"{API}/files/{urllib.parse.quote(name, safe='')}/raw?ref={commit}"))
    print(f"wrote {len(names)} notices to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], Path(sys.argv[2])))
