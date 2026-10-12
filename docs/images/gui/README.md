# GUI screenshots

The README gallery uses four 1080 × 720 PNGs: `ready.png`, `mode-wifi.png`,
`review.png` and `progress.png`.

Regenerate them from the toolkit root with Tk, Pillow, ImageMagick and Xvfb:

```sh
xvfb-run -a -s '-screen 0 1400x1000x24' python3 scripts/docs_screenshots.py
```

The docs-only script uses example data and removes PNG metadata.
