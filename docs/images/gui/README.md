# GUI screenshots

The README gallery uses four 1080 × 720 PNGs: `ready.png`, `mode-wifi.png`,
`review.png` and `progress.png`.

Regenerate them from the toolkit root with Tk, Pillow and Xvfb:

```sh
xvfb-run -a -s '-screen 0 1400x1000x24' python3 scripts/docs_screenshots.py
```

The docs-only script uses example data and removes PNG metadata.

The 5x1 setup review has a companion image, `setup.png`. See
[setup and recovery](../../setup-5x1.md). Capture it alongside the four
existing screens with `--setup`:

```sh
xvfb-run -a -s '-screen 0 1400x1000x24' python3 scripts/docs_screenshots.py --setup
```
