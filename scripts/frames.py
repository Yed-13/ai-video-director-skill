#!/usr/bin/env python3
"""Image checks for keyframes and storyboards (ffmpeg only).

  frames.py onion A.png B.png        # 50% overlay + amplified difference + SSIM: find misalignment
  frames.py gray IMG                 # grayscale version: is subject/background contrast enough?
  frames.py phone IMG [--width 390]  # phone-size preview: are small figures still readable?
  frames.py guides IMG               # draw 38% / 62% composition lines
  frames.py crop IMG --ratio 16:9    # center-crop to an aspect ratio
  frames.py crop IMG --zoom 1.2 --center 0.62,0.45   # punch-in crop, scaled back to original size

Outputs are written next to the input unless -o is given. Inputs are never overwritten.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _media import ffmpeg, need_ffmpeg, probe, ssim  # noqa: E402


def out_path(src, suffix, given):
    if given:
        return Path(given)
    src = Path(src)
    return src.with_name("%s_%s.png" % (src.stem, suffix))


def cmd_onion(a):
    info = probe(a.a)
    w, h = info["width"], info["height"]
    base = out_path(a.a, "vs_" + Path(a.b).stem, a.o)
    overlay = base.with_name(base.stem + "_onion.png")
    diff = base.with_name(base.stem + "_diff.png")
    ffmpeg(["-i", a.a, "-i", a.b, "-filter_complex",
            "[0:v]scale=%d:%d,format=rgba[a];[1:v]scale=%d:%d,format=rgba[b];[a][b]blend=all_mode=normal:all_opacity=0.5"
            % (w, h, w, h), "-frames:v", "1", overlay])
    ffmpeg(["-i", a.a, "-i", a.b, "-filter_complex",
            "[0:v]scale=%d:%d,format=rgb24[a];[1:v]scale=%d:%d,format=rgb24[b];[a][b]blend=all_mode=difference,"
            "lutrgb=r='min(val*4,255)':g='min(val*4,255)':b='min(val*4,255)'" % (w, h, w, h),
            "-frames:v", "1", diff])
    b_info = probe(a.b)
    s = ssim(a.a, a.b, w, h)
    print("叠图：%s" % overlay)
    print("差异图（亮的地方 = 两张图不同，已放大 4 倍）：%s" % diff)
    if (b_info["width"], b_info["height"]) != (w, h):
        print("⚠️  两张图尺寸不同：%dx%d vs %dx%d（比较前已缩放到同一尺寸）"
              % (w, h, b_info["width"], b_info["height"]))
    if s is not None:
        print("SSIM = %.4f（1 = 完全相同；首尾帧之间不该变的区域，在差异图里应该是黑的）" % s)


def cmd_gray(a):
    o = out_path(a.img, "gray", a.o)
    ffmpeg(["-i", a.img, "-vf", "format=gray", "-frames:v", "1", o])
    print("黑白图：%s（人和背景分不开 = 明暗对比不够）" % o)


def cmd_phone(a):
    o = out_path(a.img, "phone", a.o)
    ffmpeg(["-i", a.img, "-vf", "scale=%d:-2:flags=area" % a.width, "-frames:v", "1", o])
    print("手机尺寸预览（宽 %dpx）：%s" % (a.width, o))


def cmd_guides(a):
    o = out_path(a.img, "guides", a.o)
    t = "max(2\\,iw/640)"
    vf = ",".join([
        "drawbox=x=iw*0.382:y=0:w=%s:h=ih:color=red@0.8:t=fill" % t,
        "drawbox=x=iw*0.618:y=0:w=%s:h=ih:color=red@0.8:t=fill" % t,
        "drawbox=x=0:y=ih*0.382:w=iw:h=%s:color=red@0.5:t=fill" % t,
        "drawbox=x=0:y=ih*0.618:w=iw:h=%s:color=red@0.5:t=fill" % t,
    ])
    ffmpeg(["-i", a.img, "-vf", vf, "-frames:v", "1", o])
    print("构图线（38.2%% / 61.8%%）：%s" % o)


def cmd_crop(a):
    info = probe(a.img)
    w, h = info["width"], info["height"]
    if a.ratio:
        rn, rd = (float(x) for x in a.ratio.split(":"))
        r = rn / rd
        if w / h > r:
            cw, ch = int(round(h * r)) // 2 * 2, h // 2 * 2
        else:
            cw, ch = w // 2 * 2, int(round(w / r)) // 2 * 2
        vf = "crop=%d:%d:(iw-%d)/2:(ih-%d)/2" % (cw, ch, cw, ch)
        if a.size:
            vf += ",scale=%s:flags=lanczos" % a.size.replace("x", ":")
        o = out_path(a.img, "crop%s" % a.ratio.replace(":", "x"), a.o)
    elif a.zoom:
        if a.zoom <= 1:
            sys.exit("--zoom 必须大于 1")
        cx, cy = (float(x) for x in (a.center or "0.5,0.5").split(","))
        cw, ch = int(w / a.zoom), int(h / a.zoom)
        x = min(max(int(cx * w - cw / 2), 0), w - cw)
        y = min(max(int(cy * h - ch / 2), 0), h - ch)
        vf = "crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos" % (cw, ch, x, y, w, h)
        o = out_path(a.img, "zoom%.2f" % a.zoom, a.o)
    else:
        sys.exit("crop 需要 --ratio 或 --zoom")
    ffmpeg(["-i", a.img, "-vf", vf, "-frames:v", "1", o])
    oi = probe(o)
    print("已输出 %s（%dx%d）" % (o, oi["width"], oi["height"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("onion"); p.add_argument("a"); p.add_argument("b"); p.add_argument("-o")
    p = sub.add_parser("gray"); p.add_argument("img"); p.add_argument("-o")
    p = sub.add_parser("phone"); p.add_argument("img"); p.add_argument("--width", type=int, default=390); p.add_argument("-o")
    p = sub.add_parser("guides"); p.add_argument("img"); p.add_argument("-o")
    p = sub.add_parser("crop"); p.add_argument("img"); p.add_argument("--ratio"); p.add_argument("--size", help="如 1920x1080")
    p.add_argument("--zoom", type=float); p.add_argument("--center", help="中心点，0–1 的相对坐标，如 0.62,0.45"); p.add_argument("-o")
    a = ap.parse_args()
    need_ffmpeg()
    {"onion": cmd_onion, "gray": cmd_gray, "phone": cmd_phone, "guides": cmd_guides, "crop": cmd_crop}[a.cmd](a)


if __name__ == "__main__":
    main()
