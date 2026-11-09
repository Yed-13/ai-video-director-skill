#!/usr/bin/env python3
"""Measure and compare the look (brightness, contrast, saturation, warmth, tint, palette) of frames.

  look.py analyze FILE... [--frames 5] [--swatch]
  look.py compare REF FILE... [--frames 5]
  look.py swatch "#D9A15B" "#6E8A8F" ... [-o palette.png]

FILE can be an image or a video (videos are sampled at --frames evenly spaced points).
Warmth is an *equivalent* CCT estimated from near-neutral pixels (McCamy's formula on the
average linear sRGB of those pixels). It shows the overall warm/cool bias of the frame and is
meant for comparing shots of the same scene, not as the true colour temperature of the light.
Python 3.9+ stdlib + ffmpeg only.
"""
import argparse
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _media import ffmpeg, kind_of, need_ffmpeg, probe  # noqa: E402

W, H = 160, 90


def raw_frames(path, n_frames):
    """Return list of (label, bytes rgb24 W*H*3)."""
    k = kind_of(path)
    if k == "image":
        times = [None]
    elif k == "video":
        dur = probe(path)["duration"] or 0
        if dur <= 0:
            times = [0.0]
        else:
            times = [dur * (i + 0.5) / n_frames for i in range(n_frames)]
    else:
        sys.exit("不支持的文件类型：%s" % path)
    out = []
    for t in times:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if t is not None:
            cmd += ["-ss", "%.3f" % t]
        cmd += ["-i", str(path), "-frames:v", "1", "-vf", "scale=%d:%d:flags=area,format=rgb24" % (W, H),
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        import subprocess
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0 or len(p.stdout) < W * H * 3:
            sys.exit("读取失败：%s\n%s" % (path, p.stderr.decode(errors="ignore")[-500:]))
        out.append(("%.1fs" % t if t is not None else "image", p.stdout[:W * H * 3]))
    return out


def srgb_to_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


LIN = [srgb_to_lin(float(i)) for i in range(256)]


def cct_duv_from_lin_rgb(r, g, b):
    """Return (CCT in K via McCamy, Duv via Ohno's polynomial). Duv > 0 = greenish, < 0 = magenta/pink."""
    X = 0.4124 * r + 0.3576 * g + 0.1805 * b
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    s = X + Y + Z
    if s <= 0:
        return None, 0.0
    x, y = X / s, Y / s
    n = (x - 0.3320) / (0.1858 - y)
    cct = 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33
    d = -2 * x + 12 * y + 3
    u, v = 4 * x / d, 6 * y / d
    lfp = math.hypot(u - 0.292, v - 0.24)
    a = math.acos(max(-1.0, min(1.0, (u - 0.292) / lfp))) if lfp else 0.0
    k = (-0.471106, 1.925865, -2.4243787, 1.5317403, -0.5179722, 0.0893944, -0.00616793)
    lbb = sum(c * a ** i for i, c in enumerate(k))
    return max(1000.0, min(cct, 40000.0)), lfp - lbb


def pct(sorted_vals, q):
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def stats(buf):
    lumas, sats = [], []
    neutral = [0.0, 0.0, 0.0, 0]
    allsum = [0.0, 0.0, 0.0]
    bins = {}
    for i in range(0, len(buf), 3):
        r, g, b = buf[i], buf[i + 1], buf[i + 2]
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        lumas.append(y)
        mx, mn = max(r, g, b), min(r, g, b)
        s = (mx - mn) / mx if mx else 0.0
        sats.append(s)
        lr, lg, lb = LIN[r], LIN[g], LIN[b]
        allsum[0] += lr; allsum[1] += lg; allsum[2] += lb
        if 40 <= y <= 230 and s < 0.35:
            neutral[0] += lr; neutral[1] += lg; neutral[2] += lb; neutral[3] += 1
        key = (r >> 5, g >> 5, b >> 5)
        bins[key] = bins.get(key, 0) + 1
    n = len(lumas)
    ls = sorted(lumas)
    if neutral[3] >= n * 0.03:
        nr, ng, nb = neutral[0] / neutral[3], neutral[1] / neutral[3], neutral[2] / neutral[3]
        src = "近中性像素 %d%%" % round(neutral[3] * 100 / n)
    else:
        nr, ng, nb = allsum[0] / n, allsum[1] / n, allsum[2] / n
        src = "近中性像素太少，改用全部像素，结果不可靠"
    cct, duv = cct_duv_from_lin_rgb(nr, ng, nb)
    tint = duv * 1000      # Duv x 1000: about +-6 starts to be visible
    # palette: merge 3-bit bins, keep the most populated distinct colours
    top = sorted(bins.items(), key=lambda kv: -kv[1])
    palette = []
    for (kr, kg, kb), cnt in top:
        c = (kr * 32 + 16, kg * 32 + 16, kb * 32 + 16)
        if any(sum((a - b) ** 2 for a, b in zip(c, p[0])) < 48 ** 2 for p in palette):
            for p in palette:
                if sum((a - b) ** 2 for a, b in zip(c, p[0])) < 48 ** 2:
                    p[1] += cnt
                    break
            continue
        palette.append([c, cnt])
        if len(palette) >= 6:
            break
    palette.sort(key=lambda p: -p[1])
    return {"luma": sum(lumas) / n, "p2": pct(ls, 0.02), "p98": pct(ls, 0.98), "black": pct(ls, 0.01),
            "white": pct(ls, 0.99), "sat": sum(sats) / n * 100, "cct": cct, "tint": tint, "cct_src": src,
            "palette": [("#%02X%02X%02X" % p[0], p[1] * 100 / n) for p in palette]}


def merge(sts):
    m = {}
    for k in ("luma", "p2", "p98", "black", "white", "sat", "tint"):
        m[k] = sum(s[k] for s in sts) / len(sts)
    ccts = [s["cct"] for s in sts if s["cct"]]
    # average in mired space (perceptually more even)
    m["cct"] = 1e6 / (sum(1e6 / c for c in ccts) / len(ccts)) if ccts else None
    m["cct_src"] = sts[0]["cct_src"]
    m["palette"] = sts[len(sts) // 2]["palette"]
    m["cct_spread"] = (max(ccts) - min(ccts)) if len(ccts) > 1 else 0
    m["luma_spread"] = max(s["luma"] for s in sts) - min(s["luma"] for s in sts)
    return m


def analyze_file(path, n_frames):
    return merge([stats(buf) for _, buf in raw_frames(path, n_frames)])


def describe(m):
    warm = m["cct"]
    if warm is None:
        wt = "未知"
    elif warm < 4000:
        wt = "明显偏暖"
    elif warm < 5200:
        wt = "偏暖"
    elif warm < 7000:
        wt = "中性"
    elif warm < 9000:
        wt = "偏冷"
    else:
        wt = "明显偏冷"
    contrast = m["p98"] - m["p2"]
    ct = "高反差" if contrast > 200 else ("低反差" if contrast < 120 else "中等反差")
    key = "高调" if m["luma"] > 150 else ("低调" if m["luma"] < 70 else "中间调")
    st = "高饱和" if m["sat"] > 45 else ("低饱和" if m["sat"] < 18 else "中等饱和")
    blk = "黑位压得较死" if m["black"] < 6 else ("暗部被提起（灰雾 / 胶片感）" if m["black"] > 25 else "黑位正常")
    tn = "偏绿" if m["tint"] > 6 else ("偏洋红" if m["tint"] < -6 else "无明显色偏")
    return "%s、%s、%s、%s、%s、%s" % (key, ct, st, wt, tn, blk)


def print_report(path, m):
    print("== %s" % path)
    print("  平均亮度 %.0f / 255　反差（2%%–98%%）%.0f–%.0f　黑位 %.0f　白位 %.0f"
          % (m["luma"], m["p2"], m["p98"], m["black"], m["white"]))
    print("  平均饱和度 %.0f%%　等效色温 %s（%s）　色偏 Duv %+.1f‰（正 = 偏绿，负 = 偏洋红，±6 以上可见）"
          % (m["sat"], "%.0fK" % m["cct"] if m["cct"] else "未知", m["cct_src"], m["tint"]))
    if m.get("cct_spread", 0) > 600 or m.get("luma_spread", 0) > 20:
        print("  ⚠️  这段视频内部变化较大：色温相差 %.0fK，亮度相差 %.0f。如果剧情里没有光线变化，可能是漂移"
              % (m["cct_spread"], m["luma_spread"]))
    print("  主要颜色：" + "  ".join("%s %.0f%%" % (h, p) for h, p in m["palette"]))
    print("  一句话：" + describe(m))


def write_swatch(hexes, out, block=120):
    """Write a colour strip via a temporary PPM converted by ffmpeg."""
    cols = []
    for h in hexes:
        h = h.strip().lstrip("#")
        if len(h) != 6:
            sys.exit("色值格式不对：%s（要写成 #RRGGBB）" % h)
        cols.append(tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)))
    w, hgt = block * len(cols), block
    row = bytearray()
    for c in cols:
        row += bytes(c) * block
    data = b"P6 %d %d 255\n" % (w, hgt) + bytes(row) * hgt
    with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    ffmpeg(["-i", tmp, out])
    Path(tmp).unlink()
    return out


def cmd_analyze(a):
    for f in a.files:
        m = analyze_file(f, a.frames)
        print_report(f, m)
        if a.swatch:
            out = str(Path(f).with_name(Path(f).stem + "_palette.png"))
            write_swatch([h for h, _ in m["palette"]], out)
            print("  色块条：%s" % out)
        print()


def mired(k):
    return 1e6 / k


def cmd_compare(a):
    ref = analyze_file(a.ref, a.frames)
    print_report(a.ref + "（基准）", ref)
    print()
    print("%-34s %8s %8s %8s %8s  %s" % ("文件", "色温差", "亮度差", "饱和差", "Duv差", "判断"))
    for f in a.files:
        m = analyze_file(f, a.frames)
        dm = mired(m["cct"]) - mired(ref["cct"]) if (m["cct"] and ref["cct"]) else 0.0
        dl = m["luma"] - ref["luma"]
        ds = m["sat"] - ref["sat"]
        dt = m["tint"] - ref["tint"]
        flags, fixes, eq = [], [], []
        if abs(dm) > 15:
            flags.append("偏暖" if dm > 0 else "偏冷")
            # warmer than ref (higher mired) -> cool it: colortemperature above 6500, and vice versa
            want = mired(6500) - dm
            target = 1e6 / want if want > 25 else 40000
            if want <= 25:
                flags.append("色温偏差过大，一次校正不够")
            fixes.append("colortemperature=temperature=%d:pl=1" % min(40000, max(1000, round(target, -2))))
        if abs(dl) > 8:
            flags.append("偏亮" if dl > 0 else "偏暗")
            eq.append("brightness=%.3f" % (-dl / 255 * 0.9))
        if abs(ds) > 6:
            flags.append("饱和度偏高" if ds > 0 else "饱和度偏低")
            if ref["sat"] >= 5 and m["sat"] >= 5:
                eq.append("saturation=%.2f" % min(1.6, max(0.5, ref["sat"] / m["sat"])))
        if eq:
            fixes.append("eq=" + ":".join(eq))
        if abs(dt) > 4:
            flags.append("偏绿" if dt > 0 else "偏洋红")
            fixes.append("colorchannelmixer=gg=%.3f" % max(0.8, min(1.2, 1 - dt * 0.0082)))
        name = f if len(f) <= 34 else "…" + f[-33:]
        print("%-34s %+7.0fM %+8.0f %+7.0f%% %+7.1f‰  %s" % (name, dm, dl, ds, dt, "、".join(flags) if flags else "一致"))
        if fixes:
            print("    校正起点：-vf \"%s\"" % ",".join(fixes))
    print("\n色温差用 mired（M = 1,000,000 / K）表示：正 = 比基准暖，负 = 比基准冷；约 10M 几乎看不出，20M 以上明显。")
    print("校正参数只是起点：调完再用 compare 量一次，并且人眼确认肤色。")


def cmd_swatch(a):
    out = a.o or "palette.png"
    write_swatch(a.hexes, out)
    print("色块条：%s（从左到右：%s）" % (out, " ".join(a.hexes)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze"); p.add_argument("files", nargs="+"); p.add_argument("--frames", type=int, default=5)
    p.add_argument("--swatch", action="store_true", help="同时输出主要颜色的色块条")
    p = sub.add_parser("compare"); p.add_argument("ref"); p.add_argument("files", nargs="+")
    p.add_argument("--frames", type=int, default=5)
    p = sub.add_parser("swatch"); p.add_argument("hexes", nargs="+"); p.add_argument("-o")
    a = ap.parse_args()
    need_ffmpeg()
    {"analyze": cmd_analyze, "compare": cmd_compare, "swatch": cmd_swatch}[a.cmd](a)


if __name__ == "__main__":
    main()
