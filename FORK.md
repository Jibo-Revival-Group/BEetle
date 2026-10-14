# BEetle / 5x1 fork

Forked locally from Paskooter/Jibo-DFU-Mod-Toolkit at
`5d8b1367f29ab0ddbb73f0eaf47f4d5a9da09403` on 2026-10-13. Upstream history and licenses are retained.

The fork adds 5x1 branding and a shared USB-to-SSH setup workflow. Existing
DFU command names, backup formats and loader pins are retained. No upstream
robot assets or payload hashes are changed by rebranding.

BEam bootstrap revision: `25d2b8cbf85b101aad3b2ab537a9c3f5a3b459ae`.
Later updates come from BEaker's checksum-verified OTA catalog.

`robot-ota-repoint.sh` now forwards to the shared 5x1 setup command; old
Phoenix enrollment options are replaced by the new session-based interface.
The upstream boot diagnostic retains its internal legacy path and pinned assets
for compatibility. It performs no Phoenix enrollment.
