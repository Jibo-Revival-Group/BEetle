#!/bin/bash
# Build-time Cygwin only. Users receive these EXEs/DLLs, never an installed shell.
set -euo pipefail
export PATH=/usr/bin:/bin
work=$(cygpath -u "$1")
out="$work/tools"
mkdir -p "$out" "$work/usb-prefix" "$work/ext4-build" "$work/dfu-build" "$work/usb-build"
cd "$work/usb-build"
"$work/libusb-1.0.27/configure" --host=x86_64-w64-mingw32 \
  --prefix="$work/usb-prefix" --enable-shared --disable-static --disable-udev
make -j4
make install
export PKG_CONFIG_PATH="$work/usb-prefix/lib/pkgconfig"
export CPPFLAGS="-I$work/usb-prefix/include -I$work/usb-prefix/include/libusb-1.0"
export LDFLAGS="-L$work/usb-prefix/lib"
cd "$work/dfu-build"
"$work/dfu-util-0.11/configure" --disable-silent-rules
make -j4
cp src/dfu-util.exe "$out/"
cd "$work/entry"
gcc -O2 -Iinclude $CPPFLAGS -DJIBO_LIBUSB_BACKEND=1 -DDFU_STAGE2_ENABLE_LAUNCH=1 \
  exploit/*.c common/sha256.c $LDFLAGS -lusb-1.0 -o "$out/shofel2_t124.exe"
unset CPPFLAGS LDFLAGS PKG_CONFIG_PATH
patch -d "$work/e2fsprogs-1.47.1" -p1 < "$(dirname "$(cygpath -u "$0")")/e2fsprogs-cygwin.patch"
cd "$work/ext4-build"
"$work/e2fsprogs-1.47.1/configure" --enable-libuuid --enable-libblkid \
  --disable-nls --disable-tls --disable-mmp --disable-tdb --disable-elf-shlibs \
  --disable-fuse2fs --without-pthread --without-udev-rules-dir \
  --without-systemd-unit-dir --without-crond-dir
make -j4 libs
make -C debugfs -j4 debugfs
make -C e2fsck -j4 e2fsck
make -C resize -j4 resize2fs
make -C misc -j4 mke2fs dumpe2fs
cp debugfs/debugfs.exe e2fsck/e2fsck.exe resize/resize2fs.exe misc/mke2fs.exe misc/dumpe2fs.exe "$out/"
cp "$work/usb-prefix/bin/libusb-1.0.dll" "$out/"
