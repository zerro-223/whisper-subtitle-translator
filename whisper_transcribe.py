"""
使用 Whisper large-v3 模型进行本地音视频字幕识别
支持输出 SRT 字幕文件 + 字幕翻译
"""

import argparse
import os
import sys
import time
from pathlib import Path

# 将模型缓存目录设置为项目下的 whisper 文件夹
PROJECT_DIR = Path(__file__).parent
os.environ["XDG_CACHE_HOME"] = str(PROJECT_DIR)

import whisper
import torch
from translate_api import (
    create_translator,
    get_lang_code,
    load_config,
)


def format_timestamp(seconds: float) -> str:
    """将秒数转换为 SRT 时间戳格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list) -> str:
    """将 Whisper 识别的 segments 转换为 SRT 格式字符串"""
    srt_lines = []
    for i, segment in enumerate(segments, start=1):
        start = format_timestamp(segment["start"])
        end = format_timestamp(segment["end"])
        text = segment["text"].strip()
        srt_lines.append(f"{i}")
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(text)
        srt_lines.append("")
    return "\n".join(srt_lines)


def translate_srt(
    srt_content: str,
    translator_type: str,
    from_lang: str,
    to_lang: str,
    progress_callback=None,
    stop_event=None,
    **translator_kwargs,
) -> str:
    """
    翻译 SRT 字幕内容

    Args:
        srt_content: SRT 格式的字幕内容
        translator_type: 翻译器类型 (deepl/baidu/youdao/google/llm)
        from_lang: 源语言代码
        to_lang: 目标语言代码
        progress_callback: 可选进度回调 fn(count, total, text, result)
        stop_event: 可选 threading.Event，设置后中断逐句翻译
        **translator_kwargs: 翻译器参数

    Returns:
        翻译后的 SRT 内容
    """
    translator = create_translator(translator_type, **translator_kwargs)
    from_code = get_lang_code(translator_type, from_lang)
    to_code = get_lang_code(translator_type, to_lang)

    print(f"使用 {translator.get_name()} 翻译: {from_lang} -> {to_lang}")

    lines = srt_content.strip().split("\n")

    # 收集所有需要翻译的文本和位置
    text_positions = []  # (line_index, text)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.isdigit() and "-->" not in stripped:
            text_positions.append((idx, stripped))

    total = len(text_positions)
    if total == 0:
        return srt_content

    # 批量翻译模式（LLM）
    if hasattr(translator, 'translate_batch'):
        texts = [t for _, t in text_positions]
        batch_results = translator.translate_batch(texts, from_code, to_code)

        translated_lines = list(lines)
        for i, ((idx, original), result) in enumerate(zip(text_positions, batch_results), 1):
            translated_lines[idx] = result
            if progress_callback:
                progress_callback(i, total, original, result)
            else:
                print(f"  [{i}/{total}] {original[:30]}... -> {result[:30]}...")
        return "\n".join(translated_lines)

    # 逐句翻译模式
    translated_lines = list(lines)
    for i, (idx, text) in enumerate(text_positions, 1):
        if stop_event and stop_event.is_set():
            print("  翻译已被用户中断")
            break
        try:
            translated = translator.translate(text, from_code, to_code)
            translated_lines[idx] = translated
            if progress_callback:
                progress_callback(i, total, text, translated)
            else:
                print(f"  [{i}/{total}] {text[:30]}... -> {translated[:30]}...")
        except Exception as e:
            print(f"  [{i}/{total}] 翻译失败: {e}，保留原文")
        time.sleep(0.1)

    return "\n".join(translated_lines)


def parse_srt(srt_content: str) -> list:
    """解析 SRT 内容为结构化数据"""
    segments = []
    lines = srt_content.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.isdigit():
            index = int(line)
            i += 1
            if i < len(lines) and "-->" in lines[i]:
                time_parts = lines[i].split("-->")
                start = time_parts[0].strip()
                end = time_parts[1].strip()
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                segments.append({
                    "index": index,
                    "start": start,
                    "end": end,
                    "text": "\n".join(text_lines),
                })
            else:
                i += 1
        else:
            i += 1
    return segments


def build_bilingual_srt(original_segments: list, translated_segments: list) -> str:
    """构建双语字幕"""
    srt_lines = []
    for i, (orig, trans) in enumerate(zip(original_segments, translated_segments), start=1):
        srt_lines.append(str(i))
        srt_lines.append(f"{orig['start']} --> {orig['end']}")
        srt_lines.append(trans['text'])
        srt_lines.append(orig['text'])
        srt_lines.append("")
    return "\n".join(srt_lines)


def transcribe_file(
    input_path: str,
    model_name: str = "large-v3",
    language: str | None = None,
    output_dir: str | None = None,
    device: str | None = None,
    word_timestamps: bool = False,
    translate_to: str | None = None,
    translator_type: str = "google",
    bilingual: bool = False,
    **translator_kwargs,
) -> str:
    """
    对音视频文件进行字幕识别

    Args:
        input_path: 输入的音频或视频文件路径
        model_name: Whisper 模型名称 (默认 large-v3)
        language: 指定语言代码，如 'zh', 'en', 'ja' 等，None 表示自动检测
        output_dir: 输出目录，默认与输入文件相同目录
        device: 计算设备，'cuda' 或 'cpu'，None 自动选择
        word_timestamps: 是否生成词级时间戳
        translate_to: 翻译目标语言代码，None 表示不翻译
        translator_type: 翻译器类型 (deepl/baidu/youdao/google)
        bilingual: 是否生成双语字幕
        **translator_kwargs: 翻译器参数

    Returns:
        输出的 SRT 文件路径
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"文件不存在: {input_path}")

    supported_formats = {
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    }
    if input_path.suffix.lower() not in supported_formats:
        raise ValueError(
            f"不支持的文件格式: {input_path.suffix}\n"
            f"支持的格式: {', '.join(sorted(supported_formats))}"
        )

    # 自动选择设备
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model_dir = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")) / "whisper"
    print(f"模型缓存目录: {model_dir}")
    print(f"正在加载模型 {model_name}...")
    print(f"使用设备: {device}")
    start_time = time.time()
    model = whisper.load_model(model_name, device=device)
    print(f"模型加载完成，耗时 {time.time() - start_time:.1f}s")

    # 构建转录选项
    transcribe_options = {
        "word_timestamps": word_timestamps,
        "verbose": False,
    }
    if language:
        transcribe_options["language"] = language

    print(f"正在识别: {input_path}")
    start_time = time.time()
    result = model.transcribe(str(input_path), **transcribe_options)
    elapsed = time.time() - start_time
    print(f"识别完成，耗时 {elapsed:.1f}s")

    detected_lang = result.get("language", "unknown")
    print(f"检测到的语言: {detected_lang}")

    # 生成 SRT 内容
    srt_content = segments_to_srt(result["segments"])

    # 确定输出路径
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = input_path.parent

    # 保存原文字幕
    output_path = output_dir / f"{input_path.stem}.srt"
    output_path.write_text(srt_content, encoding="utf-8")
    print(f"原文字幕已保存到: {output_path}")

    # 翻译字幕
    if translate_to:
        translated_srt = translate_srt(
            srt_content,
            translator_type,
            detected_lang,
            translate_to,
            **translator_kwargs,
        )

        if bilingual:
            # 生成双语字幕
            original_segments = parse_srt(srt_content)
            translated_segments = parse_srt(translated_srt)
            bilingual_srt = build_bilingual_srt(original_segments, translated_segments)
            bilingual_path = output_dir / f"{input_path.stem}.{translate_to}.srt"
            bilingual_path.write_text(bilingual_srt, encoding="utf-8")
            print(f"双语字幕已保存到: {bilingual_path}")
        else:
            # 生成翻译字幕
            translated_path = output_dir / f"{input_path.stem}.{translate_to}.srt"
            translated_path.write_text(translated_srt, encoding="utf-8")
            print(f"翻译字幕已保存到: {translated_path}")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="使用 Whisper large-v3 模型进行本地音视频字幕识别 + 翻译"
    )
    parser.add_argument(
        "input",
        help="输入的音频或视频文件路径（支持 mp3/wav/mp4/mkv/avi 等格式）",
    )
    parser.add_argument(
        "-m", "--model",
        default="large-v3",
        help="Whisper 模型名称 (默认: large-v3)，可选 tiny/base/small/medium/large-v3",
    )
    parser.add_argument(
        "-l", "--language",
        default=None,
        help="指定语言代码，如 zh/en/ja/ko 等（默认自动检测）",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="输出目录（默认与输入文件同目录）",
    )
    parser.add_argument(
        "-d", "--device",
        default=None,
        choices=["cuda", "cpu"],
        help="计算设备（默认自动选择）",
    )
    parser.add_argument(
        "-w", "--word-timestamps",
        action="store_true",
        help="启用词级时间戳",
    )

    # 翻译参数
    parser.add_argument(
        "-t", "--translate-to",
        default=None,
        help="翻译目标语言代码，如 zh/en/ja/ko 等（不指定则不翻译）",
    )
    parser.add_argument(
        "-T", "--translator",
        default="google",
        choices=["llm", "deepl", "baidu", "youdao", "google"],
        help="翻译器类型 (默认: google)",
    )
    parser.add_argument(
        "--bilingual",
        action="store_true",
        help="生成双语字幕（原文+译文）",
    )
    # LLM 翻译参数
    parser.add_argument(
        "--api-key",
        default=None,
        help="翻译 API Key（LLM/DeepL）",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.openai.com/v1",
        help="LLM API Base URL (默认: https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4o-mini",
        help="LLM 模型名称 (默认: gpt-4o-mini)",
    )

    args = parser.parse_args()

    # 构建翻译器参数
    translator_kwargs = {}
    if args.translator == "llm":
        if not args.api_key:
            print("错误: 使用 LLM 翻译需要提供 --api-key", file=sys.stderr)
            sys.exit(1)
        translator_kwargs = {
            "api_key": args.api_key,
            "base_url": args.base_url,
            "model": args.llm_model,
        }
    elif args.translator == "deepl":
        if not args.api_key:
            print("错误: 使用 DeepL 翻译需要提供 --api-key", file=sys.stderr)
            sys.exit(1)
        translator_kwargs = {"api_key": args.api_key}
    elif args.translator == "baidu":
        config = load_config()
        if "baidu" not in config:
            print("错误: 使用百度翻译需要在 translate_config.json 中配置 app_id 和 secret_key", file=sys.stderr)
            sys.exit(1)
        translator_kwargs = config["baidu"]
    elif args.translator == "youdao":
        config = load_config()
        if "youdao" not in config:
            print("错误: 使用有道翻译需要在 translate_config.json 中配置 app_key 和 app_secret", file=sys.stderr)
            sys.exit(1)
        translator_kwargs = config["youdao"]

    try:
        output_path = transcribe_file(
            input_path=args.input,
            model_name=args.model,
            language=args.language,
            output_dir=args.output_dir,
            device=args.device,
            word_timestamps=args.word_timestamps,
            translate_to=args.translate_to,
            translator_type=args.translator,
            bilingual=args.bilingual,
            **translator_kwargs,
        )
        print(f"\n完成! 原文字幕: {output_path}")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
