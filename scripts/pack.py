#!/usr/bin/env python3
"""Validate a shot's assets against a video backend and build a numbered submission pack.

Usage:
  pack.py limits [--backend jimeng|ark|h3-fl2va|h3-ref2va]
  pack.py build SHOT_DIR --backend jimeng --duration 6 [--ratio 16:9] [--prompt FILE] [--model NAME]
                [--first first_v2.png] [--last last_v2.png] [--no-first] [--no-greybox] [--force]
                [--resolution 720p] [--price 0.5]      # ark only: request resolution, yuan per second for the quote

Expected files in SHOT_DIR (defaults):
  first.png  last.png  greybox.mp4  ref_*.{png,jpg,mp4,mp3,wav}
  prompt_jimeng.txt (jimeng), prompt_ark.txt (ark; falls back to prompt_jimeng.txt), prompt_h3.txt (h3-*)
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _media import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, kind_of, need_ffmpeg, probe  # noqa: E402

BACKENDS = {
    "jimeng": {
        "label": "即梦 Seedance 2.x（网页端）",
        "images": 9, "videos": 3, "audios": 3, "total": 12,
        "image_mb": 30, "video_mb": 50, "audio_mb": 15,
        "video_total": (2, 15), "audio_total": 15, "clip_each": None,
        "duration": (4, 15), "int_duration": False,
        "img_fmt": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"},
        "prompt": "prompt_jimeng.txt",
    },
    "ark": {
        "label": "Seedance · 火山方舟 API（Claude 提交）",
        "images": 9, "videos": 3, "audios": 3, "total": 12,
        "image_mb": 30, "video_mb": 50, "audio_mb": 15,
        "video_total": (2, 15), "audio_total": 15, "clip_each": None,
        "duration": (4, 15), "int_duration": True,
        "img_fmt": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"},
        "prompt": "prompt_ark.txt",
    },
    "h3-fl2va": {
        "label": "MiniMax H3 本地 · FL2VA（首尾帧）",
        "images": 2, "videos": 0, "audios": 0, "total": 2,
        "image_mb": None, "video_mb": None, "audio_mb": None,
        "video_total": None, "audio_total": None, "clip_each": None,
        "duration": (4, 15), "int_duration": True,
        "img_fmt": IMAGE_EXT, "prompt": "prompt_h3.txt",
    },
    "h3-ref2va": {
        "label": "MiniMax H3 本地 · Ref2VA（全参考）",
        "images": 9, "videos": 3, "audios": 3, "total": 12,
        "image_mb": None, "video_mb": None, "audio_mb": None,
        "video_total": (0, 15), "audio_total": 15, "clip_each": (2, 15),
        "duration": (4, 15), "int_duration": True,
        "img_fmt": IMAGE_EXT, "prompt": "prompt_h3.txt",
    },
}

H3_REF_FIELDS = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:",
                 "overall_soundscape:", "non_diegetic_music:"]
H3_BASE_FIELDS = ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]
CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u201c\u201d\u2018\u2019]")


def ratio_value(text):
    a, b = text.split(":")
    return float(a) / float(b)


def resolve_keyframe(shot, given, default, label, errors):
    """--first/--last may be absolute, relative to cwd, or relative to SHOT_DIR."""
    if not given:
        p = shot / default
        return p if p.exists() else None
    for cand in (Path(given), Path.cwd() / given, shot / given):
        if cand.exists():
            return cand.resolve()
    errors.append("指定的%s不存在：%s（可以写绝对路径、相对当前目录或相对镜头文件夹的路径）" % (label, given))
    return None


def collect(shot, args, errors, warns):
    """Return ordered list of (role_cn, path, kind)."""
    items = []
    first = resolve_keyframe(shot, args.first, "first.png", "首帧", errors)
    last = resolve_keyframe(shot, args.last, "last.png", "尾帧", errors)
    if first is None and not args.first and not args.no_first:
        errors.append("没有找到首帧 first.png。如果这个镜头确实不用首帧（只给尾帧，或纯参考图），加 --no-first")
    if first is not None:
        items.append(("首帧", first, "image"))
    if last is not None:
        items.append(("尾帧", last, "image"))
    known = IMAGE_EXT | VIDEO_EXT | AUDIO_EXT
    for p in sorted(shot.glob("ref_*")):
        if p.suffix.lower() not in known:
            warns.append("%s 的格式不受支持，没有放进提交包（图片 png/jpg/webp…，视频 mp4/mov，音频 mp3/wav）" % p.name)
    for p in sorted(shot.glob("ref_*")):
        k = kind_of(p)
        if k == "image":
            items.append(("参考图-" + p.stem[4:], p, k))
    gb = shot / "greybox.mp4"
    if gb.exists() and not args.no_greybox:
        items.append(("白膜", gb, "video"))
    for p in sorted(shot.glob("ref_*")):
        k = kind_of(p)
        if k == "video":
            items.append(("参考视频-" + p.stem[4:], p, k))
    for p in sorted(shot.glob("ref_*")):
        k = kind_of(p)
        if k == "audio":
            items.append(("参考音频-" + p.stem[4:], p, k))
    return items


ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"


def label_for(backend, kind, idx):
    if backend == "jimeng":
        return {"image": "@图片%d", "video": "@视频%d", "audio": "@音频%d"}[kind] % idx
    if backend == "ark":
        return {"image": "图片%d", "video": "视频%d", "audio": "音频%d"}[kind] % idx
    return {"image": "<Picture %d>", "video": "<Video %d>", "audio": "<Audio %d>"}[kind] % idx


def check(items, args, cfg, errors, warns):
    n = {"image": 0, "video": 0, "audio": 0}
    info = {}
    for role, p, k in items:
        n[k] += 1
        info[p] = probe(p)
    if n["image"] > cfg["images"]:
        errors.append("图片 %d 张，超过上限 %d" % (n["image"], cfg["images"]))
    if n["video"] > cfg["videos"]:
        errors.append("视频 %d 段，超过上限 %d%s" % (n["video"], cfg["videos"],
                      "（FL2VA 不接收视频；有白膜请用 h3-ref2va，或加 --no-greybox）" if args.backend == "h3-fl2va" else ""))
    if n["audio"] > cfg["audios"]:
        errors.append("音频 %d 段，超过上限 %d" % (n["audio"], cfg["audios"]))
    if sum(n.values()) > cfg["total"]:
        errors.append("文件总数 %d，超过上限 %d" % (sum(n.values()), cfg["total"]))
    if args.backend == "h3-ref2va" and n["audio"] and not (n["image"] or n["video"]):
        errors.append("H3 Ref2VA 不能只有音频，必须同时有图片或视频")
    if args.backend == "h3-ref2va" and not (n["image"] or n["video"]):
        errors.append("H3 Ref2VA 至少需要一张图片或一段视频")
    if args.backend == "h3-fl2va" and any(r.startswith("参考图") for r, _, _ in items):
        errors.append("FL2VA 只接收首帧和尾帧，参考图请改用 h3-ref2va")

    lo, hi = cfg["duration"]
    if not (lo <= args.duration <= hi):
        errors.append("生成时长 %.2f 秒不在 %d–%d 秒范围内" % (args.duration, lo, hi))
    if cfg["int_duration"] and abs(args.duration - round(args.duration)) > 1e-6:
        errors.append("这个后端的时长必须是整数秒")

    for role, p, k in items:
        i = info[p]
        ext = p.suffix.lower()
        mb_limit = cfg[{"image": "image_mb", "video": "video_mb", "audio": "audio_mb"}[k]]
        if mb_limit and i["size_mb"] >= mb_limit:
            errors.append("%s %s 有 %.1fMB，超过 %dMB" % (role, p.name, i["size_mb"], mb_limit))
        if k == "image" and ext not in cfg["img_fmt"]:
            errors.append("%s 的格式 %s 不受支持" % (role, ext))
        if k == "video" and ext not in VIDEO_EXT:
            errors.append("%s 的格式 %s 不受支持（只支持 mp4 / mov）" % (role, ext))
        if k == "audio" and ext not in AUDIO_EXT:
            errors.append("%s 的格式 %s 不受支持（只支持 mp3 / wav）" % (role, ext))
        if cfg["clip_each"] and k in ("video", "audio") and i["duration"] is not None:
            a, b = cfg["clip_each"]
            if not (a <= i["duration"] <= b + 0.05):
                errors.append("%s 时长 %.2f 秒，每段必须在 %d–%d 秒之间" % (role, i["duration"], a, b))

    vids = [info[p]["duration"] or 0 for _, p, k in items if k == "video"]
    auds = [info[p]["duration"] or 0 for _, p, k in items if k == "audio"]
    if vids and cfg["video_total"]:
        a, b = cfg["video_total"]
        if not (a <= sum(vids) <= b + 0.05):
            errors.append("参考视频总时长 %.2f 秒，必须在 %d–%d 秒之间" % (sum(vids), a, b))
    if auds and cfg["audio_total"] and sum(auds) > cfg["audio_total"] + 0.05:
        errors.append("参考音频总时长 %.2f 秒，超过 %d 秒" % (sum(auds), cfg["audio_total"]))

    # keyframe consistency
    f = next((p for r, p, _ in items if r == "首帧"), None)
    l = next((p for r, p, _ in items if r == "尾帧"), None)
    target = ratio_value(args.ratio)
    for r, p in (("首帧", f), ("尾帧", l)):
        if p is None:
            if r == "尾帧" and f is not None:
                warns.append("没有尾帧：这个镜头只锚定首帧，结尾由模型自由发挥")
            continue
        w, h = info[p]["width"], info[p]["height"]
        if w and h and abs(w / h - target) / target > 0.01:
            errors.append("%s是 %dx%d，比例 %.3f，和目标画幅 %s 不符；先用 frames.py crop --ratio 裁好"
                          % (r, w, h, w / h, args.ratio))
    if f and l:
        a, b = info[f], info[l]
        if (a["width"], a["height"]) != (b["width"], b["height"]):
            errors.append("首帧 %dx%d 和尾帧 %dx%d 尺寸不一致" % (a["width"], a["height"], b["width"], b["height"]))

    gb = next((p for r, p, _ in items if r == "白膜"), None)
    if gb:
        g = info[gb]
        if g["duration"] and abs(g["duration"] - args.duration) > 0.1:
            warns.append("白膜时长 %.2f 秒，和生成时长 %.2f 秒不一致" % (g["duration"], args.duration))
        if g["fps"] and abs(g["fps"] - 24) > 0.5:
            warns.append("白膜帧率 %.2f，建议 24fps" % g["fps"])
        if g["has_audio"]:
            warns.append("白膜带音轨，建议去掉（ffmpeg -an）")
        if f and g["width"] and info[f]["width"]:
            if abs(g["width"] / g["height"] - info[f]["width"] / info[f]["height"]) > 0.01:
                errors.append("白膜画幅比例和首帧不一致")
    return n, info


def check_prompt(text, items, backend, duration, errors, warns):
    counts = {"image": 0, "video": 0, "audio": 0}
    for _, _, k in items:
        counts[k] += 1
    if backend in ("jimeng", "ark"):
        pats = {"image": r"@?图片\s*(\d+)", "video": r"@?视频\s*(\d+)", "audio": r"@?音频\s*(\d+)"}
    else:
        pats = {"image": r"<Picture (\d+)>|Picture (\d+)", "video": r"<Video (\d+)>", "audio": r"<Audio (\d+)>"}
    for k, pat in pats.items():
        used = set()
        for m in re.finditer(pat, text):
            used.add(int(next(g for g in m.groups() if g)))
        for i in sorted(used):
            if i > counts[k] or i < 1:
                errors.append("提示词引用了 %s，但提交包里没有这个素材" % label_for(backend, k, i))
        for i in range(1, counts[k] + 1):
            if i not in used:
                warns.append("素材 %s 没有在提示词里被引用（每个素材都要写明用途）" % label_for(backend, k, i))

    if backend == "ark" and ark_mode(items) == "reference" and any(r == "首帧" for r, _, _ in items):
        if "首帧" not in text:
            warns.append("方舟全参考模式里首尾帧只能靠提示词指定，提示词里要写明“首帧为图片1”“尾帧为图片2”")
    if backend == "h3-fl2va":
        missing = [fld for fld in H3_BASE_FIELDS if fld not in text]
        if missing:
            errors.append("H3 FL2VA 提示词缺少字段：%s" % "、".join(missing))
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        if counts["image"] and "aligns with" not in first_line and "fully referenced" not in first_line:
            errors.append("H3 FL2VA 第一行必须是关键帧对齐说明（见 backends/minimax-h3.md 模板 A）")
        last_only = counts["image"] == 1 and not any(r == "首帧" for r, _, _ in items)
        if (counts["image"] == 2 or last_only) and ("%.2f-second" % duration) not in first_line:
            errors.append("第一行里尾帧的时间应写成 %.2f-second，和时长一致" % duration)
    if backend == "h3-ref2va":
        pos = [text.find(fld) for fld in H3_REF_FIELDS]
        missing = [H3_REF_FIELDS[i] for i, p in enumerate(pos) if p < 0]
        if missing:
            errors.append("H3 Ref2VA 提示词缺少字段：%s" % "、".join(missing))
        elif pos != sorted(pos):
            errors.append("H3 Ref2VA 字段顺序不对，必须是：%s" % " → ".join(f[:-1] for f in H3_REF_FIELDS))
    if backend.startswith("h3"):
        stripped = re.sub(r"<d>.*?</d>", "", text, flags=re.S)
        stripped = re.sub(r"\"[^\"]*\"", "", stripped)
        if CJK.search(stripped):
            warns.append("H3 提示词的结构化部分出现了中文字符或中文标点；除台词（<d>…</d>）和画面文字（\"…\"）外应全部用英文")
        for m in re.finditer(r"At (\d\d):(\d\d)\.(\d{3})", text):
            t = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000
            if t >= duration:
                errors.append("镜头切换时间 %s 超出了时长 %.2f 秒" % (m.group(0), duration))


def ark_mode(items):
    """first_last when only keyframes are given; otherwise full reference mode."""
    if all(r in ("首帧", "尾帧") for r, _, _ in items):
        return "first_last"
    return "reference"


def ark_request(items, args, text):
    mode = ark_mode(items)
    content = [{"type": "text", "text": text or "<粘贴提示词>"}]
    for i, (role, p, k) in enumerate(items, 1):
        name = "%02d_%s%s" % (i, role, p.suffix.lower())
        url = "<上传后可公网访问的 URL：%s>" % name
        if mode == "first_last":
            content.append({"type": "image_url", "image_url": {"url": url},
                            "role": "first_frame" if role == "首帧" else "last_frame"})
        else:
            key = {"image": "image_url", "video": "video_url", "audio": "audio_url"}[k]
            content.append({"type": key, key: {"url": url},
                            "role": {"image": "reference_image", "video": "reference_video",
                                     "audio": "reference_audio"}[k]})
    return {"model": args.model or "<模型 ID，以方舟控制台为准>", "content": content,
            "ratio": args.ratio, "duration": int(args.duration), "resolution": args.resolution,
            "generate_audio": True, "watermark": False}


def write_readme(pack, items, cfg, args, has_prompt):
    if args.backend == "ark":
        mode = ark_mode(items)
        sec = int(args.duration)
        lines = ["提交包：%s" % pack.parent.name, "后端：%s" % cfg["label"], "",
                 "模式：%s" % ("首尾帧（role = first_frame / last_frame）" if mode == "first_last"
                              else "全参考（首尾帧只能靠提示词指定，不保证和图片完全一致）"),
                 "预计费用：%d 秒 × %s" % (sec, ("%.2f 元/秒 ≈ %.2f 元" % (args.price, args.price * sec))
                                        if args.price else "单价（以方舟控制台和账单为准）"),
                 "",
                 "1. 把下面的文件上传到可公网访问的地址（如火山引擎 TOS 公共读或临时签名链接），"
                 "把 URL 填进 ark_request.json 里对应的占位符：",
                 ]
        counters = {"image": 0, "video": 0, "audio": 0}
        for i, (role, p, k) in enumerate(items, 1):
            counters[k] += 1
            lines.append("   %02d_%s%s  →  提示词里的%s" % (i, role, p.suffix.lower(), label_for("ark", k, counters[k])))
        lines += ["2. 把预计费用告诉用户，用户同意后才提交。",
                  "3. 提交（密钥只从环境变量读，不要打印）：",
                  "   curl -s %s -H 'Content-Type: application/json' -H \"Authorization: Bearer $ARK_API_KEY\" -d @ark_request.json" % ARK_URL,
                  "4. 每 15–30 秒查询一次，直到 status 为 succeeded 或 failed：",
                  "   curl -s %s/<任务 id> -H \"Authorization: Bearer $ARK_API_KEY\"" % ARK_URL,
                  "5. 成功后下载 content.video_url，保存为 shots/%s/takes/%s_takeK.mp4，并在 log.md 记下任务 id、模型、seed 和费用。" % (
                      pack.parent.name, pack.parent.name),
                  "   返回欠费或额度不足就停下，不充值。"]
        (pack / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return lines

    lines = ["提交包：%s" % pack.parent.name, "后端：%s" % cfg["label"], ""]
    if args.backend == "jimeng":
        has_video = any(k == "video" for _, _, k in items)
        lines.append("1. 打开即梦，进入%s。" % ("「全能参考 / 多模态参考」模式（有参考视频）" if has_video
                                          else "「首尾帧」模式（也可以用全能参考模式）"))
    elif args.backend == "h3-fl2va":
        lines.append("1. 使用 FL2VA checkpoint（ComfyUI：I2V 模板，首尾帧需要当前 ComfyUI 版本提供的首尾帧节点；SGLang：端口 30010，task=fl2va）。")
    else:
        lines.append("1. 使用 Ref2VA checkpoint（ComfyUI：R2V 工作流；SGLang：端口 30011，task=ref2va）。")
    lines.append("2. 按下面的顺序上传 / 接入素材：")
    counters = {"image": 0, "video": 0, "audio": 0}
    for i, (role, p, k) in enumerate(items, 1):
        counters[k] += 1
        lines.append("   %02d_%s%s  →  %s" % (i, role, p.suffix.lower(), label_for(args.backend, k, counters[k])))
    lines.append("3. 参数：时长 %s 秒，画幅 %s%s%s。" % (
        int(args.duration) if args.duration == int(args.duration) else args.duration, args.ratio,
        "，短边 768，记下 seed" if args.backend.startswith("h3") else "",
        "，模型版本：%s" % args.model if args.model else ""))
    lines.append("4. %s" % ("把 prompt.txt 的全部内容粘贴进提示词框。" if has_prompt else "（还没有提示词文件！）"))
    lines.append("5. 生成后把视频下载下来，命名为 %s_takeK.mp4，放进 shots/%s/takes/。" % (pack.parent.name, pack.parent.name))
    (pack / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def cmd_limits(args):
    names = [args.backend] if args.backend else list(BACKENDS)
    for name in names:
        c = BACKENDS[name]
        print("[%s] %s" % (name, c["label"]))
        print("  图片 ≤%d  视频 ≤%d  音频 ≤%d  总文件 ≤%d  输出时长 %d–%d 秒%s" % (
            c["images"], c["videos"], c["audios"], c["total"], c["duration"][0], c["duration"][1],
            "（整数）" if c["int_duration"] else ""))


def cmd_build(args):
    need_ffmpeg()
    shot = Path(args.shot).resolve()
    if not shot.is_dir():
        sys.exit("找不到镜头文件夹：%s" % shot)
    cfg = BACKENDS[args.backend]
    errors, warns = [], []
    items = collect(shot, args, errors, warns)
    if not items:
        for e in errors:
            print("❌ " + e)
        sys.exit("镜头文件夹里没有找到任何素材（first.png / last.png / greybox.mp4 / ref_*）。"
                 "纯文字生成（t2va）不需要提交包，直接把提示词交给用户。")
    check(items, args, cfg, errors, warns)

    prompt_path = Path(args.prompt) if args.prompt else shot / cfg["prompt"]
    if args.backend == "ark" and not args.prompt and not prompt_path.exists():
        prompt_path = shot / "prompt_jimeng.txt"
    if not prompt_path.is_absolute() and args.prompt:
        prompt_path = Path.cwd() / prompt_path
    text = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else None
    if text is None:
        warns.append("没有找到提示词文件 %s，提交包里不会有 prompt.txt" % prompt_path.name)
    else:
        check_prompt(text, items, args.backend, args.duration, errors, warns)

    for w in warns:
        print("⚠️  " + w)
    for e in errors:
        print("❌ " + e)
    if errors and not args.force:
        print("\n有 %d 个错误，没有生成提交包。修好后重跑，或加 --force 强制生成。" % len(errors))
        sys.exit(1)

    pack = shot / "pack"
    if pack.exists():
        n = 1
        while (shot / ("pack_old%d" % n)).exists():
            n += 1
        pack.rename(shot / ("pack_old%d" % n))
        print("旧的提交包已改名为 pack_old%d（没有删除）" % n)
    pack.mkdir()
    for i, (role, p, k) in enumerate(items, 1):
        shutil.copy2(p, pack / ("%02d_%s%s" % (i, role, p.suffix.lower())))
    if text is not None:
        (pack / "prompt.txt").write_text(text, encoding="utf-8")
    if args.backend == "ark":
        (pack / "ark_request.json").write_text(
            json.dumps(ark_request(items, args, text), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = write_readme(pack, items, cfg, args, text is not None)
    print("\n✅ 提交包已生成：%s\n" % pack)
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("limits", help="打印各后端的输入限制")
    a.add_argument("--backend", choices=list(BACKENDS))
    b = sub.add_parser("build", help="校验素材并生成提交包")
    b.add_argument("shot")
    b.add_argument("--backend", required=True, choices=list(BACKENDS))
    b.add_argument("--duration", required=True, type=float, help="生成时长（秒）")
    b.add_argument("--ratio", default="16:9")
    b.add_argument("--prompt", help="提示词文件（默认 prompt_jimeng.txt / prompt_h3.txt）")
    b.add_argument("--first", help="首帧文件名（默认 first.png）")
    b.add_argument("--last", help="尾帧文件名（默认 last.png）")
    b.add_argument("--no-greybox", action="store_true", help="不把 greybox.mp4 放进提交包")
    b.add_argument("--no-first", action="store_true", help="这个镜头确实不用首帧（只给尾帧 / 纯参考图）")
    b.add_argument("--model", help="模型版本：即梦写进 README；方舟写进请求（模型 ID 以控制台为准）")
    b.add_argument("--resolution", default="720p", help="方舟请求的分辨率（480p / 720p / 1080p）")
    b.add_argument("--price", type=float, help="方舟单价（元/秒），用于给用户报价")
    b.add_argument("--force", action="store_true", help="有错误也生成")
    args = ap.parse_args()
    {"limits": cmd_limits, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    main()
