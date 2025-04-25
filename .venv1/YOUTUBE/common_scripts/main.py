import os
import argparse
import shutil
import subprocess
import json
from datetime import datetime
from config import get_channel_config
from audio_processing import get_audio_files_for_video, process_audio_files, add_background_music
from video_processing import preprocess_images, process_photos_and_videos, concat_photos_random, concat_photos_in_order
from subtitles_processing import generate_subtitles
from final_assembly import create_subscribe_frame_list, final_assembly

# Цветовые коды ANSI для вывода в консоль
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

def process_auto_montage(channel_name, video_number=None):
    """Основная функция для автоматического монтажа видео."""
    config = get_channel_config(channel_name)
    if not config:
        print(f"{YELLOW}⚠️ Конфигурация для канала '{channel_name}' не найдена.{RESET}")
        return

    # Извлекаем параметры из конфигурации
    PHOTO_FOLDER = config.get("photo_folder")(config) if callable(config.get("photo_folder")) else config.get("photo_folder")
    OUTPUT_DIRECTORY = config.get("output_directory")(config) if callable(config.get("output_directory")) else config.get("output_directory")
    OUTPUT_FOLDER = config.get("output_folder")(config) if callable(config.get("output_folder")) else config.get("output_folder")
    LOGO_PATH = config.get("logo_path")(config) if callable(config.get("logo_path")) else config.get("logo_path")
    SUBSCRIBE_FRAMES_FOLDER = config.get("subscribe_frames_folder")(config) if callable(config.get("subscribe_frames_folder")) else config.get("subscribe_frames_folder")
    XLSX_FILE_PATH = config.get("xlsx_file_path")(config) if callable(config.get("xlsx_file_path")) else config.get("xlsx_file_path")
    BACKGROUND_MUSIC_PATH = config.get("background_music_path")(config) if callable(config.get("background_music_path")) else config.get("background_music_path")
    USE_SUBFOLDERS = config.get("use_subfolders", True)
    NUM_VIDEOS = config.get("num_videos", 1)
    VIDEO_RESOLUTION = config.get("video_resolution", "1920:1080")
    FRAME_RATE = config.get("frame_rate", 30)
    VIDEO_CRF = config.get("video_crf", 23)
    VIDEO_PRESET = config.get("video_preset", "fast")
    PHOTO_ORDER = config.get("photo_order", "order")
    BOKEH_ENABLED = config.get("bokeh_enabled", True)
    BOKEH_IMAGE_SIZE = tuple(config.get("bokeh_image_size", [1920, 1080]))
    BOKEH_BLUR_KERNEL = tuple(config.get("bokeh_blur_kernel", [99, 99]))
    BOKEH_BLUR_SIGMA = config.get("bokeh_blur_sigma", 30)
    LOGO_WIDTH = config.get("logo_width", 200)
    LOGO_POSITION_X = config.get("logo_position_x", "W-w-20")
    LOGO_POSITION_Y = config.get("logo_position_y", "20")
    LOGO_DURATION = config.get("logo_duration", "all")
    SUBSCRIBE_WIDTH = config.get("subscribe_width", 1400)
    SUBSCRIBE_POSITION_X = config.get("subscribe_position_x", "-50")
    SUBSCRIBE_POSITION_Y = config.get("subscribe_position_y", "main_h-overlay_h+150")
    SUBSCRIBE_DISPLAY_DURATION = config.get("subscribe_display_duration", 7)
    SUBSCRIBE_INTERVAL_GAP = config.get("subscribe_interval_gap", 30)
    AUDIO_BITRATE = config.get("audio_bitrate", "192k")
    AUDIO_SAMPLE_RATE = config.get("audio_sample_rate", 44100)
    AUDIO_CHANNELS = config.get("audio_channels", 1)
    SUBTITLES_ENABLED = config.get("subtitles_enabled", True)
    SUBTITLE_LANGUAGE = config.get("subtitle_language", "ru")
    SUBTITLE_MODEL = config.get("subtitle_model", "medium")
    SUBTITLE_FONTSIZE = config.get("subtitle_fontsize", 110)
    SUBTITLE_FONT_COLOR = config.get("subtitle_font_color", "&HFFFFFF")
    SUBTITLE_USE_BACKDROP = config.get("subtitle_use_backdrop", False)
    SUBTITLE_BACK_COLOR = config.get("subtitle_back_color", "&HFFFFFF")
    SUBTITLE_OUTLINE_THICKNESS = config.get("subtitle_outline_thickness", 4)
    SUBTITLE_OUTLINE_COLOR = config.get("subtitle_outline_color", "&H000000")
    SUBTITLE_SHADOW_THICKNESS = config.get("subtitle_shadow_thickness", 1)
    SUBTITLE_SHADOW_COLOR = config.get("subtitle_shadow_color", "&H333333")
    SUBTITLE_SHADOW_ALPHA = config.get("subtitle_shadow_alpha", 50)
    SUBTITLE_SHADOW_OFFSET_X = config.get("subtitle_shadow_offset_x", 2)
    SUBTITLE_SHADOW_OFFSET_Y = config.get("subtitle_shadow_offset_y", 2)
    SUBTITLE_MARGIN_V = config.get("subtitle_margin_v", 20)
    SUBTITLE_MARGIN_L = config.get("subtitle_margin_l", 10)
    SUBTITLE_MARGIN_R = config.get("subtitle_margin_r", 10)
    SUBTITLE_MAX_WORDS = config.get("subtitle_max_words", 3)
    SUBTITLE_TIME_OFFSET = config.get("subtitle_time_offset", -0.3)
    BACKGROUND_MUSIC_VOLUME = config.get("background_music_volume", 0.2)
    ADJUST_VIDEOS_TO_AUDIO = config.get("adjust_videos_to_audio", True)  # Новая настройка

    # Проверяем пути
    required_paths = {
        "photo_folder": PHOTO_FOLDER,
        "output_directory": OUTPUT_DIRECTORY,
        "output_folder": OUTPUT_FOLDER,
        "subscribe_frames_folder": SUBSCRIBE_FRAMES_FOLDER,
        "xlsx_file_path": XLSX_FILE_PATH
    }
    for path_name, path_value in required_paths.items():
        if not isinstance(path_value, str):
            print(f"{YELLOW}⚠️ Ошибка: '{path_name}' должен быть строкой, но получено: {type(path_value)} (значение: {path_value}).{RESET}")
            return
        if not path_value:
            print(f"{YELLOW}⚠️ Ошибка: '{path_name}' не может быть пустым.{RESET}")
            return

    if not LOGO_PATH or not os.path.isfile(LOGO_PATH):
        print(f"{YELLOW}⚠️ Логотип не найден: {LOGO_PATH}. Наложение логотипа пропущено.{RESET}")
        LOGO_PATH = None
    else:
        print(f"{BLUE}📷 Логотип найден: {LOGO_PATH}{RESET}")

    if not BACKGROUND_MUSIC_PATH or not os.path.isfile(BACKGROUND_MUSIC_PATH):
        print(f"{YELLOW}⚠️ Фоновая музыка не найдена: {BACKGROUND_MUSIC_PATH}. Используется основная аудиодорожка.{RESET}")
        BACKGROUND_MUSIC_PATH = None
    else:
        print(f"{BLUE}🎵 Фоновая музыка найдена: {BACKGROUND_MUSIC_PATH}{RESET}")

    video_numbers = [str(video_number)] if video_number else [str(i) for i in range(1, NUM_VIDEOS + 1)]
    print(f"{BLUE}🎥 Обрабатываем видео: {', '.join(video_numbers)}{RESET}")

    for vid_num in video_numbers:
        print(f"{GREEN}=== 🚀 Монтаж видео {vid_num} ==={RESET}")

        PHOTO_FOLDER_VID = os.path.join(PHOTO_FOLDER, vid_num) if USE_SUBFOLDERS else PHOTO_FOLDER
        OUTPUT_FOLDER_VID = os.path.join(OUTPUT_FOLDER, vid_num)
        os.makedirs(OUTPUT_FOLDER_VID, exist_ok=True)

        print(f"{BLUE}📂 PHOTO_FOLDER: {PHOTO_FOLDER_VID}{RESET}")
        print(f"{BLUE}📂 OUTPUT_DIRECTORY: {OUTPUT_DIRECTORY}{RESET}")
        print(f"{BLUE}📂 OUTPUT_FOLDER: {OUTPUT_FOLDER_VID}{RESET}")
        print(f"{BLUE}📂 SUBSCRIBE_FRAMES_FOLDER: {SUBSCRIBE_FRAMES_FOLDER}{RESET}")
        print(f"{BLUE}📂 XLSX_FILE_PATH: {XLSX_FILE_PATH}{RESET}")
        print(f"{BLUE}📂 LOGO_PATH: {LOGO_PATH or 'Отсутствует'}{RESET}")
        print(f"{BLUE}📂 BACKGROUND_MUSIC_PATH: {BACKGROUND_MUSIC_PATH or 'Отсутствует'}{RESET}")

        if not os.path.exists(PHOTO_FOLDER_VID):
            print(f"{YELLOW}⚠️ Папка не найдена: {PHOTO_FOLDER_VID}. Пропускаем видео {vid_num}.{RESET}")
            continue
        if not os.path.exists(OUTPUT_DIRECTORY):
            print(f"{YELLOW}⚠️ Папка не найдена: {OUTPUT_DIRECTORY}. Пропускаем видео {vid_num}.{RESET}")
            continue
        if not os.path.exists(SUBSCRIBE_FRAMES_FOLDER):
            print(f"{YELLOW}⚠️ Папка не найдена: {SUBSCRIBE_FRAMES_FOLDER}. Пропускаем видео {vid_num}.{RESET}")
            continue
        if not os.path.exists(XLSX_FILE_PATH):
            print(f"{YELLOW}⚠️ Файл не найден: {XLSX_FILE_PATH}. Пропускаем видео {vid_num}.{RESET}")
            continue

        TEMP_FOLDER = os.path.join(OUTPUT_FOLDER_VID, "temp")
        PREPROCESSED_PHOTO_FOLDER = os.path.join(TEMP_FOLDER, "preprocessed_photos")
        TEMP_AUDIO_FOLDER = os.path.join(TEMP_FOLDER, "audio")
        os.makedirs(TEMP_FOLDER, exist_ok=True)
        os.makedirs(PREPROCESSED_PHOTO_FOLDER, exist_ok=True)
        os.makedirs(TEMP_AUDIO_FOLDER, exist_ok=True)

        # Шаг 0: Получение аудиофайлов
        start_time = datetime.now()
        print(f"{BLUE}⏰ Начало обработки: {start_time.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
        audio_files = get_audio_files_for_video(XLSX_FILE_PATH, OUTPUT_DIRECTORY, vid_num, SUBTITLE_LANGUAGE)
        if not audio_files:
            print(f"{YELLOW}⚠️ Не найдены аудиофайлы для видео {vid_num}! Пропускаем.{RESET}")
            continue

        for audio_file in audio_files:
            src_path = os.path.join(OUTPUT_DIRECTORY, audio_file)
            dst_path = os.path.join(TEMP_AUDIO_FOLDER, audio_file)
            if os.path.exists(src_path):
                shutil.copy(src_path, dst_path)
            else:
                print(f"{YELLOW}⚠️ Файл не скопирован: {src_path}{RESET}")

        # Шаг 1: Обработка аудио
        print(f"{GREEN}=== 🎵 Обработка аудио ==={RESET}")
        final_audio_path, temp_audio_duration = process_audio_files(
            audio_files, TEMP_AUDIO_FOLDER, TEMP_FOLDER, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, AUDIO_BITRATE
        )
        if not final_audio_path or not temp_audio_duration:
            print(f"{YELLOW}⚠️ Ошибка обработки аудио для видео {vid_num}! Пропускаем.{RESET}")
            continue

        print(f"{BLUE}🎵 Длительность аудио: {int(temp_audio_duration // 60)}:{int(temp_audio_duration % 60):02d}{RESET}")

        # Шаг 1.1: Добавление фоновой музыки
        final_audio_with_music_path = add_background_music(
            final_audio_path, BACKGROUND_MUSIC_PATH, TEMP_FOLDER, temp_audio_duration,
            AUDIO_BITRATE, AUDIO_SAMPLE_RATE, BACKGROUND_MUSIC_VOLUME
        )

        # Шаг 2: Предобработка изображений
        print(f"{GREEN}=== 🖼️ Предобработка изображений ==={RESET}")
        if BOKEH_ENABLED:
            preprocess_images(PHOTO_FOLDER_VID, PREPROCESSED_PHOTO_FOLDER, BOKEH_ENABLED, BOKEH_IMAGE_SIZE, BOKEH_BLUR_KERNEL, BOKEH_BLUR_SIGMA)
        else:
            for image_filename in os.listdir(PHOTO_FOLDER_VID):
                if image_filename.lower().endswith(('.png', '.jpg', '.jpeg', '.mp4', '.mov')):
                    shutil.copy(os.path.join(PHOTO_FOLDER_VID, image_filename),
                                os.path.join(PREPROCESSED_PHOTO_FOLDER, image_filename))

        # Шаг 3: Обработка фото и видео
        print(f"{GREEN}=== 🎬 Обработка фото и видео ==={RESET}")
        photo_files = sorted([f for f in os.listdir(PREPROCESSED_PHOTO_FOLDER) if f.endswith(('.jpg', '.jpeg', '.png', '.mp4', '.mov'))])
        if not photo_files:
            print(f"{YELLOW}⚠️ Нет фото/видео для видео {vid_num}! Пропускаем.{RESET}")
            continue

        processed_photo_files, skipped_files = process_photos_and_videos(
            photo_files=photo_files,
            preprocessed_photo_folder=PREPROCESSED_PHOTO_FOLDER,
            temp_folder=TEMP_FOLDER,
            video_resolution=VIDEO_RESOLUTION,
            frame_rate=FRAME_RATE,
            video_crf=VIDEO_CRF,
            video_preset=VIDEO_PRESET,
            temp_audio_duration=temp_audio_duration,
            adjust_videos_to_audio=ADJUST_VIDEOS_TO_AUDIO  # Передаём новую настройку
        )
        if not processed_photo_files:
            print(f"{YELLOW}⚠️ Не удалось обработать фото/видео для видео {vid_num}! Пропускаем.{RESET}")
            continue

        print(f"{GREEN}🎬 Обработано файлов: {len(processed_photo_files)} из {len(photo_files)}{RESET}")
        if skipped_files:
            print(f"{YELLOW}⚠️ Пропущенные файлы ({len(skipped_files)}): {', '.join(skipped_files)}{RESET}")

        # Шаг 4: Конкатенация фото/видео
        if PHOTO_ORDER == "order":
            concat_list_path = concat_photos_in_order(processed_photo_files, TEMP_FOLDER, temp_audio_duration)
        else:
            concat_list_path = concat_photos_random(processed_photo_files, TEMP_FOLDER, temp_audio_duration)

        temp_video_path = os.path.join(TEMP_FOLDER, "temp_video.mp4")
        try:
            subprocess.run([
                "ffmpeg",
                "-f", "concat", "-safe", "0", "-i", concat_list_path,
                "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
                "-an", "-map", "0:v", "-map", "-0:s", "-map", "-0:d",
                "-fflags", "+genpts+igndts", "-fps_mode", "cfr", "-async", "1",
                "-probesize", "50000000", "-analyzeduration", "50000000",
                "-t", str(temp_audio_duration),
                "-y", temp_video_path
            ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"{YELLOW}❌ Ошибка при склейке фото/видео: {e.stderr.decode()}{RESET}")
            continue

        # Шаг 5: Создание списка кадров для кнопки
        print(f"{GREEN}🎞️ Накладываю кнопку 'ПОДПИСЫВАЙТЕСЬ' ==={RESET}")
        frame_list_path, num_frames = create_subscribe_frame_list(SUBSCRIBE_FRAMES_FOLDER, TEMP_FOLDER, FRAME_RATE)
        if not frame_list_path:
            print(f"{YELLOW}⚠️ Ошибка создания списка кадров для видео {vid_num}! Пропускаем.{RESET}")
            continue

        # Шаг 6: Генерация субтитров
        subtitles_path = None
        if SUBTITLES_ENABLED:
            print(f"{GREEN}=== 📝 Генерация субтитров ==={RESET}")
            subtitles_path = generate_subtitles(
                final_audio_with_music_path, TEMP_FOLDER, SUBTITLE_MODEL, SUBTITLE_LANGUAGE, SUBTITLE_MAX_WORDS,
                SUBTITLE_TIME_OFFSET, temp_audio_duration, SUBTITLE_FONTSIZE, SUBTITLE_FONT_COLOR, SUBTITLE_USE_BACKDROP,
                SUBTITLE_BACK_COLOR, SUBTITLE_OUTLINE_THICKNESS, SUBTITLE_OUTLINE_COLOR, SUBTITLE_SHADOW_THICKNESS,
                SUBTITLE_SHADOW_COLOR, SUBTITLE_SHADOW_ALPHA, SUBTITLE_SHADOW_OFFSET_X, SUBTITLE_SHADOW_OFFSET_Y,
                SUBTITLE_MARGIN_L, SUBTITLE_MARGIN_R, SUBTITLE_MARGIN_V
            )
            if not subtitles_path:
                print(f"{YELLOW}⚠️ Ошибка генерации субтитров для видео {vid_num}!{RESET}")

        # Шаг 7: Финальная сборка
        print(f"{MAGENTA}=== 🏗️ Финальная сборка ==={RESET}")
        output_file = os.path.join(OUTPUT_FOLDER_VID, "final_video.mp4")
        final_video_path = final_assembly(
            temp_video_path, final_audio_with_music_path, output_file, TEMP_FOLDER, frame_list_path, num_frames,
            LOGO_PATH, subtitles_path, VIDEO_RESOLUTION, FRAME_RATE, VIDEO_CRF, VIDEO_PRESET, temp_audio_duration,
            LOGO_WIDTH, LOGO_POSITION_X, LOGO_POSITION_Y, LOGO_DURATION, SUBSCRIBE_WIDTH, SUBSCRIBE_POSITION_X,
            SUBSCRIBE_POSITION_Y, SUBSCRIBE_DISPLAY_DURATION, SUBSCRIBE_INTERVAL_GAP, SUBTITLES_ENABLED
        )
        if not final_video_path:
            print(f"{YELLOW}❌ Ошибка финальной сборки для видео {vid_num}!{RESET}")
            continue

        # Проверка длительности
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", output_file]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        try:
            probe_data = json.loads(probe_result.stdout)
            final_video_duration = float(probe_data["format"]["duration"])
        except (json.JSONDecodeError, KeyError) as e:
            print(f"{YELLOW}❌ Ошибка при разборе длительности финального видео: {str(e)}{RESET}")
            continue

        print(f"{GREEN}🎥 Длительность видео: {int(final_video_duration // 60)}:{int(final_video_duration % 60):02d}{RESET}")
        if abs(final_video_duration - temp_audio_duration) > 0.1:
            print(f"{YELLOW}⚠️ Длительность видео не совпадает с аудио: {final_video_duration:.2f} против {temp_audio_duration:.2f}!{RESET}")

        print(f"{GREEN}=== ✅ Монтаж видео {vid_num} завершён! Видео: {output_file} ==={RESET}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Скрипт автоматического монтажа видео.')
    parser.add_argument('--channel', type=str, required=True, help='Название канала для монтажа')
    parser.add_argument('--video_number', type=str, default=None, help='Номер видео (если не указан, обрабатываются все видео)')
    args = parser.parse_args()
    process_auto_montage(args.channel, args.video_number)