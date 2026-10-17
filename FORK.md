# BEetle / 5x1 fork

Forked locally from Paskooter/Jibo-DFU-Mod-Toolkit at
`5d8b1367f29ab0ddbb73f0eaf47f4d5a9da09403` on 2026-10-13. Upstream history and licenses are retained.

The fork adds 5x1 branding and a shared USB-to-SSH setup workflow. Existing
DFU command names, backup formats and loader pins are retained. No upstream
robot assets or payload hashes are changed by rebranding.

The guided wizard sets int-developer mode, Wi-Fi and the IP display. It then
runs the external PM command sequence, selecting the GitHub OOBE version for OOBE robots and normal PM for provisioned robots. PM is maintained in
BEach, downloaded at runtime, and is never embedded in BEetle packages.

`robot-ota-repoint.sh` now forwards to the shared 5x1 setup command; old
Phoenix enrollment options are replaced by the new session-based interface.
The upstream boot diagnostic retains its internal legacy path and pinned assets
for compatibility. It performs no Phoenix enrollment.

Native release adapters are derived from the updated upstream revision
`8f757eedd7cec108508b306b2eb123d5646a354a`. They build BEetle AppImage,
macOS app/DMG and Windows EXE bundles. The Windows EXE additionally carries its
Ubuntu image, WSL and usbipd installers for setup without dependency downloads.
Build instructions and limitations are in [docs/release.md](docs/release.md).
