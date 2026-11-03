"""Find one KiCad nightly on every platform: the commit, its macOS DMG and Windows installer, and the
wheel version. Standard library only.

    python scripts/resolve_nightly.py                 # the newest commit with both a macOS and a Windows nightly
    python scripts/resolve_nightly.py --commit 113c71d59d

KiCad's macOS and Windows nightlies name the commit they were built from (`...-20261031-0512-113c71d59d.dmg`,
`kicad-nightly-10.99.0.6189.g113c71d59d-x86_64-lite.exe`), and a commit usually has both; the Linux wheel
is built from that same commit. The version is `<KiCad's version>.dev<the macOS nightly's date>`.
Prints JSON; with GITHUB_OUTPUT set, also writes each field there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

MACOS = "https://downloads.kicad.org/kicad/macos/explore/nightlies"
WINDOWS = "https://downloads.kicad.org/kicad/windows/explore/nightlies"
COMMITS = "https://gitlab.com/api/v4/projects/kicad%2Fcode%2Fkicad/repository/commits/"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "kicad-cli-bin"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def nightlies() -> tuple[dict[str, dict], dict[str, dict]]:
    """KiCad's listed macOS and Windows x86_64 nightlies, each keyed by its 10-character commit."""
    macos = {}
    for match in re.finditer(r'href="([^"]*/kicad-unified-universal-(\d{8})-(\d{4})-([0-9a-f]{10})\.dmg)"', fetch(MACOS)):
        url, date, time, commit = match.groups()
        macos.setdefault(commit, {"url": url, "date": date, "time": time})
    windows = {}
    for match in re.finditer(r'href="([^"]*/kicad-nightly-(\d+\.\d+\.\d+)\.(\d+)\.g([0-9a-f]{10})-x86_64-lite\.exe)"',
                             fetch(WINDOWS)):
        url, version, count, commit = match.groups()
        windows.setdefault(commit, {"url": url, "version": version, "count": int(count)})
    return macos, windows


def resolve(commit: str | None) -> dict:
    macos, windows = nightlies()
    both = sorted(set(macos) & set(windows), key=lambda c: windows[c]["count"], reverse=True)
    if commit:
        chosen = [c for c in both if c.startswith(commit[:10].lower())]
        if not chosen:
            listed = ", ".join(both[:10]) or "none"
            raise SystemExit(f"no macOS and Windows nightly of {commit}; commits with both: {listed}")
    elif not both:
        raise SystemExit("no commit has both a macOS and a Windows nightly listed")
    else:
        chosen = both
    short = chosen[0]
    info = json.loads(fetch(COMMITS + short))
    mac, win = macos[short], windows[short]
    return {
        "commit": info["id"],
        "commit_date": info["committed_date"],
        "kicad_version": win["version"],
        # As KiCad's own builds of the commit say it in full (git describe): the Linux build is stamped with it.
        "kicad_full_version": f"{win['version']}-{win['count']}-g{short}",
        "version": f"{win['version']}.dev{mac['date']}",
        "tag": f"v{win['version']}.dev{mac['date']}",
        "macos_url": mac["url"],
        "windows_url": win["url"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", help="a KiCad commit (10 or more hex characters); default the newest")
    args = parser.parse_args(argv)
    found = resolve(args.commit)
    print(json.dumps(found, indent=2))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            for key, value in found.items():
                out.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
