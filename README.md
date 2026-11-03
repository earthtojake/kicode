# kicad-cli-bin

`kicad-cli`, [KiCad](https://www.kicad.org)'s command line, as a Python wheel: one install puts a
headless `kicad-cli` in an environment, with nothing else of KiCad's installed and nothing of the
person's touched. It exists for [text-to-cad](https://github.com/earthtojake/text-to-cad), whose
`cad[kicad]` pins one build of it, and works for anything that runs `kicad-cli` from Python.

This is an unofficial repackaging. It is not made or endorsed by the KiCad project.

```python
import subprocess, kicad_cli_bin

env = kicad_cli_bin.environment("/tmp/kicad-run")   # private homes; merge over os.environ
subprocess.run([kicad_cli_bin.executable(), "pcb", "drc", "board.kicad_pcb"], env={**os.environ, **env})
```

`python -m kicad_cli_bin` prints the executable's path; `python -m kicad_cli_bin <args>` runs it headless.

## What a wheel carries

| Platform | Built from | Minimum OS | Wheel tag |
| --- | --- | --- | --- |
| macOS arm64 | KiCad's official nightly DMG: `kicad-cli`, its kifaces, 3D plugins and the libraries they link, thinned to arm64 with KiCad's signatures intact | macOS 14 | `macosx_14_0_arm64` |
| Windows x86_64 | KiCad's official nightly installer: `kicad-cli.exe` and its program folder | Windows 10 | `win_amd64` |
| Linux x86_64 | A build of the same KiCad commit on Debian 12, every library it links bundled but glibc | glibc 2.36 (Debian 12, Ubuntu 22.10+, RHEL 10) | `manylinux_2_36_x86_64` |

Every wheel of one version carries one KiCad commit. No GUI, and none of KiCad's symbol, footprint or
3D model libraries (over 3 GB): point `KICAD10_FOOTPRINT_DIR`, `KICAD10_SYMBOL_DIR` and
`KICAD10_3DMODEL_DIR` at a copy of them, with library tables in `KICAD_CONFIG_HOME`, when a run needs
them.

## Running it headless

`environment(root)` returns what a run must set, every folder inside `root`:

- `HOME` (and `USERPROFILE`) non-empty, and `TMPDIR` (`TEMP`/`TMP` on Windows);
- `KICAD_CONFIG_HOME`, `KICAD_DOCUMENTS_HOME` and `KICAD_CACHE_HOME`, or KiCad reads and writes the
  person's own;
- on Linux, `KICAD_STOCK_DATA_HOME` (the build looks for its stock data at a compiled-in path) and
  `APPDIR`, KiCad's AppImage variable, by which it finds its kifaces and 3D plugins inside the wheel.

`kicad-cli api-server --socket <path> <board>` serves KiCad's IPC API headless, for
[kicad-python](https://gitlab.com/kicad/code/kicad-python) (kipy). Editor state is not available
headless (selection, active and visible layers, appearance, interactive moves, `run_action`); every
read, commit, edit, zone fill, design rule, netlist import, library placement and export is.

## Versions and where they are published

- Versions are KiCad's, with `.postN` for a repackaging fix: `10.0.8`, `10.0.8.post1`.
- Nightlies are `X.99.0.devYYYYMMDD`, the date of KiCad's macOS nightly of that commit, published as
  GitHub Releases (`v10.99.0.dev20261031`). Install one with its release as a find-links page:

  ```bash
  uv pip install "kicad-cli-bin==10.99.0.dev20261031" \
    --find-links https://github.com/earthtojake/kicad-cli-bin/releases/expanded_assets/v10.99.0.dev20261031
  ```

- Stable releases go to PyPI.

## Building

`.github/workflows/build.yml` builds every platform's wheel of one nightly, smoke-tests each on its own
platform (and the Linux wheel in a bare Debian 12 root), and publishes the release. Dispatch it with a
KiCad commit, or none for the newest nightly KiCad has published for both macOS and Windows.

The scripts run locally too:

- `scripts/resolve_nightly.py`: the nightly of one commit (or the newest) on every platform.
- `scripts/stage_macos.sh <dmg> <arm64|x86_64> <out>`, `scripts/stage_windows.py <installer> <out>`,
  `scripts/build_linux.sh <commit> <out>`: a platform's `kicad_cli_bin/kicad/` tree.
- `scripts/kicad_licenses.py <commit> <out>`: KiCad's notices at that commit.
- `scripts/make_wheel.py`: the wheel from a staged tree.
- `tests/smoke.py`: run from the environment a wheel is installed into.

## License

KiCad is GPL-3.0-or-later, and so is this repository and every wheel. Each wheel ships KiCad's notices
from its commit. Each release attaches the corresponding source: KiCad's source at the commit, and for
the Linux wheel the Debian source package of every library it bundles.

KiCad is a trademark of the KiCad project; this package's name says what it carries and implies no
endorsement.
