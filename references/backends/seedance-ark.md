# 后端：Seedance · 火山方舟 API（Claude 直接提交）

和即梦网页端是同一系列模型，区别是由你通过 API 提交、轮询、下载，用户不用手动操作，但**每次提交都花真钱**。来源：火山方舟 / BytePlus ModelArk 的 Seedance 2.0、2.5 文档（2026-11），以及 Eian 原文的做法。

## 准备

- 用户在火山引擎开通方舟和 Seedance 模型，创建 API Key，并在自己的终端里设置环境变量 `ARK_API_KEY`。你只从环境变量读取，**永远不打印、不写进文件**。
- 模型 ID 和单价以方舟控制台为准。参考：`doubao-seedance-2-0-260128`、`doubao-seedance-2-0-fast-260128`、`doubao-seedance-2-0-mini-260615`（720p 约 0.5 元/秒），以及 `doubao-seedance-2-5-*`（国际站 BytePlus 的 ID 是 `dreamina-seedance-2-5-260628`、`dreamina-seedance-2-5-flash-261115`）。普通镜头用 mini 就够。
- 计费按 token：(输入视频时长 + 输出视频时长) × 宽 × 高 × 帧率 / 1024，所以带参考视频更贵；失败不收费。
- 输入素材必须是**可公网访问的 URL**（官方建议火山引擎 TOS 公共读，或临时签名链接）。本地文件要先上传。

## 流程

1. `python3 scripts/pack.py build shots/s03 --backend ark --duration 6 --model <模型ID> --price <元/秒>`。提示词默认读 `prompt_ark.txt`，没有就用 `prompt_jimeng.txt`。会生成 `pack/ark_request.json` 和带 curl 命令的 `README.txt`。
2. 上传素材，把 URL 填进 `ark_request.json` 的占位符。
3. 另开子 agent 做提交前审核（`review-briefs.md` 第 3 份）。
4. 报价给用户（秒数 × 单价，多段时列合计），**用户同意后才提交**。
5. 提交、每 15–30 秒轮询一次，直到 `status` 为 `succeeded` 或 `failed`；成功后立刻下载 `content.video_url` 到 `shots/sNN/takes/`。在 `log.md` 记下任务 id、模型、seed、费用。
6. 返回欠费或额度不足就停下，不充值，先粗剪已有片段。个人账号同时最多约 3 个任务。

## 请求格式

```json
{
  "model": "doubao-seedance-2-0-mini-260615",
  "content": [
    {"type": "text", "text": "<提示词>"},
    {"type": "image_url", "image_url": {"url": "https://…/01.png"}, "role": "first_frame"},
    {"type": "image_url", "image_url": {"url": "https://…/02.png"}, "role": "last_frame"}
  ],
  "ratio": "16:9", "duration": 6, "resolution": "720p", "generate_audio": true, "watermark": false
}
```

- **首尾帧模式**：只有首帧和尾帧时，`role` 写 `first_frame` / `last_frame`，画面严格对齐。
- **全参考模式**：有白膜、身份板、场景图或音频时，`role` 写 `reference_image` / `reference_video` / `reference_audio`（图 ≤ 9、视频 ≤ 3、音频 ≤ 3，不能只有音频）。首尾帧只能在提示词里指定（"首帧为图片1，尾帧为图片2"），不保证完全一致。
- 提示词里的引用写 `图片1`、`视频1`、`音频1`（按同类素材顺序编号），其余写法和即梦母版一样（`jimeng-seedance.md`），白膜那一句照抄。
- `duration` 是整数：2.0 为 4–15，2.5 为 4–30；2.0 的 mini 和 fast 只支持 480p / 720p，2.5 支持 480p / 720p / 1080p / 4k（flash 到 720p）。
- 2.5 的参考素材上限：图 30、视频 10、音频 10（flash：10 / 5 / 5），参考音视频合计 ≤ 30 秒，可以只有音频。`pack.py` 默认按这组限制校验，用 2.0 的模型加 `--seedance 2.0`。
- `return_last_frame: true` 会返回无水印的最后一帧，可当下一段的首帧。
- 官方文档写 `seed` 相同结果相似但不保证一致，不要指望用它复现。

## 样片模式（只有 Seedance 2.5）

抽卡流程见 `gacha.md`。

1. 出样片：请求里加 `"draft": true`，分辨率只能 480p（`pack.py build … --backend ark --draft`）。同一请求提交 2–3 次得到几条候选。记下每条的任务 id。
2. 升正片：再建一次任务，`model` 和样片一致，`draft` 省略，`resolution` 写 `1080p` 或 `4k`，`content` 里放样片任务：

```json
{
  "model": "<和样片相同的模型 ID>",
  "content": [{"type": "draft_task", "id": "<样片任务 id>"}],
  "resolution": "1080p"
}
```

- 提示词、素材、seed、时长、画幅、是否生成音频都由样片自动沿用，**不要再传**，传了即使值相同也会报错。
- 样片任务 id 的有效期是创建后 14 天。样片和正片分别计费：样片按 480p，正片按目标分辨率。
- 上面 `draft_task` 的写法来自文档摘要，没有实际调用过；第一次用先对一遍方舟文档「创建视频生成任务」页。
- 正片的小字、细纹理、人群数量可能和样片略有出入，收片时照常检查。

模型习惯和即梦相同，见 `07-review-repair.md`。
