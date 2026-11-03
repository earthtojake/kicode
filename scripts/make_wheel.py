"""Write kicode's wheels. Standard library only.

    python scripts/make_wheel.py --staged <dir> --version 10.99.0.dev20261031 --platform macosx_14_0_arm64 \
        --kicad-version 10.99.0 --commit 113c71d59d... --kicad-licenses <dir> --out dist/
    python scripts/make_wheel.py --meta --version 10.99.0.dev20261031 [--kicad-version 10.99.0 --commit 113c...] \
        --out dist/

kicode is three distributions of one version: kicode-pcb (a wheel per platform: kicad-cli, its board
support, every library it links, and KiPy, as the `kicode` import package), kicode-sch (a wheel per
platform: KiCad's schematic support, installed into kicode-pcb's folder, where kicad-cli loads it from;
it requires kicode-pcb of the same version) and kicode (one py3-none-any wheel of metadata alone, which
requires both: what everyone installs). --meta writes kicode's; the first form a platform's other two.

<staged>/kicode/ is the package as the stagers left it: _kicad/, the KiCad a stager made (stage_macos.sh,
stage_windows.py, build_linux.sh), and KiPy's modules with kicode's __init__.py (scripts/vendor_kipy.py,
which writes <staged>/kipy.json beside it: KiPy's version, commit and requirements, which become
kicode-pcb's). <staged>/schematic/files.txt (the stager's) names the files under kicode/ that only KiCad's
schematic kifaces need: those make kicode-sch, every other file kicode-pcb, with kicode's own modules from
src/kicode and _build.py written for this build.

Each wheel's dist-info/licenses/ gets this repository's LICENSE; both platform wheels also <kicad-licenses>
(KiCad's notices from the same commit) under kicad/; kicode-pcb's also <staged>/licenses/ as it is (KiPy's
licence under kipy/, and on Linux the notices of every library it bundles under linux/), kicode-sch's
<staged>/schematic/licenses/ (on Linux, the notices of the libraries only it bundles). README.md is every
wheel's description, with a line saying which distribution's page it is after the README's first line
(which must say kicode is unofficial).

A wheel of 100 MB or more (1e8 bytes, as PyPI counts the file it limits) is not written: the build fails
instead, so none can reach an upload. A wheel holds no symlinks: a stager copies each file under the
name it is loaded by. Executable bits are kept, so the installed kicad-cli runs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "kicode"  # the import package, which kicode-pcb installs
META, PCB, SCH = "kicode", "kicode-pcb", "kicode-sch"
REPOSITORY = "https://github.com/earthtojake/kicode"
LIMIT = 100_000_000
SUMMARIES = {
    META: "Unofficial headless build of KiCad's command line and IPC API client. Not affiliated with or "
          "endorsed by the KiCad project.",
    PCB: "kicode's board side: KiCad's command line with its PCB support, and KiPy, its IPC API client, as the "
         "kicode package. Unofficial: not made, endorsed or supported by the KiCad project.",
    SCH: "kicode's schematic side: KiCad's schematic support for kicad-cli's sch and sym commands. Unofficial: "
         "not made, endorsed or supported by the KiCad project.",
}
UNOFFICIAL = "Unofficial: not made, endorsed or supported by the KiCad project."
CLASSIFIERS = ["Operating System :: MacOS", "Operating System :: Microsoft :: Windows",
               "Operating System :: POSIX :: Linux",
               "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)"]
VERSION = re.compile(r"[0-9]+(\.[0-9]+)*((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?")


def _description(lead: str) -> str:
    """README.md, with `lead` (which distribution's page this is) after its first line, which says kicode is
    unofficial: every distribution's PyPI page is the README."""
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip() and not line.startswith("#")), None)
    if first is None or lines[first].strip() != UNOFFICIAL:
        raise SystemExit(f"README.md's first line under its title must be: {UNOFFICIAL}")
    return "\n".join([*lines[:first + 1], "", f"> {lead}", *lines[first + 1:]]) + "\n"


class Wheel:
    """One wheel being written: its files, each under the RECORD the installer uninstalls by."""

    def __init__(self, out: Path, name: str, version: str, tag: str, purelib: bool = False) -> None:
        self.name = name
        self.info = f"{name.replace('-', '_')}-{version}.dist-info"
        self.path = out / f"{name.replace('-', '_')}-{version}-{tag}.whl"
        self.part = self.path.with_name(self.path.name + ".part")
        self.tag, self.purelib = tag, purelib
        self.records: list[str] = []
        self.licenses: list[str] = []
        out.mkdir(parents=True, exist_ok=True)
        self.zip = zipfile.ZipFile(self.part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9)
        self.add_licenses_file("LICENSE", ROOT / "LICENSE")

    def add(self, arc: str, data: bytes, mode: int = 0o644) -> None:
        item = zipfile.ZipInfo(arc, date_time=(2020, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = (stat.S_IFREG | mode) << 16
        self.zip.writestr(item, data)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        self.records.append(f"{arc},sha256={digest},{len(data)}")

    def add_file(self, arc: str, path: Path) -> None:
        if path.is_symlink():
            raise SystemExit(f"{path} is a symlink: a wheel holds none; stage the file it points at")
        self.add(arc, path.read_bytes(), 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644)

    def add_licenses_file(self, name: str, path: Path) -> None:
        if name in self.licenses:
            raise SystemExit(f"two licence files named {name} in {self.path.name}")
        self.licenses.append(name)
        self.add(f"{self.info}/licenses/{name}", path.read_bytes())

    def add_licenses(self, folder: Path | None, prefix: str = "") -> None:
        for path in sorted(folder.rglob("*")) if folder is not None and folder.is_dir() else []:
            if path.is_file():
                self.add_licenses_file(f"{prefix}{path.relative_to(folder).as_posix()}", path)

    def finish(self, version: str, requires: list[str], requires_python: str, urls: list[str], lead: str) -> Path:
        metadata = "\n".join([
            "Metadata-Version: 2.4",
            f"Name: {self.name}",
            f"Version: {version}",
            f"Summary: {SUMMARIES[self.name]}",
            "License-Expression: GPL-3.0-or-later",
            *(f"License-File: {name}" for name in self.licenses),
            f"Requires-Python: {requires_python}",
            *(f"Requires-Dist: {requirement}" for requirement in requires),
            *(f"Classifier: {classifier}" for classifier in CLASSIFIERS),
            f"Project-URL: Source, {REPOSITORY}",
            *(f"Project-URL: {url}" for url in urls),
            "Description-Content-Type: text/markdown",
            "",
            _description(lead),
        ])
        self.add(f"{self.info}/METADATA", metadata.encode())
        self.add(f"{self.info}/WHEEL", (f"Wheel-Version: 1.0\nGenerator: kicode make_wheel\n"
                                        f"Root-Is-Purelib: {'true' if self.purelib else 'false'}\nTag: {self.tag}\n").encode())
        item = zipfile.ZipInfo(f"{self.info}/RECORD", date_time=(2020, 1, 1, 0, 0, 0))
        item.external_attr = (stat.S_IFREG | 0o644) << 16
        self.zip.writestr(item, "\n".join([*self.records, f"{self.info}/RECORD,,"]) + "\n")
        self.zip.close()
        size = self.part.stat().st_size
        if size >= LIMIT:
            with zipfile.ZipFile(self.part) as written:
                largest = sorted(written.infolist(), key=lambda item: -item.compress_size)[:30]
            self.part.unlink()
            raise SystemExit(f"{self.path.name} would be {size:,} bytes ({size / 1e6:.1f} MB): PyPI takes no file "
                             f"of {LIMIT / 1e6:.0f} MB or more, so it is not written. Its largest entries, "
                             "compressed (uncompressed), in MB:\n"
                             + "\n".join(f"  {item.compress_size / 1e6:6.2f} ({item.file_size / 1e6:6.2f}) {item.filename}"
                                         for item in largest))
        self.part.replace(self.path)
        print(f"wrote {self.path} ({size / 1e6:.1f} MB, {size:,} bytes; limit {LIMIT / 1e6:.0f} MB)")
        return self.path


def meta(version: str, kicad_version: str | None, commit: str | None, out: Path) -> Path:
    """kicode's own wheel: no files, kicode-pcb and kicode-sch of the same version."""
    wheel = Wheel(out, META, version, "py3-none-any", purelib=True)
    of = f", KiCad {kicad_version} at commit `{commit[:10]}`" if kicad_version and commit else ""
    return wheel.finish(version, [f"{PCB}=={version}", f"{SCH}=={version}"], ">=3.9", [],
                        f"This is **kicode** {version}, which installs {PCB} and {SCH} {version}{of}.")


def platform(staged: Path, version: str, tag: str, kicad_version: str, commit: str, kicad_licenses: Path | None,
             out: Path) -> list[Path]:
    """A platform's kicode-pcb and kicode-sch wheels."""
    package = staged / PACKAGE
    if not (package / "_kicad").is_dir():
        raise SystemExit(f"no staged KiCad at {package / '_kicad'}")
    if not (package / "__init__.py").is_file() or not (staged / "kipy.json").is_file():
        raise SystemExit(f"no KiPy in {package}: run scripts/vendor_kipy.py on it first")
    listing = staged / "schematic" / "files.txt"
    if not listing.is_file():
        raise SystemExit(f"no {listing}: the stager names the files only the schematic kifaces need there")
    schematic = sorted({line.strip() for line in listing.read_text(encoding="utf-8").splitlines() if line.strip()})
    missing = [name for name in schematic if not (package / name).is_file()]
    if missing or not any(name.endswith(("/_eeschema.kiface", "/_eeschema.dll")) for name in schematic):
        raise SystemExit(f"{listing} must name the staged eeschema kiface and only staged files; not staged: {missing}")
    kipy = json.loads((staged / "kipy.json").read_text(encoding="utf-8"))
    ours = sorted((ROOT / "src" / PACKAGE).glob("*.py"))
    own = {f"{PACKAGE}/{source.name}" for source in ours}
    requires_python = kipy["requires_python"] or ">=3.9"
    kicad_url = f"KiCad source, https://gitlab.com/kicad/code/kicad/-/tree/{commit}"
    tag = f"py3-none-{tag}"

    pcb = Wheel(out, PCB, version, tag)
    for source in ours:
        if source.name != "_build.py":
            pcb.add_file(f"{PACKAGE}/{source.name}", source)
    pcb.add(f"{PACKAGE}/_build.py", (f"# Written by scripts/make_wheel.py: the KiCad and the KiPy this wheel carries.\n"
                                     f"KICAD_VERSION = {kicad_version!r}\nKICAD_COMMIT = {commit!r}\n"
                                     f"KIPY_VERSION = {kipy['version']!r}\nKIPY_COMMIT = {kipy['commit']!r}\n").encode())
    for path in sorted(package.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(package).as_posix()
        if f"{PACKAGE}/{relative}" in own:
            raise SystemExit(f"{path} is staged where kicode's own {PACKAGE}/{relative} goes")
        if relative not in schematic:
            pcb.add_file(f"{PACKAGE}/{relative}", path)
    pcb.add_licenses(kicad_licenses, "kicad/")
    pcb.add_licenses(staged / "licenses")
    if not any(name.startswith("kipy/") for name in pcb.licenses):
        raise SystemExit(f"no KiPy licence in {staged / 'licenses' / 'kipy'}")
    kicad = f"KiCad {kicad_version} at commit `{commit[:10]}`"
    wheels = [pcb.finish(version, kipy["requires_dist"], requires_python,
                         [kicad_url, f"KiPy source, https://gitlab.com/kicad/code/kicad-python/-/tree/{kipy['commit']}"],
                         f"This is **{PCB}** {version}, kicode's board side and its `kicode` package: {kicad}, with "
                         f"KiPy ({kipy['name']}) {kipy['version']} at commit `{kipy['commit'][:10]}`.")]

    sch = Wheel(out, SCH, version, tag)
    for relative in schematic:
        sch.add_file(f"{PACKAGE}/{relative}", package / relative)
    sch.add_licenses(kicad_licenses, "kicad/")
    sch.add_licenses(staged / "schematic" / "licenses")
    wheels.append(sch.finish(version, [f"{PCB}=={version}"], requires_python, [kicad_url],
                             f"This is **{SCH}** {version}, kicode's schematic side: the {len(schematic)} files of "
                             f"{kicad} that only its schematic kifaces need, installed into {PCB}'s folder."))
    return wheels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--meta", action="store_true", help="write kicode's own wheel (py3-none-any)")
    parser.add_argument("--staged", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", help="the platform wheels' tag, e.g. macosx_14_0_arm64")
    parser.add_argument("--kicad-version")
    parser.add_argument("--commit")
    parser.add_argument("--kicad-licenses", type=Path, help="KiCad's notices at the commit (scripts/kicad_licenses.py)")
    parser.add_argument("--out", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    if not VERSION.fullmatch(args.version):
        parser.error(f"not a plain version: {args.version}")
    if args.meta:
        meta(args.version, args.kicad_version, args.commit, args.out)
        return 0
    if not (args.staged and args.platform and args.kicad_version and args.commit):
        parser.error("a platform's wheels need --staged, --platform, --kicad-version and --commit")
    platform(args.staged, args.version, args.platform, args.kicad_version, args.commit, args.kicad_licenses, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
