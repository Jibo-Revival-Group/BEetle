# DFU code from the Jibo DFU Mod Toolkit

These files are the [Jibo DFU Mod Toolkit](https://github.com/Jibo-Revival-Group/Jibo-DFU-Mod-Toolkit)
(GPL-3.0, by Paskooter and contributors) at commit `6a50d83346709c90caa9026c3f3d511e76ce5fd7`:
its `jibo_*.py` modules (without the toolkit's own GUI and text menu), the RAM DFU loader
`loader.bin`, and `assets/`. BEetle drives them; see `NOTICE.md` and `THIRD-PARTY-NOTICES.md`.

## BEetle's changes

All of them make the toolkit run natively on Windows, or use the tools BEetle bundles:

- `jibo_dfu.py`
  - `pwd` and `os.geteuid` are optional (Windows has neither).
  - Temporary files use the OS's temp folder instead of `/tmp`.
  - Windows lists USB devices through libusb, like macOS.
  - Bundled tools are used on every OS, with `.exe` names on Windows.
  - Backup locking is skipped on Windows, which has no `fcntl`; BEetle runs one operation at a time.
- `jibo_dfu_bounded.py`: on Windows, libusb uses the UsbDk driver.
- `jibo_images.py`: local paths inside `debugfs` commands are quoted, so folders with spaces work
  (common on Windows). On Windows, paths given to the bundled Cygwin `debugfs` and `e2fsck` use
  short names and forward slashes.

ShofEL and dfu-util get two small patches for Windows; they are in `build/patches/`.
