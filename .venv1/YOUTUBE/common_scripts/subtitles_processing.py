import os
import whisper
import ssl
from tqdm import tqdm
from utils import rgb_to_bgr, add_alpha_to_color, format_time

# Цветовые коды ANSI для вывода в консоль
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def split_segment(segment, max_words, time_offset, max_duration):
    """Разбивает сегмент субтитров на подсегменты с максимум max_words слов."""
    words = segment["text"].strip().split()
    duration = segment["end"] - segment["start"]
    total_words = len(words)

    start_shifted = max(0, segment["start"] + time_offset)
    end_shifted = min(start_shifted + duration, max_duration)

    if total_words <= max_words:
        return [{
            "start": start_shifted,
            "end": end_shifted,
            "text": segment["text"]
        }]

    new_segments = []
    for i in range(0, total_words, max_words):
        chunk_words = words[i:i + max_words]
        chunk_text = " ".join(chunk_words)
        chunk_duration = duration * len(chunk_words) / total_words
        chunk_start = start_shifted + (i / total_words) * duration
        chunk_end = min(chunk_start + chunk_duration, max_duration)
        if chunk_end > chunk_start:
            new_segments.append({
                "start": chunk_start,
                "end": chunk_end,
                "text": chunk_text
            })
    return new_segments

def generate_subtitles(audio_path, temp_folder, subtitle_model, subtitle_language, subtitle_max_words, subtitle_time_offset, temp_audio_duration, subtitle_fontsize, subtitle_font_color, subtitle_use_backdrop, subtitle_back_color, subtitle_outline_thickness, subtitle_outline_color, subtitle_shadow_thickness, subtitle_shadow_color, subtitle_shadow_alpha, subtitle_shadow_offset_x, subtitle_shadow_offset_y, subtitle_margin_l, subtitle_margin_r, subtitle_margin_v):
    """Генерирует субтитры из аудио и сохраняет их в формате ASS."""
    subtitles_path = os.path.join(temp_folder, "subtitles.ass")
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        model = whisper.load_model(subtitle_model)
        print(f"{BLUE}🎤 Модель Whisper ({subtitle_model}) загружена{RESET}")
    except Exception as e:
        print(f"{YELLOW}❌ Ошибка при загрузке модели Whisper: {str(e)}{RESET}")
        return None

    try:
        result = model.transcribe(audio_path, language=subtitle_language)
        print(f"{BLUE}🎤 Whisper успешно транскрибировал аудио. Количество сегментов: {len(result['segments'])}{RESET}")
    except Exception as e:
        print(f"{YELLOW}❌ Ошибка при транскрибировании аудио: {str(e)}{RESET}")
        return None

    if not result["segments"]:
        print(f"{YELLOW}⚠️ Whisper не обнаружил текст в аудио!{RESET}")
        return None

    processed_segments = []
    for segment in result["segments"]:
        processed_segments.extend(split_segment(segment, subtitle_max_words, subtitle_time_offset, temp_audio_duration))

    subtitle_font_color_bgr = rgb_to_bgr(subtitle_font_color)
    subtitle_outline_color_bgr = rgb_to_bgr(subtitle_outline_color)
    subtitle_shadow_color_with_alpha = add_alpha_to_color(rgb_to_bgr(subtitle_shadow_color), subtitle_shadow_alpha)
    print(f"{BLUE}🎨 Цвет шрифта субтитров: {subtitle_font_color_bgr}{RESET}")
    print(f"{BLUE}🎨 Цвет обводки субтитров: {subtitle_outline_color_bgr}{RESET}")
    print(f"{BLUE}🎨 Цвет тени субтитров: {subtitle_shadow_color_with_alpha}{RESET}")

    border_style = 3 if subtitle_use_backdrop else 1
    with open(subtitles_path, "w", encoding="utf-8") as f:
        f.write(f"""[Script Info]
Title: Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{subtitle_fontsize},{subtitle_font_color_bgr},&H000000,{subtitle_outline_color_bgr},{subtitle_back_color},0,0,0,0,100,100,0,0,{border_style},{subtitle_outline_thickness},{subtitle_shadow_thickness},2,{subtitle_margin_l},{subtitle_margin_r},{subtitle_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""")
        for i, segment in enumerate(processed_segments, 1):
            start_time = format_time(max(0, segment["start"]))
            end_time = format_time(min(segment["end"], temp_audio_duration))
            if end_time <= start_time:
                continue
            text = segment["text"].strip().replace("\n", "\\N")
            shadow_tag = f"\\shad{subtitle_shadow_offset_x},{subtitle_shadow_offset_y}"
            f.write(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{{{shadow_tag}}}{text}\n")

    if os.path.exists(subtitles_path):
        print(f"{BLUE}📝 ASS-файл с субтитрами создан: {subtitles_path}{RESET}")
        return subtitles_path
    else:
        print(f"{YELLOW}⚠️ ASS-файл с субтитрами не создан!{RESET}")
        return None