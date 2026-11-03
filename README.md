# kicode

Unofficial: not made, endorsed or supported by the KiCad project.

kicode puts [KiCad](https://www.kicad.org)'s command line, `kicad-cli`, and KiCad's client for its IPC API,
KiPy, in one Python package, `kicode`. One install gives an environment a headless `kicad-cli` and the
client that drives its API server, with nothing else of KiCad's installed and nothing of the person's own
KiCad settings touched. It exists for [text-to-cad](https://github.com/earthtojake/text-to-cad), whose
`cad[kicad]` pins one build of it, and works for anything that runs KiCad from Python.

## Unofficial build

kicode repackages KiCad's own software. It is not KiCad's: the KiCad project did not make it and does not
support it.

- `kicad-cli` is KiCad's own, unmodified. On macOS and Windows kicode carries KiCad's own files from its
  published nightly build of a commit: `kicad-cli` and what it loads (on macOS the arm64 half of each file,
  KiCad's signatures intact). On Linux it is built from KiCad's source at the same commit, stamped with the
  version KiCad's own builds of that commit report.
- KiPy ([kicad-python](https://gitlab.com/kicad/code/kicad-python)) is KiCad's as it publishes it, with its
  modules renamed from `kipy` to `kicode` and nothing else changed.
- Report problems with kicode at [earthtojake/kicode's issues](https://github.com/earthtojake/kicode/issues),
  not to the KiCad project.
- KiCad is a trademark of its owners. kicode uses no KiCad logo, and its name implies no endorsement.

## Packages

kicode is three distributions, published together under one version. Whichever you install, the Python
package is `kicode`.

| Distribution | What it is | Wheels (sizes of 10.99.0.dev20261031) |
| --- | --- | --- |
| `kicode` | What to install: no files of its own; it requires `kicode-pcb` and `kicode-sch` of the same version. | one, `py3-none-any` (17 kB) |
| `kicode-pcb` | The board side and the `kicode` package: `kicad-cli`, pcbnew's kiface (every `kicad-cli pcb` and `fp` command, and the API server), the 3D model plugins, every library they link, and KiPy. | macOS arm64 76.2 MB, Windows x86_64 54.8 MB, Linux x86_64 84.9 MB |
| `kicode-sch` | The schematic side: the eeschema and cvpcb kifaces (every `kicad-cli sch` and `sym` command) and the libraries only they link, installed into kicode-pcb's folder. It requires `kicode-pcb` of the same version. | macOS arm64 26.2 MB, Windows x86_64 18.1 MB, Linux x86_64 24.6 MB |

| Platform | kicad-cli from | Minimum OS | Wheel tag |
| --- | --- | --- | --- |
| macOS arm64 | KiCad's nightly DMG: `kicad-cli`, its kifaces, 3D plugins and the libraries they link | macOS 14 | `macosx_14_0_arm64` |
| Windows x86_64 | KiCad's nightly installer: `kicad-cli.exe`, its kifaces, 3D plugins and every DLL of the installer they import | Windows 10 | `win_amd64` |
| Linux x86_64 | A build of the same commit on Debian 12, every library it links bundled but glibc's | glibc 2.36 (Debian 12, Ubuntu 22.10 and later, RHEL 10) | `manylinux_2_36_x86_64` |

Every platform wheel of a version is built from one KiCad commit and one KiPy commit, and every wheel is
under 100 MB, PyPI's limit: the build refuses a bigger one.

## Install

```bash
pip install "kicode==10.99.0.dev20261031"       # kicode-pcb and kicode-sch
pip install "kicode-pcb==10.99.0.dev20261031"   # the board side alone
```

From PyPI once a version is promoted there; before that, or for any other nightly, from its GitHub release:

```bash
uv pip install "kicode==10.99.0.dev20261031" \
  --find-links https://github.com/earthtojake/kicode/releases/expanded_assets/v10.99.0.dev20261031
```

## Python API

kicode's own names:

- `kicode.executable()`: the packaged `kicad-cli` (`kicad-cli.exe` on Windows).
- `kicode.environment(root)`: the variables a headless run sets, every KiCad home inside `root` (below).
- `kicode.has_schematic()`: whether kicode-sch is installed.
- `kicode.stock_data_home()`: the stock data folder a Linux build reads (None elsewhere).
- `kicode.KICAD_VERSION`, `KICAD_COMMIT`, `KIPY_VERSION`, `KIPY_COMMIT`: what the wheels were built from.

Beside them, KiPy's API under the same names, with `kicode` in place of `kipy`: `from kicode import KiCad`,
`from kicode.board_types import Track`, `kicode.proto.board.board_types_pb2`.

```python
import os, subprocess, time, kicode

env = {**os.environ, **kicode.environment("/tmp/run")}   # the run's own KiCad homes
subprocess.run([kicode.executable(), "pcb", "export", "step", "-o", "board.step", "board.kicad_pcb"],
               env=env, check=True)

# The IPC API, served headless by kicad-cli and driven with KiPy. Keep the socket's path short: a Unix
# socket's path is limited to about 100 bytes.
server = subprocess.Popen([kicode.executable(), "api-server", "--socket", "/tmp/run/api.sock",
                           "board.kicad_pcb"], env=env)
kicad = kicode.KiCad(socket_path="ipc:///tmp/run/api.sock", timeout_ms=10000)
for _ in range(200):          # until the server listens and has loaded the board
    try:
        board = kicad.get_board()
        break
    except Exception:
        time.sleep(0.05)
else:
    raise RuntimeError("kicad-cli api-server did not answer")
print(len(board.get_pads()), "pads")
server.terminate()
```

`python -m kicode` prints the executable's path, and `python -m kicode <arguments>` runs it headless in a
temporary root. With kicode-pcb alone, `kicad-cli sch …` stops with KiCad's own
`Failed to load kiface library '…/_eeschema.kiface'`, and `python -m kicode sch …` says to install
kicode-sch.

`environment(root)` sets `HOME` (and `USERPROFILE`) and `TMPDIR` (`TEMP` and `TMP` on Windows);
`KICAD_CONFIG_HOME`, `KICAD_DOCUMENTS_HOME` and `KICAD_CACHE_HOME`, without which KiCad reads and writes the
person's own; and on Linux `KICAD_STOCK_DATA_HOME` and `APPDIR` (KiCad's AppImage variable), by which the
build finds its stock data, kifaces and 3D plugins inside the wheel. Merge them over the environment a run
is given.

Headless, the API serves every read, commit, edit, zone fill, design rule, netlist import, library
placement and export, but no editor state (selection, active and visible layers, appearance, interactive
moves, `run_action`). KiPy's own `KiCad(headless=True)` starts whichever `kicad-cli` it finds installed (on
macOS the one in `/Applications` first) in the person's own KiCad settings: start `kicode.executable()`
with `kicode.environment(root)` instead, as above.

## Left out

- KiCad's GUI: no `kicad`, `pcbnew` or `eeschema` programs.
- KiCad's symbol, footprint and 3D model libraries (over 3 GB). Point `KICAD10_FOOTPRINT_DIR`,
  `KICAD10_SYMBOL_DIR` and `KICAD10_3DMODEL_DIR` at a copy, with library tables in `KICAD_CONFIG_HOME`,
  when a run needs them.
- GerbView's, the PCB calculator's and the drawing sheet editor's kifaces, so `kicad-cli gerber` is not
  available.
- ngspice, which KiCad loads only to simulate, on Windows and Linux. macOS's eeschema links it, so there
  kicode-sch carries it.
- On Linux, a browser engine for wxWidgets' web view: KiCad's Linux build needs wxWidgets 3.3, built from
  its release tarball, and on GTK the only engine is WebKitGTK, which would add some 65 MB for pages only
  KiCad's GUI shows.
- KiPy's `kicad-python-packager` command; `python -m kicode.packaging` runs it.

## kicode and upstream kipy

Upstream `kipy` and `kicode` cannot be imported in one process. Both register the same protobuf files
(`board/board_types.proto`, …) in protobuf's one default pool, and whichever imports second fails with
`Couldn't build proto file into descriptor pool: duplicate file name` unless both were built from the same
KiPy commit. Install one or the other.

## Versions and where they are published

- A version is KiCad's: a nightly is `X.99.0.devYYYYMMDD`, the date of KiCad's macOS nightly of the
  commit. kicode, kicode-pcb and kicode-sch of one build share it.
- GitHub releases: every day the newest KiCad nightly that builds and passes on every platform is
  published as a prerelease of [earthtojake/kicode](https://github.com/earthtojake/kicode/releases) (tag
  `v10.99.0.dev20261031`) with all seven wheels and their sources. Its page is a find-links index (Install,
  above).
- PyPI: only versions promoted there, because a text-to-cad release pins them. The wheels are the GitHub
  release's, unchanged.

## Release flow

- `.github/workflows/build.yml` builds each platform's wheels and smoke-tests them where they run:
  kicode-pcb alone, then kicode, and the Linux wheels also in bare Debian, Ubuntu and Fedora roots. Once
  every platform passes, the release is made a draft with every asset, each asset is checked against the
  file it came from, and only then is the release published. Releases are immutable once published, so a
  failure leaves a draft (the next attempt replaces it), never a release that lacks a file.
- Promotion to PyPI is a dispatch of the workflow with `pypi`, never the daily schedule. It uploads the
  release's wheels, one distribution per job, each through its own GitHub environment and PyPI trusted
  publisher (owner `earthtojake`, repository `kicode`, workflow `build.yml`; each environment needs
  earthtojake's review and deploys from `main` only), in this order, so that PyPI never lists a kicode
  whose parts it lacks:

  | Order | PyPI project | GitHub environment | Wheels |
  | --- | --- | --- | --- |
  | 1 | `kicode-pcb` | `pypi-pcb` | one per platform |
  | 2 | `kicode-sch` | `pypi-sch` | one per platform |
  | 3 | `kicode` | `pypi` | one, `py3-none-any` |

The workflow's scripts run locally too: `scripts/resolve_nightly.py` finds a nightly on every platform;
`scripts/stage_macos.sh`, `scripts/stage_windows.py` and `scripts/build_linux.sh` stage a platform's
`kicode/_kicad/` tree and `schematic/files.txt` (what only the schematic kifaces need);
`scripts/vendor_kipy.py` puts KiPy's modules in `kicode/`; `scripts/kicad_licenses.py` fetches KiCad's
notices; `scripts/make_wheel.py` writes the wheels; and `tests/smoke.py` runs in the environment they are
installed into.

## License

kicode (this repository and its three distributions) is GPL-3.0-or-later, as KiCad is. KiPy is MIT, and
its licence ships in kicode-pcb's wheel. Each platform wheel also ships KiCad's notices from its commit,
and on Linux the copyright file of every library it bundles and wxWidgets' licence. Every GitHub release
attaches the corresponding source: KiCad's at the commit, and for the Linux wheels the Debian source
package of every library they bundle and wxWidgets' release tarball. The wheels on PyPI are the same files
as the GitHub release of their version, whose source is attached there.
