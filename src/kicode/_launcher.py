"""``kicad-cli``, the console script kicode-pcb installs: the packaged kicad-cli, run headless.

    kicad-cli version
    kicad-cli pcb export step -o board.step board.kicad_pcb

It runs :func:`kicode.executable` with the arguments it is given, and its stdin, stdout, stderr and exit
code pass straight through: on POSIX it becomes that program (``os.execve``); on Windows, which has no exec,
it runs it as a child and exits with the child's code.

Its environment is the caller's with :func:`kicode.environment` beneath it, every home inside a root kicode
keeps for these runs (:func:`home`): ``KICODE_HOME`` when it names one, else a ``kicode`` folder in the
person's cache folder (``~/Library/Caches/kicode`` on macOS; ``$XDG_CACHE_HOME/kicode``, else
``~/.cache/kicode``, on Linux and on Windows, where a packaged app's AppData is virtualized). A variable the
caller already set is kept: a caller that names KiCad's homes (``KICAD_CONFIG_HOME``,
``KICAD_DOCUMENTS_HOME``, ``KICAD_CACHE_HOME``) runs in its own, and one that names none gets kicode's,
never the person's own KiCad settings. ``KICAD_STOCK_DATA_HOME`` and ``APPDIR``, by which a Linux build finds
what the wheel carries, are always the package's.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from ._runtime import environment, executable, has_schematic

__all__ = ["environ", "home", "main", "schematic_missing"]

# kicad-cli's commands that load KiCad's schematic kiface, which the kicode-sch package carries.
SCHEMATIC_COMMANDS = {"sch", "sym"}
# The variables that say where the package's own files are: never the caller's.
_PACKAGE = {"KICAD_STOCK_DATA_HOME", "APPDIR"}


def _version() -> str:
    """kicode-pcb's version, the one kicode-sch must match."""
    try:
        from importlib.metadata import version

        return version("kicode-pcb")
    except Exception:  # noqa: BLE001 - a checkout, not an installed distribution
        return ""


def schematic_missing(args: list[str]) -> str | None:
    """What to install, for a schematic command (``sch``, ``sym``) run without kicode-sch; else None."""
    if not args or args[0] not in SCHEMATIC_COMMANDS or has_schematic():
        return None
    pin = f"=={_version()}" if _version() else ""
    return (f"kicad-cli {args[0]} needs KiCad's schematic support, which is the kicode-sch package: "
            f"pip install kicode-sch{pin} (or kicode{pin}, which is kicode-pcb and kicode-sch)")


def home(env: Mapping[str, str] | None = None) -> Path:
    """The root the console script keeps its runs' homes in: ``KICODE_HOME``, else ``kicode`` in the person's
    cache folder."""
    env = os.environ if env is None else env
    named = env.get("KICODE_HOME", "").strip()
    if named:
        return Path(named)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "kicode"
    cache = env.get("XDG_CACHE_HOME", "").strip()
    return Path(cache) / "kicode" if cache and os.path.isabs(cache) else Path.home() / ".cache" / "kicode"


def environ(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """``env`` (this process's environment) with :func:`kicode.environment` of :func:`home` beneath it: what
    ``env`` sets (and is not empty) is kept, but for where the package's own files are."""
    found = dict(os.environ if env is None else env)
    for name, value in environment(home(found)).items():
        if name in _PACKAGE or not found.get(name):
            found[name] = value
    return found


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    said = schematic_missing(args)
    if said:
        print(said, file=sys.stderr)
        return 2
    try:
        program = str(executable())
    except FileNotFoundError as error:
        print(f"kicad-cli: {error}", file=sys.stderr)
        return 1
    env = environ()
    if sys.platform.startswith("win"):
        import subprocess

        child = subprocess.Popen([program, *args], env=env)
        while True:
            try:
                return child.wait()
            except KeyboardInterrupt:  # the console gave kicad-cli the same Ctrl+C: its exit code is the run's
                continue
    os.execve(program, [program, *args], env)
    return 1  # not reached


if __name__ == "__main__":
    sys.exit(main())
