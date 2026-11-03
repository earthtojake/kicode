#!/usr/bin/env bash
# Build kicad-cli from KiCad's source at one commit and stage it, with every library it links but glibc.
# Run as root in a debian:12 container (the wheel's glibc floor is Debian 12's, 2.36):
#
#   scripts/build_linux.sh <commit> <out dir>
#
# <out dir>/kicad_cli_bin/kicad/ becomes an AppDir, the layout KiCad's AppImage support finds things in
# once APPDIR names it (the package's environment() sets it):
#   usr/bin/kicad-cli and the six kifaces (KiCad loads a kiface from beside its program),
#   usr/lib/ every shared library they link, but glibc's,
#   usr/lib/x86_64-linux-gnu/kicad/plugins/3d/ the 3D model plugins,
#   share/kicad/ the stock data a run reads (KICAD_STOCK_DATA_HOME): the image archive and the project template.
# Each ELF gets an old-style RPATH (DT_RPATH, which also serves the libraries it loads) relative to itself.
# <out dir>/licenses/ gets the Debian copyright file of every bundled library's package, and
# <out dir>/sources.txt the source package and version of each, for the release's source mirror
# (scripts/linux_sources.sh downloads them).
#
# KICAD_FULL_VERSION (10.99.0-6189-g113c71d59d, as KiCad's own builds of the commit name themselves) stamps
# the build, which a tarball has no git history to work out. KICAD_SRC (a checkout or unpacked tarball of
# the commit) and KICAD_BUILD (a build folder kept between runs, with CCACHE_DIR, to rebuild faster) are
# optional.
set -euo pipefail

commit=$1
out=$(realpath -m "$2")
src=${KICAD_SRC:-/tmp/kicad-src}
build=${KICAD_BUILD:-/tmp/kicad-build}
export DEBIAN_FRONTEND=noninteractive

# KiCad's own dependency list (install-deps.sh at the commit), as Debian 12 names it, without the
# documentation and Python test tools; the shader compilers its render hardware interface needs at build
# time (glslang-tools, spirv-tools; not in install-deps.sh); plus the build's own tools. No Vulkan headers:
# that backend is optional and a command line never draws on a GPU.
apt-get update -q
apt-get install -y -q --no-install-recommends \
    build-essential clang-19 cmake ninja-build pkg-config ccache git ca-certificates curl file patchelf python3 \
    libcairo2-dev libpixman-1-dev libpng-dev libglu1-mesa-dev libgl1-mesa-dev libegl-dev libx11-dev \
    mesa-common-dev libgtk-3-dev libglm-dev libwxgtk3.2-dev libwxgtk-webview3.2-dev libbz2-dev libssl-dev \
    libzstd-dev zlib1g-dev libocct-modeling-algorithms-dev libocct-modeling-data-dev libocct-data-exchange-dev \
    libocct-visualization-dev libocct-foundation-dev libocct-ocaf-dev libgit2-dev libsecret-1-dev \
    libboost-all-dev libcurl4-openssl-dev libngspice0-dev unixodbc-dev libsqlite3-dev libspnav-dev libnng-dev \
    libprotobuf-dev protobuf-compiler libzint-dev libpoppler-dev libpoppler-glib-dev libwayland-dev \
    libharfbuzz-dev libfreetype-dev libfontconfig-dev shared-mime-info glslang-tools spirv-tools

if [ ! -f "$src/CMakeLists.txt" ]; then
    mkdir -p "$src"
    curl -fsSL "https://gitlab.com/kicad/code/kicad/-/archive/$commit/kicad-$commit.tar.gz" |
        tar xz -C "$src" --strip-components 1
fi

if [ -n "${KICAD_FULL_VERSION:-}" ]; then
    sed -i "s/^set( KICAD_SEMANTIC_VERSION \".*\" )/set( KICAD_SEMANTIC_VERSION \"$KICAD_FULL_VERSION\" )/" \
        "$src/cmake/KiCadVersion.cmake"
    grep -q "\"$KICAD_FULL_VERSION\"" "$src/cmake/KiCadVersion.cmake"
fi

targets=(kicad-cli pcbnew_kiface eeschema_kiface cvpcb_kiface gerbview_kiface pl_editor_kiface
         pcb_calculator_kiface s3d_plugin_oce s3d_plugin_vrml s3d_plugin_idf bitmap_archive_build)
# Clang, not Debian 12's GCC 12: GCC 12.2 stops with an internal compiler error on pcbnew's constraint
# solver ("unexpected expression 'BlockRows' of kind template_parm_index"). Clang 19 is Debian 12's own
# package and builds against its libstdc++, so the libraries the build links are Debian 12's still.
cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19 \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DKICAD_BUILD_QA_TESTS=OFF -DKICAD_SPICE_QA=OFF -DKICAD_BUILD_I18N=OFF -DKICAD_UPDATE_CHECK=OFF \
    -DKICAD_USE_SENTRY=OFF -DKICAD_INSTALL_DEMOS=OFF -DKICAD_USE_PCH=OFF
cmake --build "$build" --target "${targets[@]}"
ccache --show-stats || true

kicad="$out/kicad_cli_bin/kicad"
rm -rf "$kicad" "$out/licenses" "$out/sources.txt"
bin="$kicad/usr/bin" lib="$kicad/usr/lib" plugins="$kicad/usr/lib/x86_64-linux-gnu/kicad/plugins/3d"
mkdir -p "$bin" "$lib" "$plugins" "$kicad/share/kicad/resources" "$kicad/share/kicad/template" "$out/licenses"

cp "$build/kicad/kicad-cli" "$bin/"
find "$build" -name '_*.kiface' -exec cp {} "$bin/" \;
find "$build/plugins/3d" -name 'libs3d_plugin_*.so' -exec cp {} "$plugins/" \;
cp "$build/resources/images.tar.gz" "$kicad/share/kicad/resources/"
cp "$src/resources/project_template/kicad.kicad_pro" "$kicad/share/kicad/template/"
test "$(find "$bin" -name '_*.kiface' | wc -l)" -eq 6 || { echo "expected six kifaces" >&2; exit 1; }

# glibc's own libraries, the one part of the system the wheel relies on.
is_glibc() {
    case "$1" in
        linux-vdso.so.*|ld-linux*.so.*|libc.so.*|libm.so.*|libmvec.so.*|libpthread.so.*|libdl.so.*|librt.so.*|\
        libresolv.so.*|libutil.so.*|libanl.so.*|libnsl.so.*|libnss_*|libBrokenLocale.so.*|libthread_db.so.*|libcrypt.so.*) return 0 ;;
    esac
    return 1
}

# Everything they link, transitively, resolved as the build machine resolves it (ldd follows the build
# tree's RUNPATH to KiCad's own libraries).
queue=("$bin"/* "$plugins"/*)
declare -A seen
while [ ${#queue[@]} -gt 0 ]; do
    elf=${queue[0]}; queue=("${queue[@]:1}")
    file -b "$elf" | grep -q ELF || continue
    while read -r name path; do
        is_glibc "$name" && continue
        [ -n "${seen[$name]:-}" ] && continue
        seen[$name]=1
        if [ "$path" = "not" ]; then echo "$elf links $name, which is not found" >&2; exit 1; fi
        cp -L "$path" "$lib/$name"
        queue+=("$lib/$name")
    done < <(ldd "$elf" | awk '/=>/ {print $1, $3}')
done

# Smaller and relocatable: KiCad's own binaries stripped (Debian's come stripped), every RPATH relative.
for elf in "$bin"/* "$plugins"/* "$lib"/*; do
    file -b "$elf" | grep -q ELF || continue
    chmod u+w "$elf"
    strip --strip-unneeded "$elf" 2>/dev/null || true
done
for elf in "$bin"/*; do file -b "$elf" | grep -q ELF && patchelf --force-rpath --set-rpath '$ORIGIN/../lib' "$elf"; done
for elf in "$lib"/*; do patchelf --force-rpath --set-rpath '$ORIGIN' "$elf"; done
for elf in "$plugins"/*; do patchelf --force-rpath --set-rpath '$ORIGIN/../../../..' "$elf"; done

# Each bundled library's Debian package: its copyright file, and its source package for the mirror.
for so in "$lib"/*; do
    name=$(basename "$so")
    owner=$(dpkg -S "*/$name" 2>/dev/null | head -1 | cut -d: -f1) || true
    if [ -z "$owner" ]; then
        # One of KiCad's own (libkicommon, libkigal, libkiapi, libkicad_3dsg): KiCad's notices cover it.
        continue
    fi
    echo "$owner"
done | sort -u > "$out/packages.txt"
while read -r package; do
    doc="/usr/share/doc/${package}/copyright"
    [ -f "$doc" ] && cp "$doc" "$out/licenses/${package}.copyright"
    dpkg-query -W -f '${source:Package} ${source:Version}\n' "$package"
done < "$out/packages.txt" | sort -u > "$out/sources.txt"

echo "staged $(find "$kicad" -type f | wc -l) files, $(du -sh "$kicad" | cut -f1), from $(wc -l < "$out/packages.txt") packages ($(wc -l < "$out/sources.txt") sources) in $kicad"
