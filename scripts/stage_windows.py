"""Stage KiCad's own Windows kicad-cli out of an official nightly or release installer. Needs 7-Zip (`7z`,
which unpacks KiCad's NSIS installer without running it).

    python scripts/stage_windows.py <kicad-...-x86_64-lite.exe> <out dir>
    python scripts/stage_windows.py --program <unpacked program folder> <out dir>

<out dir>/kicode/_kicad/bin/ gets what kicad-cli loads out of the installer's program folder: kicad-cli.exe,
the kifaces and 3D plugins it loads by name (pcbnew's kiface for every pcb command and the API server,
eeschema's and cvpcb's for the sch and sym ones, plugins/3d/), and every DLL of the folder they import,
transitively, by their PE import and delay-load tables. Nothing else: GerbView's, the drawing sheet
editor's and the calculator's kifaces, the GUI programs, and every DLL nothing staged imports are left out.
KiCad's signatures on the files are left as they are. Nothing of share/ is staged: a run reads none of it.
<out dir>/schematic/files.txt lists the files only the schematic kifaces need (the two kifaces and every
DLL nothing else staged imports), relative to <out dir>/kicode/: the kicode-sch wheel carries them,
and the kicode-pcb wheel everything else (make_wheel.py). An import the folder does not hold is Windows' own.
Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# KiCad's Windows kifaces are DLLs: _pcbnew.dll and so on.
BOARD = ["kicad-cli.exe", "_pcbnew.dll"]
SCHEMATIC = ["_eeschema.dll", "_cvpcb.dll"]
PLUGINS = "plugins/3d"


def unpack(installer: Path, into: Path) -> Path:
    """The installer's program folder: the folder holding kicad-cli.exe once 7-Zip has unpacked it."""
    subprocess.run(["7z", "x", "-y", f"-o{into}", str(installer)], check=True, stdout=subprocess.DEVNULL)
    found = sorted(into.rglob("kicad-cli.exe"), key=lambda path: len(path.parts))
    if not found:
        listing = "\n".join(str(path.relative_to(into)) for path in sorted(into.iterdir()))
        raise SystemExit(f"no kicad-cli.exe in {installer}; it unpacked to:\n{listing}")
    return found[0].parent


def imports(path: Path) -> list[str]:
    """The DLLs a PE file names in its import and delay-load directories."""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise SystemExit(f"{path} is not a PE file")
    header = struct.unpack_from("<I", data, 0x3C)[0]
    if data[header:header + 4] != b"PE\0\0":
        raise SystemExit(f"{path} is not a PE file")
    sections, optional_size = struct.unpack_from("<H12xH", data, header + 6)
    optional = header + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic == 0x20B:  # PE32+
        image_base = struct.unpack_from("<Q", data, optional + 24)[0]
        count, directories = struct.unpack_from("<I", data, optional + 108)[0], optional + 112
    elif magic == 0x10B:  # PE32
        image_base = struct.unpack_from("<I", data, optional + 28)[0]
        count, directories = struct.unpack_from("<I", data, optional + 92)[0], optional + 96
    else:
        raise SystemExit(f"{path}: unknown PE optional header {magic:#x}")
    spans = []
    for index in range(sections):
        size, address, raw_size, raw = struct.unpack_from("<IIII", data, optional + optional_size + 40 * index + 8)
        spans.append((address, max(size, raw_size), raw))

    def offset(rva: int) -> int:
        for address, size, raw in spans:
            if address <= rva < address + size:
                return rva - address + raw
        raise SystemExit(f"{path}: address {rva:#x} is in no section")

    def name(rva: int) -> str:
        start = offset(rva)
        return data[start:data.index(b"\0", start)].decode("ascii")

    def directory(index: int) -> int:
        return struct.unpack_from("<I", data, directories + 8 * index)[0] if index < count else 0

    names = []
    at = directory(1)  # IMAGE_DIRECTORY_ENTRY_IMPORT: IMAGE_IMPORT_DESCRIPTORs, the last all zero
    if at:
        at = offset(at)
        while any(struct.unpack_from("<5I", data, at)):
            names.append(name(struct.unpack_from("<I", data, at + 12)[0]))
            at += 20
    at = directory(13)  # IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT: ImgDelayDescrs, the last all zero
    if at:
        at = offset(at)
        while any(struct.unpack_from("<8I", data, at)):
            attributes, dll = struct.unpack_from("<II", data, at)
            names.append(name(dll if attributes & 1 else dll - image_base))  # an RVA, or (old linkers) a VA
            at += 32
    return names


def closure(program: Path, roots: list[str]) -> set[str]:
    """Every file of the program folder the roots load, transitively, the roots included (relative paths)."""
    present = {path.name.lower(): path.name for path in program.iterdir() if path.is_file()}
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        relative = queue.pop()
        if relative in seen:
            continue
        seen.add(relative)
        for dll in imports(program / relative):
            found = present.get(dll.lower())
            if found is not None and found not in seen:
                queue.append(found)
    return seen


def stage(program: Path, out: Path) -> int:
    for relative in BOARD + SCHEMATIC:
        if not (program / relative).is_file():
            raise SystemExit(f"no {relative} in the program folder {program}")
    plugins = sorted(path.relative_to(program).as_posix() for path in (program / PLUGINS).glob("*.dll"))
    if not plugins:
        raise SystemExit(f"no 3D plugins in {program / PLUGINS}")
    board = closure(program, BOARD + plugins)
    schematic = closure(program, SCHEMATIC) - board
    kicad = out / "kicode" / "_kicad"
    if kicad.exists():
        shutil.rmtree(kicad)
    shutil.rmtree(out / "schematic", ignore_errors=True)
    (out / "schematic").mkdir(parents=True)
    for relative in sorted(board | schematic):
        (kicad / "bin" / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(program / relative, kicad / "bin" / relative)
    (out / "schematic" / "files.txt").write_text("".join(f"_kicad/bin/{relative}\n" for relative in sorted(schematic)),
                                                encoding="utf-8")
    everything = [path for path in program.rglob("*") if path.is_file()]
    left = sorted((path for path in everything if path.relative_to(program).as_posix() not in board | schematic),
                  key=lambda path: -path.stat().st_size)
    megabytes = lambda paths: sum(path.stat().st_size for path in paths) / 1e6  # noqa: E731
    print(f"staged {len(board)} files for kicode-pcb ({megabytes(program / name for name in board):.0f} MB) and "
          f"{len(schematic)} for kicode-sch ({megabytes(program / name for name in schematic):.0f} MB) in {kicad}")
    print(f"schematic only: {', '.join(sorted(schematic))}")
    print(f"left out {len(left)} files ({megabytes(left):.0f} MB): "
          + ", ".join(f"{path.relative_to(program).as_posix()} ({path.stat().st_size / 1e6:.1f} MB)" for path in left[:40])
          + (", …" if len(left) > 40 else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("installer", nargs="?", type=Path, help="KiCad's Windows installer")
    parser.add_argument("out", type=Path)
    parser.add_argument("--program", type=Path, help="an unpacked program folder instead of the installer")
    args = parser.parse_args(argv)
    if args.program:
        return stage(args.program, args.out)
    if args.installer is None:
        parser.error("give the installer or --program")
    with tempfile.TemporaryDirectory(prefix="kicad-win-") as scratch:
        program = unpack(args.installer, Path(scratch))
        print(f"program folder: {program.relative_to(scratch)}")
        return stage(program, args.out)


if __name__ == "__main__":
    sys.exit(main())
