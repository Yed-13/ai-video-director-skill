# 阶段 8：后期与交付

全部用代码完成（ffmpeg + Python）。所有中间文件放在 `post/`。

## 基本规则

- **色彩空间**：Seedance 输出的 mp4 通常没有标注色彩空间，按 BT.601 解码；H3 输出先用 `ffprobe` 看标注。中间文件用无损格式（PNG 序列，或 `-c:v ffv1`）。最终交付标注 BT.709。
- **只改标注不够，要真的转换**：没有标注的源文件，在第一步处理时就加 `scale=in_color_matrix=bt601:out_color_matrix=bt709`，把 YUV 数据从 601 转成 709。只在最后加 bt709 标签、不做转换的话，播放器显示的颜色会偏。
- **不覆盖**：每一步输出新文件，比如 `s03_trim.mov`、`s03_grade.mov`。
- **抽查切点**：每个剪辑点前后各抽 3 帧检查。

## 常用操作

剪掉开头和结尾（精确到帧，重新编码到无损中间格式）：

```bash
ffmpeg -i s03_take2.mp4 -vf "trim=start_frame=1:end_frame=140,setpts=PTS-STARTPTS,scale=in_color_matrix=bt601:out_color_matrix=bt709" -an -c:v ffv1 post/s03_trim.mkv
```

（`end_frame=140` 表示保留到第 139 帧为止，帧号从 0 开始。）

结尾跳变时，停在最后一张好的帧上（下面的例子停在第 129 帧，也就是 `end_frame` 减 1，再补 0.5 秒）：

```bash
ffmpeg -i in.mp4 -vf "trim=end_frame=130,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.5" -an -c:v ffv1 post/s03_hold.mkv
```

720p / 768p 放大到 1080p，加轻微锐化：

```bash
ffmpeg -i in.mkv -vf "scale=-2:1080:flags=lanczos,unsharp=5:5:0.4" -c:v ffv1 out.mkv
```

最终交付编码（标注 BT.709）：

```bash
ffmpeg -i final.mkv -i music.wav -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a aac -b:a 256k -shortest final.mp4
```

`-shortest` 会按画面和音乐里较短的那个截断。音乐比画面短时，先把音乐补长或调整剪辑，不然片尾会被剪掉。

## 转场

用户指定哪一镜接哪一镜、用什么转场（硬切、用前景物体盖屏带过、甩镜）。甩镜和盖屏转场要加运动模糊：把转场段内插成 8–16 个子帧再混合，模拟半帧快门（180°）。不要对整段视频做插帧。

## 调色

- 按故事分段调色，每段对照 `palette.md`。
- 只调饱和度和亮度，不动色相；强调色受保护；肤色不变。
- 不加颗粒、柔光、暗角（除非用户要）。
- 漂移修正：用 `clip.py inspect` 生成的 `drift.csv`，以首帧的数值为目标逐段校正。

## 配乐和卡点

- 拍点只在**原曲**上测，不在剪过的文件上测。
- 关键动作对重拍，转折对副歌。
- 视频自带的声音能用就用，不能用就全部静音，另外配音效。

## 全片复核和交付

1. 输出成片后，另开子 agent 做"全片复核"（见 `review-briefs.md`），只给成片，不告诉它任何结论。
2. 按硬伤和小问题分开处理。
3. 交付：`post/final.mp4` + 一段说明（片长、分辨率、哪些地方没有经过人工检查，比如声音）。
4. 写 `lessons.md`：这次定下来的画风描述、好用的提示词写法、踩过的坑和解决办法、每个后端的新发现。下次开工前先读它。
