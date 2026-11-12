# BEetle

BEetle mods your Jibo for [5x1](https://www.5x1.com) by plugging him in and clicking Next.

You enter your Wi-Fi details and choose whether to back Jibo up. BEetle does the rest:

1. You plug Jibo into your computer in RCM mode. BEetle shows you how.
2. BEetle puts Jibo into DFU mode.
3. You choose whether to back Jibo up, and enter your Wi-Fi.
4. If you chose a backup, BEetle saves one to the `Jibo-Backups` folder in your home folder.
5. BEetle switches Jibo to int-developer mode, saves your Wi-Fi, and installs the Wi-Fi screen
   patch, which shows Jibo's Wi-Fi status and IP address while he starts up.
6. You restart Jibo and type in the IP address on his screen.
7. BEetle runs 5x1's PM script on Jibo.

## Download

Get the file for your computer from [Releases](https://github.com/Jibo-Revival-Group/BEetle/releases):

- **Windows:** `BEetle.exe`. If SmartScreen appears, click **More info**, then **Run anyway**.
  The first time, BEetle installs a small USB driver ([UsbDk](https://github.com/daynix/UsbDk), by Red Hat);
  choose **Yes** when Windows asks.
- **Mac:** `BEetle-macOS-arm64.app.zip` (Apple silicon) or `BEetle-macOS-x86_64.app.zip` (Intel).
  Unzip it and open BEetle. If macOS blocks it, open **System Settings**, then **Privacy & Security**,
  then **Open Anyway**.
- **Linux:** `BEetle-x86_64.AppImage`. Make it executable (`chmod +x`), then open it and approve the
  administrator prompt, which BEetle needs for USB.

## How it works

The DFU work (RCM to DFU, backups, mode, Wi-Fi and the Wi-Fi screen patch) is the
[Jibo DFU Mod Toolkit](https://github.com/Jibo-Revival-Group/Jibo-DFU-Mod-Toolkit)'s own code, in `dfu/`.
BEetle's part is the window (`beetle/app.py`), the order of the steps (`beetle/flow.py`), and running PM over
SSH the same way BEep does (`beetle/pm.py`).

## Build

GitHub Actions builds all three apps (`.github/workflows/build.yml`); `build/build.py` holds the steps.
Each app bundles its own dfu-util, e2fsprogs (`debugfs`, `e2fsck`), libusb and ShofEL host, built from the
pinned sources listed in `build/build.py`. On Windows, `debugfs` and `e2fsck` come from Cygwin.

Run the tests with `python -m unittest discover -s tests -t .` (the window test needs a display).

## License

GPL-3.0, like the DFU Mod Toolkit it is built on. See `LICENSE` and `dfu/NOTICE.md`.
