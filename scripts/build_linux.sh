#!/usr/bin/env bash
# Build kicad-cli from KiCad's source at one commit, against wxWidgets built from its release tarball, and
# stage it with every library it links but glibc. Run as root in a debian:12 container (the wheels' glibc
# floor is Debian 12's, 2.36):
#
#   scripts/build_linux.sh <commit> <out dir>
#
# <out dir>/kicode/_kicad/ becomes an AppDir, the layout KiCad's AppImage support finds things in once
# APPDIR names it (the package's environment() sets it):
#   usr/bin/kicad-cli and three kifaces (KiCad loads a kiface from beside its program): pcbnew's (every pcb
#     command and the API server), eeschema's (every sch and sym command) and cvpcb's (which eeschema's
#     netlist work calls on); GerbView's, the drawing sheet editor's and the calculator's are not built,
#   usr/lib/ every shared library they link, but glibc's,
#   usr/lib/x86_64-linux-gnu/kicad/plugins/3d/ the 3D model plugins,
#   share/kicad/ the stock data a run reads (KICAD_STOCK_DATA_HOME): the image archive, the project template
#     and the API plugin manager's schema.
# Each ELF is stripped and gets an old-style RPATH (DT_RPATH, which also serves the libraries it loads)
# relative to itself, and none needs a glibc newer than 2.36.
# <out dir>/schematic/files.txt lists, relative to <out dir>/kicode/, the files only the schematic kifaces
# need (the two kifaces and every library nothing else links): the kicode-sch wheel carries them, the
# kicode-pcb wheel the rest (make_wheel.py). The notices of what each carries go to <out dir>/licenses/linux/
# and <out dir>/schematic/licenses/linux/: the Debian copyright file of every bundled library's package,
# and wxWidgets' licence. <out dir>/sources.txt gets the source package and version of every bundled Debian
# library and <out dir>/upstream/ the wxWidgets release tarball, for the release's source mirror
# (scripts/linux_sources.sh).
#
# wxWidgets: KiCad master needs newer than Debian 12's 3.2.2 (eeschema asserts that wxString swaps without
# throwing, which only later releases promise), and KiCad's own macOS and Windows builds use 3.3, so 3.3.3 is
# built here (WX_VERSION and WX_SHA256 to change it): shared GTK 3 libraries with the components KiCad asks
# for, from Debian's own image, compression and expat libraries, into WX_PREFIX (/opt/wxwidgets), with
# ccache. Its wxWebView has no browser engine: on GTK the only one is WebKitGTK, which with GStreamer and the
# codecs it links would add some 65 MB to the wheel for web pages only KiCad's GUI shows. wxWidgets builds
# wxWebView only with an engine, so its two checks of that are relaxed below; wxWebView::New() then returns
# null, which only KiCad's GUI ever calls.
#
# KiCad and wxWidgets are compiled with Debian 12's Clang 19 at -O2. Not GCC 12: GCC 12.2 stops with an
# internal compiler error on pcbnew's constraint solver ("unexpected expression 'BlockRows' of kind
# template_parm_index"). Clang builds against Debian 12's libstdc++, so the libraries the build links are
# Debian 12's still.
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
wx_version=${WX_VERSION:-3.3.3}
wx_sha256=${WX_SHA256:-81b09d6dd9f1ed9301f8c55a968a488d0491f264dc2bab19a7e407ac67009482}
wx_prefix=${WX_PREFIX:-/opt/wxwidgets}
wx_tarball=/tmp/wxWidgets-$wx_version.tar.bz2 wx_src=/tmp/wxWidgets-$wx_version wx_build=/tmp/wx-build
release_flags="-O2 -DNDEBUG"
export DEBIAN_FRONTEND=noninteractive

# KiCad's own dependency list (install-deps.sh at the commit), as Debian 12 names it, without the
# documentation and Python test tools and with wxWidgets' own dependencies in place of Debian's wxWidgets;
# the shader compilers KiCad's render hardware interface needs at build time (glslang-tools, spirv-tools;
# not in install-deps.sh); plus the build's own tools. No Vulkan headers: that backend is optional and a
# command line never draws on a GPU.
apt-get update -q
apt-get install -y -q --no-install-recommends \
    build-essential clang-19 cmake ninja-build pkg-config ccache git ca-certificates curl bzip2 file patchelf python3 \
    libcairo2-dev libpixman-1-dev libpng-dev libjpeg-dev libtiff-dev libwebp-dev libexpat1-dev libpcre2-dev \
    libglu1-mesa-dev libgl1-mesa-dev libegl-dev libx11-dev mesa-common-dev libgtk-3-dev libglm-dev libbz2-dev \
    libssl-dev libzstd-dev zlib1g-dev libocct-modeling-algorithms-dev libocct-modeling-data-dev \
    libocct-data-exchange-dev libocct-visualization-dev libocct-foundation-dev libocct-ocaf-dev libgit2-dev \
    libsecret-1-dev libboost-all-dev libcurl4-openssl-dev libngspice0-dev unixodbc-dev libsqlite3-dev libspnav-dev \
    libnng-dev libprotobuf-dev protobuf-compiler libzint-dev libpoppler-dev libpoppler-glib-dev libwayland-dev \
    libharfbuzz-dev libfreetype-dev libfontconfig-dev shared-mime-info glslang-tools spirv-tools

# wxWidgets, from its release tarball.
mkdir -p "$out/upstream"
if [ ! -f "$out/upstream/wxWidgets-$wx_version.tar.bz2" ]; then
    curl -fsSL --retry 5 -o "$wx_tarball" \
        "https://github.com/wxWidgets/wxWidgets/releases/download/v$wx_version/wxWidgets-$wx_version.tar.bz2"
    mv "$wx_tarball" "$out/upstream/wxWidgets-$wx_version.tar.bz2"
fi
echo "$wx_sha256  $out/upstream/wxWidgets-$wx_version.tar.bz2" | sha256sum -c -
rm -rf "$wx_src"
mkdir -p "$wx_src"
tar xjf "$out/upstream/wxWidgets-$wx_version.tar.bz2" -C "$wx_src" --strip-components 1
python3 - "$wx_src" <<'PY'
# wxWebView without a browser engine: drop the two places wxWidgets turns it off for want of one.
import sys
from pathlib import Path

root = Path(sys.argv[1])
for relative, check in [
    ("build/cmake/init.cmake", r"""            elseif(NOT wxUSE_WEBVIEW_CHROMIUM)
                message(WARNING "webkit or chromium not found or enabled, wxWebview won't be available")
                wx_option_force_value(wxUSE_WEBVIEW OFF)
"""),
    ("include/wx/chkconf.h", r"""#if wxUSE_WEBVIEW && !(wxUSE_WEBVIEW_WEBKIT || wxUSE_WEBVIEW_WEBKIT2 || \
                       wxUSE_WEBVIEW_IE || wxUSE_WEBVIEW_EDGE || \
                       wxUSE_WEBVIEW_CHROMIUM)
#   ifdef wxABORT_ON_CONFIG_ERROR
#       error "wxUSE_WEBVIEW requires at least one backend"
#   else
#       undef wxUSE_WEBVIEW
#       define wxUSE_WEBVIEW 0
#   endif
#endif /* wxUSE_WEBVIEW && !any web view backend */
"""),
]:
    path = root / relative
    text = path.read_text()
    if text.count(check) != 1:
        raise SystemExit(f"{relative}: the wxWebView check to relax is not there once; has wxWidgets changed it?")
    path.write_text(text.replace(check, ""))
    print(f"relaxed {relative}")
PY
cmake -S "$wx_src" -B "$wx_build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$wx_prefix" \
    -DCMAKE_C_FLAGS_RELEASE="$release_flags" -DCMAKE_CXX_FLAGS_RELEASE="$release_flags" \
    -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19 \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DwxBUILD_TOOLKIT=gtk3 -DwxBUILD_SHARED=ON -DwxBUILD_MONOLITHIC=OFF -DwxBUILD_PRECOMP=OFF -DwxBUILD_LOCALES=OFF \
    -DwxBUILD_SAMPLES=OFF -DwxBUILD_TESTS=OFF -DwxBUILD_DEMOS=OFF -DwxBUILD_BENCHMARKS=OFF \
    -DwxUSE_REGEX=sys -DwxUSE_ZLIB=sys -DwxUSE_EXPAT=sys -DwxUSE_LIBJPEG=sys -DwxUSE_LIBPNG=sys -DwxUSE_LIBTIFF=sys \
    -DwxUSE_LIBWEBP=sys -DwxUSE_NANOSVG=builtin -DwxUSE_LUNASVG=OFF \
    -DwxUSE_WEBVIEW=ON -DwxUSE_WEBVIEW_WEBKIT=OFF -DwxUSE_WEBVIEW_CHROMIUM=OFF -DwxUSE_MEDIACTRL=OFF \
    -DwxUSE_LIBNOTIFY=OFF -DwxUSE_LIBSDL=OFF -DwxUSE_LIBMSPACK=OFF -DwxUSE_SPELLCHECK=OFF -DwxUSE_LIBGNOMEVFS=OFF \
    -DwxUSE_GLCANVAS_EGL=OFF
cmake --build "$wx_build"
# Every library wxWidgets links is Debian's, with its copyright file, but the code it builds in (Scintilla
# and Lexilla, NanoSVG), whose notices are staged below.
for builtin in regex zlib expat jpeg png tiff webp lunasvg; do
    if find "$wx_build" -name "libwx${builtin}*" | grep -q .; then echo "wxWidgets built its own $builtin" >&2; exit 1; fi
done
rm -rf "$wx_prefix"
cmake --install "$wx_build"
grep -q "^#define wxUSE_WEBVIEW 1" "$wx_prefix"/lib*/wx/include/gtk3-unicode-*/wx/setup.h ||
    { echo "wxWidgets was configured without wxWebView" >&2; exit 1; }
wx_lib=$(find "$wx_prefix" -name 'libwx_baseu-*.so.*' -printf '%h\n' | head -1)
test -n "$wx_lib" -a -x "$wx_prefix/bin/wx-config" || { echo "no wxWidgets libraries or wx-config in $wx_prefix" >&2; exit 1; }
# The build tree's KiCad binaries find wxWidgets here, as ldd does below.
export LD_LIBRARY_PATH="$wx_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

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

targets=(kicad-cli pcbnew_kiface eeschema_kiface cvpcb_kiface s3d_plugin_oce s3d_plugin_vrml s3d_plugin_idf
         bitmap_archive_build)
cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_C_FLAGS_RELEASE="$release_flags" -DCMAKE_CXX_FLAGS_RELEASE="$release_flags" \
    -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19 \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DwxWidgets_CONFIG_EXECUTABLE="$wx_prefix/bin/wx-config" \
    -DKICAD_BUILD_QA_TESTS=OFF -DKICAD_SPICE_QA=OFF -DKICAD_BUILD_I18N=OFF -DKICAD_UPDATE_CHECK=OFF \
    -DKICAD_USE_SENTRY=OFF -DKICAD_INSTALL_DEMOS=OFF -DKICAD_USE_PCH=OFF
cmake --build "$build" --target "${targets[@]}"
ccache --show-stats || true

kicad="$out/kicode/_kicad"
rm -rf "$kicad" "$out/licenses/linux" "$out/schematic" "$out/sources.txt"
bin="$kicad/usr/bin" lib="$kicad/usr/lib" plugins="$kicad/usr/lib/x86_64-linux-gnu/kicad/plugins/3d"
mkdir -p "$bin" "$lib" "$plugins" "$kicad/share/kicad/resources" "$kicad/share/kicad/template" \
    "$kicad/share/kicad/schemas" "$out/licenses/linux" "$out/schematic/licenses/linux"

cp "$build/kicad/kicad-cli" "$bin/"
for kiface in pcbnew eeschema cvpcb; do cp "$build/$kiface/_$kiface.kiface" "$bin/"; done
find "$build/plugins/3d" -name 'libs3d_plugin_*.so' -exec cp {} "$plugins/" \;
cp "$build/resources/images.tar.gz" "$kicad/share/kicad/resources/"
cp "$src/resources/project_template/kicad.kicad_pro" "$kicad/share/kicad/template/"
cp "$src/api/schemas/api.v1.schema.json" "$kicad/share/kicad/schemas/"
test "$(find "$plugins" -name 'libs3d_plugin_*.so' | wc -l)" -eq 3 || { echo "expected three 3D plugins" >&2; exit 1; }

# glibc's own libraries, the one part of the system the wheels rely on.
is_glibc() {
    case "$1" in
        linux-vdso.so.*|ld-linux*.so.*|libc.so.*|libm.so.*|libmvec.so.*|libpthread.so.*|libdl.so.*|librt.so.*|\
        libresolv.so.*|libutil.so.*|libanl.so.*|libnsl.so.*|libnss_*|libBrokenLocale.so.*|libthread_db.so.*|libcrypt.so.*) return 0 ;;
    esac
    return 1
}

# Every library an ELF loads, transitively, but glibc's, as the build machine resolves it (ldd follows the
# build tree's RUNPATH to KiCad's own libraries, and LD_LIBRARY_PATH to wxWidgets'): "name path" per line.
needs() {
    ldd "$1" | awk '/=>/ {print $1, $3}' | while read -r name path; do
        is_glibc "$name" || echo "$name $path"
    done
}
for elf in "$bin"/* "$plugins"/*; do
    if ldd "$elf" | grep -q "not found"; then echo "$elf links what is not found:" >&2; ldd "$elf" | grep "not found" >&2; exit 1; fi
done
work=$(mktemp -d)
for elf in "$bin/kicad-cli" "$bin/_pcbnew.kiface" "$plugins"/*; do needs "$elf"; done | sort -u > "$work/board"
for elf in "$bin/_eeschema.kiface" "$bin/_cvpcb.kiface"; do needs "$elf"; done | sort -u > "$work/schematic"
sort -u "$work/board" "$work/schematic" | while read -r name path; do cp -L "$path" "$lib/$name"; done
cut -d' ' -f1 "$work/board" | sort -u > "$work/board.names"
cut -d' ' -f1 "$work/schematic" | sort -u | comm -23 - "$work/board.names" > "$work/schematic.names"
{ echo "_kicad/usr/bin/_eeschema.kiface"; echo "_kicad/usr/bin/_cvpcb.kiface"; sed 's|^|_kicad/usr/lib/|' "$work/schematic.names"
} > "$out/schematic/files.txt"

# Smaller and relocatable: KiCad's and wxWidgets' binaries stripped (Debian's come stripped), every RPATH relative.
for elf in "$bin"/* "$plugins"/* "$lib"/*; do
    file -b "$elf" | grep -q ELF || continue
    chmod u+w "$elf"
    strip --strip-unneeded "$elf" 2>/dev/null || true
done
for elf in "$bin"/*; do file -b "$elf" | grep -q ELF && patchelf --force-rpath --set-rpath '$ORIGIN/../lib' "$elf"; done
for elf in "$lib"/*; do [ -f "$elf" ] || continue; patchelf --force-rpath --set-rpath '$ORIGIN' "$elf"; done  # the plugins' folder too
for elf in "$plugins"/*; do patchelf --force-rpath --set-rpath '$ORIGIN/../../../..' "$elf"; done

# The glibc floor: no staged ELF may need a symbol version newer than Debian 12's glibc, 2.36. ($lib holds
# the plugins' folder too: only its files are ELFs.)
for elf in "$bin"/* "$plugins"/* "$lib"/*; do
    [ -f "$elf" ] || continue
    objdump -T "$elf" || { echo "objdump cannot read $elf" >&2; exit 1; }
done > "$work/symbols"
newest=$(grep -o 'GLIBC_2\.[0-9][0-9.]*' "$work/symbols" | sed 's/GLIBC_//' | sort -u -V | tail -1)
test -n "$newest" || { echo "no staged ELF names a glibc version" >&2; exit 1; }
if [ "$(printf '%s\n2.36\n' "$newest" | sort -V | tail -1)" != "2.36" ]; then
    echo "a staged library needs glibc $newest, newer than 2.36" >&2; exit 1
fi
echo "the newest glibc any staged ELF needs: $newest"

# Each bundled library's notice: a Debian package's copyright file (and its source package for the mirror),
# wxWidgets' licence and the notices of the code it builds in; KiCad's own are covered by KiCad's notices.
wx_notices() {
    mkdir -p "$1/wxwidgets"
    for doc in licence.txt licendoc.txt lgpl.txt gpl.txt preamble.txt; do cp "$wx_src/docs/$doc" "$1/wxwidgets/"; done
    cp "$wx_src/src/stc/scintilla/License.txt" "$1/wxwidgets/scintilla-License.txt"
    cp "$wx_src/src/stc/lexilla/License.txt" "$1/wxwidgets/lexilla-License.txt"
    cp "$wx_src/3rdparty/nanosvg/LICENSE.txt" "$1/wxwidgets/nanosvg-LICENSE.txt"
}
: > "$work/packages"
for side in board schematic; do
    if [ "$side" = board ]; then names="$work/board.names" notices="$out/licenses/linux"
    else names="$work/schematic.names" notices="$out/schematic/licenses/linux"; fi
    while read -r name; do
        owner=$(dpkg -S "*/$name" 2>/dev/null | head -1 | cut -d: -f1) || true
        if [ -n "$owner" ]; then
            doc="/usr/share/doc/$owner/copyright"
            test -f "$doc" || { echo "$owner, which ships $name, has no copyright file" >&2; exit 1; }
            cp "$doc" "$notices/$owner.copyright"
            echo "$owner" >> "$work/packages"
        else
            case "$name" in
                libkicommon.so*|libkigal.so*|libkiapi.so*|libkicad_3dsg.so*|libkicad_3d_import.so*) ;;
                libwx_*) [ -d "$notices/wxwidgets" ] || wx_notices "$notices" ;;
                *) echo "$name is neither Debian's, KiCad's nor wxWidgets': whose notice covers it?" >&2; exit 1 ;;
            esac
        fi
    done < "$names"
done
sort -u "$work/packages" | while read -r package; do
    dpkg-query -W -f '${source:Package} ${source:Version}\n' "$package"
done | sort -u > "$out/sources.txt"

for side in board schematic; do
    file=$([ "$side" = board ] && echo "$work/board.names" || echo "$work/schematic.names")
    echo "$side: $(wc -l < "$file") libraries"
done
echo "staged $(find "$kicad" -type f | wc -l) files, $(du -sh "$kicad" | cut -f1), from $(sort -u "$work/packages" | wc -l)" \
     "Debian packages ($(wc -l < "$out/sources.txt") sources) in $kicad; schematic only: $(tr '\n' ' ' < "$out/schematic/files.txt")"
rm -rf "$work"
