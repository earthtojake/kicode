"""The ``kicad-cli`` console script (``kicode._launcher``), without a KiCad: standard library only.

    python3 -m unittest discover -s tests

kicode-pcb's wheel, written by scripts/make_wheel.py from a staged tree whose kicad-cli is a stand-in that
reports what it was given, declares the script; installed into a fresh environment (by uv when it is on
PATH, else venv's pip), the script runs the stand-in with the arguments, stdio and exit code passed through,
its KiCad homes kicode's private ones unless the caller named its own, and the package's own variables
always the package's. On Windows the stand-in cannot be a .exe, so only the environment the script makes is
checked there; tests/smoke.py runs the real one on every platform.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import make_wheel  # noqa: E402

from kicode import _launcher  # noqa: E402

POSIX = not sys.platform.startswith("win")
# The stand-in kicad-cli: what it was run with, as JSON on stdout, a line on stderr, and exit code 7.
STAND_IN = """#!/bin/sh
exec "{python}" -c '
import json, os, sys
names = ("HOME", "KICAD_CONFIG_HOME", "KICAD_DOCUMENTS_HOME", "KICAD_CACHE_HOME", "APPDIR", "KICODE_HOME")
print(json.dumps({{"argv": sys.argv[1:], "stdin": sys.stdin.read(), "env": {{n: os.environ.get(n) for n in names}}}}))
print("said on stderr", file=sys.stderr)
sys.exit(7)
' "$@"
"""


def _cli_path() -> str:
    """Where a stager puts kicad-cli and the eeschema kiface on this platform, under ``kicode/_kicad``."""
    if sys.platform == "darwin":
        return "Contents/MacOS"
    return "bin" if sys.platform.startswith("win") else "usr/bin"


def _kiface() -> str:
    return "Contents/PlugIns/_eeschema.kiface" if sys.platform == "darwin" else f"{_cli_path()}/_eeschema.kiface"


class ConsoleScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="kicode-launcher-")).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        staged = cls.root / "staged"
        package = staged / "kicode"
        cli = package / "_kicad" / _cli_path() / ("kicad-cli.exe" if not POSIX else "kicad-cli")
        cli.parent.mkdir(parents=True)
        cli.write_text(STAND_IN.format(python=sys.executable), encoding="utf-8")
        cli.chmod(0o755)
        kiface = package / "_kicad" / _kiface()
        kiface.parent.mkdir(parents=True, exist_ok=True)
        kiface.write_bytes(b"kiface")
        (package / "__init__.py").write_text("from ._runtime import environment, executable, has_schematic\n",
                                             encoding="utf-8")
        (staged / "kipy.json").write_text(json.dumps({"name": "kicad-python", "version": "0.0", "commit": "0" * 40,
                                                      "requires_python": ">=3.9", "requires_dist": []}), encoding="utf-8")
        (staged / "schematic").mkdir()
        (staged / "schematic" / "files.txt").write_text(f"_kicad/{_kiface()}\n", encoding="utf-8")
        (staged / "licenses" / "kipy").mkdir(parents=True)
        (staged / "licenses" / "kipy" / "LICENSE").write_text("MIT\n", encoding="utf-8")
        cls.wheels = make_wheel.platform(staged, "10.99.0.dev20991231", "any", "10.99.0", "f" * 40, None,
                                         cls.root / "dist")

    def test_kicode_pcb_declares_the_console_script(self) -> None:
        import zipfile

        (pcb,) = [wheel for wheel in self.wheels if wheel.name.startswith("kicode_pcb-")]
        with zipfile.ZipFile(pcb) as wheel:
            entries = wheel.read("kicode_pcb-10.99.0.dev20991231.dist-info/entry_points.txt").decode()
            self.assertIn("kicode/_launcher.py", wheel.namelist())
        self.assertEqual(entries, "[console_scripts]\nkicad-cli = kicode._launcher:main\n")
        (sch,) = [wheel for wheel in self.wheels if wheel.name.startswith("kicode_sch-")]
        with zipfile.ZipFile(sch) as wheel:
            self.assertNotIn("kicode_sch-10.99.0.dev20991231.dist-info/entry_points.txt", wheel.namelist())

    def test_the_caller_s_variables_are_kept_and_kicode_s_homes_fill_the_rest(self) -> None:
        own = self.root / "own"
        env = {"KICODE_HOME": str(own), "KICAD_CONFIG_HOME": str(self.root / "callers-settings"),
               "APPDIR": "/somewhere/else", "KICAD_CACHE_HOME": ""}
        packaged = _launcher.environment
        with mock.patch.object(_launcher, "environment", lambda root: {**packaged(root), "APPDIR": "/the/package"}):
            found = _launcher.environ(env)
        self.assertEqual(found["KICAD_CONFIG_HOME"], str(self.root / "callers-settings"), "the caller's is kept")
        self.assertEqual(found["KICAD_DOCUMENTS_HOME"], str(own / "documents"))
        self.assertEqual(found["KICAD_CACHE_HOME"], str(own / "cache"), "an empty one is no one's")
        self.assertEqual(found["APPDIR"], "/the/package", "where the package's files are is the package's")
        with mock.patch.object(Path, "home", return_value=self.root / "person"):
            self.assertEqual(_launcher.home({}), self.root / "person" / (
                "Library/Caches/kicode" if sys.platform == "darwin" else ".cache/kicode"))
            if sys.platform != "darwin":
                self.assertEqual(_launcher.home({"XDG_CACHE_HOME": str(self.root / "xdg")}), self.root / "xdg" / "kicode")

    @unittest.skipUnless(POSIX, "the stand-in kicad-cli is a shell script")
    def test_installed_it_runs_the_packaged_kicad_cli_passing_everything_through(self) -> None:
        env_root = self.root / "env"
        (pcb,) = [wheel for wheel in self.wheels if wheel.name.startswith("kicode_pcb-")]
        uv = shutil.which("uv")
        if uv:
            subprocess.run([uv, "venv", "-q", "--python", sys.executable, str(env_root)], check=True)
            subprocess.run([uv, "pip", "install", "-q", "--python", str(env_root / "bin" / "python"), "--no-deps",
                            str(pcb)], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(env_root)], check=True)
            subprocess.run([str(env_root / "bin" / "python"), "-m", "pip", "install", "-q", "--no-deps", str(pcb)],
                           check=True)
        script = env_root / "bin" / "kicad-cli"
        self.assertTrue(script.is_file(), "the installer wrote the console script")
        base = {key: value for key, value in os.environ.items() if not key.startswith(("KICAD_", "KICODE_"))}

        home = self.root / "kicode-home"
        done = subprocess.run([str(script), "pcb", "drc", "a board.kicad_pcb"], input="in", capture_output=True,
                              text=True, env={**base, "KICODE_HOME": str(home)}, check=False)
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertEqual(done.stderr.strip(), "said on stderr")
        said = json.loads(done.stdout)
        self.assertEqual((said["argv"], said["stdin"]), (["pcb", "drc", "a board.kicad_pcb"], "in"))
        self.assertEqual({name: said["env"][name] for name in ("KICAD_CONFIG_HOME", "KICAD_DOCUMENTS_HOME",
                                                               "KICAD_CACHE_HOME")},
                         {"KICAD_CONFIG_HOME": str(home / "settings"), "KICAD_DOCUMENTS_HOME": str(home / "documents"),
                          "KICAD_CACHE_HOME": str(home / "cache")})
        self.assertEqual(said["env"]["HOME"], base.get("HOME"), "the caller's HOME is kept")
        self.assertTrue((home / "settings").is_dir())

        callers = self.root / "callers"
        done = subprocess.run([str(script), "version"], input="", capture_output=True, text=True, check=False,
                              env={**base, "KICODE_HOME": str(home), "KICAD_CONFIG_HOME": str(callers / "settings"),
                                   "KICAD_DOCUMENTS_HOME": str(callers / "documents"),
                                   "KICAD_CACHE_HOME": str(callers / "cache")})
        self.assertEqual(json.loads(done.stdout)["env"]["KICAD_CONFIG_HOME"], str(callers / "settings"),
                         "a caller that names KiCad's homes runs in its own")


if __name__ == "__main__":
    unittest.main()
