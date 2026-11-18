#!/usr/bin/env python3
"""Scene-level helpers: stills animatic, tail clip for continuation, cut / voice / mouth checks (ffmpeg only).

  scene.py animatic OUT.mp4 IMG:SEC [IMG:SEC ...] [--audio a.wav] [--size 1920x1080]
  scene.py tail CLIP [--seconds 4] [--height 1080] [-o OUT.mp4]
  scene.py cuts CLIP [--threshold 0.3] [--plan 5,10]
  scene.py seam A.mp4 B.mp4 [--threshold 0.3]
  scene.py voice CLIP [--window 0.1] [--drop 20]
  scene.py spectro CLIP [-o OUT.png] [--top 8000]
  scene.py strip CLIP --crop W:H:X:Y [--every 0.25] [--start S] [--end E] [-o OUT.jpg]

animatic  首帧样片：按顺序把静帧各停几秒拼成一条，生成前看叙事和衔接。
tail      截上一场成片最后几秒，做下一场的 @视频1（接着往下拍）。
cuts      检测切点，可和计划的切点对比。
seam      两段接起来后检查接缝：A 尾帧信息量、接缝处场景得分、A 尾帧和 B 首帧的相似度。
voice    300-3500 Hz 带通后的 RMS 包络，列出有人声的时间段。
spectro   频谱图：有清楚谐波是正常发声，只有噪声带是耳语或气声。
strip     裁一块（比如嘴部）按时间排成一行，看不说话的人嘴动没动。
"""
import argparse
import re
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _media import ffmpeg, need_ffmpeg, probe, run, ssim  # noqa: E402


def cmd_animatic(a):
    items = []
    for spec in a.items:
        path, _, sec = spec.rpartition(":")
        try:
            sec = float(sec)
        except ValueError:
            sys.exit("写成 图片路径:秒数，例如 shots/s01/first.png:3.5（出错的是 %s）" % spec)
        if not Path(path).exists():
            sys.exit("找不到 %s" % path)
        items.append((path, sec))
    if a.size:
        w, h = (int(v) for v in a.size.lower().split("x"))
    else:
        info = probe(items[0][0])
        w, h = info["width"] // 2 * 2, info["height"] // 2 * 2
    args, chains = [], []
    for i, (path, sec) in enumerate(items):
        args += ["-loop", "1", "-t", "%.3f" % sec, "-i", path]
        chains.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,"
                      "setsar=1,fps=24,format=yuv420p[v%d]" % (i, w, h, w, h, i))
    graph = ";".join(chains) + ";" + "".join("[v%d]" % i for i in range(len(items))) + \
        "concat=n=%d:v=1:a=0[v]" % len(items)
    out_args = ["-filter_complex", graph, "-map", "[v]"]
    if a.audio:
        args += ["-i", a.audio]
        out_args += ["-map", "%d:a" % len(items), "-c:a", "aac", "-b:a", "192k", "-shortest"]
    ffmpeg(args + out_args + ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", a.out])
    t = 0.0
    print("样片：%s（%dx%d）" % (a.out, w, h))
    for path, sec in items:
        print("  %6.2f - %6.2f  %s" % (t, t + sec, path))
        t += sec
    print("  合计 %.2f 秒" % t)


def cmd_tail(a):
    info = probe(a.clip)
    sec = min(a.seconds, info["duration"] or a.seconds)
    out = a.out or str(Path(a.clip).with_name(Path(a.clip).stem + "_tail%ds.mp4" % round(sec)))
    args = ["-sseof", "-%.3f" % sec, "-i", a.clip, "-vf", "scale=-2:%d" % a.height,
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "aac", "-b:a", "192k"] if info["has_audio"] else ["-an"]
    ffmpeg(args + [out])
    o = probe(out)
    print("%s  %.2f 秒  %dx%d  %.1f MB" % (out, o["duration"], o["width"], o["height"], o["size_mb"]))
    if o["size_mb"] >= 50:
        print("超过 50 MB，上传前把 --height 调小。")


def cmd_cuts(a):
    p = run(["ffmpeg", "-hide_banner", "-i", a.clip, "-vf",
             "select='gt(scene,%s)',showinfo" % a.threshold, "-an", "-f", "null", "-"], check=False)
    cuts = [float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", p.stderr)]
    dur = probe(a.clip)["duration"]
    print("%s  时长 %.2f 秒，检测到 %d 个切点（阈值 %s）" % (a.clip, dur, len(cuts), a.threshold))
    for c in cuts:
        print("  %.2f 秒" % c)
    if a.plan:
        plan = [float(v) for v in a.plan.split(",") if v.strip()]
        print("和计划对比：")
        for want in plan:
            near = min(cuts, key=lambda c: abs(c - want)) if cuts else None
            if near is None or abs(near - want) > 3:
                print("  计划 %.2f 秒：没找到对应切点" % want)
            else:
                print("  计划 %.2f 秒 -> 实际 %.2f 秒（%+.2f）" % (want, near, near - want))
        if len(cuts) != len(plan):
            print("  切点数量和计划不同：计划 %d，实际 %d" % (len(plan), len(cuts)))


def cmd_seam(a):
    """A、B 两段接起来后：A 尾帧信息量、接缝处场景得分、A 尾帧和 B 首帧的相似度。"""
    ia, ib = probe(a.a), probe(a.b)
    w, h = ia["width"] // 2 * 2, ia["height"] // 2 * 2
    with tempfile.TemporaryDirectory(prefix="seam_") as tmp:
        tmp = Path(tmp)
        last, first = tmp / "a_last.jpg", tmp / "b_first.jpg"
        ffmpeg(["-sseof", "-0.2", "-i", a.a, "-vf", "scale=%d:%d" % (w, h), "-update", "1", "-q:v", "3", last])
        ffmpeg(["-i", a.b, "-vf", "scale=%d:%d" % (w, h), "-frames:v", "1", "-q:v", "3", first])
        ffmpeg(["-sseof", "-2.5", "-t", "2", "-i", a.a, "-vf", "fps=6,scale=%d:%d" % (w, h),
                "-q:v", "3", str(tmp / "t_%03d.jpg")])
        base = sorted((p.stat().st_size for p in tmp.glob("t_*.jpg")))
        last_kb = last.stat().st_size / 1024
        s = ssim(last, first, w, h)
    print("A：%s  %.2f 秒    B：%s  %.2f 秒" % (a.a, ia["duration"], a.b, ib["duration"]))
    ratio = 1.0
    if base:
        med = statistics.median(base) / 1024
        ratio = last_kb / med if med else 1
        print("尾帧信息量：A 最后一帧 %.1f KB；A 倒数 2.5–0.5 秒的帧中位数 %.1f KB（比值 %.2f）" % (last_kb, med, ratio))
        print("  " + ("明显更小：画面接近被盖满或变暗，适合遮挡转场" if ratio < 0.4 else
                      "没有明显变小：做遮挡转场的话，A 结尾还没被遮挡物盖满"))
    if s is not None:
        print("A 尾帧和 B 首帧 SSIM %.3f  " % s + ("接得上" if s >= 0.9 else "差距较大：B 首帧不是 A 的尾帧，或 B 一开始就大幅运动") +
              ("（尾帧很暗时 SSIM 不可靠，以接缝得分为准）" if ratio < 0.4 else ""))
    graph = ("[0:v]scale=%d:%d,fps=24,setsar=1[a];[1:v]scale=%d:%d,fps=24,setsar=1[b];"
             "[a][b]concat=n=2:v=1:a=0,select='gte(scene,0)',metadata=print:key=lavfi.scene_score" % (w, h, w, h))
    p = run(["ffmpeg", "-hide_banner", "-i", a.a, "-i", a.b, "-filter_complex", graph, "-an", "-f", "null", "-"],
            check=False)
    times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", p.stderr)]
    scores = [float(m) for m in re.findall(r"lavfi\.scene_score=([\d.]+)", p.stderr)]
    rows = list(zip(times, scores))
    if not rows:
        print("没有读到场景得分（ffmpeg 版本不支持 metadata 输出？）")
        return
    seam = max((sc for t, sc in rows if abs(t - ia["duration"]) <= 0.1), default=None)
    near = max((sc for t, sc in rows if 0.1 < abs(t - ia["duration"]) <= 1.0), default=0.0)
    thr = float(a.threshold)
    if seam is None:
        print("没找到接缝处的帧")
        return
    print("接缝得分 %.3f（硬切阈值 %s；前后 1 秒内其他帧最高 %.3f）  " % (seam, a.threshold, near) +
          ("低于硬切阈值：接缝不明显" if seam < thr else "高于硬切阈值：接缝能看出来，检查方向、速度、光色"))
    print("得分和 SSIM 只是参考，最后抽接缝前后各 3 帧（clip.py stills）和实际播放确认。")


def cmd_voice(a):
    if not probe(a.clip)["has_audio"]:
        sys.exit("这个文件没有音轨")
    n = max(1, int(16000 * a.window))
    p = run(["ffmpeg", "-hide_banner", "-i", a.clip, "-vn", "-af",
             "aresample=16000,highpass=f=300,lowpass=f=3500,asetnsamples=n=%d:p=0,"
             "astats=metadata=1:reset=1,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level" % n,
             "-f", "null", "-"], check=False)
    rows, t = [], None
    for line in p.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[\d.]+|-inf)", line)
        if m and t is not None:
            rows.append((t, -120.0 if m.group(1) == "-inf" else float(m.group(1))))
    if not rows:
        sys.exit("没有量到音量数据")
    peak = max(v for _, v in rows)
    gate = max(peak - a.drop, -55.0)
    segs, start, last = [], None, None
    for t, v in rows:
        if v >= gate:
            if start is None:
                start = t
            last = t
        elif start is not None and t - last > 0.25:
            segs.append((start, last + a.window))
            start = None
    if start is not None:
        segs.append((start, last + a.window))
    print("%s  人声频段峰值 %.1f dB，门限 %.1f dB" % (a.clip, peak, gate))
    for s, e in segs:
        print("  %6.2f - %6.2f 秒（%.2f 秒）" % (s, e, e - s))
    print("只能看出什么时候有声音，判断不了字对不对，也分不清人声和同频段的音乐。")


def cmd_spectro(a):
    if not probe(a.clip)["has_audio"]:
        sys.exit("这个文件没有音轨")
    out = a.out or str(Path(a.clip).with_name(Path(a.clip).stem + "_spectro.png"))
    ffmpeg(["-i", a.clip, "-lavfi",
            "aresample=%d,showspectrumpic=s=1600x600:legend=1:scale=log" % (a.top * 2), "-frames:v", "1", out])
    print("%s（纵轴 0-%d Hz）：平行的谐波条纹是正常发声；只有一片噪声带是耳语或气声；"
          "贯穿全片的水平细线多半是配乐或空调声。" % (out, a.top))


def cmd_strip(a):
    info = probe(a.clip)
    start = a.start or 0.0
    end = a.end if a.end is not None else info["duration"]
    n = max(1, int((end - start) / a.every))
    out = a.out or str(Path(a.clip).with_name(Path(a.clip).stem + "_strip.jpg"))
    ffmpeg(["-ss", "%.3f" % start, "-t", "%.3f" % (end - start), "-i", a.clip, "-vf",
            "fps=%.4f,crop=%s,tile=%dx1" % (1.0 / a.every, a.crop, n), "-frames:v", "1", "-q:v", "3", out])
    print("%s：%d 格，每格 %.2f 秒，从 %.2f 秒开始" % (out, n, a.every, start))


def main():
    need_ffmpeg()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("animatic")
    s.add_argument("out")
    s.add_argument("items", nargs="+", metavar="IMG:SEC")
    s.add_argument("--audio")
    s.add_argument("--size")
    s = sub.add_parser("tail")
    s.add_argument("clip")
    s.add_argument("--seconds", type=float, default=4)
    s.add_argument("--height", type=int, default=1080)
    s.add_argument("-o", "--out")
    s = sub.add_parser("cuts")
    s.add_argument("clip")
    s.add_argument("--threshold", default="0.3")
    s.add_argument("--plan")
    s = sub.add_parser("seam")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--threshold", default="0.3")
    s = sub.add_parser("voice")
    s.add_argument("clip")
    s.add_argument("--window", type=float, default=0.1)
    s.add_argument("--drop", type=float, default=20)
    s = sub.add_parser("spectro")
    s.add_argument("clip")
    s.add_argument("-o", "--out")
    s.add_argument("--top", type=int, default=8000)
    s = sub.add_parser("strip")
    s.add_argument("clip")
    s.add_argument("--crop", required=True)
    s.add_argument("--every", type=float, default=0.25)
    s.add_argument("--start", type=float)
    s.add_argument("--end", type=float)
    s.add_argument("-o", "--out")
    a = ap.parse_args()
    {"animatic": cmd_animatic, "tail": cmd_tail, "cuts": cmd_cuts, "seam": cmd_seam, "voice": cmd_voice,
     "spectro": cmd_spectro, "strip": cmd_strip}[a.cmd](a)


if __name__ == "__main__":
    main()
