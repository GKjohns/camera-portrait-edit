"""Reproducible portrait edit pipeline: rotate, 4:5 crop, grade, export.

Usage:
  python edit.py params.json [--src FILE] [--out DIR] [--tag v1]   # draft: 1080x1350 + before/after
  python edit.py params.json --full [--src FILE] [--out DIR]        # full-res 4:5 + 1080x1350 IG export
  python edit.py params.json --styles all [--full] --out DIR         # natural + every preset in styles.json
  python edit.py params.json --style portra --style warm_bw          # selected presets (draft unless --full)

Styles run on the base correction (rotate/crop/NR/WB from params) and are defined in styles.json.
Optional params["probes"] = {"skin": [x, y], ...} in 1080x1350 coords prints Lab stats per style.

RAW files (.arw .cr2 .cr3 .nef .raf .orf .rw2 .dng) are developed with rawpy if installed.
"""
import argparse, colorsys, json, os, sys
import numpy as np, cv2
from PIL import Image, ImageOps, ImageFilter, ImageCms

RAW_EXT = {'.arw', '.cr2', '.cr3', '.nef', '.nrw', '.raf', '.orf', '.rw2', '.dng', '.pef', '.srw'}
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()

def s2l(x): return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
def l2s(x): x = np.clip(x, 0, 1); return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)
def lum(a): return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722

def is_raw(path): return os.path.splitext(path)[1].lower() in RAW_EXT

def load(src, full):
    """Return (RGB image, icc bytes). Draft renders at ~1/4 size for speed."""
    if is_raw(src):
        try:
            import rawpy
        except ImportError:
            sys.exit('RAW input needs rawpy: pip install rawpy (or pass the camera JPEG with --src)')
        with rawpy.imread(src) as r:
            rgb = r.postprocess(use_camera_wb=True, no_auto_bright=True, bright=1.0,
                                output_bps=8, half_size=not full)
        im = Image.fromarray(rgb)          # LibRaw already applies orientation; output is sRGB
        return (im if full else im.reduce(2)), SRGB
    im = ImageOps.exif_transpose(Image.open(src)).convert('RGB')
    icc = im.info.get('icc_profile') or SRGB
    return (im if full else im.reduce(4)), icc

def exif_bytes(src):
    """Camera EXIF with orientation reset. For RAW, borrow from a same-named JPEG if present."""
    cands = [src] if not is_raw(src) else [os.path.splitext(src)[0] + e for e in ('.JPG', '.jpg', '.jpeg')]
    for c in cands:
        try:
            ex = Image.open(c).getexif(); ex[0x0112] = 1; return ex.tobytes()
        except Exception:
            continue
    return b''

# ---------- style layer: one generic engine driven by styles.json ----------
BANDS = dict(red=0, orange=30, yellow=55, green=110, aqua=175, blue=220, pink=330)
STYLES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'styles.json')

def load_styles(): return {k: v for k, v in json.load(open(STYLES_FILE)).items() if not k.startswith('_')}

def blur(x, sig):
    """Gaussian blur; large sigmas run on a downsampled copy for speed."""
    if sig < 8: return cv2.GaussianBlur(x, (0, 0), sig)
    f = sig / 4; h, w = x.shape[:2]
    sm = cv2.resize(x, (max(1, int(w / f)), max(1, int(h / f))), interpolation=cv2.INTER_AREA)
    return cv2.resize(cv2.GaussianBlur(sm, (0, 0), 4), (w, h), interpolation=cv2.INTER_LINEAR)

def curve_lut(pts, n=1024):
    x = np.linspace(0, 1, n); p = np.array(pts, dtype=np.float64)
    y = np.interp(x, p[:, 0], p[:, 1])
    y = np.convolve(np.pad(y, 40, mode='edge'), np.ones(41) / 41, 'same')[40:-40]   # smooth the kinks
    return x, y.astype(np.float32)

def skin_mask(s):
    hsv = cv2.cvtColor(np.clip(s, 0, 1), cv2.COLOR_RGB2HSV); h, sa = hsv[..., 0], hsv[..., 1]
    m = np.clip(np.minimum(h - 5, 50 - h) / 5, 0, 1) * np.clip(np.minimum(sa - 0.10, 0.68 - sa) / 0.08, 0, 1)
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), 2)

def lab_offset(s, off, w):
    lab = cv2.cvtColor(np.clip(s, 0, 1), cv2.COLOR_RGB2Lab)
    lab[..., 1] += off[0] * w; lab[..., 2] += off[1] * w
    return cv2.cvtColor(lab, cv2.COLOR_Lab2RGB)

def stylize(s, S, k):
    """s: float32 sRGB 0-1 after base correction. k: pixel scale vs a 1080-wide export."""
    if 'mono' in S: s = np.repeat((s @ np.array(S['mono'], dtype=np.float32))[..., None], 3, 2)
    # exposure in linear light with a soft shoulder, so the window rolls off instead of clipping
    lin = s2l(s) * 2 ** S.get('ev', 0); kn = S.get('knee', 0.7)
    Y = lum(lin)[..., None]; Yc = np.where(Y > kn, kn + (1 - kn) * np.tanh((Y - kn) / (1 - kn)), Y)
    s = l2s(lin * np.where(Y > 1e-6, Yc / np.maximum(Y, 1e-6), 1)).astype(np.float32)
    if 'curve' in S:   # applied to luma as an additive shift: keeps chroma, so pastels don't bleach
        Y = lum(s); s = s + (np.interp(Y, *curve_lut(S['curve'])) - Y)[..., None].astype(np.float32)
    # white balance as Lab offsets (optionally neutralize bright low-chroma areas first)
    lab = cv2.cvtColor(np.clip(s, 0, 1), cv2.COLOR_RGB2Lab)
    wb = np.array(S.get('wb', [0, 0]), dtype=np.float32)
    if S.get('neutralize'):
        m = (lab[..., 0] > 70) & (np.hypot(lab[..., 1], lab[..., 2]) < 15)
        if m.mean() > 0.01: wb -= S['neutralize'] * lab[m][:, 1:].mean(0)
    if wb.any(): s = lab_offset(s, wb, np.clip(lab[..., 0] / 40, 0, 1))
    # colour: per-band HSV shifts, then global sat/vibrance with skin handled separately
    skin = skin_mask(s)
    hsv = cv2.cvtColor(np.clip(s, 0, 1), cv2.COLOR_RGB2HSV); h = hsv[..., 0]
    dh = np.zeros_like(h); ds = np.zeros_like(h); dl = np.zeros_like(h)
    for band, (sh, sa, lu) in S.get('hue', {}).items():
        d = (h - BANDS[band] + 180) % 360 - 180; m = np.exp(-0.5 * (d / 22) ** 2)
        if band != 'orange': m = m * (1 - skin)   # only the orange band is allowed to touch skin
        dh += m * sh; ds += m * sa; dl += m * lu
    f = 1 + S.get('sat', 0) + S.get('vib', 0) * (1 - np.clip(hsv[..., 1] / 0.7, 0, 1))
    f = f * (1 - skin) + (1 + S.get('skin_sat', 0)) * skin
    hsv[..., 0] = (h + dh) % 360
    hsv[..., 1] = np.clip(hsv[..., 1] * (1 + ds) * f, 0, 1)
    hsv[..., 2] = hsv[..., 2] * (1 + dl)
    s = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    # split tone + clarity on Lab L
    lab = cv2.cvtColor(np.clip(s, 0, 1), cv2.COLOR_RGB2Lab); L = lab[..., 0] / 100
    for key, wgt in (('shadow', (1 - L) ** 2), ('highlight', L ** 2)):
        o = S.get('split', {}).get(key)
        if o: lab[..., 1] += o[0] * wgt; lab[..., 2] += o[1] * wgt
    if 'clarity' in S:
        amt, sig = S['clarity']; w = 4 * L * (1 - L)
        if not S.get('clarity_skin', True): w = w * (1 - skin)
        lab[..., 0] += 100 * amt * 3 * (L - blur(L, sig * k)) * w
    s = cv2.cvtColor(lab, cv2.COLOR_Lab2RGB)
    if 'halation' in S:
        thr, rad, r, g = S['halation']; hl = np.clip((lum(s) - thr) / (1 - thr), 0, 1)
        glow = blur(hl, rad * s.shape[1])[..., None] * np.array([r, g, 0], dtype=np.float32)
        s = 1 - (1 - np.clip(s, 0, 1)) * (1 - glow)
    if 'vignette' in S:
        amt, inner = S['vignette']; H, W = s.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / np.sqrt(2)
        s = s * (1 + amt * np.clip((r - inner) / (1 - inner), 0, 1) ** 2)[..., None]
    return np.clip(s, 0, 1).astype(np.float32)

def add_grain(im, S, k, seed=7):
    """Luminance grain at output resolution, weighted to the midtones; dithers lifted blacks."""
    a = np.asarray(im, dtype=np.float32) / 255
    if S and 'grain' in S:
        sig, size = S['grain']
        n = np.random.default_rng(seed).standard_normal(a.shape[:2]).astype(np.float32)
        n = cv2.GaussianBlur(n, (0, 0), max(0.3, size * k)); n *= sig / (n.std() + 1e-8)
        Y = lum(a)[..., None]; a = a * (1 + n[..., None] * 4 * (1 - Y))   # ~4Y(1-Y) in absolute terms, chroma-neutral
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))

def to_img(a): return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))

def probe_report(ig, base, probes):
    """Print Lab stats for named probe points ([x, y] in 1080x1350 coords) vs the uncorrected crop."""
    labs = [cv2.cvtColor(np.asarray(x, dtype=np.float32) / 255, cv2.COLOR_RGB2Lab) for x in (base, ig)]
    out = []
    for name, (x, y) in probes.items():
        (L0, _, _), (L, A, B) = [l[y - 12:y + 12, x - 12:x + 12].reshape(-1, 3).mean(0) for l in labs]
        out.append(f'{name}: L{L:.0f} ({(L / L0 - 1) * 100:+.0f}%) a{A:.1f} b{B:.1f} hue{np.degrees(np.arctan2(B, A)):.0f} C{np.hypot(A, B):.1f}')
    print('   ' + ' | '.join(out))

def develop(P, src, full, style=None):
    im, icc = load(src, full)
    if P.get('rotate', 0): im = im.rotate(P['rotate'], resample=Image.BICUBIC, expand=False)
    W, H = im.size
    # 4:5 crop from center (relative) + relative width; keep crop_w small enough to hide rotation corners
    cw = P['crop_w'] * W; ch = cw * 5 / 4
    cx, cy = P['crop_cx'] * W, P['crop_cy'] * H
    box = [cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2]
    if box[0] < -0.5 or box[1] < -0.5 or box[2] > W + 0.5 or box[3] > H + 0.5:
        sys.exit(f'crop out of bounds {[round(v) for v in box]} for {W}x{H}: lower crop_w or move crop_cx/crop_cy')
    im = im.crop(tuple(int(round(v)) for v in box))
    a = np.asarray(im, dtype=np.float32) / 255.0
    # chroma noise reduction (blur Cr/Cb only)
    if P.get('chroma_nr', 0):
        ycc = cv2.cvtColor(a, cv2.COLOR_RGB2YCrCb)
        sig = max(0.6, P['chroma_nr'] * (1 if full else 0.25))
        for c in (1, 2): ycc[..., c] = cv2.GaussianBlur(ycc[..., c], (0, 0), sig)
        a = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)
    lin = s2l(np.clip(a, 0, 1))
    # white balance in linear light: temp + warmer, tint + magenta
    t, g = P.get('temp', 0), P.get('tint', 0)
    lin = lin * np.array([1 + t, 1 - g, 1 - t], dtype=np.float32)
    if style is not None:   # style layer replaces the natural grade; base = rotate/crop/NR/WB
        return stylize(l2s(lin).astype(np.float32), style, a.shape[1] / 1080), icc
    lin = lin * 2 ** P.get('ev', 0)
    # soft highlight rolloff above the knee (luma-based, hue-preserving)
    kn = P.get('hl_knee', 0.8)
    Y = lum(lin)[..., None]
    Yc = np.where(Y > kn, kn + (1 - kn) * np.tanh((Y - kn) / (1 - kn)), Y)
    lin = lin * np.where(Y > 1e-6, Yc / np.maximum(Y, 1e-6), 1)
    s = l2s(lin)
    # tone curve on luma, applied as a ratio so hue is preserved
    x = np.clip(lum(s)[..., None], 0, 1)
    y = x + P.get('contrast', 0.0) * (x - x * x) * (2 * x - 1)
    y = y + P.get('shadows', 0.0) * np.exp(-((x - 0.18) / 0.14) ** 2)
    y = y + P.get('highlights', 0.0) * np.exp(-((x - 0.82) / 0.12) ** 2)
    lift, white = P.get('fade', 0.0), P.get('white', 1.0)
    y = lift + y * (white - lift)
    s = s * np.where(x > 1e-4, y / np.maximum(x, 1e-4), 1)
    # saturation / vibrance with skin protection
    Ys = lum(s)[..., None]
    chroma = (s.max(2) - s.min(2))[..., None]
    hsv = cv2.cvtColor(np.clip(s, 0, 1).astype(np.float32), cv2.COLOR_RGB2HSV)
    h = hsv[..., 0][..., None]; sat = hsv[..., 1][..., None]
    skin = ((h >= 5) & (h <= 45)).astype(np.float32) * np.clip((0.75 - sat) / 0.2, 0, 1) * np.clip(sat / 0.1, 0, 1)
    skin = cv2.GaussianBlur(skin[..., 0], (0, 0), 2)[..., None]
    f = P.get('sat', 1.0) * (1 + P.get('vib', 0.0) * (1 - np.clip(chroma / 0.6, 0, 1)))
    f = 1 + (f - 1) * (1 - skin * P.get('skin_protect', 0.7))
    f = f * (1 + P.get('green_sat', 0.0) * np.clip(1 - np.abs(h - 140) / 60, 0, 1))
    s = Ys + (s - Ys) * f
    s = s + skin * P.get('skin_warm', 0.0) * np.array([1, 0.2, -0.8], dtype=np.float32)
    # subtle split tone
    Ys = np.clip(lum(s)[..., None], 0, 1)
    s = s + np.array(P.get('shadow_tint', [0, 0, 0]), dtype=np.float32) * (1 - Ys) ** 2 \
          + np.array(P.get('hl_tint', [0, 0, 0]), dtype=np.float32) * Ys ** 2
    return s.astype(np.float32), icc

def sharpen(im, amt, rad, thr=2):
    return im.filter(ImageFilter.UnsharpMask(radius=rad, percent=int(amt), threshold=thr))

def ig_version(out, P):
    return sharpen(out.resize((1080, 1350), Image.LANCZOS), P.get('ig_sharp_amt', 45), 0.7, 1)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('params'); ap.add_argument('--src', help='override params["src"]')
    ap.add_argument('--out', default='edited', help='output dir (default ./edited)')
    ap.add_argument('--full', action='store_true', help='final full-res export')
    ap.add_argument('--tag', default='v1', help='draft label, e.g. v2')
    ap.add_argument('--style', action='append', help='style preset from styles.json (repeatable)')
    ap.add_argument('--styles', help='"all" or comma list; writes <name>_<style>_* plus <name>_original_1080x1350.jpg')
    A = ap.parse_args()
    P = json.load(open(A.params))
    src = os.path.expanduser(A.src or P['src'])
    if not os.path.isabs(src) and not os.path.exists(src):   # allow src relative to the params file
        src = os.path.join(os.path.dirname(os.path.abspath(A.params)), src)
    name = P.get('name') or os.path.splitext(os.path.basename(src))[0]
    os.makedirs(A.out, exist_ok=True)
    kw = dict(quality=92, icc_profile=None, exif=exif_bytes(src), subsampling=0)
    B = {k: P[k] for k in ('rotate', 'crop_w', 'crop_cx', 'crop_cy') if k in P}; B['hl_knee'] = 1.01
    ST = load_styles()
    names = (A.style or []) + ([] if not A.styles else list(ST) if A.styles == 'all' else A.styles.split(','))
    if names:   # style mode: natural + presets, plus an ungraded crop for before/after
        base, icc = develop(B, src, A.full); base = to_img(base).resize((1080, 1350), Image.LANCZOS)
        kw['icc_profile'] = icc
        if A.full: base.save(os.path.join(A.out, f'{name}_original_1080x1350.jpg'), **kw)
        for st in names:
            S = ST[st]; out, _ = develop(P, src, A.full, None if st == 'natural' else S)
            ig = add_grain(ig_version(to_img(out), P), S, 1)
            if A.full:
                fr = add_grain(sharpen(to_img(out), P.get('sharp_amt', 60), P.get('sharp_rad', 1.4)), S, out.shape[1] / 1080)
                fr.save(os.path.join(A.out, f'{name}_{st}_full.jpg'), **kw)
                p = os.path.join(A.out, f'{name}_{st}_1080x1350.jpg'); ig.save(p, **kw)
            else:
                os.makedirs(os.path.join(A.out, 'iter'), exist_ok=True)
                p = os.path.join(A.out, 'iter', f'{name}_{st}_{A.tag}.jpg'); ig.save(p, quality=90)
            print('saved', p)
            if P.get('probes'): probe_report(ig, base, P['probes'])
        return
    out, icc = develop(P, src, A.full); out = to_img(out)
    kw['icc_profile'] = icc
    if A.full:
        fr = sharpen(out, P.get('sharp_amt', 60), P.get('sharp_rad', 1.4))
        p1 = os.path.join(A.out, f'{name}_4x5_full.jpg'); fr.save(p1, **kw)
        p2 = os.path.join(A.out, f'{name}_4x5_1080x1350.jpg'); ig_version(out, P).save(p2, **kw)
        print('saved', p1, fr.size); print('saved', p2); return
    d = os.path.join(A.out, 'iter'); os.makedirs(d, exist_ok=True)
    ig = ig_version(out, P); p = os.path.join(d, f'{name}_{A.tag}.jpg'); ig.save(p, quality=90)
    # before/after: same rotation + crop, no grade
    b, _ = develop(B, src, False); b = to_img(b).resize((540, 675), Image.LANCZOS)
    S = Image.new('RGB', (1090, 675), 'white'); S.paste(b, (0, 0)); S.paste(ig.resize((540, 675), Image.LANCZOS), (550, 0))
    pb = os.path.join(d, f'{name}_{A.tag}_ba.jpg'); S.save(pb, quality=88)
    print('draft', p); print('before/after', pb)
    a = np.asarray(ig, dtype=float) / 255
    if P.get('skin_px'):   # sample point in 1080x1350 draft coordinates
        bb = np.asarray(b.resize((1080, 1350)), dtype=float) / 255
        x0, y0 = [int(v) for v in P['skin_px']]
        for lab, arr in (('before', bb), ('after', a)):
            px = arr[max(0, y0 - 12):y0 + 12, max(0, x0 - 12):x0 + 12].reshape(-1, 3).mean(0)
            hh, ss, vv = colorsys.rgb_to_hsv(*px)
            print(f'skin {lab}: rgb={np.round(px * 255)} hue={hh * 360:.1f} sat={ss:.2f} val={vv:.2f}')
    L = lum(a)
    print('clip% ', round(float((a.max(2) > 0.995).mean() * 100), 3), ' luma p1/50/99', np.percentile(L, [1, 50, 99]).round(3))

if __name__ == '__main__':
    main()
