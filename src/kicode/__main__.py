"""``python -m kicode``: print the packaged kicad-cli's path, or run it headless with what follows.

    python -m kicode                    # the path
    python -m kicode pcb drc board.kicad_pcb

A schematic command (``sch``, ``sym``) without kicode-sch installed stops with what to install.
"""

import os
import subprocess
import sys
import tempfile

from ._runtime import environment, executable, has_schematic

# kicad-cli's commands that load KiCad's schematic kiface, which the kicode-sch package carries.
_SCHEMATIC_COMMANDS = {"sch", "sym"}


def _version() -> str:
    """kicode-pcb's version, the one kicode-sch must match."""
    try:
        from importlib.metadata import version

        return version("kicode-pcb")
    except Exception:  # noqa: BLE001 - a checkout, not an installed distribution
        return ""


def main() -> int:
    if len(sys.argv) == 1:
        print(executable())
        return 0
    if sys.argv[1] in _SCHEMATIC_COMMANDS and not has_schematic():
        pin = f"=={_version()}" if _version() else ""
        print(f"kicad-cli {sys.argv[1]} needs KiCad's schematic support, which is the kicode-sch package: "
              f"pip install kicode-sch{pin} (or kicode{pin}, which is kicode-pcb and kicode-sch)", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="kicode-") as root:
        return subprocess.call([str(executable()), *sys.argv[1:]], env={**os.environ, **environment(root)})


if __name__ == "__main__":
    sys.exit(main())
