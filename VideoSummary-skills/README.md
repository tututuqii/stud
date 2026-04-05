# 视频总结 Skill

Claude Code 的视频总结技能，支持本地 `.mp4` 文件和在线视频（YouTube、Bilibili）。

## 安装依赖

### 必需
- **Python 3.8+** - Whisper 转录需要
- **Whisper** - `pip install openai-whisper`
- **ffmpeg** - 音频处理需要

### 可选
- **yt-dlp** - 下载在线视频
  ```powershell
  winget install yt-dlp
  ```

## 使用方法

### 方式一：直接使用 Claude Code

在 Claude Code 中输入：

```
/video-summary <视频路径或URL>
```

例如：

```
/video-summary ./video.mp4
/video-summary https://www.youtube.com/watch?v=xxxxx
/video-summary https://www.bilibili.com/video/xxxxx
```

### 方式二：运行脚本

```powershell
.\scripts\video_processor.ps1 -Input "<视频路径或URL>"
```

## 功能特性

- 支持本地 `.mp4`, `.mkv`, `.avi`, `.mov` 视频
- 支持 YouTube 视频
- 支持 Bilibili 视频
- 优先提取视频内嵌字幕
- 无字幕时使用 Whisper AI 转录
- 生成 Markdown 格式总结

## 工作流程

1. **输入验证** - 检测是本地文件还是 URL
2. **字幕检测** - 优先使用已有字幕
3. **语音转录** - 无字幕则使用 Whisper 转录
4. **AI 总结** - 基于文字内容生成结构化总结

## 输出格式

```markdown
# 视频总结

## 基本信息
- 标题: xxx
- 时长: xx 分钟
- 来源: 本地/YouTube/Bilibili

## 关键要点
1. 要点一
2. 要点二
...

## 详细内容
...

## 重要引用
...
```

## 注意事项

- 在线视频需要网络连接
- Whisper 转录需要较长时间（取决于视频长度）
- 建议首次使用前安装所有依赖
