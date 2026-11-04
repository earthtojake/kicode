"""Smoke-test installed kicode wheels: run from the environment they were installed into.

    python tests/smoke.py --installed kicode-pcb [--expect-version 10.99.0] [--no-api]   # the board side alone
    python tests/smoke.py --installed kicode [--expect-version 10.99.0] [--no-api]       # kicode-pcb and kicode-sch

Every run is headless with the package's own environment() and a scratch root, from a copy of the fixture
board: the version, the `kicad-cli` console script beside the Python (the packaged kicad-cli's output and
exit code, its homes in KICODE_HOME's root), DRC, and every board export text-to-cad uses (STEP, Gerbers,
drill, positions, SVG, PDF); and (unless --no-api) the board edited through `kicad-cli api-server` with kicode's KiPy and saved.
With kicode installed it also exports the schematic's netlist; with kicode-pcb alone it checks that
`python -m kicode sch` says to install kicode-sch instead. Either way the import package must be kicode
(KiPy's modules under it, no kipy), and the run fails when any step fails or left anything in the person's
own KiCad folders.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import kicode

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _personal_folders() -> list[Path]:
    """Where KiCad keeps a person's settings, documents and caches on this platform."""
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library" / "Preferences" / "kicad", home / "Documents" / "KiCad",
                home / "Library" / "Caches" / "kicad"]
    if sys.platform.startswith("win"):
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return [appdata / "kicad", home / "Documents" / "KiCad", local / "kicad"]
    return [home / ".config" / "kicad", home / ".local" / "share" / "kicad", home / ".cache" / "kicad"]


def _snapshot() -> dict[str, float]:
    found = {}
    for folder in _personal_folders():
        if folder.exists():
            for path in [folder, *folder.rglob("*")]:
                found[str(path)] = path.stat().st_mtime
    return found


class Smoke:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kicode-smoke-"))
        self.cli = kicode.executable()
        self.env = {**os.environ, **kicode.environment(self.root / "homes")}
        self.work = self.root / "work"
        shutil.copytree(FIXTURES, self.work)
        self.board = self.work / "smoke.kicad_pcb"
        self.out = self.root / "out"
        self.failures: list[str] = []

    def run(self, *args: str, ok=(0,)) -> subprocess.CompletedProcess:
        started = time.monotonic()
        done = subprocess.run([str(self.cli), *args], env=self.env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=300)
        said = (done.stdout + done.stderr).strip().splitlines()
        line = said[-1] if said else ""
        status = "ok " if done.returncode in ok else "ERR"
        print(f"{status} {time.monotonic() - started:6.2f}s kicad-cli {' '.join(args[:3])}: {line[:160]}")
        if done.returncode not in ok:
            self.failures.append(f"kicad-cli {' '.join(args)} exited {done.returncode}: {done.stdout}\n{done.stderr}")
        return done

    def export(self, kind: str, target: str, *options: str, of: Path | None = None) -> None:
        """One `kicad-cli <pcb|sch> export <kind>`, which must write something at out/<target>."""
        path = self.out / target
        self.run("sch" if of else "pcb", "export", kind, *options, "-o", str(path) + (os.sep if target.endswith("/") else ""),
                 str(of or self.board))
        if not (path.is_file() and path.stat().st_size > 0 or path.is_dir() and any(path.iterdir())):
            self.failures.append(f"export {kind} wrote nothing at {path}")

    def package(self, installed: str) -> None:
        """The import package is kicode-pcb's: KiPy's modules under kicode, no kipy. kicode-sch, when there,
        ships KiCad's files alone, and kicode (the distribution) no files at all."""
        if not hasattr(kicode, "KiCad"):
            self.failures.append("kicode has no KiCad (KiPy's client)")
        files = [str(file) for file in importlib.metadata.files("kicode-pcb") or []]
        if not any(file == "kicode/__init__.py" for file in files) or any(file.startswith("kipy/") for file in files):
            self.failures.append("kicode-pcb does not ship the kicode package, or ships kipy/")
        if importlib.util.find_spec("kipy") is not None:
            self.failures.append(f"kipy is importable here ({importlib.util.find_spec('kipy').origin}): only kicode's "
                                 "distributions and their dependencies belong in this environment")
        for name in ("KICAD_COMMIT", "KIPY_COMMIT", "KIPY_VERSION"):
            if not getattr(kicode, name, ""):
                self.failures.append(f"kicode.{name} is empty")
        everything = installed == "kicode"
        if kicode.has_schematic() != everything:
            self.failures.append(f"kicode.has_schematic() is {kicode.has_schematic()}, expected {everything}")
        versions = {}
        for name, prefixes in (("kicode-sch", ("kicode/_kicad/", "kicode_sch-")), ("kicode", ("kicode-",))):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                if everything:
                    self.failures.append(f"{name} is not installed")
                continue
            if not everything:
                self.failures.append(f"{name} is installed beside kicode-pcb alone")
            strays = [str(file) for file in importlib.metadata.files(name) or [] if not str(file).startswith(prefixes)]
            if strays:
                self.failures.append(f"{name} ships files of its own outside {prefixes[0]}: {strays[:5]}")
        pcb = importlib.metadata.version("kicode-pcb")
        if any(version != pcb for version in versions.values()):
            self.failures.append(f"versions differ: kicode-pcb {pcb}, {versions}")
        print(f"ok  kicode-pcb {pcb} {' '.join(f'{name} {version}' for name, version in versions.items())}: KiCad "
              f"{kicode.KICAD_VERSION} ({kicode.KICAD_COMMIT[:10]}), KiPy {kicode.KIPY_VERSION} ({kicode.KIPY_COMMIT[:10]}), "
              f"schematic {kicode.has_schematic()}")

    def console_script(self, version: str) -> None:
        """The `kicad-cli` console script beside this Python runs the packaged one: its output and exit code
        as the binary's, its KiCad homes in KICODE_HOME's root."""
        script = Path(sys.executable).parent / ("kicad-cli.exe" if sys.platform.startswith("win") else "kicad-cli")
        if not script.is_file():
            self.failures.append(f"no kicad-cli console script at {script}")
            return
        root = self.root / "console-script"
        env = {key: value for key, value in os.environ.items() if not key.startswith(("KICAD_", "KICODE_"))}
        env["KICODE_HOME"] = str(root)
        done = subprocess.run([str(script), "version"], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=300)
        if (done.returncode, done.stdout.strip()) != (0, version):
            self.failures.append(f"console script kicad-cli version exited {done.returncode}: {done.stdout}{done.stderr}")
        if not (root / "settings").is_dir() or not any((root / "settings").iterdir()):
            self.failures.append(f"console script kicad-cli wrote no settings in KICODE_HOME's root, {root}")
        missing = str(self.work / "missing.kicad_pcb")
        ours = subprocess.run([str(script), "pcb", "drc", missing], env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=300).returncode
        theirs = self.run("pcb", "drc", missing, ok=range(1, 256)).returncode
        if ours != theirs or ours == 0:
            self.failures.append(f"console script kicad-cli exited {ours} on a missing board, the binary {theirs}")
        else:
            print(f"ok  console script {script.name}: version {version}, exit code {ours} passed through")

    def schematic_missing(self) -> None:
        """Without kicode-sch, `python -m kicode sch` stops with what to install."""
        done = subprocess.run([sys.executable, "-m", "kicode", "sch", "export", "netlist", "-o", str(self.out / "x.net"),
                               str(self.work / "smoke.kicad_sch")], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=60)
        if done.returncode == 0 or "pip install kicode-sch" not in done.stderr:
            self.failures.append(f"python -m kicode sch without kicode-sch exited {done.returncode}: {done.stderr}")
        else:
            print(f"ok  python -m kicode sch: {done.stderr.strip()[:160]}")

    def api(self) -> None:
        from kicode import KiCad
        from kicode.board_types import Track
        from kicode.proto.board.board_types_pb2 import BoardLayer

        sock = self.root / "api.sock"
        log = (self.root / "api-server.log").open("w")
        started = time.monotonic()
        server = subprocess.Popen([str(self.cli), "api-server", "--socket", str(sock), str(self.board)], env=self.env,
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            kicad = KiCad(socket_path=f"ipc://{sock}", client_name="smoke", timeout_ms=60000)
            board = None
            while time.monotonic() - started < 120:
                try:
                    kicad.ping()
                    board = kicad.get_board()
                    break
                except Exception as error:  # noqa: BLE001 - KiPy's, until the server listens and has loaded the board
                    if server.poll() is not None:
                        raise RuntimeError(f"api-server exited {server.returncode}") from error
                    time.sleep(0.05)
            if board is None:
                raise RuntimeError("api-server did not answer within 120 s")
            ready = time.monotonic() - started
            pads = sorted(board.get_pads(), key=lambda pad: pad.position.x)
            commit = board.begin_commit()
            track = Track()
            track.start, track.end = pads[0].position, pads[-1].position
            track.width, track.layer = 250_000, BoardLayer.BL_F_Cu
            board.create_items([track])
            board.push_commit(commit, "smoke track")
            board.save()
            print(f"ok  {ready:6.2f}s api-server: board ready; {len(pads)} pads, track added and saved")
        except Exception as error:  # noqa: BLE001
            self.failures.append(f"api-server: {type(error).__name__}: {error}")
        finally:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()
            log.close()
        if "(segment" not in self.board.read_text(encoding="utf-8"):
            self.failures.append("api-server: the saved board has no track")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--installed", required=True, choices=["kicode-pcb", "kicode"],
                        help="kicode-pcb alone, or kicode (kicode-pcb and kicode-sch)")
    parser.add_argument("--expect-version")
    parser.add_argument("--no-api", action="store_true")
    args = parser.parse_args(argv)

    before = _snapshot()
    smoke = Smoke()
    print(f"kicad-cli at {smoke.cli}")
    smoke.package(args.installed)
    version = smoke.run("version").stdout.strip()
    expected = args.expect_version or kicode.KICAD_VERSION
    if expected and version != expected:
        smoke.failures.append(f"kicad-cli version says {version!r}, expected {expected!r}")
    smoke.console_script(version)
    smoke.run("pcb", "drc", "--format", "json", "-o", str(smoke.out / "drc.json"), str(smoke.board))
    if (smoke.out / "drc.json").is_file():
        json.loads((smoke.out / "drc.json").read_text(encoding="utf-8"))
    else:
        smoke.failures.append("pcb drc wrote no report")
    smoke.export("step", "board.step")
    smoke.export("gerbers", "gerbers/")
    smoke.export("drill", "drill/")
    smoke.export("pos", "board.pos", "--format", "ascii", "--units", "mm")
    smoke.export("svg", "board.svg", "-l", "F.Cu,Edge.Cuts")
    smoke.export("pdf", "board.pdf", "-l", "F.Cu,Edge.Cuts", "--mode-single")
    if args.installed == "kicode":
        smoke.export("netlist", "board.net", of=smoke.work / "smoke.kicad_sch")
    else:
        smoke.schematic_missing()
    help_text = smoke.run("api-server", "--help").stdout
    if "--socket" not in help_text:
        smoke.failures.append("kicad-cli api-server --help lists no --socket")
    if not args.no_api:
        smoke.api()

    after = _snapshot()
    touched = sorted(path for path, stamp in after.items() if before.get(path) != stamp)
    if touched:
        smoke.failures.append("runs wrote into the person's KiCad folders: " + ", ".join(touched[:10]))
    shutil.rmtree(smoke.root, ignore_errors=True)
    if smoke.failures:
        print("\nFAILED:\n" + "\n".join(f"- {failure}" for failure in smoke.failures))
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
