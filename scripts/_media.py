"""Shared ffprobe / ffmpeg helpers. Python 3.9+, stdlib only."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
VIDEO_EXT = {".mp4", ".mov"}
AUDIO_EXT = {".mp3", ".wav"}


def need_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        sys.exit("缺少 %s，请先安装（macOS: brew install ffmpeg）" % "、".join(missing))


def run(cmd, check=True):
    """Run a command, return CompletedProcess with text output."""
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        sys.exit("命令失败：%s\n%s" % (" ".join(str(c) for c in cmd), p.stderr[-2000:]))
    return p


def ffmpeg(args, check=True):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + [str(a) for a in args], check)


def probe(path):
    """Return dict: width, height, duration, fps, has_audio, vcodec, nb_frames, size_mb, color."""
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    data = json.loads(p.stdout or "{}")
    info = {"width": None, "height": None, "duration": None, "fps": None, "has_audio": False,
            "vcodec": None, "nb_frames": None, "color": None,
            "size_mb": Path(path).stat().st_size / 1e6}
    fmt_dur = data.get("format", {}).get("duration")
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and info["width"] is None:
            info["width"], info["height"] = s.get("width"), s.get("height")
            info["vcodec"] = s.get("codec_name")
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            try:
                n, d = rate.split("/")
                info["fps"] = float(n) / float(d) if float(d) else None
            except ValueError:
                pass
            if s.get("nb_frames", "").isdigit():
                info["nb_frames"] = int(s["nb_frames"])
            info["color"] = "/".join(str(s.get(k, "?")) for k in ("color_space", "color_primaries", "color_transfer"))
            if s.get("duration"):
                info["duration"] = float(s["duration"])
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
            if info["duration"] is None and s.get("duration") and Path(path).suffix.lower() in AUDIO_EXT:
                info["duration"] = float(s["duration"])
    if info["duration"] is None and fmt_dur:
        info["duration"] = float(fmt_dur)
    return info


def count_frames(path):
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)])
    try:
        return int(p.stdout.strip().split(",")[0])
    except ValueError:
        return None


def ssim(img_a, img_b, width, height):
    """SSIM between two images after scaling both to width x height. Returns float or None."""
    p = run(["ffmpeg", "-hide_banner", "-i", str(img_a), "-i", str(img_b), "-lavfi",
             "[0:v]scale=%d:%d,format=yuv420p[a];[1:v]scale=%d:%d,format=yuv420p[b];[a][b]ssim"
             % (width, height, width, height), "-f", "null", "-"], check=False)
    for line in p.stderr.splitlines():
        if "SSIM" in line and "All:" in line:
            try:
                return float(line.split("All:")[1].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def kind_of(path):
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return None
