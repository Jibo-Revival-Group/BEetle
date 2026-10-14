# Set up with 5x1

BEetle prepares Jibo over USB and completes installation over Wi-Fi/SSH. It
uses hosted BEefy and BEaker without Phoenix enrollment or an account portal.
OOBE robots finish in normal mode with BEam; the original app/QR setup is bypassed.

## Start

Use `BEetle.desktop`, `BEetle.command`, or the existing Windows GUI launcher.
Enter RCM/APX and choose **Enter DFU with ShofEL** first. Then choose **Set up
with 5x1**. The sidebar action also lets you resume after USB is disconnected.

For source launches on macOS, or if SSH dependencies are unavailable, run
`python3 scripts/install_setup_deps.py` using the same Python as the launcher.
The Linux/WSL package builder includes these dependencies locally. Existing
offline DFU operations do not require SSH dependencies.

The CLI uses the same controller and explicit reviews:

```sh
python3 jibo_dfu.py setup-5x1 --session ~/Jibo-Backups/beetle-5x1-session.json
```

Use a new session filename for a different robot. Keep Jibo powered and allow
space for backups of var, both rootfs slots, services and skills (roughly a full
user-area image). The actual BEam archive is about 513 MiB and expands to about
1.12 GiB. BEetle stages it on `/opt` and checks available space first.

## Sequence

1. Save robot-bound partition backups, inspect factory identity/calibration and
   credentials, then configure `int-developer` mode and Wi-Fi. Unsupported fast
   file layouts use the reviewed full-var transfer with readback verification.
2. Restart out of recovery mode, find the IP in your router, and connect over
   SSH. Defaults are `root` / `jibo`; both can be changed. Accept the displayed
   host fingerprint. Robot identity and calibration must match the USB backup.
3. Preserve credential keys, or provision missing keys through BEefy's prepared
   OOBE protocol. Configure `api.5x1.com:443` and `http://joap.5x1.com:80`.
4. Install the revision-pinned BEam archive, retaining unrelated custom skills,
   Knowledge, custom eyes and music. Preserve a local copy of overwritten skills.
5. Apply legacy TLS compatibility and the SSM pre-OTA backup skip. Use System
   Manager's normal check/download/apply path for BEaker updates. Require a
   successful download before apply; verify target versions after reboot and
   reapply configuration replaced by services OTA.
6. Run the established board-detecting BBFW updater, set normal mode, reboot,
   and verify identity, calibration, installed versions, service processes,
   endpoints, BEefy health reachability and OTA check. The active firewall init
   script is removed, matching BEach bring-up, so SSH remains available.

The legacy compatibility path disables certificate rejection only in the known
robot Node clients, as BEach does. Host downloads and provisioning use verified
HTTPS. Unknown patch layouts stop setup with an actionable error.

## Resume and restore

Reuse the same session file through the GUI, TUI or CLI. Its private JSON stores
identity, calibration hashes, accepted host fingerprints, backup paths and
completed stages. Wi-Fi/SSH passwords and cloud credential secrets are never
stored in that session. Partition backups themselves contain private robot data.

Completed installations are skipped; configuration is reapplied after reconnect.
If OTA was interrupted during apply, the requested target versions must be
present before continuing. If they are absent, inspect the robot's update status
and recover the failed update first. A changed SSH fingerprint or mismatched
identity stops setup. A completed session can rerun verification.

To undo filesystem changes, enter recovery and use **More tools → Restore
selected partitions** with the session's `backup_set` path. Restore all modified
partitions for a complete filesystem rollback. BBFW updates target the body
controllers and are not undone by restoring eMMC partitions.

## Validation status

Automated tests cover credential-free and provisioned fixtures, malformed keys,
server errors, host-key acceptance/change, wrong robot identity, cancellation,
resume, OTA download failure and configuration replaced by OTA.

Celeste was inspected read-only with e2fsprogs: active mode `oobe`, complete
factory identity and all three camera calibration JSON files, credentials absent.
Its filesystem uses `meta_bg` and contains non-extent inodes. A disposable var
copy passed mode/Wi-Fi preparation and e2fsck with identity and calibration
unchanged. The actual pinned archive was installed into a disposable tree,
restoring all 49 relative links and preserving fixture user assets.

These checks do not prove live conversation, body firmware, or reboot behavior.
Full OOBE and provisioned hardware setup remains unverified. Linux GUI and
cross-platform launcher tests are available; Windows/WSL and macOS hardware
execution must be checked on those systems before release.

![5x1 setup review](images/gui/setup.png)
