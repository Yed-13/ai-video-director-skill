#!/usr/bin/env python3
"""Render a top-down camera floor plan for one scene and check the 180-degree rule.

  floorplan.py blocking/scene.json [-o out.png] [--svg]

Input JSON (meters; x to the right, y downward as seen from above):
  {"scene": "...", "size": [w, h],
   "characters": [{"id": "A", "name": "...", "pos": [x, y], "faces": "B" | [x, y] | degrees}],
   "axis": ["A", "B"]                       # or [[x1, y1], [x2, y2]] for a movement axis
   "props": [{"name": "...", "rect": [x, y, w, h]}],
   "cameras": [{"id": "s01", "pos": [x, y], "aim": "A" | [x, y], "fov": 45, "note": "...", "cross": false}]}

Outputs a PNG (needs Pillow) or SVG, and prints for every camera: which side of the axis it is on,
where each character lands in frame (left / center / right / out of frame), plus warnings when
consecutive cameras jump the axis or flip the left/right order of characters.
Cameras are checked in the order listed, so list them in shot order.
"""
import argparse
import json
import math
import sys
from pathlib import Path

PX = 90          # pixels per meter
MARGIN = 60
COLORS = {"bg": "#f4f2ea", "grid": "#e2ded2", "prop": "#d6cfbd", "ink": "#2b2b2b", "axis": "#b03a2e",
          "cam": "#3d5a80", "cam_cross": "#c77d00", "cone": "#3d5a80", "char": "#ffffff"}


# ---------- geometry ----------

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def norm(v):
    l = math.hypot(*v)
    return (v[0] / l, v[1] / l) if l else (0.0, 0.0)


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def rot(v, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def resolve_point(ref, chars):
    if isinstance(ref, str):
        if ref not in chars:
            sys.exit("找不到人物 id：%s" % ref)
        return tuple(chars[ref]["pos"])
    return tuple(ref)


def facing_vec(c, chars):
    f = c.get("faces")
    if f is None:
        return (1.0, 0.0)
    if isinstance(f, (int, float)):
        return rot((1.0, 0.0), f)          # degrees, clockwise on screen because y points down
    return norm(sub(resolve_point(f, chars), c["pos"]))


def screen_pos(cam_pos, aim_dir, fov, p):
    """Return (in_front, x_norm) where x_norm in [-1, 1] spans the horizontal field of view."""
    v = sub(p, cam_pos)
    fwd = dot(v, aim_dir)
    right = (-aim_dir[1], aim_dir[0])     # camera's right-hand side, y-down coordinates
    lat = dot(v, right)
    if fwd <= 1e-6:
        return False, None
    return True, (lat / fwd) / math.tan(math.radians(fov) / 2)


def side_of_axis(axis, p, eps=0.15):
    a, b = axis
    d = cross(sub(b, a), sub(p, a)) / (math.hypot(*sub(b, a)) or 1)
    if abs(d) < eps:
        return 0
    return 1 if d > 0 else -1


# ---------- drawing backends ----------

class Canvas:
    def __init__(self, w, h):
        self.w, self.h, self.ops = w, h, []

    def line(self, a, b, color, width=2, dash=None):
        self.ops.append(("line", a, b, color, width, dash))

    def poly(self, pts, fill, outline=None, alpha=255):
        self.ops.append(("poly", pts, fill, outline, alpha))

    def circle(self, c, r, fill, outline):
        self.ops.append(("circle", c, r, fill, outline))

    def text(self, p, s, color, size=16, anchor="mm"):
        self.ops.append(("text", p, s, color, size, anchor))


def dashed(a, b, dash):
    on, off = dash
    L = math.hypot(*sub(b, a))
    if L == 0:
        return []
    u = norm(sub(b, a))
    segs, t = [], 0.0
    while t < L:
        e = min(t + on, L)
        segs.append(((a[0] + u[0] * t, a[1] + u[1] * t), (a[0] + u[0] * e, a[1] + u[1] * e)))
        t = e + off
    return segs


def find_font(size):
    from PIL import ImageFont
    for f in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/STHeiti Medium.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/msyh.ttc"):
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default()


def hex_rgba(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def save_png(cv, path):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (cv.w, cv.h), hex_rgba(COLORS["bg"]))
    overlay = Image.new("RGBA", (cv.w, cv.h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fonts = {}
    for op in cv.ops:
        if op[0] == "poly" and op[4] < 255:
            od.polygon(op[1], fill=hex_rgba(op[2], op[4]))
    img = Image.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img)
    for op in cv.ops:
        kind = op[0]
        if kind == "line":
            _, a, b, color, width, dash = op
            for s, e in (dashed(a, b, dash) if dash else [(a, b)]):
                d.line([s, e], fill=hex_rgba(color), width=width)
        elif kind == "poly" and op[4] == 255:
            d.polygon(op[1], fill=hex_rgba(op[2]), outline=hex_rgba(op[3]) if op[3] else None)
        elif kind == "circle":
            _, c, r, fill, outline = op
            d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=hex_rgba(fill), outline=hex_rgba(outline), width=3)
        elif kind == "text":
            _, p, s, color, size, anchor = op
            if size not in fonts:
                fonts[size] = find_font(size)
            try:
                d.text(p, s, fill=hex_rgba(color), font=fonts[size], anchor=anchor)
            except (TypeError, ValueError):
                d.text(p, s, fill=hex_rgba(color), font=fonts[size])
    img.convert("RGB").save(path)


def save_svg(cv, path):
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    anchors = {"m": "middle", "l": "start", "r": "end"}
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (cv.w, cv.h, cv.w, cv.h),
           '<rect width="100%%" height="100%%" fill="%s"/>' % COLORS["bg"]]
    for op in cv.ops:
        kind = op[0]
        if kind == "line":
            _, a, b, color, width, dash = op
            da = ' stroke-dasharray="%d %d"' % dash if dash else ""
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%d"%s/>'
                       % (a[0], a[1], b[0], b[1], color, width, da))
        elif kind == "poly":
            _, pts, fill, outline, alpha = op
            out.append('<polygon points="%s" fill="%s" fill-opacity="%.2f"%s/>' % (
                " ".join("%.1f,%.1f" % p for p in pts), fill, alpha / 255,
                ' stroke="%s"' % outline if outline else ""))
        elif kind == "circle":
            _, c, r, fill, outline = op
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="3"/>' % (c[0], c[1], r, fill, outline))
        elif kind == "text":
            _, p, s, color, size, anchor = op
            out.append('<text x="%.1f" y="%.1f" fill="%s" font-size="%d" text-anchor="%s" dominant-baseline="middle" '
                       'font-family="PingFang SC, Noto Sans CJK SC, sans-serif">%s</text>'
                       % (p[0], p[1], color, size, anchors.get(anchor[0], "middle"), esc(s)))
    out.append("</svg>")
    Path(path).write_text("\n".join(out), encoding="utf-8")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("-o", help="输出路径（.png 或 .svg）")
    ap.add_argument("--svg", action="store_true", help="强制输出 SVG")
    a = ap.parse_args()

    spec = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    W, H = spec.get("size", [10, 6])
    chars = {c["id"]: c for c in spec.get("characters", [])}
    for c in chars.values():
        c["pos"] = tuple(c["pos"])
    cams = spec.get("cameras", [])

    axis = None
    if spec.get("axis"):
        ax = spec["axis"]
        axis = (resolve_point(ax[0], chars), resolve_point(ax[1], chars))

    def P(p):
        return (MARGIN + p[0] * PX, MARGIN + p[1] * PX)

    cw, ch = int(W * PX + 2 * MARGIN), int(H * PX + 2 * MARGIN + 30)
    cv = Canvas(cw, ch)
    for gx in range(int(W) + 1):
        cv.line(P((gx, 0)), P((gx, H)), COLORS["grid"], 1)
    for gy in range(int(H) + 1):
        cv.line(P((0, gy)), P((W, gy)), COLORS["grid"], 1)
    cv.text((MARGIN, MARGIN / 2), "%s  （俯视，1 格 = 1 米）" % spec.get("scene", ""), COLORS["ink"], 20, "lm")

    for pr in spec.get("props", []):
        x, y, w, h = pr["rect"]
        cv.poly([P((x, y)), P((x + w, y)), P((x + w, y + h)), P((x, y + h))], COLORS["prop"], "#b8ae96")
        cv.text(P((x + w / 2, y + h / 2)), pr.get("name", ""), "#6b6250", 14)

    # axis: extend across the whole plan
    if axis:
        u = norm(sub(axis[1], axis[0]))
        far = W + H
        a0 = (axis[0][0] - u[0] * far, axis[0][1] - u[1] * far)
        a1 = (axis[1][0] + u[0] * far, axis[1][1] + u[1] * far)
        cv.line(P(a0), P(a1), COLORS["axis"], 2, (10, 7))
        lab = (min(max(axis[1][0] + u[0] * 1.2, 0.3), W - 0.3), min(max(axis[1][1] + u[1] * 1.2 - 0.3, 0.2), H - 0.2))
        cv.text(P(lab), "轴线", COLORS["axis"], 16)

    # camera cones first (so characters stay on top)
    cam_info, cones = [], []
    for cam in cams:
        pos = tuple(cam["pos"])
        aim_pt = resolve_point(cam.get("aim", [pos[0], pos[1] - 1]), chars)
        d = norm(sub(aim_pt, pos))
        fov = float(cam.get("fov", 45))
        reach = min(max(math.hypot(*sub(aim_pt, pos)) * 1.1, 1.0), max(W, H) * 0.5)
        l = rot(d, -fov / 2)
        r = rot(d, fov / 2)
        color = COLORS["cam_cross"] if cam.get("cross") else COLORS["cone"]
        pl = (pos[0] + l[0] * reach, pos[1] + l[1] * reach)
        pr_ = (pos[0] + r[0] * reach, pos[1] + r[1] * reach)
        cones.append(([P(pos), P(pl), P(pr_)], color))
        cam_info.append((cam, pos, d, fov))

    for pts, color in cones:
        cv.poly(pts, color, None, 18)
    for pts, color in cones:
        cv.line(pts[0], pts[1], color, 1, (4, 4))
        cv.line(pts[0], pts[2], color, 1, (4, 4))
    for cid, c in chars.items():
        f = facing_vec(c, chars)
        cpx = P(c["pos"])
        R = 0.32 * PX
        tip = (cpx[0] + f[0] * R * 1.55, cpx[1] + f[1] * R * 1.55)
        s1 = rot(f, 90)
        b1 = (cpx[0] + f[0] * R * 0.9 + s1[0] * R * 0.45, cpx[1] + f[1] * R * 0.9 + s1[1] * R * 0.45)
        b2 = (cpx[0] + f[0] * R * 0.9 - s1[0] * R * 0.45, cpx[1] + f[1] * R * 0.9 - s1[1] * R * 0.45)
        cv.poly([tip, b1, b2], COLORS["char"], COLORS["ink"])
        cv.circle(cpx, R, COLORS["char"], COLORS["ink"])
        cv.text(cpx, cid, COLORS["ink"], 20)
        if c.get("name"):
            cv.text((cpx[0], cpx[1] - R - 14), c["name"], COLORS["ink"], 14)

    placed = []
    for cam, pos, d, fov in cam_info:
        color = COLORS["cam_cross"] if cam.get("cross") else COLORS["cam"]
        c = P(pos)
        s = rot(d, 90)
        bw, bl = 0.22 * PX, 0.32 * PX
        back = (c[0] - d[0] * bl, c[1] - d[1] * bl)
        body = [(back[0] + s[0] * bw / 2, back[1] + s[1] * bw / 2), (c[0] + s[0] * bw / 2, c[1] + s[1] * bw / 2),
                (c[0] - s[0] * bw / 2, c[1] - s[1] * bw / 2), (back[0] - s[0] * bw / 2, back[1] - s[1] * bw / 2)]
        cv.poly(body, color, None)
        lens = [(c[0] + d[0] * bl * 0.7, c[1] + d[1] * bl * 0.7),
                (c[0] + s[0] * bw * 0.55, c[1] + s[1] * bw * 0.55),
                (c[0] - s[0] * bw * 0.55, c[1] - s[1] * bw * 0.55)]
        cv.poly(lens, color, None)
        lab = (c[0] - d[0] * bl * 1.9, c[1] - d[1] * bl * 1.9)
        for _ in range(8):
            clash = next((q for q in placed if math.hypot(lab[0] - q[0], lab[1] - q[1]) < 26), None)
            if not clash:
                break
            away = norm(sub(lab, clash)) if lab != clash else (s[0], s[1])
            lab = (lab[0] + away[0] * 14, lab[1] + away[1] * 14)
        placed.append(lab)
        cv.text(lab, cam["id"], color, 17)

    cv.text((MARGIN, ch - 22), "圆圈加三角 = 人物和朝向；方块加三角 = 机位（数字 = 镜头号），虚线扇形 = 视角；红色虚线 = 轴线；橙色 = 有意越轴",
            "#6b6250", 13, "lm")

    out = Path(a.o) if a.o else Path(a.plan).with_suffix(".png")
    use_svg = a.svg or out.suffix.lower() == ".svg"
    if not use_svg:
        try:
            import PIL  # noqa: F401
        except ImportError:
            use_svg = True
            print("没有安装 Pillow，改为输出 SVG")
    if use_svg:
        out = out.with_suffix(".svg")
        save_svg(cv, out)
    else:
        save_png(cv, out)

    # ---------- report ----------
    print("机位图：%s\n" % out)
    names = list(chars)
    header = "%-6s %-8s %s" % ("镜头", "轴线侧", "  ".join("%s:画面位置" % n for n in names))
    print(header)
    rows = []
    main_side = None
    if axis:
        main_side = next((side_of_axis(axis, c[1]) for c in cam_info if side_of_axis(axis, c[1]) != 0), None)
    for cam, pos, d, fov in cam_info:
        side = side_of_axis(axis, pos) if axis else None
        if not axis:
            side_txt = "-"
        elif side == 0:
            side_txt = "骑轴"
        else:
            side_txt = "主侧" if side == main_side else "对侧"
        place, xs = [], {}
        for n in names:
            ok, x = screen_pos(pos, d, fov, chars[n]["pos"])
            if not ok:
                place.append("身后")
            elif abs(x) > 1.0:
                place.append("画外" + ("右" if x > 0 else "左"))
                xs[n] = x
            else:
                xs[n] = x
                place.append("%s(%d%%)" % ("左" if x < -0.25 else ("右" if x > 0.25 else "中"), round((x + 1) * 50)))
        rows.append((cam, side, xs))
        print("%-6s %-8s %s   %s" % (cam["id"], side_txt, "  ".join("%-10s" % p for p in place), cam.get("note", "")))

    print()
    warns = 0
    # 180-degree rule: compare every camera with the side established so far;
    # a camera marked "cross": true legitimately establishes the new side.
    if axis:
        established = None
        for cam, side, xs in rows:
            if side == 0:
                continue
            if established is None:
                established = (side, cam["id"])
            elif side != established[0]:
                if cam.get("cross"):
                    established = (side, cam["id"])
                else:
                    print("⚠️  越轴：%s 在轴线的另一侧（这场戏由 %s 建立的是另一侧）。如果是有意的，写明越轴办法并加 \"cross\": true"
                          % (cam["id"], established[1]))
                    warns += 1
    # screen order: characters in front of the camera (in frame or just outside) keep their left/right order
    order = {}
    for cam, side, xs in rows:
        front = [n for n in names if n in xs]
        for i in range(len(front)):
            for j in range(i + 1, len(front)):
                pq = (front[i], front[j])
                sign = 1 if xs[pq[0]] < xs[pq[1]] else -1
                if pq in order and order[pq][0] != sign and not cam.get("cross"):
                    print("⚠️  左右对调：%s 里 %s 和 %s 的左右顺序和 %s 相反" % (cam["id"], pq[0], pq[1], order[pq][1]))
                    warns += 1
                elif pq not in order or cam.get("cross"):
                    order[pq] = (sign, cam["id"])
    if not warns:
        print("没有发现越轴或左右对调。")
    print("\n“画面位置”的百分比是从画面左边缘算起的横向位置，写首尾帧和视频提示词时直接引用。")


if __name__ == "__main__":
    main()
