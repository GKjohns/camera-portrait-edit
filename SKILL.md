---
name: camera-portrait-edit
description: Pull the latest shoot off a camera card, cull to 1-2 keepers, and edit them into natural-looking 4:5 Instagram portraits (straighten, crop, white balance, color grade, sharpen, export). Use when the user says "edit photos from my camera", "grab the pictures off my camera", "Instagram portrait", "crop and color grade", "make this post-ready", "edit the best shots from today", or plugs in an SD card and wants photos edited.
---

# Camera to Instagram portrait

Scripts live next to this file: `scripts/edit.py`, `scripts/styles.json`, `scripts/make_viewer.py`, `examples/params.example.json`.
Setup once: `python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt` (add `rawpy` for RAW).

## 1. Find the camera (read only)
- `ls -d /Volumes/*/DCIM`. If nothing mounts, the camera may be in PTP mode: `gphoto2 --auto-detect`, then `gphoto2 --list-files` / `--get-file N`.
- Never write, rename, or delete anything on the card. Copy out, work on copies.

## 2. Pick the shoot and cull
- Newest shoot = the latest cluster of files by capture time (`exiftool -DateTimeOriginal`, or file mtime). Ask only if two clusters look equally recent.
- Cull from small previews, never full-res files in context:
  - `sips -Z 800 IMG.JPG --out /tmp/prev/` for JPEGs, `exiftool -b -PreviewImage X.ARW > prev.jpg` for RAW-only.
  - Contact sheet: `magick montage prev/*.jpg -tile 5x -geometry 320x320+4+4 -label '%f' contact.jpg`.
- Check focus on the shortlist with 100% crops of the face/eyes (PIL crop of ~600px around the face). Soft eyes = reject.
- Pick 1-2 keepers: sharp eyes, natural expression, clean background, horizon/verticals salvageable.

## 3. Copy out
`~/Desktop/<Subject> <YYYY-MM-DD>/{raw,originals,edited,styles}`: RAW files in `raw/`, camera JPEGs in `originals/`. If the shoot has no RAW, say so; edit the JPEG.

## 4. Edit with the bundled script
Copy `examples/params.example.json` per keeper into the shoot folder, set `src` (relative paths resolve from the params file), then:
```
python scripts/edit.py params.json --out "<shoot>/edited" --tag v1   # draft + before/after + stats
python scripts/edit.py params.json --out "<shoot>/edited" --full     # final export
```
RAW input goes through rawpy (camera WB, no auto-brighten, so expect to raise `ev` ~0.3-0.8); otherwise the JPEG path. Draft renders are 1080x1350 in `edited/iter/`.

Key params:
| param | meaning |
|---|---|
| `rotate` | degrees CCW; fix tilt from door frames, walls, horizon |
| `crop_w`, `crop_cx`, `crop_cy` | 4:5 crop: width and center as fractions of the rotated frame; rotation needs `crop_w` < 1 to hide corners |
| `temp`, `tint` | WB in linear light (+warm, +magenta); keep within about ±0.06 |
| `ev`, `hl_knee`, `contrast`, `shadows`, `highlights`, `fade`, `white` | exposure, highlight rolloff, hue-preserving luma curve |
| `sat`, `vib`, `skin_protect`, `green_sat`, `skin_warm` | color; vibrance spares skin |
| `shadow_tint`, `hl_tint` | subtle warm split tone (RGB offsets, ~0.005) |
| `chroma_nr`, `sharp_amt`, `sharp_rad`, `ig_sharp_amt` | noise and output sharpening |
| `skin_px` | optional [x,y] in draft coords; prints before/after skin hue/sat |
| `probes` | optional `{"skin": [x,y], "shirt": ..., "rug": ...}` in 1080x1350 coords; style renders print Lab L (and % change), a, b, hue angle, chroma per probe |

## 5. Critique loop (at least 3 passes)
Render, view the downsized draft and the `_ba` before/after, then check:
- **Straight**: verticals (door frames, walls) vertical, horizon level. Adjust `rotate` in 0.1-0.3 deg steps.
- **WB and skin**: skin hue ~15-25 deg, sat ~0.3-0.5 from the printed stats; no orange or grey faces; whites neutral.
- **Clipping**: `clip%` near 0 on skin and sky; p99 luma under ~0.97.
- **Crop**: eyes near the upper third, no limbs cut at joints, breathing room above the head, no edge distractions.
- **Over-processing**: halos, crunchy texture, plastic skin, candy colors. If it looks "edited", back off.
Adjust params, bump `--tag`, re-render. Aim for tasteful and natural, never a heavy filter.

## 6. Export
`--full` writes `<name>_4x5_full.jpg` (full-res, q92, sRGB/ICC, camera EXIF, orientation reset) and `<name>_4x5_1080x1350.jpg` for Instagram.
Offer tighter/looser crop variants: copy the params with a new `name` (e.g. `..._tight`) and a different `crop_w`, so nothing gets overwritten.

## 7. Style variants, viewer, let the user pick
Once the base edit (straighten, crop, WB) is right, render the natural edit plus 3-5 styles from the same params:
```
python scripts/edit.py params.json --styles all --out "<shoot>/styles" --tag s1      # drafts in styles/iter/
python scripts/edit.py params.json --styles all --out "<shoot>/styles" --full        # <name>_<style>_{full,1080x1350}.jpg
python scripts/make_viewer.py "<shoot>"                                              # <shoot>/viewer.html
open "<shoot>/viewer.html"
```
`--full` also writes `<name>_original_1080x1350.jpg` (same crop, no grade) for the viewer's before/after slider. The viewer has a grid per photo, a lightbox with arrow keys, a two-up compare and the slider. Add `probes` to the params, then loop per style: render, view downsized, read the probe stats, tune `styles.json`, re-render (2+ passes, judge all photos together). Grain is added at output resolution, so check a 100% crop of one `_full.jpg`.

| style | vibe |
|---|---|
| `natural` | the base edit: honest color, gentle contrast |
| `clean_editorial` | bright, neutral, crisp; magazine-clean |
| `portra` | soft film: lifted blacks, creamy highlights, muted greens, fine grain |
| `kodak_gold` | warm film, punchy reds/yellows, light halation |
| `muted_earth` | quiet desaturated earth tones, warm skin |
| `warm_bw` | warm-toned black and white with grain |

Skin guardrails for every style: cheek Lab hue angle `atan2(b,a)` 50-62 deg, chroma under ~28 (or no higher than the natural edit), skin no more than 8% lighter than the original, no orange or ashy grey. Also: bright neutrals (rug, walls) b* at most ~6, window not a clipped slab, saturated clothing loses at most ~10% luminance, pinks must not drift purple. Avoid heavy matte fade, orange-teal and HDR crunch. Recipes are starting points; tune per shoot and say what you changed.

Show the viewer and ask which style (or two) they want. Only the chosen style's `_full.jpg` is the deliverable.

## Tips
- Delegate the render/view/critique loop (base and styles) to a subagent that returns text notes + file paths, keeping images out of the main context.
- Show the user the final before/after and the output paths; don't post anything anywhere.
