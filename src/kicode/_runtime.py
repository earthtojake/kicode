"""kicode's own part of the package: the KiCad command line it carries, and how to run it headless.

The wheel carries KiCad's own ``kicad-cli`` and only what it loads, in ``kicode/_kicad/``: on macOS the
binaries out of KiCad's signed app bundle, signatures intact; on Windows what kicad-cli loads out of the
program folder of KiCad's installer; on Linux a build of the same KiCad commit, with every library it
links but glibc. No GUI, no libraries of symbols, footprints or 3D models. KiCad's schematic support
(the eeschema and cvpcb kifaces, and what only they link) is the kicode-sch package, which installs
into the same folder (:func:`has_schematic`). Every other module of the package is KiPy's.

Run it headless with :func:`environment`: KiCad otherwise reads and writes the person's own settings,
libraries and caches.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["environment", "executable", "has_schematic", "stock_data_home"]

_KICAD = Path(__file__).resolve().parent / "_kicad"
# KiCad's own homes, which a headless run keeps inside its own folder (KiCad 10 otherwise still writes
# its documents and cache folders under the person's home).
_HOMES = {"KICAD_CONFIG_HOME": "settings", "KICAD_DOCUMENTS_HOME": "documents", "KICAD_CACHE_HOME": "cache"}


def executable() -> Path:
    """The packaged ``kicad-cli`` (``kicad-cli.exe`` on Windows)."""
    if sys.platform == "darwin":
        path = _KICAD / "Contents" / "MacOS" / "kicad-cli"
    elif sys.platform.startswith("win"):
        path = _KICAD / "bin" / "kicad-cli.exe"
    else:
        path = _KICAD / "usr" / "bin" / "kicad-cli"
    if not path.is_file():
        raise FileNotFoundError(f"kicode has no kicad-cli at {path}: this wheel is not for {sys.platform}")
    return path


def _kiface(name: str) -> Path:
    """Where kicad-cli loads one of its kifaces from (``_eeschema.kiface``; on Windows ``_eeschema.dll``)."""
    if sys.platform == "darwin":
        return _KICAD / "Contents" / "PlugIns" / f"_{name}.kiface"
    if sys.platform.startswith("win"):
        return _KICAD / "bin" / f"_{name}.dll"
    return _KICAD / "usr" / "bin" / f"_{name}.kiface"


def has_schematic() -> bool:
    """Whether KiCad's schematic support is installed (the kicode-sch package, of this version): the
    eeschema kiface, which every ``kicad-cli sch`` and ``sym`` command loads."""
    return _kiface("eeschema").is_file()


def stock_data_home() -> Path | None:
    """The stock data folder this build reads, for ``KICAD_STOCK_DATA_HOME``: a Linux build looks for its
    own at an absolute path compiled in, so it needs this one named; macOS and Windows read none (None)."""
    path = _KICAD / "share" / "kicad"
    return path if path.is_dir() else None


def _appdir() -> Path | None:
    """The Linux build's AppDir, for ``APPDIR``: KiCad's own way of running from a folder it was not
    built for (its AppImage), by which it finds its kifaces in ``usr/bin`` and its 3D plugins in
    ``usr/lib/x86_64-linux-gnu/kicad/plugins``. None on macOS and Windows, which find both beside the
    program."""
    return _KICAD if (_KICAD / "usr" / "bin").is_dir() else None


def environment(root: str | os.PathLike[str]) -> dict[str, str]:
    """The variables a headless run of :func:`executable` sets, every home inside ``root`` (created):
    ``HOME`` and ``TMPDIR`` (``TEMP``/``TMP`` on Windows), ``KICAD_CONFIG_HOME``, ``KICAD_DOCUMENTS_HOME``
    and ``KICAD_CACHE_HOME``, and on Linux ``KICAD_STOCK_DATA_HOME`` and ``APPDIR``. Merge them over the
    environment the run is given."""
    root = Path(root)
    env = {"HOME": str(root / "home")}
    temp = str(root / "tmp")
    if sys.platform.startswith("win"):
        env.update({"USERPROFILE": env["HOME"], "TEMP": temp, "TMP": temp})
    else:
        env["TMPDIR"] = temp
    env.update({name: str(root / folder) for name, folder in _HOMES.items()})
    for name in ("HOME", "KICAD_CONFIG_HOME", "KICAD_DOCUMENTS_HOME", "KICAD_CACHE_HOME"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    Path(temp).mkdir(parents=True, exist_ok=True)
    stock = stock_data_home()
    if stock is not None:
        env["KICAD_STOCK_DATA_HOME"] = str(stock)
    appdir = _appdir()
    if appdir is not None:
        env["APPDIR"] = str(appdir)
    return env
