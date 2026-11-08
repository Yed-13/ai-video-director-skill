# ai-video-director

一个 Claude Code skill：让 Claude 当 AI 短片的总导演。从一个想法出发，经过故事 → 分镜与配色 → 画风与设定图 → 首尾帧 → **白膜（greybox）运镜视频** → 视频提示词 → 收片检查 → ffmpeg 后期，做出完整成片。

- **Claude**：导演和审核，写所有文字和提示词，跑检查脚本，做后期
- **Codex**：画样帧、设定图、首尾帧；写代码渲染白膜视频
- **视频模型**：由你手动生成。即梦 Seedance 2.x（网页端），或者本地部署的 MiniMax H3（FL2VA / Ref2VA）

核心原则：错误越早发现越便宜。文字阶段能发现的不留到图上，图上能发现的不留到视频上。每个镜头交给你生成之前，都会先过一个新开的审核 agent。

## 安装

```bash
git clone https://github.com/Yed-13/ai-video-director-skill.git ~/.claude/skills/ai-video-director
```

然后在 Claude Code 里说"我想做一支 AI 短片……"即可。

依赖：`ffmpeg` / `ffprobe`、Python 3.9+（只用标准库）、Codex CLI（画图用）。

## 结构

```
SKILL.md                       总流程、规则、分工
references/
  01-story.md                  故事
  02-shotlist.md               分镜与配色
  03-style-sheets.md           画风与设定图
  04-keyframes.md              首尾帧
  05-greybox.md                白膜运镜视频
  06-video-prompt.md           七段式提示词 + 模型常见错误对照表 + 提交包
  07-review-repair.md          收片检查，剪 → 修 → 重拍
  08-post.md                   后期与交付
  review-briefs.md             四个审核 agent 的任务书
  four-thread.md               可选：四线程协作
  backends/jimeng-seedance.md  即梦
  backends/minimax-h3.md       MiniMax H3（本地）
scripts/
  pack.py                      校验素材 + 生成按上传顺序编号的提交包
  frames.py                    首尾帧叠图、黑白检查、手机尺寸预览、构图线、裁切
  clip.py                      收片检查：联系表、首尾帧相似度、亮度 / 饱和度漂移、抽帧
```

## 致谢

- 工作流方法：Eian（@EianLu）的文章《Claude code/Codex+Seedance AI视频：从一个想法到成片的全流程》
- 即梦 Seedance 输入限制与 @ 引用语法：[dexhunter/seedance2-skill](https://github.com/dexhunter/seedance2-skill)（MIT）
- MiniMax H3 提示词格式：[MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) 中的 `h3-prompt-writing` 指南
- 白膜参考视频的思路：本仓库作者
