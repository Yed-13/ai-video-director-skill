# 后端：MiniMax H3（本地）

来源：github.com/MiniMax-AI/MiniMax-H3（README、`skills/h3-prompt-writing/`）、Hugging Face MiniMaxAI/MiniMax-H3、ComfyUI 博客（2026-11）。

## 要点

- 视频和立体声音频一起生成；4–15 秒（整数），24fps，本地短边 768（2K 重生成模块没有开源，后期再放大）；中文对白稳定。
- 官方的提示词预处理模块 Context-IR 没有开源，官方称它"对质量至关重要"。**这一步由你来做**：H3 提示词要写成它输出的结构化格式（见下）。
- 两个 checkpoint，一次请求只能用一个：

| Checkpoint | 能做 | 输入 |
|---|---|---|
| FL2VA | 文生视频；首帧 / 尾帧 / 首尾帧生视频 | 文本 + 0–2 张图 |
| Ref2VA | 参考图、视频、音频生成；编辑或续写视频 | 图 ≤ 9；视频 ≤ 3 段（每段 2–15 秒，合计 ≤ 15 秒）；音频 ≤ 3 段（同上，不能只有音频）；总数 ≤ 12 |

- 怎么选：只有首尾帧用 FL2VA；首尾帧 + 白膜、身份板、场景图、音频参考，用 Ref2VA；纯文字用 FL2VA，第一行不写对齐说明，也不需要提交包。

## 部署：建议在自己电脑上用 ComfyUI

全精度约 124GB 内存，官方 SGLang 示例用了 4 张卡。在自己电脑上用 ComfyUI（0.30.0 以上）可以大幅降低硬件要求：
- 用 `Comfy-Org/MiniMax-H3` 的量化权重（Transformer 和视频 VAE 用 int8，文本编码器用 4bit），配合显存卸载，3060 级别的显卡都能跑；最小组合约 42.5GB，系统内存建议 64GB 以上。
- 社区的 Ref2VA 4 步加速 LoRA 适合抽卡和预览，定稿再用完整步数。
- R2V 节点的参考图输入口是动态增加的，网页界面默认显示得少，通过 API 提交工作流时可以接更多张。首尾帧节点要看当前 ComfyUI 版本有没有。
- 用 API 批量跑：`/upload/image` 上传 → `/prompt` 提交 → `/history/<id>` 轮询（默认 8188 端口）。

如果有 `minimax-h3-local.md`（本机部署信息，不进仓库），先读它。

## 提示词格式

- 结构化部分用英文；台词、歌词、画面文字保留原语言。字段名、顺序、标签写法完全照下面。
- 镜头：`[Shot 1]` 不写时间，后面写 `[Shot 2] At 00:03.500, the camera cuts to ...`，时间严格递增且在时长内。一镜到底只用 `[Shot 1]`。
- 运镜写成句子：类型 + 幅度 + 速度。类型：`Push In / Pull Out`、`Zoom In / Out`、`Pan Left / Right`、`Truck Left / Right`、`Tilt Up / Down`、`Pedestal Up / Down`、`Arc Shot`、`Tracking Shot`、`Static Shot`、`Shake Slightly / Strongly`、`POV`、`Roll`；幅度 `with small / large amplitude`；速度 `at slow / fast speed`。
- 说话人用固定编号 `(S1)`，台词 `<d>[Chinese] 原文</d>`；旁白和内心独白写 `says in an off-screen voiceover: <d>…</d> while his lips remain completely closed.`；不说话的人不编号。
- 画面文字：`a sign reading "营业中"`。写具体细节，不写 cinematic、beautiful 这类空词。

### 模板 A：FL2VA

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 6.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] <英文画风句>, a medium shot begins in the position and framing established by Picture 1: <首帧状态>. <按时间顺序写中间的可见变化，谁先谁后、往画面哪侧>. At the end of the shot, <角色> settles into the pose, spacing, and composition established by Picture 2.

overall_soundscape: <1–4 句环境声和动作声，不写台词>

non_diegetic_music: N/A
```

- 只有首帧：第一行写 `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- 只有尾帧：`How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 6.00-second mark of the target video.`
- 正文写从首帧到尾帧的运动路径，不要把两张图分别静态描述一遍。

### 模板 B：Ref2VA（首尾帧 + 白膜）

```
subject_definitions:
<Subject 1> is <人物卡的英文>, whose appearance comes from <Picture 1> and <Picture 2>.
<Picture 1> is the first frame of [Shot 1], showing <首帧概述>.
<Picture 2> is the last frame of [Shot 1], showing <尾帧概述>.
<Video 1> is an untextured grey blocking animation that defines only the camera trajectory, subject paths, and action timing for [Shot 1].

summary:
[keyframe completion + reference generation] The target video is a single 6-second shot that begins from <Picture 1> and ends on <Picture 2>. <Subject 1> <主要动作>. Camera movement, paths, and timing follow <Video 1>; all visual style, color, and character appearance follow <Picture 1> and <Picture 2>.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - <保留的外观特征>.
<Picture 1> ([Shot 1] first frame): fully_preserved - composition, colors, and pose at 0.00 seconds.
<Picture 2> ([Shot 1] last frame): fully_preserved - composition, colors, and pose at the final frame.
<Video 1> (camera trajectory and blocking): fully_preserved - camera path, subject positions, and action timing are followed exactly.

detailed_description:
The target video is in <英文画风句>. <英文光色句>
[Shot 1] The shot begins from <Picture 1>: <构图、人物位置、环境、光线>. Following the camera trajectory of <Video 1>, the camera <运镜句>. <Subject 1> <按时间写动作、方向、表情、手的位置>. <其他人的反应，写先后>. The shot ends on <Picture 2>, with <尾帧的姿势和构图>.

overall_soundscape:
<环境声和动作声>

non_diegetic_music:
N/A
```

- 白膜的角色在 `subject_definitions` 里已经限定为"只给运镜、走位和时间"，所以标 `fully_preserved`。
- 身份板、场景图这类只用来定义外观的图，不单独写 `<Picture N>` 行，写进 `<Subject N>` 的定义里（`whose appearance comes from <Picture 3>`）；场景写成一个 `<Subject N>`。
- 声音参考：`<Audio 1> is the voice-timbre reference for <Subject 1> (S1).`，retention 写 `<Audio 1>: reference - …`。
- `detailed_description` 官方建议 350–500 个英文单词；标签含义在六个字段里保持一致，`summary` 里不能出现新标签。

## SGLang 接口（自己起服务时）

`POST /v1/videos`，例如 `{"task": "fl2va", "prompt": "…", "conditions": [{"type": "image", "uri": "<URL 或 data URL>", "role": "keyframe", "frame_index": 0}], "target": {"short_edge": 768, "aspect_ratio": "16:9", "duration_seconds": 6}, "seed": 0}`。查询状态 `GET /v1/videos/<id>`，下载 `GET /v1/videos/<id>/content`。Ref2VA 用 `"task": "ref2va"`，视频和音频的 `role` 写 `reference`。**未验证**：尾帧的 `frame_index` 和 Ref2VA 关键帧图的 `role` 怎么填，查清 SGLang cookbook 之前，首尾帧镜头用 ComfyUI 跑。
