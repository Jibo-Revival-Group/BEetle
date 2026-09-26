# DFU pieces

`loader.bin` is the pinned Jibo RAM DFU loader from [Jibo-DFU-Mod-Toolkit](https://github.com/Paskooter/Jibo-DFU-Mod-Toolkit). SHA-256 `8f46062f2d201824337093a1e4c154e3048c019b147930da35b9d62e00c5e689`, 415088 bytes.

It is a U-Boot 2016.05 image (GPL-2.0-or-later). The corresponding source, patch, and license texts are in that toolkit's `vendor/jibo-ram-dfu-v1-source.tar.gz`. A copy of its notice is `UBOOT-NOTICE.md`.

`bounded.py` is the toolkit's read-only GPT marker reader. `shofel2-dfu-entry.patch` is its ShofEL entry patch. `build.sh` compiles `dfu-util`, `shofel2_t124`, `intermezzo.bin`, and `dfu_stage2.bin` into this directory.

The loader's RAM profile is the Meerkat Rev02 profile the toolkit verified. BEetle passes that confirmation when it starts DFU.
