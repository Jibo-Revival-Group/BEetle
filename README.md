# BEetle

BEep for your computer. BEetle finds Jibo on your network and opens BEacon, his control panel, in the 5x1 look, with BEep's tabs down the side. It can also turn a modded Jibo into a 5x1 Jibo.

- Finds every Jibo with BEacon on your network by itself, and remembers them.
- With one robot, it opens straight into BEacon.
- Add a robot by IP address if it isn't found (Jibo shows his IP in Settings › Wi-Fi).
- All of BEacon: Status, Screen, Photos, People, Reports, Store, Server and Settings.
- Downloads (like Jibo's photos) ask where to save; uploads use your computer's file picker.
- Convert a Jibo to 5x1: for a Jibo that has already been modded, BEetle logs in over SSH and runs the 5x1 install, showing its progress. The install keeps going on Jibo even if BEetle closes; opening it again picks up where it left off.

## Download

Get the file for your computer from the [latest release](https://github.com/Jibo-Revival-Group/BEetle/releases/latest):

- **Windows:** `BEetle-…-win-x64.exe` installs BEetle; `BEetle-…-windows-portable.exe` runs without installing. Windows may say it "protected your PC" because BEetle isn't signed: click **More info**, then **Run anyway**.
- **Mac:** `BEetle-…-mac-universal.zip` (Apple silicon and Intel). Unzip it and move BEetle to Applications. The first time, right-click BEetle and choose **Open**, then **Open** again, because it isn't notarized by Apple.
- **Linux:** `BEetle-…-linux-x86_64.AppImage`. Make it executable (`chmod +x`) and run it.

Your computer must be on the same network as Jibo, and Jibo needs BEam with BEacon.

## Build

```sh
npm ci
npm start          # run it
npm test           # finder and conversion tests (a stand-in SSH Jibo)
npm run dist       # build for this computer into dist/
```

Every push runs the tests and an app check (the real BEacon page from BEam beta, a stand-in robot, a full conversion), then builds Windows, Mac and Linux files on GitHub. Pushing a `v*` tag publishes a release.

BEetle uses BEep's own page scripts: `web/theme.js` (the 5x1 look) and `web/bridge.js` (title, tabs and toolbar buttons). After changing them in BEep, copy them over with `node tools/sync-beep-scripts.js <path to BEep/BEacon.swift>`.

## The old BEetle

Before version 2, BEetle was a USB modding tool built on the DFU Mod Toolkit. It has been retired; its code is kept in the tags `old-beetle-main`, `old-beetle-v2` and `old-beetle-native-windows`.

## License

BEetle is free software under the GNU Affero General Public License v3.0, like BEep. See [LICENSE](LICENSE).
