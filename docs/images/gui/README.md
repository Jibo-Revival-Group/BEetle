# GUI screenshot provenance

These four images show the real Tkinter/ttk interface on **Linux under Xvfb,
with a simulated device**. They are documentation illustrations, not Windows
screenshots, real robot captures, physical USB acceptance or performance evidence.

| Published image | Source capture | View |
| --- | --- | --- |
| [ready.png](ready.png) | `05-dfu-ready.png` | DFU-ready actions and USB readiness |
| [mode-wifi.png](mode-wifi.png) | `12-combined-mode.png` | Mode selection before Wi-Fi setup |
| [review.png](review.png) | `18-combined-full-var-review-armed.png` | Explicit write review with Cancel/Confirm |
| [progress.png](progress.png) | `36-backup-progress.png` | Simulated var-backup progress and log |

The source walkthrough receipt identifies clean revision
`5bbaa01d23ad97a8f18e6919d59e36563194b915`, `dirty: false` and
`fake_device: true`. Each selected capture's SHA-256 was checked against that
receipt before publication. All images retain their original **1080 × 720**
pixels, without retouching, cropping, resizing or changing interface labels.
They were losslessly re-encoded to optimize the PNGs and remove metadata.

## Privacy and interpretation

- The visible `/tmp/fake-jibo-backups` directory, USB port `1-1`, repeated
  example hashes and progress values are synthetic fixture data, not private
  host paths or real device identifiers. No personal directories, credentials,
  actual Wi-Fi names or device serials are visible in the selected captures.
- All published PNGs contain only `IHDR`, `IDAT` and `IEND` chunks. There are
  no EXIF, text, XMP, timestamps, embedded profiles or trailing payloads.
- The progress screen says **FAKE DEVICE**; its speed and duration must not be
  read as hardware measurements. The review says **fake var transaction**.
- No test `.pyz`, synthetic loader/tool archive, backup image or flashing
  package is distributed with these screenshots.

For the implementation, platform setup and remaining hardware gates, see
[GUI documentation](../../gui.md) and the [main README](../../../README.md).
