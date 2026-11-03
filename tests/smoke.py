"""Smoke-test an installed kicad-cli-bin: run from the environment the wheel was installed into.

    python tests/smoke.py [--expect-version 10.99.0] [--no-api]

Every run is headless with the package's own environment() and a scratch root, from a copy of the fixture
board: the version, DRC, STEP, SVG and Gerber exports, a schematic's netlist, and (unless --no-api, or
kipy is not installed) a board edited through `kicad-cli api-server` with kipy and saved. Fails when any
step fails, or when a run left anything in the person's own KiCad folders.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import kicad_cli_bin

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
        self.root = Path(tempfile.mkdtemp(prefix="kicad-cli-bin-smoke-"))
        self.cli = kicad_cli_bin.executable()
        self.env = {**os.environ, **kicad_cli_bin.environment(self.root / "homes")}
        self.work = self.root / "work"
        shutil.copytree(FIXTURES, self.work)
        self.board = self.work / "smoke.kicad_pcb"
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

    def expect_file(self, path: Path, what: str) -> None:
        if not (path.is_file() and path.stat().st_size > 0 or path.is_dir() and any(path.iterdir())):
            self.failures.append(f"{what} wrote nothing at {path}")

    def api(self) -> None:
        try:
            from kipy import KiCad
            from kipy.board_types import Track
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
        except ImportError:
            print("-- kipy not installed: api-server not tested")
            return
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
                except Exception as error:  # noqa: BLE001 - kipy's, until the server listens and has loaded the board
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
    parser.add_argument("--expect-version")
    parser.add_argument("--no-api", action="store_true")
    args = parser.parse_args(argv)

    before = _snapshot()
    smoke = Smoke()
    print(f"kicad-cli-bin {kicad_cli_bin.KICAD_VERSION} ({kicad_cli_bin.KICAD_COMMIT}) at {smoke.cli}")
    version = smoke.run("version").stdout.strip()
    expected = args.expect_version or kicad_cli_bin.KICAD_VERSION
    if expected and version != expected:
        smoke.failures.append(f"kicad-cli version says {version!r}, expected {expected!r}")
    out = smoke.root / "out"
    smoke.run("pcb", "drc", "--format", "json", "-o", str(out / "drc.json"), str(smoke.board))
    if (out / "drc.json").is_file():
        json.loads((out / "drc.json").read_text(encoding="utf-8"))
    smoke.expect_file(out / "drc.json", "pcb drc")
    smoke.run("pcb", "export", "step", "-o", str(out / "board.step"), str(smoke.board))
    smoke.expect_file(out / "board.step", "pcb export step")
    smoke.run("pcb", "export", "svg", "-l", "F.Cu,Edge.Cuts", "-o", str(out / "board.svg"), str(smoke.board))
    smoke.expect_file(out / "board.svg", "pcb export svg")
    smoke.run("pcb", "export", "gerbers", "-o", str(out / "gerbers") + os.sep, str(smoke.board))
    smoke.expect_file(out / "gerbers", "pcb export gerbers")
    smoke.run("sch", "export", "netlist", "-o", str(out / "board.net"), str(smoke.work / "smoke.kicad_sch"))
    smoke.expect_file(out / "board.net", "sch export netlist")
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
