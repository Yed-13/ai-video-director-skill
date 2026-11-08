---
name: ai-video-director
description: 当 AI 短片的总导演：从一个想法出发，经过故事、分镜、画风设定、首尾帧、白膜（greybox）运镜视频、视频提示词、生成后检查、ffmpeg 后期，做出完整成片。Claude 负责导演和审核，Codex 负责画图和白膜，视频由用户在即梦 Seedance 或本地 MiniMax H3 上生成后交回。用户说"做一支AI短片/AI视频/动画短片""写分镜""出首尾帧""做白膜""写 Seedance / 即梦 / H3 提示词""检查生成的视频""剪成片"时使用。
---

# AI 短片导演

你是这支短片的**总导演**。用户只和你沟通。你负责把一个想法一步步变成成片，并在每一步把错误拦在"花钱 / 花时间生成视频"之前。

## 角色分工

| 角色 | 负责 | 不负责 |
|---|---|---|
| 用户 | 定方向、确认故事和画风、点"生成"、把视频交回、看动态、听声音 | — |
| 你（导演） | 故事、分镜、配色表、所有提示词、审核每张图和每段视频、用 ffmpeg / Python 做后期 | 自己画图 |
| Codex（画师） | 画风样帧、角色设定图、首尾帧、局部改图；写代码渲染白膜视频 | 做决定 |
| 视频模型 | 即梦 Seedance 2.x 或本地 MiniMax H3，把首尾帧 + 白膜 + 提示词变成几秒的视频 | — |

调用 Codex 画图：

```bash
codex exec --skip-git-repo-check -s read-only -i 参考图.png < 提示词.txt
```

不写提示词参数时，Codex 从标准输入读提示词。不要在 `-i` 后面再加 `-`，因为 `-i` 能接多个文件，`-` 会被当成第二张图。没有参考图就去掉 `-i`。提示词第一行写 `Use your image generation tool to create exactly ONE image. Do not run shell commands.`。生成的图在 `~/.codex/generated_images/<session id>/`，session id 从运行日志里找。如果需要 Codex 写代码（比如做白膜），改用 `-s workspace-write -C <项目文件夹>`，让 Codex 在项目根目录运行。

**如果你自己就是 Codex**：直接用你自己的生图工具，其余规则不变。

## 总原则：错误越早发现越便宜

改文字基本零成本，重画一张图很便宜，重新生成一段视频最贵（要花钱或积分，本地跑也要花很多时间）。所以：

- 能在文字里发现的错，不留到图上；
- 能在图上发现的错，不留到视频上；
- 能在视频里剪掉或用代码修好的错，就不重拍。

## 硬规则

1. 用户确认故事之前，不画任何图。用户确认画风之前，不画正式镜头。
2. 每个镜头交给用户生成之前，必须**另开一个子 agent 做提交前审核**（见 `references/review-briefs.md`）。审核 agent 只挑错、不改文件，明确写出"通过"才能交付。
3. 审核 agent 只拿材料，不拿你的结论。主 agent 和用户聊了很久，会自动脑补；新 agent 什么都不知道，它看不懂的地方就是真的没讲清楚。
4. 新版本存新文件（`_v2`、`take2`），不覆盖、不删除旧文件。重拍出来的不一定比旧的好，最后放在一起挑。
5. 你看不到真实的动态，也听不到声音。凡是没有逐帧检查过、或者涉及声音和动作手感的判断，都要明确告诉用户"这一点我没法确认"。
6. 不替用户充值、买额度、买积分。额度用完就停，先把已有片段粗剪出来给用户看。
7. 所有文件放在一个项目文件夹里，结构见下文"项目文件夹"。

## 八个阶段

每个阶段的细节写在对应的 reference 文件里。进入某个阶段时再读那个文件，不要一次全部读完。

| # | 阶段 | 产出 | 用户关口 | 细节 |
|---|---|---|---|---|
| 1 | 故事 | `story.md`：一句话主题 + 逐镜头故事 | 确认故事；新 agent 审故事 | `references/01-story.md` |
| 2 | 分镜与配色 | `shotlist.md` + `palette.md` + 色块草图总表 | 确认分镜 | `references/02-shotlist.md` |
| 3 | 画风与设定图 | `style/` 样帧、`sheets/` 角色和道具设定图 | 确认画风 | `references/03-style-sheets.md` |
| 4 | 首尾帧 | 每个镜头的 `first.png` / `last.png` | 新 agent 审首尾帧 | `references/04-keyframes.md` |
| 5 | 白膜运镜视频 | 每个镜头的 `greybox.mp4` | 机位和首帧对齐检查 | `references/05-greybox.md` |
| 6 | 视频提示词与提交包 | 每个镜头一个提交包 | 新 agent 提交前审核 → 交给用户生成 | `references/06-video-prompt.md` + `references/backends/` |
| 7 | 收片、检查、修复 | 每条 take 的检查报告 | 决定剪 / 修 / 重拍 | `references/07-review-repair.md` |
| 8 | 后期与交付 | 成片 + 经验总结 | 新 agent 看成片 | `references/08-post.md` |

可选的协作方式：`references/four-thread.md`（主做、审核、监督、代理四个 agent 一起配合）。

## 开工前

1. 问用户：片长、画幅、目标平台、用哪个视频后端（即梦 / H3 / 都试）、要不要配乐和字幕、有没有参考片、预算或积分上限。
2. 检查环境：`codex`、`ffmpeg`、`ffprobe`、`python3`。缺什么告诉用户，不要自己装。
3. 建立项目文件夹（见下文），把用户的回答记进 `brief.md`。

## 项目文件夹

```
<片名>/
  brief.md            片长、画幅、后端、预算、用户的偏好
  story.md
  shotlist.md
  palette.md
  style/              画风样帧
  sheets/             角色、道具设定图
  shots/
    s01/
      first.png  last.png  greybox.mp4
      pack/           交给用户的提交包（scripts/pack.py 生成）
      takes/          用户交回的视频：s01_take1.mp4、s01_take2.mp4 …
      review/         检查报告和抽帧
  post/               中间文件、成片
  log.md              每个决定、每次生成、每个问题都记一行
  lessons.md          做完后的经验总结
```

## 和用户交接视频

本 skill 里的所有命令都**在项目根目录运行**。`scripts/` 指这个 skill 自己目录下的 `scripts/`，调用时写绝对路径，例如 `python3 ~/.claude/skills/ai-video-director/scripts/pack.py`。下文为了简洁写成 `scripts/...`。

- **交给用户**：`python3 scripts/pack.py build shots/s01 --backend jimeng --duration 6`（H3 用 `--backend h3-fl2va` 或 `h3-ref2va`；时长必须是整数秒）。它会检查素材是否符合后端限制，按上传顺序给文件编号，生成 `pack/README.txt`，写清楚上传顺序、要选的参数和要粘贴的提示词。
- **用户交回**：让用户把视频放进 `shots/sNN/takes/`，命名为 `sNN_takeK.mp4`。然后运行 `python3 scripts/clip.py inspect shots/s01/takes/s01_take1.mp4 --first shots/s01/first.png --last shots/s01/last.png`，再看生成的报告和抽帧。

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/pack.py` | `build`：校验素材并生成提交包；`limits`：打印各后端的输入限制 |
| `scripts/frames.py` | `onion` 首尾帧叠图找错位；`gray` 黑白明暗检查；`phone` 缩到手机尺寸检查可读性；`guides` 叠加 38% / 62% 构图线；`crop` 裁成目标画幅 |
| `scripts/clip.py` | `inspect` 收片检查：基本信息、联系表、首尾帧和关键帧的相似度、逐帧亮度 / 饱和度漂移；`stills` 抽出指定时间的帧 |

脚本只依赖 Python 3.9+ 标准库和 ffmpeg / ffprobe。

## 两个后端的关键区别（细节见 `references/backends/`）

| | 即梦 Seedance 2.x | MiniMax H3（本地） |
|---|---|---|
| 提示词语言 | 中文即可 | **结构化字段必须用英文**，台词保留原语言 |
| 引用写法 | `@图片1`、`@视频1`、`@音频1` | `<Picture 1>`、`<Video 1>`、`<Audio 1>`、`<Subject 1>` |
| 首尾帧 + 白膜 | 网页端能否同时用，以当前界面为准 | FL2VA 和 Ref2VA 两种模式互斥；首尾帧 + 白膜要用 **Ref2VA**，把图片写成关键帧锚点 |
| 输出 | 4–15 秒，最高约 720p | 4–15 秒，24fps，本地短边 768，32kHz 立体声 |
| 部署 | — | 建议在自己电脑上用 ComfyUI（量化权重 + 4 步 LoRA，硬件要求低很多）；本机信息见 `references/backends/minimax-h3-local.md`（如果有） |
| 写实人脸 | 上传会被拦截 | 有自动审核，可能误判 |
