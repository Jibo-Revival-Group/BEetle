# BEetle

BEetle flashes a full Jibo eMMC image onto a robot over DFU. A normal flash leaves `/var` on the robot, so identity, Wi-Fi, calibration, and faces stay. `--setup` is the one path that changes `/var`, and it only writes the Wi-Fi network you enter.

## What you need

- A full eMMC image (a `.bin` from a dump) whose `rootfsA`, `rootfsB`, `services`, and `skills` partitions are the same size as the robot's
- Python 3
- Root, for USB
- The DFU tools in `dfu/`. If `dfu/dfu-util` or `dfu/shofel2_t124` is missing, run `./dfu/build.sh` once

## Run

Put the robot in RCM (hold the RCM button, press power, release when the red LED is on and there is no boot animation). Then:

```bash
sudo python3 beetle.py /path/to/image.bin
```

BEetle loads the RAM DFU program, reads the live partition map, and refuses to write if a partition it is about to flash is a different size on the robot. It then writes `rootfsA`, `rootfsB`, `services`, and `skills`. `var` is not extracted and not written.

`--partitions rootfsA,services` limits the write to that subset. `var` in that list is an error. `--write-only` continues after Ctrl-C from `work/dfu-write-progress.json`.

## Setup

`--setup` downloads the current BEam and BEnch master branches, copies them into the image's skills and services partitions, and deletes the firewall init script on `rootfsA` and `rootfsB`. It asks for a Wi-Fi name and password and writes that network onto the robot's existing `/var`. The rest of `/var` is not replaced by the image.

```bash
sudo python3 beetle.py /path/to/image.bin --setup
```

Skills is about 10 GiB. Let the flash finish before unplugging.

## Dump

`--dump` and `--dump-var` read the robot over DFU. They do not take an image path.

```bash
sudo python3 beetle.py --dump
sudo python3 beetle.py --dump-var
```

`--dump` writes `work/jibo-full-dump.bin`: the primary GPT and every partition, with unused space left zero. `--dump-var` writes only `/var` to `work/jibo-var-dump.bin`. A failed or interrupted read deletes the partial file. Keep the robot powered until the command prints that the dump finished.
