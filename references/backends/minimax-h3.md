# 后端：MiniMax H3（本地部署，RTX 5090）

资料来源：官方仓库 github.com/MiniMax-AI/MiniMax-H3（README 和 `skills/h3-prompt-writing/` 里的两份提示词指南）、Hugging Face 模型卡 MiniMaxAI/MiniMax-H3、ComfyUI 官方博客。整理于 2026-11。

## 它是什么

- 33B 参数的扩散 Transformer，文本编码器是 Qwen3-VL-32B。视频和**立体声音频一起生成**。
- 完整系统分三块，**本地只有中间那块**：
  1. **H3-Context-IR**（未开源，只能调 API）：把用户随手写的多模态指令改写成结构化提示词。官方说它"对最终质量至关重要"，建议自己按提示词指南做一个等价的预处理。**在这个 skill 里，这一步由你来做**：你写的 H3 提示词，就要写成 Context-IR 输出的那种格式。
  2. **H3-Base**（开源）：生成 768p 视频 + 音频。
  3. **H3-Regenerate-2K**（未开源）：把 768p 重新生成成 2K。本地拿不到，所以本地成片就是 768p，后期用 lanczos 放大。
- 开源权重分两个 checkpoint，**一次请求只能用其中一个，两种模式不能混用**：

| Checkpoint | 能做什么 | 输入 |
|---|---|---|
| **FL2VA** | 文生视频（t2va）；首帧、尾帧或首尾帧生视频 | 文本 + 0 / 1 / 2 张图 |
| **Ref2VA** | 全参考：参考图片、视频、音频生成，也能编辑或续写视频 | 图片 ≤ 9；视频 ≤ 3 段，每段 2–15 秒，总 ≤ 15 秒；音频 ≤ 3 段，每段 2–15 秒，总 ≤ 15 秒，**不能只有音频**；总文件 ≤ 12 |

- 输出：4–15 秒（整数秒），24fps，默认短边 768，画幅 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16 等，32kHz 立体声。对白稳定支持中、英、日、韩等 11 种语言。
- 有自动内容审核，可能误判。

## 我们的流程怎么对应到 H3

| 镜头素材 | 用哪个 checkpoint |
|---|---|
| 只有首尾帧 | **FL2VA** |
| 首尾帧 + 白膜 | **Ref2VA**：首尾帧写成 `<Picture N>` 关键帧锚点，白膜写成 `<Video 1>` 运镜和走位参考 |
| 首帧 + 白膜 + 角色设定图 | **Ref2VA**（设定图的写法见模板 B 后面的说明） |
| 纯文字 | FL2VA（t2va）：第一行不写对齐说明，直接从 `integrated_multimodal_description:` 开始。不需要提交包（`pack.py` 不处理没有素材的镜头），直接把提示词交给用户 |

## 在 5090（32GB）上部署

- 全精度需要约 124GB 内存；官方的 SGLang 示例用 4 张卡。**单张 5090 要走量化 + 显存卸载**。
- 推荐 **ComfyUI**（0.30.0 以上）：官方博客说 int8 量化 + 自定义 kernel + 动态卸载后，3060 都能跑；最小的变体总内存约 42.5GB，所以**系统内存要足够大**（建议 64GB 以上）。权重在 Hugging Face 的 `Comfy-Org/MiniMax-H3`。ComfyUI 博客提到 T2V、I2V、R2V 三个入门工作流，但官方仓库只链接了 T2V 和 R2V 两个模板；首尾帧（两张图）要看当前 ComfyUI 版本有没有对应节点，第一次部署时确认，并写进这里。
- 注意：有用户反映 ComfyUI 的 R2V 模板只开放了 2 个图片输入口（模型本身支持 9 张）。首尾帧 + 设定图超过 2 张时，需要改工作流或用别的前端。
- 也可以用 SGLang / vLLM / diffusers 自己起服务（见下文的接口格式）。
- 生成速度目前没有可靠的 5090 实测数据。第一次跑时，分别记录冷启动时间和热生成时间，写进 `lessons.md`。

## 提示词格式（必须照着写）

通用规则：

- **结构化部分全部用英文**。台词、歌词、画面里的文字保留原语言。
- 字段名、字段顺序、标签写法必须和下面完全一致。
- 第一个镜头 `[Shot 1]` 不写时间；后面的镜头写 `[Shot 2] At 00:03.500, the camera cuts to ...`。时间要严格递增，并且在时长以内。我们的镜头基本都是一镜到底，只用 `[Shot 1]`。
- 运镜写成自然的英文句子：运动类型 + 幅度 + 速度。可用的说法：`Push In / Pull Out`、`Zoom In / Zoom Out`、`Pan Left / Right`、`Truck Left / Right`、`Tilt Up / Down`、`Pedestal Up / Down`、`Arc Shot`、`Tracking Shot`、`Static Shot`、`Shake Slightly / Strongly`、`POV`、`Roll Clockwise / Counterclockwise`；幅度用 `with small amplitude` / `with large amplitude`，速度用 `at slow speed` / `at fast speed`。例：`The camera pushes in with small amplitude at slow speed toward ...`
- 说话的角色用固定编号 `(S1)`、`(S2)`，台词写成 `<d>[Chinese] 台词原文</d>`。不说话的角色不编号。
- 旁白的写法：`The man (S1) says in an off-screen voiceover: <d>[Chinese] 台词</d> while his lips remain completely closed.`。嘴唇闭合那句要放在 `</d>` 后面。
- 画面里出现的文字用英文双引号括起来，保留原文：`a sign reading "营业中"`。
- 具体的视觉和声音细节，比 "cinematic"、"beautiful" 这种空词有用得多。

### 模板 A：FL2VA（只有首尾帧）

第一行固定写法（S.SS 是时长，保留两位小数）：

```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 6.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] <画风那句话的英文版>, a medium shot begins in the position and framing established by Picture 1: <首帧状态>. <中间可见的变化，按时间顺序，包括谁先谁后、往画面哪一侧>. <逐渐收敛>. At the end of the shot, <角色> settles into the pose, spacing, and composition established by Picture 2.

overall_soundscape: <1–4 句：环境声、动作声、呼吸等；不写台词>

non_diegetic_music: <乐器、速度、强弱变化；没有就写 N/A>
```

- 只有首帧时，第一行改成：`For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- 只有尾帧时：`How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 6.00-second mark of the target video.`
- 正文不要把两张图分别静态描述一遍，要写**从首帧到尾帧的运动路径**。

### 模板 B：Ref2VA（首尾帧 + 白膜）

六个字段，顺序固定：`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`。

```
subject_definitions:
<Subject 1> is <角色外观，来自人物卡>, whose appearance comes from <Picture 1> and <Picture 2>.
<Picture 1> is the first frame of [Shot 1], showing <首帧概述>.
<Picture 2> is the last frame of [Shot 1], showing <尾帧概述>.
<Video 1> is an untextured grey blocking animation that defines only the camera trajectory, subject paths, and action timing for [Shot 1].

summary:
[keyframe completion + reference generation] The target video is a single 6-second shot that begins from <Picture 1> and ends on <Picture 2>. <Subject 1> <主要动作>. The camera movement, walking path, and timing follow <Video 1>, while all visual style, color, and character appearance follow <Picture 1> and <Picture 2>.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - <保留哪些外观特征>.
<Picture 1> ([Shot 1] first frame): fully_preserved - composition, colors, and character pose at 0.00 seconds.
<Picture 2> ([Shot 1] last frame): fully_preserved - composition, colors, and character pose at the final frame.
<Video 1> (camera trajectory and blocking): fully_preserved - the camera path, subject positions, and action timing are followed exactly.

detailed_description:
The target video is in <画风那句话的英文版>.
[Shot 1] The shot begins from <Picture 1>: <首帧里的构图、人物位置、环境和光线>. Following the camera trajectory of <Video 1>, the camera <运镜句子>. <Subject 1> <按时间写动作：在几秒开始、往画面哪一侧、表情怎么变、手放在哪>. <其他人的反应，写清先后>. <中间状态>. The shot ends on <Picture 2>, with <尾帧的姿势和构图>.

overall_soundscape:
<环境声和动作声>

non_diegetic_music:
<没有就写 N/A>
```

- 白膜的角色在 `subject_definitions` 里就限定为"只提供运镜、走位和时间"，所以 `retention_analysis` 里写 `fully_preserved`：按官方规则，这个标记只针对已定义的角色来判断。"不保留灰色材质"这层意思，已经由 `subject_definitions` 和 `summary` 表达了。
- **加角色设定图时**：只用来定义角色外观的图片，不单独写一行 `<Picture N>`，而是写进 `<Subject N>` 的定义里，比如 `<Subject 1> is ..., whose appearance comes from <Picture 3>.`。`pack.py` 会把 `ref_*.png` 排在首帧、尾帧后面，所以设定图从 `<Picture 3>` 开始编号。
- `detailed_description` 官方建议 350–500 个英文单词。一镜到底的镜头也要写细，不能因为只有一个镜头就写得短。
- 标签一旦定义，在六个字段里含义不变；`summary` 里不能出现新标签。
- 角色说话时写 `<Subject 1> (S1) says, <d>[Chinese] ……</d>`。

## 接口格式（自己起 SGLang 服务时）

官方示例：FL2VA 服务在 30010 端口，Ref2VA 在 30011 端口。

```json
POST http://localhost:30010/v1/videos
{
  "task": "fl2va",
  "prompt": "<上面写好的完整提示词>",
  "conditions": [
    {"type": "image", "uri": "<首帧 URL 或 data URL>", "role": "keyframe", "frame_index": 0}
  ],
  "target": {"short_edge": 768, "aspect_ratio": "16:9", "duration_seconds": 6},
  "seed": 0
}
```

- 查询状态：`GET /v1/videos/<id>`；下载：`GET /v1/videos/<id>/content`。
- Ref2VA：`"task": "ref2va"`，视频和音频条件写 `"role": "reference"`。
- **⚠️ 未验证，首尾帧暂时不要走这条路**：官方示例只演示了首帧（`frame_index: 0`）。FL2VA 的尾帧 `frame_index` 怎么填、Ref2VA 里用作关键帧的图片 `role` 怎么填，都还没确认。在 SGLang cookbook（docs.sglang.io 的 MiniMax-H3 页面）查清楚之前，首尾帧镜头用 ComfyUI；确认后把结论写进这里。

## 提交包里给用户的说明（pack.py 会自动生成）

- 用哪个 checkpoint / 哪个 ComfyUI 模板
- 每个文件接到哪个输入口（`<Picture 1>` = 01_首帧，以此类推）
- 时长（整数秒）、画幅、短边 768、seed
- 粘贴 `prompt.txt` 的全部内容（英文）
- 生成后命名为 `sNN_takeK.mp4`，放进 `shots/sNN/takes/`；同时记下 seed，方便复现
