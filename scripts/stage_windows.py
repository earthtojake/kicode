"""Stage KiCad's own Windows kicad-cli out of an official nightly or release installer. Needs 7-Zip (`7z`,
which unpacks KiCad's NSIS installer without running it).

    python scripts/stage_windows.py <kicad-...-x86_64-lite.exe> <out dir>

<out dir>/kicad_cli_bin/kicad/bin/ gets the installer's program folder (kicad-cli.exe, the kifaces, the
DLLs they load and plugins/3d), less the programs a headless command line never runs: the GUI programs,
the crash handler and Python's launchers. KiCad's signatures on the files are left as they are. Nothing of
share/ is staged: a run reads none of it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The installer's programs other than kicad-cli, and what only they or the crash reporter use.
DROP_PROGRAMS = {"kicad.exe", "pcbnew.exe", "eeschema.exe", "gerbview.exe", "pl_editor.exe", "pcb_calculator.exe",
                 "bitmap2component.exe", "crashpad_handler.exe", "python.exe", "pythonw.exe", "kicad-cmd.bat"}


def unpack(installer: Path, into: Path) -> Path:
    """The installer's program folder: the folder holding kicad-cli.exe once 7-Zip has unpacked it."""
    subprocess.run(["7z", "x", "-y", f"-o{into}", str(installer)], check=True, stdout=subprocess.DEVNULL)
    found = sorted(into.rglob("kicad-cli.exe"), key=lambda path: len(path.parts))
    if not found:
        listing = "\n".join(str(path.relative_to(into)) for path in sorted(into.iterdir()))
        raise SystemExit(f"no kicad-cli.exe in {installer}; it unpacked to:\n{listing}")
    return found[0].parent


def main(installer: Path, out: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="kicad-win-") as scratch:
        program = unpack(installer, Path(scratch))
        print(f"program folder: {program.relative_to(scratch)}")
        dest = out / "kicad_cli_bin" / "kicad" / "bin"
        if dest.parent.exists():
            shutil.rmtree(dest.parent)
        dropped = []

        def ignore(folder: str, names: list[str]) -> list[str]:
            skip = [name for name in names if name.lower() in DROP_PROGRAMS]
            dropped.extend(str(Path(folder, name).relative_to(program)) for name in skip)
            return skip

        shutil.copytree(program, dest, ignore=ignore)
    files = [path for path in dest.rglob("*") if path.is_file()]
    size = sum(path.stat().st_size for path in files)
    print(f"dropped: {', '.join(sorted(dropped)) or 'nothing'}")
    print(f"staged {len(files)} files, {size / 1e6:.0f} MB, in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
