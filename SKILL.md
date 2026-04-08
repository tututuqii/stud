---
name: video-summary
description: Summarize videos from local .mp4 files or online sources (YouTube, Bilibili). Extracts embedded subtitles or uses Whisper AI for transcription, then generates a structured markdown summary using Claude Haiku.
---

# 视频总结 Skill

分析并总结视频内容，支持本地 `.mp4` 文件和在线视频（YouTube、Bilibili）。

## 输入

- 视频文件路径（本地 .mp4）
- 在线视频 URL（YouTube、Bilibili）

## 命令格式

```
/video-summary <视频路径或URL>
```

## 处理流程

### 第一步：运行转录脚本

```bash
python .claude/skills/video-summary/scripts/video_summary.py "<视频路径或URL>"
```

此步骤由脚本自动完成：
1. **输入验证**：判断是本地文件还是在线 URL
2. **时长检测**：获取视频时长，在线视频从元数据读取，本地视频用 ffprobe 获取
3. **字幕检测**：优先提取视频内嵌字幕（Bilibili 需登录）
4. **语音转录**：无字幕时使用 Whisper AI (GPU) 转录
5. **结果保存**：转录文本保存到 `transcript.txt`，视频信息保存到 `video_info.json`
6. **自动清理**：删除临时音视频文件

### 第二步：生成 AI 总结

脚本执行完成后，根据视频类型继续：

**普通视频（≤40分钟）**
- 读取 `transcript.txt` 和 `video_info.json`
- 使用 **Claude Haiku** 模型生成结构化总结
- 保存到 `ai总结/{视频标题}.md`

**长视频（>40分钟）**
- 读取 `transcript.txt` 和 `video_info.json`
- 检查 `video_info.json` 中的 `need_chunked_processing: true`
- 将转录文本分块（每块约 15-20 分钟内容）
- 对每块使用 Haiku 生成小结
- 合并所有小结生成最终总结
- 保存到 `ai总结/{视频标题}.md`

## AI 总结说明

- 使用 **Claude Haiku** 模型生成总结（成本优化，约降低 20 倍 token 消耗）
- 长视频（>40分钟）自动分段处理，先总结各段再合并

## 输出格式

```markdown
# 视频总结

## 基本信息
- **标题**: xxx
- **时长**: xx 分钟
- **来源**: 本地/YouTube/Bilibili

## 关键要点
1. 要点一
2. 要点二
...

## 详细内容
...
```

## 输出位置

- 转录文本：`transcript.txt`（项目根目录）
- 视频信息：`video_info.json`（项目根目录）
- AI 总结：`ai总结/{视频标题}.md`（项目根目录）

## 环境要求

- Python 依赖：`faster-whisper`
- Whisper 转录需要 NVIDIA GPU 支持
- 在线视频需要网络连接

## 长视频分块总结策略

当 `need_chunked_processing: true` 时：
1. 转录文本按时间顺序分块（每块 ~3000 字符）
2. 每块独立生成小结
3. 各小结按顺序拼接
4. 基于拼接小结生成最终结构化总结

这样做的好处：
- 避免单次 token 超出模型限制
- 各段小结可并行生成
- 最终合并保证内容连贯性

## Cookies 登录配置（用于 YouTube、Bilibili 等平台）

部分视频的字幕（如会员内容、自动字幕）需要登录才能获取。配置方式：

### 步骤 1：导出 Cookies

1. 使用浏览器插件（如 **EditThisCookie** 或 **Cookie-Editor**）导出对应网站的 cookies
2. 导出格式选择 **Netscape HTTP Cookie File**
3. 保存为项目根目录的 `cookies.txt`

### 步骤 2：配置路径（可选）

默认会自动读取项目根目录的 `cookies.txt`。如需自定义路径，可设置环境变量：

```bash
# Windows
set COOKIES_FILE=D:\path\to\cookies.txt

# Linux/Mac
export COOKIES_FILE=/path/to/cookies.txt
```

### 注意事项

- Cookies 有效期通常为 30 天，过期后需重新导出
- 请勿分享你的 cookies 文件，包含登录凭证
- 如果未配置 cookies，脚本会自动回退使用 Whisper 转录，不影响正常使用

## 环境变量配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `COOKIES_FILE` | Cookies 文件路径（支持 YouTube、Bilibili 等） | `{项目根目录}/cookies.txt` |
| `FFMPEG_BIN` | ffmpeg bin 目录路径 | `{项目根目录}/ffmpeg-8.1-essentials_build/bin` |

## 注意事项

- YouTube、Bilibili 部分字幕需要登录才能获取（配置 cookies 可提取，否则自动改用 Whisper 转录）
- Whisper 转录时间取决于视频长度
- 临时文件在转录完成后自动删除，转录文本会保留
- 分块总结仅针对 >40 分钟的视频
