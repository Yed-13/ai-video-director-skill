# 阶段 8：后期与交付

全部用 ffmpeg / Python 做，中间文件放 `post/`。先写剪辑单，再动手剪。

## 规则

- 未标注色彩空间的源（Seedance 常见）按 BT.601 解码，第一步就**真的转换**：`scale=in_color_matrix=bt601:out_color_matrix=bt709`。H3 输出先用 `ffprobe` 看标注。中间文件用无损（`-c:v ffv1` 或 PNG 序列），交付标 BT.709。
- 每一步输出新文件，不覆盖。每个剪辑点前后各抽 3 帧检查。
- 不对整段插帧。甩镜、盖屏转场在转场段内插 8–16 个子帧混合，做运动模糊。

## 剪辑单 `post/edit_list.md`

1. 按剧情排素材，标出每段保留的起止秒数；
2. 长台词处在第几秒盖哪段反应镜头、盖多长；
3. 还缺的补拍镜头；
4. 配乐分段：情绪、起止时间，有台词处标"压低"；
5. 全部字幕，和剧本逐字核对，标明说 / 内心独白 / 画外音；
6. 开头 3 秒有冲突吗、结尾停在悬念上吗。

## 常用命令

```bash
# 精确到帧地剪（end_frame 不含：保留 1–139 帧），同时转色彩空间
ffmpeg -i in.mp4 -vf "trim=start_frame=1:end_frame=140,setpts=PTS-STARTPTS,scale=in_color_matrix=bt601:out_color_matrix=bt709" -an -c:v ffv1 post/s03_trim.mkv
# 结尾跳变：停在第 129 帧并延长 0.5 秒
ffmpeg -i in.mp4 -vf "trim=end_frame=130,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.5" -an -c:v ffv1 post/s03_hold.mkv
# 放大到 1080p
ffmpeg -i in.mkv -vf "scale=-2:1080:flags=lanczos,unsharp=5:5:0.4" -c:v ffv1 out.mkv
# 交付（-shortest 按较短的一轨截断，音乐比画面短时先补长）
ffmpeg -i final.mkv -i mix.wav -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a aac -b:a 256k -shortest final.mp4
```

对白戏一直对着说话的人时：音轨只取说话镜头，保持不断；用 `overlay` 在指定时间段盖 1–2 秒反应镜头。

## 调色

先校正：每场戏以定稿的样帧或首帧为基准，`look.py compare` 后按参数调，调完再量一次。再风格化：全片一套参数。最后统一加颗粒和暗角。肤色不变，强调色受保护。积木命令见 `light-color.md` 第 4 节。

## 声音

- 三层：对白最响，音效其次，配乐最小；有人说话时压低配乐（`sidechaincompress` 或音量关键帧）。全片 `loudnorm=I=-16:TP=-1.5:LRA=11`。
- 配乐后期统一加一首，所以提示词里写"不要背景音乐"。
- 模型自带的声轨先查：可能有乱语和它自己生成的背景音乐。要保留的台词用 Demucs 分离人声，其余静音，底噪换成干净的环境声。
- 拍点只在原曲上测。文生音乐做纯器乐时，生成后用语音识别扫一遍，确认没有把提示词唱出来。

## 字幕

模型画的字常出错，字幕后期加。用语音识别（Whisper / SenseVoice）出时间轴，再逐句对剧本；念错的字要么重新生成这一段，要么字幕跟着声音改，**字幕必须和声音一致**。字幕放在下三分之一，内心独白换颜色或加括号。烧字幕需要 ffmpeg 带 libass（`ffmpeg -h filter=subtitles` 检查）；没有就交付 `.srt`，或者用剪映加。

## 复核与交付

1. 另开子 agent 做全片复核（`review-briefs.md` 第 4 份），按硬伤和小问题处理。
2. 交付 `post/final.mp4`，附说明：片长、分辨率、哪些地方没经人工检查（声音、动作手感）。
3. 提醒用户：在中国大陆平台发布要按《人工智能生成合成内容标识办法》（2025-09-01 起施行）声明 AI 生成，并勾选平台的 AI 标识；其他平台按各自规则。
4. 写 `lessons.md`：画风句、好用的写法、踩过的坑、各后端的新发现。下次开工前先读。
