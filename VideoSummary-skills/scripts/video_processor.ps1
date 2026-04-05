# video-summary.ps1
# 视频总结处理脚本
# 支持本地 .mp4 和在线视频（YouTube、Bilibili）

param(
    [Parameter(Mandatory=$true)]
    [string]$Input,
    [Parameter(Mandatory=$false)]
    [string]$OutputDir = "."
)

$ErrorActionPreference = "Stop"

# 颜色输出函数
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[WARNING] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

# 检测是否为 URL
function Test-Url {
    param([string]$str)
    return $str -match "^https?://"
}

# 清理临时文件
function Remove-TempFiles {
    param([string[]]$paths)
    foreach ($path in $paths) {
        if (Test-Path $path) { Remove-Item $path -Force -Recurse }
    }
}

# 下载在线视频
function Get-OnlineVideo {
    param([string]$url, [string]$outputPath)

    Write-Info "正在下载视频: $url"

    # 检查 yt-dlp 是否安装
    $ytDlp = Get-Command yt-dlp -ErrorAction SilentlyContinue
    if (-not $ytDlp) {
        Write-Err "yt-dlp 未安装，请先安装: winget install yt-dlp"
        exit 1
    }

    # 创建临时目录
    $tempDir = Join-Path $outputPath "temp_video_$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        # 下载视频（包含字幕）
        Push-Location $tempDir
        yt-dlp --write-subs --write-auto-subs --sub-lang zh-Hans,zh-Hant,en --skip-download --no-playlist -o "%(title)s.%(ext)s" $url

        # 查找字幕文件
        $videoTitle = (Get-ChildItem -Filter "*.info.json" | Select-Object -First 1).BaseName
        if (-not $videoTitle) {
            # 手动获取标题
            $videoTitle = "video_$(Get-Random)"
        }

        # 获取字幕文件路径
        $subFiles = @()
        $subFiles += Get-ChildItem -Filter "*.vtt" -ErrorAction SilentlyContinue
        $subFiles += Get-ChildItem -Filter "*.srt" -ErrorAction SilentlyContinue
        $subFiles += Get-ChildItem -Filter "*.ass" -ErrorAction SilentlyContinue

        # 下载实际视频
        Write-Info "正在提取视频..."
        yt-dlp -f "best[ext=mp4]" --no-playlist -o "%(title)s.%(ext)s" $url

        $videoFile = Get-ChildItem -Filter "*.mp4" | Select-Object -First 1
        if (-not $videoFile) {
            $videoFile = Get-ChildItem | Where-Object { $_.Extension -in @('.mp4', '.mkv', '.avi', '.mov') } | Select-Object -First 1
        }

        Pop-Location

        if ($videoFile) {
            return @{
                VideoPath = $videoFile.FullName
                SubtitleFiles = $subFiles
                Title = $videoFile.BaseName
                TempDir = $tempDir
            }
        } else {
            throw "视频下载失败"
        }
    }
    catch {
        Pop-Location
        Remove-TempFiles $tempDir
        throw
    }
}

# 提取本地视频字幕
function Get-LocalSubtitles {
    param([string]$videoPath)

    $videoDir = Split-Path $videoPath -Parent
    $videoName = [System.IO.Path]::GetFileNameWithoutExtension($videoPath)

    $subFiles = @()
    $subFiles += Get-ChildItem -Path $videoDir -Filter "$videoName*.vtt" -ErrorAction SilentlyContinue
    $subFiles += Get-ChildItem -Path $videoDir -Filter "$videoName*.srt" -ErrorAction SilentlyContinue
    $subFiles += Get-ChildItem -Path $videoDir -Filter "$videoName*.ass" -ErrorAction SilentlyContinue

    return $subFiles
}

# 使用 Whisper 转录
function Get-WhisperTranscription {
    param([string]$videoPath)

    Write-Info "正在使用 Whisper 转录音频..."

    # 检查 Python 是否安装
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Err "Python 未安装，无法使用 Whisper"
        exit 1
    }

    # 检查 whisper 是否安装
    $whisperCheck = python -c "import whisper" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Info "正在安装 Whisper..."
        pip install openai-whisper
    }

    # 创建临时转录文件
    $transcriptFile = Join-Path $env:TEMP "transcript_$(Get-Random).txt"

    # 运行 Whisper 转录
    Write-Info "转录中（可能需要几分钟）..."
    $result = python -c "
import whisper
import sys

model = whisper.load_model('base')
result = model.transcribe(r'$videoPath', language='zh')

with open(r'$transcriptFile', 'w', encoding='utf-8') as f:
    f.write(result['text'])

print(result['text'][:200])
"

    if ($LASTEXITCODE -ne 0) {
        Remove-Item $transcriptFile -ErrorAction SilentlyContinue
        Write-Err "Whisper 转录失败"
        exit 1
    }

    $transcript = Get-Content $transcriptFile -Raw -Encoding UTF8
    Remove-Item $transcriptFile -ErrorAction SilentlyContinue

    return $transcript
}

# 转换字幕为纯文本
function Convert-SubtitlesToText {
    param([System.IO.FileInfo[]]$subFiles)

    $fullText = ""

    foreach ($subFile in $subFiles) {
        Write-Info "正在读取字幕: $($subFile.Name)"
        $content = Get-Content $subFile.FullName -Raw -Encoding UTF8

        # 移除 VTT/SRT 标签
        $content = $content -replace '<[^>]+>', ''
        $content = $content -replace '^\d+$', ''
        $content = $content -replace '^\d{2}:\d{2}:\d{2}.*$', ''
        $content = $content -replace '^\s*$', ' '

        $fullText += $content + " "
    }

    return $fullText.Trim()
}

# 获取视频时长
function Get-VideoDuration {
    param([string]$videoPath)

    # 使用 ffprobe（如果可用）
    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($ffprobe) {
        $duration = ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $videoPath
        $seconds = [double]$duration
        $minutes = [int]($seconds / 60)
        $remainingSeconds = [int]($seconds % 60)
        return "$minutes 分钟 $remainingSeconds 秒"
    }

    return "未知"
}

# 主函数
function Start-VideoSummary {
    Write-Info "========================================"
    Write-Info "       视频总结工具 v1.0"
    Write-Info "========================================"

    $tempDir = $null
    $tempVideoPath = $null

    try {
        # 确定输入类型
        $isUrl = Test-Url $Input
        $videoPath = $Input
        $videoTitle = ""

        if ($isUrl) {
            Write-Info "检测到在线视频 URL"
            $result = Get-OnlineVideo -url $Input -outputPath $OutputDir
            $videoPath = $result.VideoPath
            $videoTitle = $result.Title
            $tempDir = $result.TempDir
            $tempVideoPath = $videoPath
        } else {
            Write-Info "检测到本地视频文件"
            if (-not (Test-Path $videoPath)) {
                Write-Err "视频文件不存在: $videoPath"
                exit 1
            }
            $videoTitle = [System.IO.Path]::GetFileNameWithoutExtension($videoPath)
        }

        # 获取字幕
        $subFiles = @()
        if ($isUrl) {
            $subFiles = $result.SubtitleFiles
        } else {
            $subFiles = Get-LocalSubtitles -videoPath $videoPath
        }

        # 获取视频时长
        $duration = Get-VideoDuration -videoPath $videoPath
        Write-Info "视频时长: $duration"

        # 决定使用字幕还是转录
        $textContent = ""
        if ($subFiles.Count -gt 0) {
            Write-Success "找到字幕文件: $($subFiles.Count) 个"
            $textContent = Convert-SubtitlesToText -subFiles $subFiles
            Write-Info "字幕内容长度: $($textContent.Length) 字符"
        } else {
            Write-Warning "未找到字幕，使用 Whisper 转录"
            $textContent = Get-WhisperTranscription -videoPath $videoPath
            Write-Info "转录内容长度: $($textContent.Length) 字符"
        }

        # 生成摘要文本
        $summaryPrompt = @"
请为以下视频内容生成详细的总结，输出为 Markdown 格式。

视频标题: $videoTitle
视频时长: $duration

视频内容转录:
$textContent

请生成以下格式的总结:
# 视频总结

## 基本信息
- 标题:
- 时长:
- 来源:

## 关键要点
（列出 3-5 个关键要点）

## 详细内容
（详细的总结内容，至少 300 字）

## 重要引用
（如有重要原话引用）
"@

        Write-Info "========================================"
        Write-Info "请将以下内容复制给 Claude 进行总结:"
        Write-Info "========================================"
        Write-Host ""
        Write-Host $summaryPrompt
        Write-Host ""

        # 询问用户是否要让 Claude 处理
        $continue = Read-Host "是否继续？(y/n)"

    }
    finally {
        # 清理临时文件
        if ($tempDir -and (Test-Path $tempDir)) {
            Write-Info "清理临时文件..."
            Remove-TempFiles $tempDir
        }
    }
}

# 运行
Start-VideoSummary -Input $args[0] -OutputDir $args[1]