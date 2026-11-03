"""Vendor KiPy (kicad-python), KiCad's IPC API client, into kicode: KiPy's modules become kicode's.
Standard library only.

    python scripts/vendor_kipy.py <kicad_python wheel> <staged dir> --commit <KiPy commit>

Unpacks KiPy's built wheel (with the protobuf code its build generates) and writes:

- <staged>/kicode/: every file of KiPy's kipy/ package, with each absolute import of kipy, and every other
  dotted kipy.<name> (docstring cross-references, its importlib.resources lookups, a probe's client name),
  renamed to kicode; and __init__.py, KiPy's own followed by kicode's names (kicode._runtime: executable(),
  environment(), has_schematic(), stock_data_home(); kicode._build: KICAD_VERSION, KICAD_COMMIT,
  KIPY_VERSION, KIPY_COMMIT).
  The generated protobuf modules import each other relatively and need no rename.
- <staged>/licenses/kipy/: KiPy's licence files.
- <staged>/kipy.json: KiPy's version and commit, Requires-Dist and Requires-Python, for make_wheel.py.

Fails when KiPy ships a module named as one of kicode's own (src/kicode's, and _kicad, the KiCad tree a
stager writes), binds one of kicode's names in its __init__, ships compiled code (the wheel is one per
platform; KiPy's part must be pure Python), or still says kipy anywhere once renamed: a new way KiPy names
itself is a build failure to look at, not a module that breaks at run time. KiPy's console script
(kicad-python-packager) is not installed; `python -m kicode.packaging` runs it. Leaves <staged>/kicode/_kicad/
alone and replaces everything else this script wrote before.
"""

from __future__ import annotations

import argparse
import ast
import email.parser
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "kicode"
KIPY = "kipy"
DATA = "_kicad"
# What kicode adds to KiPy's __init__, by the module of ours that defines it.
NAMES = {"_build": ["KICAD_COMMIT", "KICAD_VERSION", "KIPY_COMMIT", "KIPY_VERSION"],
         "_runtime": ["environment", "executable", "has_schematic", "stock_data_home"]}
IMPORT = re.compile(r"^(\s*)(from|import)(\s+)kipy\b", re.M)
# Any other dotted kipy.<name> that is not part of a longer word, path or URL.
DOTTED = re.compile(r"(?<![\w./-])kipy(?=\.[A-Za-z_])")
LEFT = re.compile(r"\bkipy\b")
COMPILED = {".so", ".pyd", ".dylib", ".dll", ".exe"}
SHA = re.compile(r"[0-9a-f]{7,40}")


def fail(message: str) -> None:
    raise SystemExit(f"vendor_kipy: {message}")


def ours() -> set[str]:
    """kicode's own module names, lower-cased (a case-insensitive file system holds one of each)."""
    source = ROOT / "src" / PACKAGE
    if (source / "__init__.py").exists():
        fail(f"src/{PACKAGE}/__init__.py: kicode's __init__ is KiPy's with kicode's names added, written here")
    names = {path.stem.lower() for path in source.glob("*.py")} | {DATA.lower()}
    missing = set(NAMES) - names
    if missing:
        fail(f"src/{PACKAGE} has no {', '.join(sorted(missing))}.py")
    return names


def top_level_name(member: PurePosixPath) -> str:
    """The name a file of kipy/ takes in the package's namespace: its folder, or its module's name."""
    first = member.parts[1]
    if len(member.parts) > 2:
        return first
    for suffix in (".py", ".pyi", *COMPILED):
        if first.endswith(suffix):
            return first[: -len(suffix)].split(".")[0]
    return first


def bound_names(tree: ast.Module) -> tuple[set[str], bool]:
    """The names KiPy's __init__ binds at module level, and whether it sets __all__."""
    names: set[str] = set()
    has_all = False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        names.add(name.id)
                        if name.id == "__all__":
                            has_all = True
                            if isinstance(node.value, (ast.List, ast.Tuple)):
                                names.update(item.value for item in node.value.elts
                                             if isinstance(item, ast.Constant) and isinstance(item.value, str))
    return names, has_all


def rename(text: str) -> tuple[str, int, list[str]]:
    """The text with kipy renamed kicode: how many import lines changed, and every other line that did."""
    text, imports = IMPORT.subn(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{PACKAGE}", text)
    others = [line.strip() for line in text.splitlines() if DOTTED.search(line)]
    return DOTTED.sub(PACKAGE, text), imports, others


def init_source(kipy_init: str, has_all: bool, version: str, commit: str) -> str:
    header = (
        f'"""kicode: KiCad\'s headless command line and KiPy, its IPC API client, in one package.\n\n'
        f"``kicode.executable()`` is the kicad-cli this wheel carries and ``kicode.environment(root)`` what a\n"
        f"headless run of it sets. ``kicode.KiCad`` and every other module of the package are KiPy's\n"
        f"(kicad-python {version}, commit {commit[:10]}), renamed from ``kipy``.\n"
        f'"""\n\n'
        f"# KiPy's __init__ as it ships, its imports renamed by scripts/vendor_kipy.py.\n"
    )
    ours_lines = "\n".join(f"from {PACKAGE}.{module} import {', '.join(names)}  # noqa: E402"
                           for module, names in sorted(NAMES.items()))
    added = ", ".join(f'"{name}"' for names in NAMES.values() for name in sorted(names))
    tail = f"\n\n# kicode's own: the KiCad command line this wheel carries, and what it was built from.\n{ours_lines}\n"
    if has_all:
        tail += f"\n__all__ = (*__all__, {added})\n"
    return header + kipy_init.rstrip() + "\n" + tail


def vendor(wheel: Path, staged: Path, commit: str) -> dict:
    if not SHA.fullmatch(commit):
        fail(f"--commit must be KiPy's commit as hex, not {commit!r}")
    with zipfile.ZipFile(wheel) as zf:
        members = [PurePosixPath(name) for name in zf.namelist() if not name.endswith("/")]
        infos = sorted({member.parts[0] for member in members if member.parts[0].endswith(".dist-info")})
        if len(infos) != 1:
            fail(f"{wheel.name} has {len(infos)} .dist-info folders")
        info = infos[0]
        metadata = email.parser.Parser().parsestr(zf.read(f"{info}/METADATA").decode("utf-8"))
        others = sorted({member.parts[0] for member in members} - {KIPY, info})
        if others:
            fail(f"{wheel.name} ships more than {KIPY}/: {', '.join(others)}")
        package = [member for member in members if member.parts[0] == KIPY]
        compiled = [str(member) for member in package if member.suffix in COMPILED]
        if compiled:
            fail(f"KiPy ships compiled code, which a wheel per platform cannot carry as is: {', '.join(compiled)}")

        mine = ours()
        clashes = sorted(str(member) for member in package if top_level_name(member).lower() in mine)
        if clashes:
            fail(f"KiPy ships a module named as one of kicode's own ({', '.join(sorted(mine))}): {', '.join(clashes)}")
        init_member = f"{KIPY}/__init__.py"
        if PurePosixPath(init_member) not in package:
            fail(f"{wheel.name} has no {init_member}")
        kipy_init = zf.read(init_member).decode("utf-8")
        bound, has_all = bound_names(ast.parse(kipy_init))
        taken = sorted(bound & {name for names in NAMES.values() for name in names})
        if taken:
            fail(f"KiPy's __init__ binds names kicode adds: {', '.join(taken)}")

        dest = staged / PACKAGE
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.iterdir():
            if old.name != DATA:
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        imports = files = 0
        rewritten: list[str] = []
        for member in package:
            relative = PurePosixPath(*member.parts[1:])
            data = zf.read(str(member))
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                text, count, changed = rename(text)
                if count or changed:
                    files += 1
                imports += count
                rewritten.extend(f"{PACKAGE}/{relative}: {line[:110]}" for line in changed)
                left = [f"{PACKAGE}/{relative}:{number}: {line.strip()[:110]}"
                        for number, line in enumerate(text.splitlines(), 1) if LEFT.search(line)]
                if left:
                    fail("KiPy still says kipy once renamed; teach scripts/vendor_kipy.py the new name:\n  "
                         + "\n  ".join(left))
                if str(relative) == "__init__.py":
                    text = init_source(text, has_all, metadata["Version"], commit)
                if relative.suffix == ".py":
                    compile(text, f"{PACKAGE}/{relative}", "exec")
                data = text.encode("utf-8")
            elif LEFT.search(data.decode("latin-1")):
                fail(f"{member} is not UTF-8 text and says kipy")
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        licenses = staged / "licenses" / "kipy"
        shutil.rmtree(licenses, ignore_errors=True)
        licenses.mkdir(parents=True)
        license_names = metadata.get_all("License-File") or []
        for name in license_names:
            for candidate in (f"{info}/licenses/{name}", f"{info}/{name}"):
                if candidate in zf.namelist():
                    (licenses / PurePosixPath(name).name).write_bytes(zf.read(candidate))
                    break
            else:
                fail(f"{wheel.name} names License-File {name} but does not ship it")
        if not any(licenses.iterdir()):
            fail(f"{wheel.name} ships no licence file")
        scripts = []
        if f"{info}/entry_points.txt" in zf.namelist():
            entry_points = zf.read(f"{info}/entry_points.txt").decode("utf-8")
            section = None
            for line in entry_points.splitlines():
                line = line.strip()
                if line.startswith("["):
                    section = line
                elif line and section == "[console_scripts]":
                    scripts.append(line)

    record = {
        "name": metadata["Name"],
        "version": metadata["Version"],
        "commit": commit,
        "license": metadata.get("License-Expression") or metadata.get("License") or "",
        "requires_python": metadata.get("Requires-Python") or "",
        "requires_dist": metadata.get_all("Requires-Dist") or [],
    }
    (staged / "kipy.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"vendored {record['name']} {record['version']} ({commit[:10]}) into {dest}: {len(package)} files, "
          f"{imports} import lines renamed in {files} files")
    for line in rewritten:
        print(f"  also renamed: {line}")
    print(f"  requires: {'; '.join(record['requires_dist']) or 'nothing'} (Python {record['requires_python'] or 'any'})")
    print(f"  licence ({record['license'] or 'unstated'}): {', '.join(sorted(p.name for p in licenses.iterdir()))}")
    for script in scripts:
        print(f"  not installed: console script {script}")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel", type=Path, help="KiPy's built wheel (kicad_python-*.whl)")
    parser.add_argument("staged", type=Path, help="the staged dir make_wheel.py takes")
    parser.add_argument("--commit", required=True, help="the KiPy commit the wheel was built from")
    args = parser.parse_args(argv)
    vendor(args.wheel, args.staged, args.commit.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
