# 后端：Seedance · 火山方舟 API（Claude 直接提交）

和即梦网页端是同一系列模型，区别是由你通过 API 提交、轮询、下载，用户不用手动操作，但**每次提交都花真钱**。来源：火山方舟 Seedance 2.0 文档（2026-11），以及 Eian 原文的做法。

## 准备

- 用户在火山引擎开通方舟和 Seedance 模型，创建 API Key，并在自己的终端里设置环境变量 `ARK_API_KEY`。你只从环境变量读取，**永远不打印、不写进文件**。
- 模型 ID 和单价以方舟控制台为准。参考：`doubao-seedance-2-0-260128`、`doubao-seedance-2-0-fast-260128`、`doubao-seedance-2-0-mini-260615`（720p 约 0.5 元/秒），以及较新的 `doubao-seedance-2-5-*`（720p 约 1.5 元/秒）。普通镜头用 mini 就够。
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
- `duration` 是 4–15 的整数；mini 和 fast 只支持 480p / 720p。

模型习惯和即梦相同，见 `07-review-repair.md`。
