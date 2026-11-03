#!/usr/bin/env bash
# Stage KiCad's own macOS kicad-cli for one architecture, out of an official nightly or release DMG.
#
#   scripts/stage_macos.sh <kicad.dmg> <arm64|x86_64> <out dir>
#
# <out dir>/kicode/_kicad/Contents/ gets the command line and only what it loads: MacOS/kicad-cli, the
# kifaces and the 3D plugins under PlugIns/, the libraries they link under Frameworks/ (followed through
# @rpath, @loader_path and @executable_path). Three kifaces only: pcbnew's (every pcb command and the API
# server), eeschema's (every sch and sym command) and cvpcb's (which eeschema's netlist work calls on);
# GerbView's, the drawing sheet editor's and the calculator's are left out. No SharedSupport: a run reads
# none of it (DRC, every export, the netlist and the render run the same without it). Every Mach-O is
# thinned to the one architecture with lipo, which keeps each slice's own signature: nothing is re-signed,
# and KiCad's signatures are verified before the script ends. Kept under Contents/MacOS so the system
# still finds PlugIns/ beside it, as in the bundle.
# <out dir>/schematic/files.txt lists the files only the schematic kifaces need (the two kifaces and every
# library nothing else staged links), relative to <out dir>/kicode/: the kicode-sch wheel carries
# them, and the kicode-pcb wheel everything else (make_wheel.py).
# No .app, no crash handler, no GUI binaries. One file of ours: Contents/Info.plist, marking kicad-cli
# background-only, without which macOS puts a Dock icon up for every run (it registers a Cocoa program
# as a foreground app; KiCad's own kicad-cli shows the KiCad icon). kicad-cli's signature binds no
# Info.plist, so every binary's signature stays valid; the folder is no sealed bundle, which macOS only
# asks of a quarantined download (an installed wheel is none).
set -euo pipefail

dmg=$1 arch=$2 out=$3
case "$arch" in arm64|x86_64) ;; *) echo "arch must be arm64 or x86_64" >&2; exit 2 ;; esac

mount=$(mktemp -d)
cleanup() { hdiutil detach -quiet "$mount" 2>/dev/null || true; rmdir "$mount" 2>/dev/null || true; }
trap cleanup EXIT
hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint "$mount" "$dmg"
app="$mount/KiCad/KiCad.app/Contents"
test -x "$app/MacOS/kicad-cli" || { echo "no KiCad.app/Contents/MacOS/kicad-cli in $dmg" >&2; exit 1; }

dest="$out/kicode/_kicad/Contents"
rm -rf "$out/kicode/_kicad" "$out/schematic"
mkdir -p "$dest/MacOS" "$dest/Frameworks" "$dest/PlugIns/3d" "$out/schematic"

# Copy one Mach-O, thinned to $arch (a file with only that slice is copied as it is).
thin() {
    local from=$1 to=$2
    if lipo "$from" -verify_arch "$arch" 2>/dev/null; then
        if [ "$(lipo -archs "$from")" = "$arch" ]; then cp "$from" "$to"; else lipo "$from" -thin "$arch" -output "$to"; fi
    else
        echo "$from has no $arch slice" >&2; exit 1
    fi
}

board=(MacOS/kicad-cli PlugIns/_pcbnew.kiface
       PlugIns/3d/libs3d_plugin_oce.so PlugIns/3d/libs3d_plugin_vrml.so PlugIns/3d/libs3d_plugin_idf.so)
schematic=(PlugIns/_eeschema.kiface PlugIns/_cvpcb.kiface)
for rel in "${board[@]}" "${schematic[@]}"; do thin "$app/$rel" "$dest/$rel"; done

# The libraries a staged Mach-O links: every @rpath/@loader_path/@executable_path name resolves to a file of
# the same name in Frameworks (the bundle's only rpath).
links() {
    otool -L "$dest/$1" | tail -n +2 | awk '{print $1}' | grep -E '^@(rpath|loader_path|executable_path)/' |
        sed 's|.*/|Frameworks/|' || true
}

# Everything the roots load, transitively, copied under the name it is linked by, so the symlinked aliases
# in the bundle are never needed (a wheel holds no symlinks).
queue=("${board[@]}" "${schematic[@]}")
while [ ${#queue[@]} -gt 0 ]; do
    rel=${queue[0]}; queue=("${queue[@]:1}")
    for dep in $(links "$rel"); do
        [ -e "$dest/$dep" ] && continue
        src="$app/$dep"
        test -e "$src" || { echo "$rel links $dep, not in Frameworks" >&2; exit 1; }
        thin "$(cd "$(dirname "$src")" && realpath "$(basename "$src")")" "$dest/$dep"
        queue+=("$dep")
    done
done

# What a set of staged roots loads, transitively, the roots included: one sorted path per line.
closure() {
    local list rel dep
    list=$(mktemp)
    printf '%s\n' "$@" > "$list"
    local queue=("$@")
    while [ ${#queue[@]} -gt 0 ]; do
        rel=${queue[0]}; queue=("${queue[@]:1}")
        for dep in $(links "$rel"); do
            grep -qxF "$dep" "$list" && continue
            echo "$dep" >> "$list"
            queue+=("$dep")
        done
    done
    sort -u "$list"
    rm -f "$list"
}
closure "${board[@]}" > "$out/schematic/board.txt"
closure "${schematic[@]}" > "$out/schematic/all.txt"
comm -13 "$out/schematic/board.txt" "$out/schematic/all.txt" | sed 's|^|_kicad/Contents/|' > "$out/schematic/files.txt"
orphans=$(cd "$dest" && find . -type f | sed 's|^\./||' | sort | comm -23 - <(sort -u "$out/schematic/board.txt" "$out/schematic/all.txt"))
test -z "$orphans" || { echo "staged, but nothing loads: $orphans" >&2; exit 1; }
rm "$out/schematic/board.txt" "$out/schematic/all.txt"

# KiCad's signatures, intact on every thinned binary.
find "$dest" -type f \( -name kicad-cli -o -name '*.dylib' -o -name '*.kiface' -o -name '*.so' \) -print0 |
    xargs -0 -n 1 codesign --verify --strict

# Written after the check: with an Info.plist beside it, codesign also asks the folder for a bundle seal.
cat > "$dest/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>dev.texttocad.kicode</string>
	<key>CFBundleName</key>
	<string>kicad-cli</string>
	<key>CFBundleExecutable</key>
	<string>kicad-cli</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>LSBackgroundOnly</key>
	<true/>
</dict>
</plist>
PLIST
plutil -lint -s "$dest/Info.plist"
echo "staged $(find "$dest" -type f | wc -l | tr -d ' ') files, $(du -sh "$dest" | cut -f1), in $dest;" \
     "schematic only: $(tr '\n' ' ' < "$out/schematic/files.txt")"
