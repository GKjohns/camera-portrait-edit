# camera-portrait-edit

A [Claude Code](https://claude.com/claude-code) skill that takes a camera card to a finished Instagram portrait: find the latest shoot, cull to one or two keepers, then straighten, crop to 4:5, white balance, grade, sharpen and export. Claude runs an iterative render-critique loop so the edit stays natural.

The editing engine is a single reproducible script (`scripts/edit.py`) driven by a JSON params file: rotation, 4:5 crop, white balance in linear light, soft highlight rolloff, hue-preserving contrast curve, skin-protected vibrance, warm split tone, chroma noise reduction and output sharpening. RAW files are developed with `rawpy` when it is installed.

After the base edit, the same script renders style variants from `scripts/styles.json` (Natural, Clean Editorial, Portra 400, Kodak Gold, Muted Earth, Warm B&W) through one recipe-driven engine with skin protection, and `scripts/make_viewer.py` builds a local `viewer.html` (grid, lightbox, two-up compare, before/after slider) so you can pick a look.

## Install

```
git clone https://github.com/GKjohns/camera-portrait-edit ~/.claude/skills/camera-portrait-edit
cd ~/.claude/skills/camera-portrait-edit
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/pip install rawpy   # optional, for RAW input
```

Optional tools the skill uses for culling (macOS): `sips` (built in), `brew install exiftool imagemagick gphoto2`.

## Use

Ask Claude something like "edit the photos from my camera for Instagram". Or run the script directly:

```
python scripts/edit.py examples/params.example.json --src photo.JPG --out edited --tag v1   # draft + before/after
python scripts/edit.py examples/params.example.json --src photo.JPG --out edited --full     # full-res + 1080x1350
python scripts/edit.py examples/params.example.json --src photo.JPG --out shoot/styles --styles all --full
python scripts/make_viewer.py shoot                                                          # shoot/viewer.html
```

See `SKILL.md` for the workflow and a table of every param.

## Notes

- Everything runs locally. No accounts, no API keys, no uploads. Open source under MIT.
- The skill only reads from the camera card; it never modifies or deletes files there.
