import sys
import os
from pathlib import Path

# Добавляем путь к common_scripts в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common_scripts")))

from main import process_auto_montage

# Имя канала и номер видео
channel_name = "13 Formula Salud!"  # Укажите имя канала
video_number = ""  # Укажите номер видео, если нужно, или оставьте пустым для обработки всех видео

# Временные настройки на основе config.txt (замените на импорт из config.py, когда уточните его структуру)
channel_config = {
    "channel_folder": "13 Formula Salud!",
    "base_path": "/Users/mikman/Youtube/Структура",
    "num_videos": 11,
    "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовое видео",
}

# Получаем конфигурацию
num_videos = channel_config.get("num_videos", 1)
output_folder = channel_config["output_folder"](channel_config)


def is_video_processed(video_num):
    """Проверяет, существует ли выходной файл для видео с номером video_num."""
    video_output_path = os.path.join(output_folder, str(video_num), "final_video.mp4")
    return os.path.exists(video_output_path)


if video_number:
    # Обработка одного конкретного видео
    print(f"📥 Обрабатываем видео: {video_number}")
    try:
        process_auto_montage(channel_name, video_number=video_number)
    except Exception as e:
        print(f"❌ Ошибка при обработке видео {video_number}: {e}")
else:
    # Обработка всех видео, начиная с первого необработанного
    start_video = None
    for i in range(1, num_videos + 1):
        if not is_video_processed(i):
            start_video = i
            break

    if start_video is None:
        print(f"✅ Все видео (1–{num_videos}) уже обработаны!")
    else:
        print(f"📥 Начинаем обработку с видео {start_video}")
        for i in range(start_video, num_videos + 1):
            if not is_video_processed(i):
                print(f"📥 Обрабатываем видео: {i}")
                try:
                    process_auto_montage(channel_name, video_number=str(i))
                except Exception as e:
                    print(f"❌ Ошибка при обработке видео {i}: {e}")
                    continue
            else:
                print(f"⏭️ Видео {i} уже обработано, пропускаем")