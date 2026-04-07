# Claude Video Summary Skill

Claude Code 的视频总结技能，支持本地视频和在线视频（YouTube、Bilibili）的语音转录和 AI 总结。

## 功能特性

- 支持本地 `.mp4` 文件和在线视频 URL
- 自动提取内嵌字幕（Bilibili 需登录，支持 AI 自动字幕）
- Whisper GPU 加速语音转录
- Claude Haiku AI 生成结构化总结
- 长视频（>40分钟）自动分块处理
- 自动清理临时文件

## 安装

### 1. 安装依赖

```bash
pip install faster-whisper yt-dlp
```

### 2. 安装 ffmpeg

需要将 ffmpeg 添加到系统 PATH，或将 ffmpeg 放在项目目录的 `ffmpeg-8.1-essentials_build/bin` 下。

### 3. 配置 Claude Code Skill

将项目复制到 Claude Code 的 skills 目录：

```
.claude/skills/video-summary/
├── SKILL.md
└── scripts/
    └── video_summary.py
```

## 使用方法

### 运行视频总结

```
/video-summary <视频路径或URL>
```

### 示例

```bash
# Bilibili 视频
/video-summary https://www.bilibili.com/video/BV1xxxxxxx

# YouTube 视频
/video-summary https://www.youtube.com/watch?v=xxxxxxx

# 本地视频
/video-summary /path/to/video.mp4
```

### 手动运行脚本

```bash
python .claude/skills/video-summary/scripts/video_summary.py "<视频路径或URL>"
```

## 配置

### Bilibili Cookies（可选）

如需下载 Bilibili 字幕，需配置 cookies：

1. 使用浏览器插件导出 bilibili.com 的 cookies（Netscape 格式）
2. 保存为项目根目录的 `bilibili_cookies.txt`
3. 或设置环境变量指定路径：

```bash
# Windows
set BILIBILI_COOKIES_FILE=D:\path\to\cookies.txt

# Linux/Mac
export BILIBILI_COOKIES_FILE=/path/to/cookies.txt
```

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `BILIBILI_COOKIES_FILE` | Bilibili cookies 文件路径 | `{项目根目录}/bilibili_cookies.txt` |
| `FFMPEG_BIN` | ffmpeg bin 目录路径 | `{项目根目录}/ffmpeg-8.1-essentials_build/bin` |

## 工作流程

```
用户: /video-summary <URL>
    ↓
Claude Code: 运行转录脚本
    ↓
脚本: 尝试下载字幕 → 无字幕时 Whisper 转录
    ↓
脚本: 保存 transcript.txt 和 video_info.json
    ↓
Claude Code: 读取结果 → 生成 AI 总结
```

## 项目结构

```
claude-video-summary/
├── SKILL.md                    # Skill 定义文档
├── scripts/
│   └── video_summary.py       # 转录脚本
├── README.md
└── LICENSE
```

## 环境要求

- Python 3.8+
- NVIDIA GPU（Whisper 转录加速，非必需但推荐）
- 网络连接（下载在线视频）

## License

MIT
