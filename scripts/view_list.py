#!/usr/bin/env python3
"""Per-camera view list from a blocking JSON (same file floorplan.py reads).

  view_list.py blocking/<场景>.json [--camera s02]

For each camera: every prop, character and wall, whether it is in frame, where it sits
horizontally (左 / 中 / 右, -1 .. +1) and how far away. Paste the result into the
VIEW[机位] part of keyframe and video prompts so each angle shows the same room.
Plan is top-down, x to the right (east), y downward (south), units in metres.
"""
import argparse
import json
import math


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--camera", help="只看这一个机位 id")
    a = ap.parse_args()
    d = json.load(open(a.scene, encoding="utf-8"))
    width, height = d["size"]
    chars = {c["id"]: c for c in d.get("characters", [])}
    walls = {"北墙": ((0, 0), (width, 0)), "东墙": ((width, 0), (width, height)),
             "南墙": ((width, height), (0, height)), "西墙": ((0, height), (0, 0))}

    def point(v):
        return chars[v]["pos"] if isinstance(v, str) else v

    for cam in d["cameras"]:
        if a.camera and cam["id"] != a.camera:
            continue
        cx, cy = cam["pos"]
        ax, ay = point(cam["aim"])
        yaw = math.atan2(ay - cy, ax - cx)
        half = math.radians(cam.get("fov", 45)) / 2

        def where(x, y):
            ang = (math.atan2(y - cy, x - cx) - yaw + math.pi) % (2 * math.pi) - math.pi
            dist = math.hypot(x - cx, y - cy)
            if abs(ang) > half:
                return None, dist, ang
            u = ang / half
            return "%s(%+.2f)" % ("左" if u < -0.33 else "右" if u > 0.33 else "中", u), dist, ang

        print("== %s  %s" % (cam["id"], cam.get("note", "")))
        for p in d.get("props", []):
            x, y, w, h = p["rect"]
            seen = [r for r in (where(x + w * i / 4, y + h * j / 4) for i in range(5) for j in range(5)) if r[0]]
            if not seen:
                print("  画外        %s" % p["name"])
                continue
            us = sorted(r[2] / half for r in seen)
            print("  %-10s 横向 %+.2f..%+.2f  约 %.1f 米  %s"
                  % (seen[len(seen) // 2][0], us[0], us[-1], min(r[1] for r in seen), p["name"]))
        for c in d.get("characters", []):
            pos, dist, _ = where(*c["pos"])
            print("  %-10s 约 %.1f 米  [人] %s" % (pos or "画外", dist, c.get("name", c["id"])))
        for name, (p0, p1) in walls.items():
            seen = [r for r in (where(p0[0] + (p1[0] - p0[0]) * t / 10, p0[1] + (p1[1] - p0[1]) * t / 10)
                                for t in range(11)) if r[0]]
            if seen:
                print("  墙 %s：画面横向 %+.2f..%+.2f"
                      % (name, min(r[2] for r in seen) / half, max(r[2] for r in seen) / half))


if __name__ == "__main__":
    main()
