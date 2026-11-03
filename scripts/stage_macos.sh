#!/usr/bin/env bash
# Stage KiCad's own macOS kicad-cli for one architecture, out of an official nightly or release DMG.
#
#   scripts/stage_macos.sh <kicad.dmg> <arm64|x86_64> <out dir>
#
# <out dir>/kicad_cli_bin/kicad/Contents/ gets the command line and only what it loads: MacOS/kicad-cli,
# the kifaces and the 3D plugins under PlugIns/, the libraries they link under Frameworks/ (followed
# through @rpath, @loader_path and @executable_path). No SharedSupport: a run reads none of it (DRC,
# every export, the netlist and the render run the same without it). Every Mach-O is thinned to the one
# architecture with lipo, which keeps each slice's own signature: nothing is re-signed, and KiCad's
# signatures are verified before the script ends. Kept under Contents/MacOS so the system still finds
# PlugIns/ beside it, as in the bundle.
# No .app, no Info.plist (kicad-cli's signature binds none), no crash handler, no GUI binaries.
set -euo pipefail

dmg=$1 arch=$2 out=$3
case "$arch" in arm64|x86_64) ;; *) echo "arch must be arm64 or x86_64" >&2; exit 2 ;; esac

mount=$(mktemp -d)
cleanup() { hdiutil detach -quiet "$mount" 2>/dev/null || true; rmdir "$mount" 2>/dev/null || true; }
trap cleanup EXIT
hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint "$mount" "$dmg"
app="$mount/KiCad/KiCad.app/Contents"
test -x "$app/MacOS/kicad-cli" || { echo "no KiCad.app/Contents/MacOS/kicad-cli in $dmg" >&2; exit 1; }

dest="$out/kicad_cli_bin/kicad/Contents"
rm -rf "$out/kicad_cli_bin/kicad"
mkdir -p "$dest/MacOS" "$dest/Frameworks" "$dest/PlugIns/3d"

# Copy one Mach-O, thinned to $arch (a file with only that slice is copied as it is).
thin() {
    local from=$1 to=$2
    if lipo "$from" -verify_arch "$arch" 2>/dev/null; then
        if [ "$(lipo -archs "$from")" = "$arch" ]; then cp "$from" "$to"; else lipo "$from" -thin "$arch" -output "$to"; fi
    else
        echo "$from has no $arch slice" >&2; exit 1
    fi
}

# Every kiface: kicad-cli loads them by subcommand (sch export netlist loads cvpcb's, gerber gerbview's).
roots=(MacOS/kicad-cli PlugIns/_pcbnew.kiface PlugIns/_eeschema.kiface PlugIns/_cvpcb.kiface
       PlugIns/_gerbview.kiface PlugIns/_pl_editor.kiface PlugIns/_pcb_calculator.kiface
       PlugIns/3d/libs3d_plugin_oce.so PlugIns/3d/libs3d_plugin_vrml.so PlugIns/3d/libs3d_plugin_idf.so)
for rel in "${roots[@]}"; do thin "$app/$rel" "$dest/$rel"; done

# The libraries they link, transitively: every @rpath/@loader_path/@executable_path name resolves to a
# file of the same name in Frameworks (the bundle's only rpath). Copied under the name they are linked
# by, so the symlinked aliases in the bundle are never needed (a wheel holds no symlinks).
queue=("${roots[@]}")
while [ ${#queue[@]} -gt 0 ]; do
    rel=${queue[0]}; queue=("${queue[@]:1}")
    while read -r dep; do
        name=${dep##*/}
        [ -e "$dest/Frameworks/$name" ] && continue
        src="$app/Frameworks/$name"
        test -e "$src" || { echo "$rel links $dep, not in Frameworks" >&2; exit 1; }
        thin "$(cd "$(dirname "$src")" && realpath "$name")" "$dest/Frameworks/$name"
        queue+=("Frameworks/$name")
    done < <(otool -arch "$arch" -L "$dest/$rel" | tail -n +2 | awk '{print $1}' | grep -E '^@(rpath|loader_path|executable_path)/' || true)
done

# KiCad's signatures, intact on every thinned binary.
find "$dest" -type f \( -name kicad-cli -o -name '*.dylib' -o -name '*.kiface' -o -name '*.so' \) -print0 |
    xargs -0 -n 1 codesign --verify --strict
echo "staged $(find "$dest" -type f | wc -l | tr -d ' ') files, $(du -sh "$dest" | cut -f1), in $dest"
