#!/usr/bin/env python3
"""Inspect a generated clip returned by the user (ffmpeg only).

  clip.py inspect CLIP [--first first.png] [--last last.png] [--out DIR] [--every 0.5]
  clip.py stills CLIP (--every 0.5 | --at 1.2,3.4) [--out DIR]

inspect writes: info.txt, contact.jpg (12 frames), first_frame.png, last_frame.png,
SSIM against the intended keyframes, drift.csv + drift.txt (per-frame luma / saturation),
and frames/ (one full-res frame every --every seconds).
Default output: <shot>/review/<clip stem>/ when the clip sits in <shot>/takes/.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _media import count_frames, ffmpeg, need_ffmpeg, probe, run, ssim  # noqa: E402


def default_out(clip):
    clip = Path(clip).resolve()
    if clip.parent.name == "takes":
        return clip.parent.parent / "review" / clip.stem
    return clip.parent / (clip.stem + "_review")


def extract_frame(clip, index, dst):
    ffmpeg(["-i", clip, "-vf", "select=eq(n\\,%d)" % index, "-frames:v", "1", dst])


def drift(clip):
    """Per-frame YAVG / SATAVG via signalstats; returns list of (frame, yavg, satavg)."""
    p = run(["ffmpeg", "-hide_banner", "-i", str(clip), "-vf",
             "signalstats,metadata=mode=print", "-an", "-f", "null", "-"], check=False)
    rows, cur = [], {}
    for line in p.stderr.splitlines():
        m = re.search(r"frame:(\d+)", line)
        if m:
            if cur.get("f") is not None and "y" in cur and "s" in cur:
                rows.append((cur["f"], cur["y"], cur["s"]))
            cur = {"f": int(m.group(1))}
            continue
        m = re.search(r"lavfi\.signalstats\.YAVG=([\d.]+)", line)
        if m:
            cur["y"] = float(m.group(1))
        m = re.search(r"lavfi\.signalstats\.SATAVG=([\d.]+)", line)
        if m:
            cur["s"] = float(m.group(1))
    if cur.get("f") is not None and "y" in cur and "s" in cur:
        rows.append((cur["f"], cur["y"], cur["s"]))
    return rows


def pct(a, b):
    return (b - a) / a * 100 if a else 0.0


def cmd_inspect(a):
    clip = Path(a.clip).resolve()
    info = probe(clip)
    if not info["width"]:
        sys.exit("%s 里没有视频流，无法检查" % clip.name)
    out = Path(a.out).resolve() if a.out else default_out(clip)
    if out.exists() and any(out.iterdir()):
        k = 2
        while out.with_name("%s_run%d" % (out.name, k)).exists():
            k += 1
        out = out.with_name("%s_run%d" % (out.name, k))
        print("之前的检查结果保留不动，这次输出到 %s" % out.name)
    out.mkdir(parents=True, exist_ok=True)
    n = count_frames(clip) or info["nb_frames"] or 0
    lines = [
        "文件：%s" % clip.name,
        "分辨率：%sx%s　帧率：%.3f　时长：%.3f 秒　帧数：%s" % (info["width"], info["height"], info["fps"] or 0,
                                                      info["duration"] or 0, n),
        "视频编码：%s　色彩标注（space/primaries/trc）：%s" % (info["vcodec"], info["color"]),
        "音轨：%s" % ("有（需要人听过才能决定用不用）" if info["has_audio"] else "无"),
        "大小：%.1f MB" % info["size_mb"],
    ]
    if "unknown" in (info["color"] or "") or "?" in (info["color"] or ""):
        lines.append("提示：没有色彩标注，后期按 BT.601 解码（见 references/08-post.md）")

    # contact sheet
    dur = info["duration"] or 1
    ffmpeg(["-i", clip, "-vf", "fps=12/%.4f,scale=480:-2,tile=4x3:padding=4:color=white" % dur,
            "-frames:v", "1", "-q:v", "3", out / "contact.jpg"])

    # first / last frame + similarity to intended keyframes
    extract_frame(clip, 0, out / "first_frame.png")
    if n:
        extract_frame(clip, n - 1, out / "last_frame.png")
    w, h = info["width"], info["height"]
    for label, ours, ref in (("首帧", out / "first_frame.png", a.first), ("尾帧", out / "last_frame.png", a.last)):
        if ref and not Path(ref).exists():
            lines.append("⚠️  找不到用来对比的%s：%s" % (label, ref))
            continue
        if ref and Path(ref).exists() and ours.exists():
            s = ssim(ours, ref, w, h)
            if s is not None:
                verdict = "很接近" if s >= 0.85 else ("有差异，放大对比" if s >= 0.7 else "差异明显，重点检查")
                lines.append("%s 与 %s 的 SSIM = %.3f（%s）" % (label, Path(ref).name, s, verdict))
            # also near-end frames: model may jump to last frame in final frames
            if label == "尾帧" and n > 8:
                extract_frame(clip, max(n - 8, 0), out / "last_minus7.png")
                s2 = ssim(out / "last_minus7.png", ref, w, h)
                if s2 is not None and s is not None and s - s2 > 0.1:
                    lines.append("⚠️  最后 8 帧内和尾帧的相似度突然上升（%.3f → %.3f），可能是结尾突然跳到尾帧，检查最后几帧"
                                 % (s2, s))

    # first-frame sharpness jump: compare frame 0 vs 1 vs 2
    if n > 3:
        extract_frame(clip, 1, out / "_f1.png")
        extract_frame(clip, 2, out / "_f2.png")
        s01 = ssim(out / "first_frame.png", out / "_f1.png", w, h)
        s12 = ssim(out / "_f1.png", out / "_f2.png", w, h)
        if s01 is not None and s12 is not None and s12 - s01 > 0.05:
            lines.append("⚠️  第 0 帧和后面的帧差异偏大（SSIM %.3f vs %.3f），可能是第一帧特别锐，考虑去掉第一帧" % (s01, s12))
        for t in ("_f1.png", "_f2.png"):
            (out / t).unlink()

    # drift
    rows = drift(clip)
    if rows:
        with open(out / "drift.csv", "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["frame", "luma_avg", "sat_avg"])
            wr.writerows(rows)
        k = max(1, len(rows) // 10)
        y0 = sum(r[1] for r in rows[:k]) / k
        y1 = sum(r[1] for r in rows[-k:]) / k
        s0 = sum(r[2] for r in rows[:k]) / k
        s1 = sum(r[2] for r in rows[-k:]) / k
        d = ["开头 10% 帧 → 结尾 10% 帧：", "  平均亮度 %.1f → %.1f（%+.1f%%）" % (y0, y1, pct(y0, y1)),
             "  平均饱和度 %.1f → %.1f（%+.1f%%）" % (s0, s1, pct(s0, s1))]
        if abs(pct(y0, y1)) > 5 or abs(pct(s0, s1)) > 8:
            d.append("⚠️  漂移超过阈值（亮度 ±5% / 饱和度 ±8%）。如果剧情里没有光线变化，后期要按首帧校色。")
        else:
            d.append("漂移在阈值以内。")
        (out / "drift.txt").write_text("\n".join(d) + "\n", encoding="utf-8")
        lines += d

    # stills
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    ffmpeg(["-i", clip, "-vf", "fps=1/%s" % a.every, frames / "t%03d.png"])
    lines.append("全分辨率抽帧（每 %s 秒一张）：%s" % (a.every, frames))
    lines.append("")
    lines.append("这份报告只覆盖画面的静态检查。动作是否流畅、节奏和声音，需要人看过、听过才能确认。")

    (out / "info.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("\n输出目录：%s（先看 contact.jpg）" % out)


def cmd_stills(a):
    clip = Path(a.clip).resolve()
    out = Path(a.out).resolve() if a.out else clip.parent / (clip.stem + "_stills")
    out.mkdir(parents=True, exist_ok=True)
    if a.at:
        for t in a.at.split(","):
            t = float(t)
            ffmpeg(["-ss", "%.3f" % t, "-i", clip, "-frames:v", "1", out / ("at_%06.2fs.png" % t)])
    else:
        ffmpeg(["-i", clip, "-vf", "fps=1/%s" % (a.every or 0.5), out / "t%03d.png"])
    print("已输出到 %s" % out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("clip"); p.add_argument("--first"); p.add_argument("--last"); p.add_argument("--out")
    p.add_argument("--every", default="0.5")
    p = sub.add_parser("stills")
    p.add_argument("clip"); p.add_argument("--every"); p.add_argument("--at"); p.add_argument("--out")
    a = ap.parse_args()
    need_ffmpeg()
    {"inspect": cmd_inspect, "stills": cmd_stills}[a.cmd](a)


if __name__ == "__main__":
    main()
