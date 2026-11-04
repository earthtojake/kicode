"""``python -m kicode``: print the packaged kicad-cli's path, or run it headless with what follows.

    python -m kicode                    # the path
    python -m kicode pcb drc board.kicad_pcb

Each run gets a temporary root of its own for KiCad's homes; the ``kicad-cli`` console script keeps one
root instead (``kicode._launcher``). A schematic command (``sch``, ``sym``) without kicode-sch installed
stops with what to install.
"""

import os
import subprocess
import sys
import tempfile

from ._launcher import schematic_missing
from ._runtime import environment, executable


def main() -> int:
    if len(sys.argv) == 1:
        print(executable())
        return 0
    said = schematic_missing(sys.argv[1:])
    if said:
        print(said, file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="kicode-") as root:
        return subprocess.call([str(executable()), *sys.argv[1:]], env={**os.environ, **environment(root)})


if __name__ == "__main__":
    sys.exit(main())
