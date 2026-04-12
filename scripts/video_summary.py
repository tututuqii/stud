#!/usr/bin/env python3
"""视频总结脚本 - 支持本地视频和在线视频（YouTube、Bilibili）

此脚本负责：
1. 输入处理（视频下载/音频提取）
2. 语音转录（Whisper GPU 加速）
3. 长视频检测（>40分钟标记为需分块处理）

转录完成后结果保存在 transcript.txt，由 Claude Code 直接读取生成总结。
长视频（>40分钟）会自动标记，Claude Code 会进行分块总结。
"""

import os
import sys

# 关键：在任何其他模块导入前，用 stub 替换 tqdm 模块，
# 防止 tqdm monitor 线程在 Python 退出时崩溃（所有版本的 tqdm 都有此问题）
import types as _types
_tqdm_stub = _types.ModuleType("tqdm")
_tqdm_stub.__file__ = "<tqdm stub>"
class _DummyTqdm:
    def __init__(self, *args, **kwargs):
        kwargs["disable"] = True
        self._iter = iter(args[0]) if args else iter(())
        self._close_callback = None
    def __iter__(self): return self
    def __next__(self): return next(self._iter)
    def update(self, n=1): return self
    def set_postfix(self, *a, **kw): pass
    def write(self, s, file=None, end="\n"): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def close(self): pass
    @staticmethod
    def write(s, file=None, end="\n", nelim=None): pass
_tqdm_stub.tqdm = _tqdm_stub.std = _tqdm_stub.cli = _DummyTqdm
_tqdm_stub.main = lambda *a, **k: None
_tqdm_stub.utils = _types.ModuleType("tqdm.utils")
_tqdm_stub.utils.Comparable = object
sys.modules["tqdm"] = _tqdm_stub
sys.modules["tqdm.std"] = _tqdm_stub.std
sys.modules["tqdm.utils"] = _tqdm_stub.utils
sys.modules["tqdm.cli"] = _tqdm_stub.cli

import json
import subprocess
import re
import time
from pathlib import Path
from typing import Optional, NamedTuple

# 禁用 tqdm/huggingface_hub 进度条，避免 Python 3.14 线程机制冲突导致崩溃
os.environ["TQDM_DISABLE"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

# 延迟导入 tqdm：先导入真实的 tqdm（用于 faster-whisper），然后再替换 stub
# 这样可以避免 faster-whisper 导入失败
import importlib
_tqdm_real = importlib.import_module("tqdm")

# 路径配置（优先定位到工作区根目录，避免写入 .claude/skills/video-summary）
SCRIPT_DIR = Path(__file__).resolve().parent


def _detect_base_dir() -> Path:
    """检测工作区根目录。

    优先级：
    1. 环境变量 VIDEO_SUMMARY_BASE_DIR
    2. 当前工作目录及其父目录（包含 ffmpeg/.claude 标记）
    3. 脚本目录的父链（包含 ffmpeg/.claude 标记）
    4. 回退到脚本父目录
    """
    override = os.environ.get("VIDEO_SUMMARY_BASE_DIR")
    if override:
        return Path(override).expanduser().resolve()

    cwd = Path.cwd().resolve()
    script_parent = SCRIPT_DIR.parent

    candidates = [cwd, *cwd.parents, script_parent, *script_parent.parents]
    uniq_candidates = []
    seen = set()
    for d in candidates:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq_candidates.append(d)

    marker_groups = [
        ("ffmpeg-8.1-essentials_build", ".claude"),
        ("ffmpeg-8.1-essentials_build",),
        (".claude",),
    ]
    for markers in marker_groups:
        for d in uniq_candidates:
            if all((d / marker).exists() for marker in markers):
                return d

    return script_parent


BASE_DIR = _detect_base_dir()

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", str(BASE_DIR / "ffmpeg-8.1-essentials_build" / "bin"))
OUTPUT_DIR = BASE_DIR / "ai总结"
TEMP_DIR = BASE_DIR / "temp_video_summary"
TRANSCRIPT_FILE = BASE_DIR / "transcript.txt"
VIDEO_INFO_FILE = BASE_DIR / "video_info.json"

# 长视频阈值（分钟）
LONG_VIDEO_THRESHOLD_MINUTES = 40

# Cookies 配置（通过环境变量指定路径）
# 默认读取项目根目录的 cookies.txt（支持 YouTube、Bilibili 等平台）
COOKIES_FILE = os.environ.get(
    "COOKIES_FILE",
    str(BASE_DIR / "cookies.txt")
)


def load_cookies() -> Optional[Path]:
    """加载 cookies 文件路径

    返回 cookies 文件路径，用于 yt-dlp。
    支持 YouTube、Bilibili 等平台的会员内容访问。
    如果 cookies 文件不存在或不可读，返回 None。
    """
    cookie_path = Path(COOKIES_FILE)
    if cookie_path.exists() and cookie_path.is_file():
        print(f"[INFO] 检测到 Cookies 文件: {cookie_path}")
        return cookie_path
    return None


def setup_environment():
    """配置环境变量"""
    if FFMPEG_BIN not in os.environ.get("PATH", ""):
        os.environ["PATH"] = FFMPEG_BIN + os.pathsep + os.environ.get("PATH", "")


def is_url(path_or_url: str) -> bool:
    """判断是否为在线URL"""
    return path_or_url.startswith("http://") or path_or_url.startswith("https://")


def normalize_url(url: str) -> str:
    """将 http:// 转换为 https://（优先使用 HTTPS）"""
    if url.startswith("http://"):
        # 对于 Bilibili 等主流平台，转换为 https
        if "bilibili.com" in url or "youtube.com" in url:
            return url.replace("http://", "https://", 1)
    return url


class CmdResult(NamedTuple):
    """命令执行结果"""
    returncode: int
    stdout: str
    stderr: str


def run_cmd(cmd, capture=True, shell=False, quiet=False) -> CmdResult:
    """执行命令

    Args:
        cmd: 命令（字符串或列表）
        capture: 是否捕获输出
        shell: 是否通过 shell 执行（默认 False，减少 shell=True 依赖）

    Returns:
        CmdResult(returncode, stdout, stderr)
    """
    if isinstance(cmd, str) and not shell:
        import shlex
        cmd = shlex.split(cmd, posix=(os.name != "nt"))

    cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
    print(f"[CMD] {cmd_str}")

    if capture:
        result = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
        return CmdResult(result.returncode, result.stdout, result.stderr)
    else:
        stdout_target = subprocess.DEVNULL if quiet else None
        stderr_target = subprocess.DEVNULL if quiet else None
        result = subprocess.run(
            cmd,
            shell=shell,
            stdout=stdout_target,
            stderr=stderr_target,
            text=True
        )
        return CmdResult(result.returncode, "", "")


def get_video_duration_from_ffprobe(path: Path) -> float:
    """使用 ffprobe 获取视频时长（秒）"""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'json',
        str(path)
    ]
    _, stdout, _ = run_cmd(cmd, capture=True, shell=False)
    try:
        info = json.loads(stdout)
        return float(info.get('format', {}).get('duration', 0))
    except:
        return 0


def get_video_info(url: str) -> tuple:
    """获取视频信息，返回 (标题, 时长(秒), 时长字符串, 来源)"""
    cmd = [sys.executable, '-m', 'yt_dlp', '--dump-json', '--no-playlist', url]
    _, stdout, _ = run_cmd(cmd, capture=True, shell=False)
    title = "video"
    duration_sec = 0
    duration_str = "未知"
    source = "在线视频"

    try:
        info = json.loads(stdout)
        title = info.get("title", "video")
        # 清理标题中的非法字符
        title = re.sub(r'[<>:"/\\|?*]', '_', title)
        duration_sec = info.get("duration", 0)
        minutes = int(duration_sec // 60)
        seconds = int(duration_sec % 60)
        duration_str = f"{minutes}分{seconds}秒"

        if "bilibili.com" in url:
            source = "Bilibili"
        elif "youtube.com" in url:
            source = "YouTube"
        else:
            source = "在线视频"
    except:
        pass

    return title, duration_sec, duration_str, source


def get_local_video_duration(video_path: str) -> float:
    """获取本地视频时长"""
    setup_environment()
    path = Path(video_path)
    if path.suffix.lower() in ['.mp4', '.mkv', '.avi', '.mov', '.flv']:
        return get_video_duration_from_ffprobe(path)
    return 0


def extract_subtitles(url: str) -> Optional[str]:
    """提取字幕文件，返回字幕文本内容"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    original_cwd = os.getcwd()
    os.chdir(TEMP_DIR)

    # 尝试加载 cookies
    cookie_path = load_cookies()
    if cookie_path:
        print(f"[INFO] 使用 Cookies 尝试获取字幕...")

    # 构建 yt-dlp 命令（列表形式）
    # 支持多语言：zh-Hans(简体中文), zh-Hant(繁体中文), en(英语), ja(日语), ko(韩语)
    # 以及 Bilibili AI 自动字幕：ai-zh, ai-en
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--write-subs', '--write-auto-subs',
        '--sub-lang', 'zh-Hans,zh-Hant,en,en-US,en-GB,zh-CN,zh-TW,ja,ko,ai-zh,ai-en',
        '--skip-download', '--no-playlist',
        '-o', 'subtitle'
    ]
    if cookie_path:
        cmd.extend(['--cookies', str(cookie_path)])
    cmd.append(url)

    code, _, stderr = run_cmd(cmd, capture=True, shell=False)

    # 如果获取失败且有 cookies，打印详细信息
    if code != 0 and cookie_path:
        if "Sign in" in stderr or "login" in stderr.lower():
            print("[WARN] Cookies 可能已过期，请重新导出 cookies")
        else:
            print(f"[WARN] 字幕获取失败: {stderr[:200]}")

    text_content = None
    if code == 0:
        sub_files = list(TEMP_DIR.glob("*.vtt")) + list(TEMP_DIR.glob("*.srt")) + list(TEMP_DIR.glob("*.ass"))
        if sub_files:
            text_content = subtitles_to_text(sub_files)
            print(f"[INFO] 已提取字幕，共 {len(text_content)} 字符")

    os.chdir(original_cwd)
    return text_content


def subtitles_to_text(sub_files: list) -> str:
    """将字幕文件转换为纯文本"""
    text = ""
    for sub_file in sub_files:
        with open(sub_file, encoding="utf-8") as f:
            content = f.read()
        # 移除 VTT/SRT 标签
        content = re.sub(r'<[^>]+>', '', content)
        content = re.sub(r'^\d+$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\d{2}:\d{2}:\d{2}.*$', '', content, flags=re.MULTILINE)
        text += content + " "
    return text.strip()


def download_audio(url: str) -> Path:
    """下载音频"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = TEMP_DIR / "audio.m4a"

    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '-f', 'bestaudio[ext=m4a]',
        '--no-playlist',
        '-o', str(audio_path),
        url
    ]
    result = run_cmd(cmd, capture=True, shell=False)

    if result.returncode != 0:
        raise RuntimeError(
            f"音频下载失败，返回码: {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )

    # 验证音频文件
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError(
            "音频下载命令执行后未找到有效音频文件。"
            f"返回码: {result.returncode}\n"
            f"stdout: {result.stdout[:300]}\n"
            f"stderr: {result.stderr[:300]}"
        )

    print(f"[INFO] 音频下载完成: {audio_path} ({audio_path.stat().st_size} bytes)")

    return audio_path


def extract_audio_local(video_path: str) -> Path:
    """从本地视频提取音频"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = TEMP_DIR / "audio.m4a"

    setup_environment()
    video_path_resolved = str(Path(video_path).resolve())
    audio_path_resolved = str(audio_path.resolve())

    # 优先尝试直接复制音频流（无损）
    cmd_copy = [
        'ffmpeg',
        '-i', video_path_resolved,
        '-vn',
        '-acodec', 'copy',
        '-y',
        audio_path_resolved
    ]
    result = run_cmd(cmd_copy, capture=True, shell=False)

    if result.returncode == 0 and audio_path.exists() and audio_path.stat().st_size > 0:
        print(f"[INFO] 音频提取完成（copy模式）: {audio_path} ({audio_path.stat().st_size} bytes)")
        return audio_path

    # 回退到 AAC 转码
    print(f"[WARN] audio copy 失败（{result.returncode}），回退到 AAC 转码模式")
    cmd_aac = [
        'ffmpeg',
        '-i', video_path_resolved,
        '-vn',
        '-acodec', 'aac',
        '-y',
        audio_path_resolved
    ]
    result = run_cmd(cmd_aac, capture=True, shell=False)

    if result.returncode != 0:
        raise RuntimeError(
            f"音频提取失败（转码也失败），返回码: {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError(
            "音频提取命令执行后未找到有效音频文件。"
            f"返回码: {result.returncode}\n"
            f"stdout: {result.stdout[:300]}\n"
            f"stderr: {result.stderr[:300]}"
        )

    print(f"[INFO] 音频提取完成（AAC模式）: {audio_path} ({audio_path.stat().st_size} bytes)")
    return audio_path


def transcribe_whisper(audio_path: Path) -> str:
    """使用 faster-whisper 转录"""
    setup_environment()

    # 恢复真正的 tqdm（stub 会导致 faster-whisper 导入失败）
    # 删除 stub 模块，让 Python 重新导入真正的 tqdm
    for mod in list(sys.modules.keys()):
        if mod == "tqdm" or mod.startswith("tqdm."):
            del sys.modules[mod]
    importlib.reload(importlib.import_module("tqdm"))

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[INFO] 正在安装 faster-whisper...")
        subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper"], check=True)
        from faster_whisper import WhisperModel

    # 自动检测可用设备
    print("[INFO] 正在检测可用设备...")
    device = "cuda"
    compute_type = "float16"

    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用 (torch.cuda.is_available() = False)")
        # 测试 CUDA 是否真的可用
        test_tensor = torch.zeros(1).cuda()
        del test_tensor
        print("[INFO] CUDA 检测通过")
    except Exception as e:
        print(f"[INFO] CUDA 不可用，回退到 CPU: {e}")
        device = "cpu"
        compute_type = "int8"

    print(f"[INFO] 正在加载 Whisper 模型 ({device.upper()} / {compute_type})...")
    try:
        model = WhisperModel("base", device=device, compute_type=compute_type)
    except Exception as e:
        if device == "cuda":
            print(f"[WARN] CUDA 模式加载失败，回退到 CPU/int8: {e}")
            device = "cpu"
            compute_type = "int8"
            model = WhisperModel("base", device=device, compute_type=compute_type)
        else:
            raise

    print(f"[INFO] Whisper 模型加载成功，设备: {device.upper()} / {compute_type}")

    print("[INFO] 正在转录音频...")
    start = time.time()
    segments, info = model.transcribe(str(audio_path), language="zh")
    text = ""
    for segment in segments:
        text += segment.text
    print(f"[INFO] 转录完成，耗时 {time.time() - start:.2f}s，共 {len(text)} 字符")

    return text


def is_long_video(duration_sec: float) -> bool:
    """判断是否为长视频"""
    if duration_sec <= 0:
        return False
    return duration_sec > LONG_VIDEO_THRESHOLD_MINUTES * 60


def save_transcript(title: str, duration_sec: float, duration_str: str, source: str, transcript: str):
    """保存转录结果和视频信息"""
    # 保存转录文本
    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
        f.write(transcript)
    print(f"[INFO] 转录文本已保存到: {TRANSCRIPT_FILE}")

    # 判断是否长视频
    need_chunk = is_long_video(duration_sec)

    # 保存视频信息
    info = {
        "title": title,
        "duration_seconds": duration_sec,
        "duration": duration_str,
        "source": source,
        "transcript_length": len(transcript),
        "need_chunked_processing": need_chunk,
        "long_video_threshold_minutes": LONG_VIDEO_THRESHOLD_MINUTES
    }
    with open(VIDEO_INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 视频信息已保存到: {VIDEO_INFO_FILE}")

    if need_chunk:
        print(f"[INFO] 检测到长视频（>{LONG_VIDEO_THRESHOLD_MINUTES}分钟），Claude Code 将进行分块总结")


def _extract_summary_text(content_blocks) -> str:
    """从 Claude 返回的 content blocks 中提取文本，跳过 ThinkingBlock。"""
    parts = []
    for block in content_blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
            continue

        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)

    return "\n\n".join(parts).strip()


def _strip_markdown_code_fence(text: str) -> str:
    """移除包裹摘要的 markdown code fence。"""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            stripped = "\n".join(lines[1:-1]).strip()
    return stripped


def generate_summary():
    """使用 Claude Haiku 生成视频总结"""
    import anthropic

    # 读取转录和视频信息
    with open(TRANSCRIPT_FILE, "r", encoding="utf-8") as f:
        transcript = f.read()

    with open(VIDEO_INFO_FILE, "r", encoding="utf-8") as f:
        info = json.load(f)

    title = info["title"]
    duration = info["duration"]
    source = info["source"]

    prompt = f"""请为以下视频内容生成结构化总结：

## 视频信息
- 标题: {title}
- 时长: {duration}
- 来源: {source}

## 转录内容
{transcript}

请只输出以下两节，不要重复输出 `# 视频总结` 和 `## 基本信息`：

## 关键要点
（使用编号列表，至少 3 条）

## 详细内容
（按主题分段描述）
"""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )

    # 处理 Haiku 返回的内容（兼容 ThinkingBlock + TextBlock）
    summary = _extract_summary_text(response.content)
    summary = _strip_markdown_code_fence(summary)

    if not summary:
        print("[WARN] 未能从 Haiku 获取文本摘要")
        summary = "（摘要生成失败）"

    # 保存总结
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(c if c not in '<>:"/\\|?*' else "_" for c in title)
    output_file = output_dir / f"{safe_title}.md"

    # 如果模型已经返回完整文档（含标题或基本信息），则直接使用，避免重复拼接
    if "## 基本信息" in summary or summary.lstrip().startswith("#"):
        full_content = summary
    else:
        full_content = f"""# 视频总结

## 基本信息
- **标题**: {title}
- **时长**: {duration}
- **来源**: {source}

{summary}
"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(full_content)

    print(f"[INFO] 总结已保存到: {output_file}")



def cleanup(remove_intermediate_files=False):
    """清理临时文件。

    Args:
        remove_intermediate_files: 是否删除 transcript.txt/video_info.json
    """
    if TEMP_DIR.exists():
        import shutil
        import time
        # Windows 上文件可能还被占用，等待一下再删除
        time.sleep(0.5)
        try:
            shutil.rmtree(TEMP_DIR)
            print("[INFO] 临时文件已清理")
        except PermissionError:
            # 忽略权限错误（文件被占用），不影响主流程
            print("[WARN] 临时文件清理被跳过（文件被占用）")

    if remove_intermediate_files:
        for f in [TRANSCRIPT_FILE, VIDEO_INFO_FILE]:
            if f.exists():
                try:
                    f.unlink()
                    print(f"[INFO] 已清理中间文件: {f}")
                except PermissionError:
                    print(f"[WARN] 中间文件清理被跳过（文件被占用）: {f}")


def main():
    if len(sys.argv) < 2:
        print("用法: python video_summary.py <视频路径或URL>")
        sys.exit(1)

    video_input = sys.argv[1]
    source = "本地"
    title = "video"
    duration_sec = 0
    duration_str = "未知"
    transcript = ""
    cleanup_intermediate_files = False

    print(f"[INFO] 工作区根目录: {BASE_DIR}")

    try:
        if is_url(video_input):
            # 规范化 URL（http -> https）
            video_input = normalize_url(video_input)
            print(f"[INFO] 检测到在线视频: {video_input}")

            # 获取视频信息
            title, duration_sec, duration_str, source = get_video_info(video_input)
            print(f"[INFO] 视频标题: {title}")
            print(f"[INFO] 视频时长: {duration_str}")
            print(f"[INFO] 视频来源: {source}")

            # 尝试提取字幕
            transcript = extract_subtitles(video_input)

            if not transcript:
                print("[INFO] 未找到字幕，下载音频进行转录...")
                audio_path = download_audio(video_input)
                print(f"[INFO] 准备进入 Whisper 转录: {audio_path}")
                transcript = transcribe_whisper(audio_path)
        else:
            print(f"[INFO] 检测到本地视频: {video_input}")
            title = Path(video_input).stem
            source = "本地"

            # 获取本地视频时长
            duration_sec = get_local_video_duration(video_input)
            if duration_sec > 0:
                duration_str = f"{int(duration_sec // 60)}分{int(duration_sec % 60)}秒"
            print(f"[INFO] 视频时长: {duration_str}")

            audio_path = extract_audio_local(video_input)
            print(f"[INFO] 准备进入 Whisper 转录: {audio_path}")
            transcript = transcribe_whisper(audio_path)

        # 保存转录结果
        save_transcript(title, duration_sec, duration_str, source, transcript)

        # 生成 AI 总结
        print("[INFO] 正在生成 AI 总结...")
        generate_summary()
        cleanup_intermediate_files = True

        print("\n" + "="*60)
        print("总结完成！")
        print("="*60)

    except Exception as e:
        print(f"[ERROR] 处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        cleanup(remove_intermediate_files=cleanup_intermediate_files)


if __name__ == "__main__":
    main()
