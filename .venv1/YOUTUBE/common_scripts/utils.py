import re

def filter_hidden_files(files):
    """Фильтрует скрытые файлы (начинающиеся с точки)."""
    return [file for file in files if not file.startswith(".")]

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