# BEep for computers

BEep for Windows, Mac and Linux (called BEetle until 2.1; this repository keeps that name). It finds Jibo on your network and opens BEacon, his control panel, in the 5x1 look, with BEep's tabs down the side. It can also turn a modded Jibo into a 5x1 Jibo.

- Finds every Jibo with BEacon on your network by itself, and remembers them.
- With one robot, it opens straight into BEacon.
- Add a robot by IP address if it isn't found (Jibo shows his IP in Settings › Wi-Fi).
- All of BEacon: Status, Screen, Photos, People, Reports, Store, Server and Settings.
- Downloads (like Jibo's photos) ask where to save; uploads use your computer's file picker.
- Convert a Jibo to 5x1: for a Jibo that has already been modded, BEep logs in over SSH and runs the 5x1 install, showing its progress. The install keeps going on Jibo even if BEep closes; opening it again picks up where it left off.
- Jibo on USB (home screen): with Jibo in RCM mode and plugged in by USB, **Switch to int-developer** changes his mode and installs the toolkit's Wi-Fi/IP status on his boot screen, without keeping a backup (the var copy the toolkit makes for the boot-screen write is deleted once the write verifies), and **Back up** saves every partition to `Jibo-Backups` in your home folder. Both use the [DFU Mod Toolkit](https://github.com/Jibo-Revival-Group/Jibo-DFU-Mod-Toolkit)'s own code, [dfu-util](https://dfu-util.sourceforge.net/) and ShofEL, built into BEep for each system, so nothing else (like WSL) is needed. Windows asks once to install the signed UsbDk USB driver; Linux asks for your password each time, because USB access needs it.

## Download

Get the file for your computer from the [latest release](https://github.com/Jibo-Revival-Group/BEetle/releases/latest):

- **Windows:** `BEep-…-win-x64.exe` installs BEep; `BEep-…-windows-portable.exe` runs without installing. Windows may say it "protected your PC" because BEep isn't signed: click **More info**, then **Run anyway**.
- **Mac:** `BEep-…-mac-universal.zip` (Apple silicon and Intel). Unzip it and move BEep to Applications. The first time, right-click BEep and choose **Open**, then **Open** again, because it isn't notarized by Apple.
- **Linux:** `BEep-…-linux-x86_64.AppImage`. Make it executable (`chmod +x`) and run it.

Your computer must be on the same network as Jibo, and Jibo needs BEam with BEacon. Updating from BEetle keeps your saved robots; on Windows and Mac you can delete the old BEetle app afterwards.

## Build

```sh
npm ci
npm start          # run it
npm test           # finder and conversion tests (a stand-in SSH Jibo)
npm run dist       # build for this computer into dist/
```

Every push runs the tests and an app check (the real BEacon page from BEam beta, a stand-in robot, a full conversion), then builds Windows, Mac and Linux files on GitHub. Pushing a `v*` tag publishes a release.

The USB helper is `dfu/beep_dfu.py` (tests: `python3 -m unittest discover -s tests -p "test_*.py"`). `build/dfu.py` checks out the toolkit at its pinned commit, builds libusb, dfu-util 0.11 and ShofEL from pinned sources (cross-compiled with MinGW for Windows) and freezes the helper with PyInstaller; CI builds it on each system. The RAM loader's corresponding source is in the toolkit repository.

It uses the phone app's own page scripts: `web/theme.js` (the 5x1 look) and `web/bridge.js` (title, tabs and toolbar buttons). After changing them in BEep, copy them over with `node tools/sync-beep-scripts.js <path to BEep/BEacon.swift>`.

## The old BEetle

Before version 2, this app (then BEetle) was a full USB modding tool built on the DFU Mod Toolkit. That tool has been retired (BEep's USB section reuses its build); its code is kept in the tags `old-beetle-main`, `old-beetle-v2` and `old-beetle-native-windows`.

## License

BEep for computers is free software under the GNU Affero General Public License v3.0, like BEep. See [LICENSE](LICENSE).
