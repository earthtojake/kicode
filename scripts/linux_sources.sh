#!/usr/bin/env bash
# Gather the source of every library the Linux wheels bundle, for the release's source mirror (GPL-3.0
# section 6): the Debian source package of each of Debian's, and the upstream tarballs build_linux.sh built
# from (wxWidgets'). Run as root in the debian:12 container build_linux.sh ran in:
#
#   scripts/linux_sources.sh <sources.txt from build_linux.sh> <out.tar> [upstream tarball...]
#
# Each line of sources.txt is "<source package> <version>"; the exact versions the bundled libraries
# came from are fetched (apt-get source --download-only) and written into one tar, with each upstream
# tarball beside them.
set -euo pipefail

list=$(realpath "$1") out=$(realpath -m "$2")
shift 2
upstream=()
for tarball in "$@"; do upstream+=("$(realpath "$tarball")"); done
export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources
apt-get update -q
apt-get install -y -q --no-install-recommends dpkg-dev

work=$(mktemp -d)
cd "$work"
while read -r package version; do
    # A binary package's source version can carry the binary's own rebuild suffix ("1.2-3+b1"):
    # the source is the version before it.
    apt-get source --download-only -q "${package}=${version%+b[0-9]*}"
done < "$list"
for tarball in ${upstream[@]+"${upstream[@]}"}; do cp "$tarball" "$work/"; done
mkdir -p "$(dirname "$out")"
tar cf "$out" -C "$work" .
echo "wrote $out: $(wc -l < "$list") Debian source packages and ${#upstream[@]} upstream tarballs, $(du -h "$out" | cut -f1)"
