"""
Утилиты для FlexMontage Studio
"""
from .app_paths import get_app_directory, get_config_file_path, ensure_config_files_external, create_sample_config_files

# Импортируем функции из основного utils.py
import sys
from pathlib import Path

# Добавляем корневую папку в путь для импорта utils.py
utils_root = Path(__file__).parent.parent
if str(utils_root) not in sys.path:
    sys.path.insert(0, str(utils_root))

try:
    from utils import filter_hidden_files, natural_sort_key, find_files, rgb_to_bgr, add_alpha_to_color, format_time, find_matching_folder
except ImportError:
    # Если импорт не удался, определяем функции локально
    def filter_hidden_files(files):
        """Фильтрует скрытые файлы (начинающиеся с точки)."""
        return [file for file in files if not file.startswith(".")]
    
    def natural_sort_key(s):
        """Ключ для естественной сортировки."""
        import re
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', str(s))]
    
    def find_files(directory, extensions, recursive=True):
        """Находит файлы с указанными расширениями."""
        import os
        found_files = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                if any(file.lower().endswith(ext.lower()) for ext in extensions):
                    found_files.append(os.path.join(root, file))
            if not recursive:
                break
        return found_files
    
    def rgb_to_bgr(color):
        """Проверяет и возвращает цвет в формате BGR для ASS."""
        color = color.replace("&H", "")
        if len(color) == 6:  # Формат без альфа-канала (BBGGRR)
            return f"&H{color}"
        elif len(color) == 8:  # Формат с альфа-каналом (AABBGGRR)
            return f"&H{color}"
        return color
    
    def add_alpha_to_color(color, alpha):
        """Добавляет альфа-канал к цвету."""
        color = color.replace("&H", "")
        alpha_hex = f"{alpha:02X}"
        return f"&H{alpha_hex}{color}"
    
    def format_time(seconds):
        """Форматирует время в ASS-формат (H:MM:SS.CC)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours}:{minutes:02d}:{secs:02d}.{millis // 10:02d}"
    
    def find_matching_folder(photo_folder, video_number, start_row, end_row, fallback_mode="error"):
        """Ищет папку, соответствующую номеру видео, и подпапку по диапазону строк."""
        import os
        import unicodedata
        
        # Нормализуем путь для избежания проблем с кодировкой
        photo_folder = unicodedata.normalize('NFC', photo_folder)
        print(f"📂 Проверяю папку с фото: {photo_folder}")

        if not os.path.exists(photo_folder):
            print(f"❌ Папка с фото не найдена: {photo_folder}")
            return None

        # Получаем список элементов в папке
        try:
            folder_contents = os.listdir(photo_folder)
        except Exception as e:
            print(f"❌ Ошибка при чтении содержимого папки {photo_folder}: {str(e)}")
            return None

        print(f"📂 Содержимое папки Фото: {folder_contents}")

        # Ищем папку с именем, соответствующим номеру видео
        target_folder = str(video_number)
        video_folder_path = os.path.join(photo_folder, target_folder)

        if target_folder not in folder_contents or not os.path.isdir(video_folder_path):
            print(f"❌ Не найдена папка для видео {video_number} в {photo_folder}")
            return None

        print(f"✅ Найдена папка для видео {video_number}: {video_folder_path}")
        return video_folder_path

__all__ = [
    'get_app_directory',
    'get_config_file_path', 
    'ensure_config_files_external',
    'create_sample_config_files',
    'filter_hidden_files',
    'natural_sort_key', 
    'find_files',
    'rgb_to_bgr',
    'add_alpha_to_color',
    'format_time',
    'find_matching_folder'
]