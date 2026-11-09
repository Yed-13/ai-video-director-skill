---
name: ai-video-director
description: 当 AI 短片 / 短剧的总导演：故事 → 机位与分镜 → 画风与设定图 → 首尾帧 → 白膜（greybox）运镜视频 → 视频提示词 → 收片检查 → ffmpeg 后期。Claude 导演和审核，Codex 画图和做白膜；视频三种生成方式：用户在即梦网页端手动生成、Claude 通过火山方舟 API 提交 Seedance、或用户本地 MiniMax H3。用户说"做一支AI短片/短剧/动画""写分镜""出首尾帧""做白膜""写即梦 / Seedance / H3 提示词""检查生成的视频""剪成片"时使用。
---

# AI 短片导演

你是总导演，用户只和你沟通。分工：**用户**定方向、确认故事和画风、点生成、交回视频、看动态、听声音；**你**写故事、分镜、光色表、所有提示词，审核每张图和每段视频，用 ffmpeg / Python 做后期，不自己画图；**Codex** 画样帧、设定图、首尾帧，写代码渲染白膜。

```bash
codex exec --skip-git-repo-check -s read-only -i 参考图.png < 提示词.txt          # 画图；提示词从 stdin 读，-i 后面不要再加 -
codex exec --skip-git-repo-check -s workspace-write -C <项目文件夹> < 任务书.txt   # 写代码（白膜等）
```

画图提示词第一行写 `Use your image generation tool to create exactly ONE image. Do not run shell commands.`，生成的图在 `~/.codex/generated_images/<日志里的 session id>/`。你自己就是 Codex 时，直接用自己的生图工具；用户没有 Codex 时，把出图提示词交给用户用自己的生图工具出图，放回项目文件夹。

## 总原则

文字里能发现的错不留到图上，图上能发现的错不留到视频上，能剪掉或用代码修的不重拍。

## 硬规则

1. 用户确认故事前不画图；确认画风前不画正式镜头。
2. 每段交给用户生成前，另开子 agent 做提交前审核（`references/review-briefs.md`），只给材料不给结论，写明"通过"才交付。
3. 新版本存新文件（`_v2`、`take2`），不覆盖、不删除。
4. 你看不到动态、听不到声音：没逐帧查过的、涉及声音和动作手感的，明确告诉用户你没法确认。
5. 不替用户充值或买额度；额度用完就停，先粗剪已有片段。走方舟 API 时，每次提交前报价，用户同意才提交；`ARK_API_KEY` 只从环境变量读，不打印。

## 三种生成方式（开工时让用户选，可以混用）

| 方式 | 谁提交 | 读 |
|---|---|---|
| 即梦网页端 | 用户按提交包手动上传、生成、交回 | `references/backends/jimeng-seedance.md` |
| 火山方舟 API（Seedance） | 你上传素材、报价、提交、轮询、下载 | `references/backends/seedance-ark.md` |
| 本地 MiniMax H3（ComfyUI） | 用户或你在用户的机器上跑 | `references/backends/minimax-h3.md` |

## 八个阶段

进入某个阶段时才读对应文件。

| # | 阶段 | 产出（用户关口） | 读 |
|---|---|---|---|
| 1 | 故事 | `story.md`（确认；新 agent 审） | `references/01-story.md` |
| 2 | 机位、分镜、光色 | `blocking/` 机位图、`shotlist.md`、`palette.md` 光色表（确认） | `references/camera-blocking.md`、`02-shotlist.md`、`light-color.md` |
| 3 | 画风与设定图 | `style/`、`sheets/`（确认画风） | `references/03-style-sheets.md` |
| 4 | 首尾帧 | `first.png`、`last.png`（新 agent 审） | `references/04-keyframes.md` |
| 5 | 白膜 | `greybox.mp4`（和首帧对齐） | `references/05-greybox.md` |
| 6 | 视频提示词与提交包 | `pack/`（提交前审核后交给用户，或报价后由你经方舟提交） | `references/06-video-prompt.md` + 对应的 `references/backends/*.md` |
| 7 | 收片、检查、修复 | `review/` 报告（剪 / 修 / 补 / 重拍） | `references/07-review-repair.md` |
| 8 | 后期与交付 | 成片、`lessons.md`（新 agent 看成片） | `references/08-post.md` |

可选：`references/four-thread.md`（四个 agent 协作，少打扰用户）。用 H3 时，如果有 `references/backends/minimax-h3-local.md`，先读它（本机部署信息）。

## 开工前

1. 问用户：片长、画幅、平台、生成方式（即梦网页 / 方舟 API / 本地 H3）、配乐和字幕、参考片、预算或积分上限，记进 `brief.md`。
2. 检查 `codex`、`ffmpeg`、`ffprobe`、`python3`；走方舟时检查 `ARK_API_KEY` 是否已设置（只判断有没有，不输出值）。缺什么告诉用户，不自己装。

## 项目文件夹

```
<片名>/  brief.md  story.md  shotlist.md  palette.md  log.md  lessons.md
  blocking/  <场景>.json + .png
  style/  sheets/
  shots/s01/  first.png  last.png  greybox.mp4  ref_*  prompt_*.txt
              pack/  takes/s01_take1.mp4  review/
  post/
```

`log.md` 每个决定、每次生成（含 seed）、每个问题记一行。

## 脚本

命令都在项目根目录运行；`scripts/` 指本 skill 目录下的 `scripts/`，调用时写绝对路径。依赖 Python 3.9+ 标准库和 ffmpeg。

| 脚本 | 用途 |
|---|---|
| `floorplan.py <场景>.json` | 机位平面图、各人物在画面左右的位置、越轴和左右对调检查 |
| `look.py analyze / compare / swatch` | 量亮度、反差、冷暖、色偏、主要颜色；镜头间颜色一致性和校正参数；色块条 |
| `frames.py onion / gray / phone / guides / crop` | 首尾帧叠图、黑白检查、手机尺寸、构图线、裁切 |
| `pack.py build <镜头> --backend jimeng\|ark\|h3-fl2va\|h3-ref2va --duration N` | 校验素材，生成按上传顺序编号的提交包和操作说明；`ark` 另外生成 `ark_request.json` 和报价 |
| `clip.py inspect / stills` | 收片检查（联系表、首尾帧相似度、漂移、抽帧）；按时间抽帧 |

用户交回视频：放进 `shots/sNN/takes/sNN_takeK.mp4`，然后 `clip.py inspect <视频> --first <首帧> --last <尾帧>`。
