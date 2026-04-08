# Claude Video Summary

基于 Claude Code 的智能视频总结工具，支持本地视频和在线视频（YouTube、Bilibili）的自动转录和 AI 总结。

## 功能特性

- **多平台支持** - 本地 `.mp4`、YouTube、Bilibili
- **字幕提取** - 自动提取内嵌字幕，Bilibili 支持 AI 自动字幕
- **语音转录** - Whisper GPU 加速转录，CPU 回退支持
- **AI 总结** - Claude Haiku 生成结构化总结
- **长视频处理** - 40 分钟以上自动分块总结
- **跨平台** - Windows、Linux、macOS

## 快速开始

### 1. 安装依赖

```bash
pip install faster-whisper yt-dlp
```

### 2. 配置 ffmpeg

下载 ffmpeg 并添加到系统 PATH，或将 ffmpeg 放在项目目录的 `ffmpeg-8.1-essentials_build/bin` 下。

### 3. 安装 Skill

将项目复制到 Claude Code 的 skills 目录：

```bash
# 克隆仓库
git clone https://github.com/yourname/claude-video-summary.git

# 或手动复制到 skills 目录
# ~/.claude/skills/video-summary/
```

### 4. 使用

```
/video-summary <视频路径或URL>
```

**示例：**
```bash
# Bilibili 视频
/video-summary https://www.bilibili.com/video/BV1xxxxxxx

# YouTube 视频
/video-summary https://www.youtube.com/watch?v=xxxxxxx

# 本地视频
/video-summary /path/to/video.mp4
```

## 项目结构

```
claude-video-summary/
├── SKILL.md                    # Claude Code Skill 定义
├── scripts/
│   └── video_summary.py       # 主转录脚本
├── ai总结/                     # 总结输出目录
├── ffmpeg-8.1-essentials_build/  # ffmpeg（可选）
├── cookies.txt                 # Cookies 文件（可选）
├── README.md
├── UPDATE_LOG.md
└── LICENSE
```

## 工作流程

```
用户: /video-summary <URL>
    ↓
Claude Code: 运行 video_summary.py
    ↓
脚本: 字幕提取 → 无字幕时 Whisper 转录
    ↓
脚本: 自动生成 AI 总结
    ↓
输出: ai总结/{视频标题}.md
```

## 配置

### Cookies（可选）

用于下载会员内容或受限字幕：

1. 使用浏览器插件导出 cookies（Netscape 格式）
2. 保存为 `cookies.txt` 或设置环境变量：

```bash
# Windows
set COOKIES_FILE=D:\path\to\cookies.txt

# Linux/Mac
export COOKIES_FILE=/path/to/cookies.txt
```

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `COOKIES_FILE` | Cookies 文件路径 | `{项目根目录}/cookies.txt` |
| `FFMPEG_BIN` | ffmpeg bin 目录 | `{项目根目录}/ffmpeg-8.1-essentials_build/bin` |

## 环境要求

- Python 3.8+
- NVIDIA GPU（推荐，用于 Whisper 加速）
- 网络连接（下载在线视频）

## License

MIT License - 详见 [LICENSE](LICENSE) 文件
