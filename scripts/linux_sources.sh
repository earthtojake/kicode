#!/usr/bin/env bash
# Download the Debian source package of every library the Linux wheel bundles, for the release's source
# mirror (GPL-3.0 section 6). Run as root in the debian:12 container build_linux.sh ran in:
#
#   scripts/linux_sources.sh <sources.txt from build_linux.sh> <out.tar>
#
# Each line of sources.txt is "<source package> <version>"; the exact versions the bundled libraries
# came from are fetched (apt-get source --download-only) and written into one tar.
set -euo pipefail

list=$(realpath "$1") out=$(realpath -m "$2")
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
tar cf "$out" -C "$work" .
echo "wrote $out: $(wc -l < "$list") source packages, $(du -h "$out" | cut -f1)"
