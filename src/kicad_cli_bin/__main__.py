"""``python -m kicad_cli_bin``: print the packaged kicad-cli's path, or run it headless with what follows.

    python -m kicad_cli_bin                    # the path
    python -m kicad_cli_bin pcb drc board.kicad_pcb
"""

import os
import subprocess
import sys
import tempfile

from . import environment, executable


def main() -> int:
    if len(sys.argv) == 1:
        print(executable())
        return 0
    with tempfile.TemporaryDirectory(prefix="kicad-cli-bin-") as root:
        return subprocess.call([str(executable()), *sys.argv[1:]], env={**os.environ, **environment(root)})


if __name__ == "__main__":
    sys.exit(main())
