#!/bin/bash
# Build the DFU entry helper and dfu-util into this directory.
# The RAM loader (loader.bin) is already vendored; this does not rebuild U-Boot.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build=$here/build
loader_sha=8f46062f2d201824337093a1e4c154e3048c019b147930da35b9d62e00c5e689
shofel_commit=31ac3a260c8a1501869aff6690b3b9ad4904ef58
make=/usr/bin/make

say() { printf 'BEetle DFU: %s\n' "$*"; }
die() { printf 'BEetle DFU: %s\n' "$*" >&2; exit 1; }

[[ -f $here/loader.bin ]] || die "loader.bin is missing from $here"
printf '%s  %s\n' "$loader_sha" "$here/loader.bin" | sha256sum -c -

mkdir -p -- "$build"

if [[ ! -x $here/dfu-util ]]; then
  src=$build/dfu-util
  if [[ ! -f $src/configure.ac && ! -f $src/configure ]]; then
    rm -rf -- "$src"
    say 'Downloading dfu-util.'
    git clone --depth 1 --branch v0.11 https://github.com/dfu-util/dfu-util.git "$src" \
      || git clone --depth 1 https://git.code.sf.net/p/dfu-util/dfu-util "$src"
  fi
  say 'Building dfu-util.'
  (
    cd -- "$src"
    if [[ -f autogen.sh ]]; then ./autogen.sh; fi
    ./configure --prefix="$build/dfu-util-prefix"
    $make -j"$(nproc)"
  )
  cp -a "$src/src/dfu-util" "$here/dfu-util"
  chmod 755 "$here/dfu-util"
fi

shofel_src=$build/ShofEL2-for-T124
if [[ ! -d $shofel_src/.git ]]; then
  say 'Downloading the pinned ShofEL source.'
  rm -rf -- "$shofel_src"
  git clone https://github.com/devsparx/ShofEL2-for-T124.git "$shofel_src"
  git -C "$shofel_src" checkout --detach "$shofel_commit"
fi
if git -C "$shofel_src" apply --reverse --check "$here/shofel2-dfu-entry.patch" >/dev/null 2>&1; then
  say 'ShofEL DFU patch is already applied.'
else
  say 'Applying the ShofEL DFU patch.'
  git -C "$shofel_src" apply --check "$here/shofel2-dfu-entry.patch"
  git -C "$shofel_src" apply "$here/shofel2-dfu-entry.patch"
fi
say 'Building the launch-enabled ShofEL helper.'
$make -B -C "$shofel_src" DFU_STAGE2_ENABLE_LAUNCH=1 all
for file in shofel2_t124 intermezzo.bin dfu_stage2.bin; do
  [[ -s $shofel_src/$file ]] || die "The ShofEL build did not create $file."
  cp -a "$shofel_src/$file" "$here/$file"
done
chmod 755 "$here/shofel2_t124"
capability=$("$here/shofel2_t124" --dfu-stage-capability)
[[ $capability == dfu-stage-launch=1 ]] || die "ShofEL cannot launch the RAM DFU loader ($capability)."
say 'DFU tools are in '"$here"
