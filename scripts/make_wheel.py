"""Write a kicad-cli-bin wheel from a staged KiCad. Standard library only.

    python scripts/make_wheel.py --staged <dir> --version 10.99.0.dev20261031 --platform macosx_14_0_arm64 \
        --kicad-version 10.99.0 --commit 113c71d59d... --licenses <dir> --out dist/

<staged>/kicad_cli_bin/kicad/ is the KiCad a stager made (stage_macos.sh, stage_windows.py, build_linux.sh);
the package's Python comes from src/kicad_cli_bin, with _build.py written for this build. <licenses> holds
the notices the wheel ships (KiCad's LICENSE files from the same commit, and on Linux the copyright file of
every bundled library), under <name>.dist-info/licenses/. A wheel holds no symlinks: a stager copies each
file under the name it is loaded by. Executable bits are kept, so the installed kicad-cli runs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "kicad-cli-bin"
DIST = "kicad_cli_bin"
SUMMARY = "kicad-cli, KiCad's command line, headless and installable from a package index"


def _record_line(arc: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{arc},sha256={digest},{len(data)}"


def _metadata(version: str, kicad_version: str, commit: str, licenses: list[str]) -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lines = [
        "Metadata-Version: 2.4",
        f"Name: {NAME}",
        f"Version: {version}",
        f"Summary: {SUMMARY}",
        "Home-page: https://github.com/earthtojake/kicad-cli-bin",
        "License-Expression: GPL-3.0-or-later",
        *(f"License-File: {name}" for name in licenses),
        "Requires-Python: >=3.9",
        "Classifier: Operating System :: MacOS",
        "Classifier: Operating System :: Microsoft :: Windows",
        "Classifier: Operating System :: POSIX :: Linux",
        "Classifier: Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        f"Project-URL: KiCad source, https://gitlab.com/kicad/code/kicad/-/tree/{commit}",
        f"Project-URL: Source, https://github.com/earthtojake/kicad-cli-bin",
        "Description-Content-Type: text/markdown",
        "",
        f"KiCad {kicad_version}, commit {commit}.",
        "",
        readme,
    ]
    return "\n".join(lines)


def build(staged: Path, version: str, platform: str, kicad_version: str, commit: str, licenses: Path | None,
          out: Path) -> Path:
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)*((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?", version):
        raise SystemExit(f"not a plain version: {version}")
    kicad = staged / DIST / "kicad"
    if not kicad.is_dir():
        raise SystemExit(f"no staged KiCad at {kicad}")
    tag = f"py3-none-{platform}"
    info = f"{DIST}-{version}.dist-info"
    out.mkdir(parents=True, exist_ok=True)
    wheel = out / f"{DIST}-{version}-{tag}.whl"
    records: list[str] = []

    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        def add(arc: str, data: bytes, mode: int = 0o644) -> None:
            item = zipfile.ZipInfo(arc, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(item, data)
            records.append(_record_line(arc, data))

        for source in sorted((ROOT / "src" / DIST).glob("*.py")):
            if source.name == "_build.py":
                continue
            add(f"{DIST}/{source.name}", source.read_bytes())
        add(f"{DIST}/_build.py", (f"# Written by scripts/make_wheel.py: the KiCad this wheel carries.\n"
                                  f"KICAD_VERSION = {kicad_version!r}\nKICAD_COMMIT = {commit!r}\n").encode())
        for path in sorted(kicad.rglob("*")):
            if path.is_symlink():
                raise SystemExit(f"{path} is a symlink: a wheel holds none; stage the file it points at")
            if not path.is_file():
                continue
            executable = path.stat().st_mode & stat.S_IXUSR
            add(f"{DIST}/kicad/{path.relative_to(kicad).as_posix()}", path.read_bytes(), 0o755 if executable else 0o644)

        license_names = ["LICENSE"]
        add(f"{info}/licenses/LICENSE", (ROOT / "LICENSE").read_bytes())
        if licenses is not None:
            for path in sorted(licenses.rglob("*")):
                if path.is_file():
                    name = f"kicad/{path.relative_to(licenses).as_posix()}"
                    license_names.append(name)
                    add(f"{info}/licenses/{name}", path.read_bytes())
        add(f"{info}/METADATA", _metadata(version, kicad_version, commit, license_names).encode())
        add(f"{info}/WHEEL", (f"Wheel-Version: 1.0\nGenerator: kicad-cli-bin make_wheel\n"
                              f"Root-Is-Purelib: false\nTag: {tag}\n").encode())
        records.append(f"{info}/RECORD,,")
        item = zipfile.ZipInfo(f"{info}/RECORD", date_time=(2020, 1, 1, 0, 0, 0))
        item.external_attr = (stat.S_IFREG | 0o644) << 16
        zf.writestr(item, "\n".join(records) + "\n")
    print(f"wrote {wheel} ({wheel.stat().st_size / 1e6:.1f} MB)")
    return wheel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True, help="the wheel's platform tag, e.g. macosx_14_0_arm64")
    parser.add_argument("--kicad-version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--licenses", type=Path)
    parser.add_argument("--out", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    build(args.staged, args.version, args.platform, args.kicad_version, args.commit, args.licenses, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
