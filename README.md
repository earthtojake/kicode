# kicode

Unofficial headless build of KiCad's command line and IPC API client. Not affiliated with or endorsed by the KiCad project.

kicode puts [KiCad](https://www.kicad.org)'s own `kicad-cli` and KiPy
([kicad-python](https://gitlab.com/kicad/code/kicad-python), KiCad's client for its IPC API) in one Python
package: one install gives an environment a headless `kicad-cli` and the client that drives its API
server, with nothing else of KiCad's installed and nothing of the person's touched. It exists for
[text-to-cad](https://github.com/earthtojake/text-to-cad), whose `cad[kicad]` pins one build of it, and
works for anything that runs KiCad from Python.

```bash
pip install "kicode==10.99.0.dev20261031"
```

## Three distributions, one package

Every version is three distributions, built together, whose import package is always `kicode`:

- **`kicode`**: what everyone installs. It has no files of its own: it requires `kicode-pcb` and
  `kicode-sch` of the same version.
- **`kicode-pcb`**: the board side and the `kicode` package itself: `kicad-cli`, pcbnew's kiface, the 3D
  model plugins, every library they link, and KiPy. Every `kicad-cli pcb` and `fp` command, and the API
  server.
- **`kicode-sch`**: the schematic side: the eeschema and cvpcb kifaces and the libraries only they link,
  for `kicad-cli sch` and `sym`. It installs into kicode-pcb's folder, beside the kifaces `kicad-cli`
  loads, and requires `kicode-pcb` of the same version.

Each of kicode-pcb and kicode-sch is one wheel per platform, so that every wheel stays under 100 MB, PyPI's
limit (the build fails a wheel that is not). `kicode.has_schematic()` says whether kicode-sch is installed.
With kicode-pcb alone, `kicad-cli sch …` stops with KiCad's own
`Failed to load kiface library '…/_eeschema.kiface'`, and `python -m kicode sch …` says to install kicode-sch.

## Using it

```python
import os, subprocess, kicode

env = {**os.environ, **kicode.environment("/tmp/kicad-run")}   # the run's own homes, see below
subprocess.run([kicode.executable(), "pcb", "drc", "board.kicad_pcb"], env=env, check=True)
```

`python -m kicode` prints the executable's path; `python -m kicode <args>` runs it headless.

`kicad-cli api-server --socket <path> <board>` serves KiCad's IPC API headless, and KiPy is kicode's own:

```python
server = subprocess.Popen([kicode.executable(), "api-server", "--socket", "/tmp/run.sock", "board.kicad_pcb"],
                          env=env)
kicad = kicode.KiCad(socket_path="ipc:///tmp/run.sock")   # retry until the server answers ping()
board = kicad.get_board()
```

Editor state is not available headless (selection, active and visible layers, appearance, interactive
moves, `run_action`); every read, commit, edit, zone fill, design rule, netlist import, library placement
and export is. KiPy's own `KiCad(headless=True)` starts whichever `kicad-cli` it finds installed (on macOS
the one in `/Applications` first), in the person's own KiCad settings: start `kicode.executable()` with
`kicode.environment(root)` instead, as above.

## Naming

KiPy's modules are kicode's, under the same names: `kipy.X` is `kicode.X` (`from kicode import KiCad`,
`from kicode.board_types import Track`, `kicode.proto.board.board_types_pb2`). They are KiPy's as it ships,
with its imports renamed (`scripts/vendor_kipy.py`), beside kicode's own:

- `executable()`: the packaged `kicad-cli` (`kicad-cli.exe` on Windows);
- `environment(root)`: what a headless run sets (below);
- `has_schematic()`: whether kicode-sch is installed;
- `stock_data_home()`: the stock data folder a Linux build reads;
- `KICAD_VERSION`, `KICAD_COMMIT`, `KIPY_VERSION`, `KIPY_COMMIT`: what the wheels were built from.

Upstream `kipy` and `kicode` cannot be imported in one process: both register the same protobuf files
(`board/board_types.proto`, …) in protobuf's one default pool, and the second to import fails
(`Couldn't build proto file into descriptor pool: duplicate file name`) unless both were built from the same
KiPy commit. Install one of them. KiPy's `kicad-python-packager` command is not installed;
`python -m kicode.packaging` runs it.

The name is kicode's own, not KiCad's: KiCad is a trademark of the KiCad project, and nothing here implies
its endorsement.

## What the wheels carry

| Platform | Built from | Minimum OS | Wheel tag |
| --- | --- | --- | --- |
| macOS arm64 | KiCad's official nightly DMG: `kicad-cli`, its kifaces, 3D plugins and the libraries they link, thinned to arm64 with KiCad's signatures intact | macOS 14 | `macosx_14_0_arm64` |
| Windows x86_64 | KiCad's official nightly installer: `kicad-cli.exe`, its kifaces, 3D plugins and every DLL of the installer they import | Windows 10 | `win_amd64` |
| Linux x86_64 | A build of the same KiCad commit on Debian 12, against wxWidgets 3.3.3 built from its release, every library it links bundled but glibc | glibc 2.36 (Debian 12, Ubuntu 22.10+, RHEL 10) | `manylinux_2_36_x86_64` |

Every wheel of one version carries one KiCad commit and one KiPy commit. Three of KiCad's kifaces:
pcbnew's in kicode-pcb, eeschema's and cvpcb's in kicode-sch. GerbView's, the drawing sheet editor's and
the calculator's are left out, so `kicad-cli gerber` is not available. No GUI, and none of KiCad's
symbol, footprint or 3D model libraries (over 3 GB): point `KICAD10_FOOTPRINT_DIR`, `KICAD10_SYMBOL_DIR`
and `KICAD10_3DMODEL_DIR` at a copy of them, with library tables in `KICAD_CONFIG_HOME`, when a run needs
them. On Windows, ngspice is not carried (KiCad loads it only to simulate).

The Linux build's wxWidgets has wxWebView without a browser engine: on GTK the only one is WebKitGTK,
which with what it links would add some 65 MB to a wheel, for web pages only KiCad's GUI shows.

## Running it headless

`environment(root)` returns what a run must set, every folder inside `root`:

- `HOME` (and `USERPROFILE`) non-empty, and `TMPDIR` (`TEMP`/`TMP` on Windows);
- `KICAD_CONFIG_HOME`, `KICAD_DOCUMENTS_HOME` and `KICAD_CACHE_HOME`, or KiCad reads and writes the
  person's own;
- on Linux, `KICAD_STOCK_DATA_HOME` (the build looks for its stock data at a compiled-in path) and
  `APPDIR`, KiCad's AppImage variable, by which it finds its kifaces and 3D plugins inside the wheel.

## Versions and where they are published

- Versions are KiCad's. A nightly is `X.99.0.devYYYYMMDD`, the date of KiCad's macOS nightly of its
  commit; the three distributions of one build share it.
- Every day, the newest KiCad nightly that builds and passes on every platform is published as a GitHub
  prerelease (`v10.99.0.dev20261031`), whose page is a find-links index:

  ```bash
  uv pip install "kicode==10.99.0.dev20261031" \
    --find-links https://github.com/earthtojake/kicode/releases/expanded_assets/v10.99.0.dev20261031
  ```

- A nightly that a text-to-cad release pins is promoted to PyPI, the release's own wheels unchanged.

## Building

`.github/workflows/build.yml` builds every platform's wheels of one nightly, smoke-tests them on their own
platform (kicode-pcb alone, then kicode; the Linux wheels also in bare roots of other distributions) and
publishes the release. Dispatched with `pypi`, it uploads a published release's wheels to PyPI.

The scripts run locally too:

- `scripts/resolve_nightly.py`: the nightly of one commit (or the newest) on every platform.
- `scripts/stage_macos.sh <dmg> <arm64|x86_64> <out>`, `scripts/stage_windows.py <installer> <out>`,
  `scripts/build_linux.sh <commit> <out>`: a platform's `kicode/_kicad/` tree, and `schematic/files.txt`,
  what only the schematic kifaces need.
- `scripts/vendor_kipy.py <kicad_python wheel> <out> --commit <sha>`: KiPy's modules into `kicode/`.
- `scripts/kicad_licenses.py <commit> <out>`: KiCad's notices at that commit.
- `scripts/make_wheel.py`: a platform's kicode-pcb and kicode-sch wheels from a staged tree, or (`--meta`)
  kicode's.
- `tests/smoke.py`: run from the environment the wheels are installed into.

## License

KiCad is GPL-3.0-or-later, and so are this repository and the three distributions. KiPy is MIT, and its
licence ships in kicode-pcb's wheel. Each platform wheel ships KiCad's notices from its commit, and on
Linux the copyright file of every library it bundles and wxWidgets' licence. Each release attaches the
corresponding source: KiCad's at the commit, and for the Linux wheels the Debian source package of every
library they bundle and wxWidgets' release tarball.
