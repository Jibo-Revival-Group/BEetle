# BEetle

BEetle takes a full eMMC dump from [JiboAutoMod](https://github.com/Jibo-Revival-Group/JiboAutoMod) and patches it so an out-of-box Jibo can join your Wi-Fi, boot into BEacon, and update to current BEam and BEnch. It does not dump the robot.

Already-provisioned robots (mode `normal` with credentials) should keep using [BEam `post-mod.sh`](../BEam/post-mod.sh) over SSH. BEetle is the offline path for a robot that is still in OOBE, where there is no Wi-Fi, no IP, and no SSH.

Hub and OTA are fixed. BEetle never asks for them:

- Hub: `api.5x1.com:443`
- OTA: `http://joap.5x1.com:80`

No separate OS or body-board flash is required. BEaker publishes skills and the BEnch `services` package. Body-board firmware, when a robot needs it, is inside that services tree and is applied later by `jibo-bbfw-update`.

## What you need

- The robot's full eMMC dump (a file like `Name-Word-Word-Word.bin` from AutoMod)
- Python 3, `debugfs` (e2fsprogs), and `openssl`
- Root, or passwordless `sudo`, to mount the skills image and to run ShofEL
- JiboAutoMod's `shofel2_t124` (by default `~/JiboAutoMod/Shofel/shofel2_t124`)
- A sibling checkout of BEam (`../BEam`), which is baked into the skills partition
- Enough free disk for a second copy of the partitions you patch (the skills partition is about 10 GB, and BEetle keeps an unpatched copy beside the patched one)

BEetle works on any Jibo eMMC with the stock partition names `rootfsA`, `rootfsB`, `services`, `var`, and `skills`. It keeps that robot's `identity.json`, camera calibration, and SSH host keys.

## Run

1. Dump the robot with JiboAutoMod while it is in RCM. A later failed stock setup ("Cannot connect to Jibo's server") does not mean you have to dump again.
2. Put the robot back in RCM when you are ready to write.

```bash
python3 beetle.py --dump-path /path/to/Robot-Name.bin --write
```

You are prompted for the Wi-Fi name and password. Add `--patch-only` to build the patched images and `work/sector-plan.json` without touching the robot.

BEetle writes only the 512-byte sectors that changed, then reads them back and checks they match. Before that write it compares the live eMMC to the dump:

- Same serial and CPU ID, or it stops (wrong robot).
- If `/var` changed because the robot was powered on after the dump (including a failed “Cannot connect to Jibo's server” Wi-Fi attempt), BEetle re-reads that 500 MB partition, applies the same patches there, and writes the new diff. Other partitions are re-read only when their free space changed, so a normal boot does not turn into another full dump.
- It refuses a robot that is already `normal` and has credentials, unless you pass `--force`.

## After it boots

The face does not show the eye. It says:

```text
Go to http://192.168.x.x:8123 to setup
```

Open that page. Setup asks you to add household members and to install BEam skills plus BEnch services from `joap.5x1.com`. Finish reboots into the normal eye.

An older factory image may not be offered a `services` update if BEaker has no package for that version. Setup reports that instead of asking you to choose a server. Skills from this BEam tree are already on the robot from the bake.

## What gets patched

| Partition | Change |
|-----------|--------|
| `var` | Your Wi-Fi, generated `credentials.json` (`region` `api`, endpoint `http://joap.5x1.com:80`), an RSA `keys/keypair.json` if missing, `mode.json` set to `normal`, and `/var/jibo/beetle-setup.json` pending |
| `skills` | Current BEam skill trees (`@be`, `oobe-config`, diagnostics, tbd, fin-goods), Knowledge folders, the ISRG Root X1 certificate, and `rejectUnauthorized: false` where that assignment exists |
| `services` | Jetstream hub override to `api.5x1.com:443` when that config exists, SSM pre-OTA backup skip when that code exists |
| `rootfsA` / `rootfsB` | Removes `S21firewall` or `S30firewall` (whichever is present) so the LAN is reachable without a frankencable. Installs the same CA into the system trust store when those paths exist |

Identity, LPS calibration, and SSH host keys are not replaced, and nothing is copied from another robot's dump.
