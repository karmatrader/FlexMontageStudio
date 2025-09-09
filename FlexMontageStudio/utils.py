import re
import os
import unicodedata

# Цветовые коды ANSI для вывода в консоль
BLUE = "\033[94m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


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


def find_matching_folder(photo_folder, video_number, start_row, end_row, fallback_mode="error"):
    """Ищет папку, соответствующую номеру видео, и подпапку по диапазону строк."""
    # Нормализуем путь для избежания проблем с кодировкой
    photo_folder = unicodedata.normalize('NFC', photo_folder)
    print(f"{BLUE}📂 Проверяю папку с фото: {photo_folder}{RESET}")

    if not os.path.exists(photo_folder):
        print(f"{YELLOW}❌ Папка с фото не найдена: {photo_folder}{RESET}")
        return None

    # Получаем список элементов в папке
    try:
        folder_contents = os.listdir(photo_folder)
    except Exception as e:
        print(f"{YELLOW}❌ Ошибка при чтении содержимого папки {photo_folder}: {str(e)}{RESET}")
        return None

    print(f"{BLUE}📂 Содержимое папки Фото: {folder_contents}{RESET}")

    # Ищем папку с именем, соответствующим номеру видео
    target_folder = str(video_number)
    video_folder_path = os.path.join(photo_folder, target_folder)

    if target_folder not in folder_contents or not os.path.isdir(video_folder_path):
        # Если папка не найдена, проверяем параметр fallback_mode
        available_folders = []  # Инициализируем список доступных папок
        if fallback_mode == "closest":
            closest_folder = None
            closest_diff = float('inf')
            for folder_name in folder_contents:
                folder_path = os.path.join(photo_folder, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                try:
                    folder_num = int(folder_name)
                    available_folders.append((folder_name, folder_num))
                    diff = abs(folder_num - int(video_number))
                    if diff < closest_diff:
                        closest_diff = diff
                        closest_folder = folder_path
                except ValueError:
                    print(f"{YELLOW}⚠️ Папка {folder_name} не является номером видео, пропускаю{RESET}")
                    continue

            if closest_folder:
                print(
                    f"{YELLOW}⚠️ Папка для видео {video_number} не найдена. Использую ближайшую папку: {closest_folder}{RESET}")
                video_folder_path = closest_folder
            else:
                print(
                    f"{YELLOW}❌ Не найдена подходящая папка для видео {video_number} в {photo_folder}. Доступные папки: {available_folders}{RESET}")
                return None
        else:
            print(
                f"{YELLOW}❌ Не найдена папка для видео {video_number} в {photo_folder}. Доступные папки: {available_folders}{RESET}")
            return None

    print(f"{GREEN}✅ Найдена папка для видео {video_number}: {video_folder_path}{RESET}")

    # Теперь ищем подпапку внутри video_folder_path, которая соответствует диапазону строк
    try:
        subfolder_contents = os.listdir(video_folder_path)
    except Exception as e:
        print(f"{YELLOW}❌ Ошибка при чтении содержимого папки {video_folder_path}: {str(e)}{RESET}")
        return None

    print(f"{BLUE}📂 Содержимое папки {video_folder_path}: {subfolder_contents}{RESET}")

    matching_subfolders = []
    best_subfolder = None
    closest_start = float('inf')
    available_subfolders = []

    for subfolder_name in subfolder_contents:
        subfolder_path = os.path.join(video_folder_path, subfolder_name)
        if not os.path.isdir(subfolder_path):
            continue
        try:
            folder_start, folder_end = map(int, subfolder_name.split('-'))
            available_subfolders.append((subfolder_name, folder_start, folder_end))
            # Проверяем, пересекаются ли диапазоны
            if start_row <= folder_end and (end_row - 1) >= folder_start:
                print(f"{GREEN}✅ Найдена подходящая подпапка: {subfolder_path}{RESET}")
                matching_subfolders.append(subfolder_path)
            # Ищем ближайшую подпапку по началу диапазона для fallback
            if folder_start <= start_row and (start_row - folder_start) < closest_start:
                closest_start = start_row - folder_start
                best_subfolder = subfolder_path
            elif folder_start > start_row and (folder_start - start_row) < closest_start:
                closest_start = folder_start - start_row
                best_subfolder = subfolder_path
        except (ValueError, IndexError):
            print(f"{YELLOW}⚠️ Подпапка {subfolder_name} не соответствует формату 'start-end', пропускаю{RESET}")
            continue

    # ИСПРАВЛЕНО: Если найдено несколько подходящих подпапок, возвращаем родительскую папку
    # чтобы find_files() мог рекурсивно обработать ВСЕ подпапки
    if len(matching_subfolders) > 1:
        print(f"{GREEN}✅ Найдено {len(matching_subfolders)} подходящих подпапок. Возвращаем родительскую папку для рекурсивного сканирования: {video_folder_path}{RESET}")
        return video_folder_path
    elif len(matching_subfolders) == 1:
        print(f"{GREEN}✅ Найдена одна подходящая подпапка: {matching_subfolders[0]}{RESET}")
        return matching_subfolders[0]

    # Fallback логика остается прежней
    if best_subfolder and fallback_mode == "closest":
        print(
            f"{YELLOW}⚠️ Точный диапазон для строк {start_row}-{end_row - 1} не найден. Использую ближайшую подпапку: {best_subfolder}{RESET}")
        return best_subfolder

    print(
        f"{YELLOW}❌ Не найдена подходящая подпапка для строк {start_row}-{end_row - 1} в {video_folder_path}. Доступные подпапки: {available_subfolders}{RESET}")
    return None


def find_files(directory, extensions, recursive=True):
    """Ищет файлы с заданными расширениями в папке, включая подпапки, если recursive=True."""
    extensions = tuple(ext.lower() for ext in extensions)  # Приводим расширения к нижнему регистру
    matching_files = []
    skipped_files = []
    print(f"{BLUE}📂 Поиск файлов в {directory} с расширениями {extensions}{RESET}")

    for root, dirs, files in os.walk(directory):
        for f in files:
            file_path = os.path.join(root, f)
            file_ext = os.path.splitext(f)[1].lower()  # Приводим расширение файла к нижнему регистру
            if file_ext in extensions:
                print(f"{GREEN}✅ Найден файл: {file_path}{RESET}")
                matching_files.append(file_path)
            else:
                print(f"{YELLOW}⚠️ Пропущен файл (неподдерживаемое расширение): {file_path}{RESET}")
                skipped_files.append(file_path)
        if not recursive:
            break  # Останавливаемся после первого уровня, если recursive=False

    print(f"{BLUE}📂 Найдено {len(matching_files)} файлов: {matching_files}{RESET}")
    if skipped_files:
        print(f"{YELLOW}⚠️ Пропущено {len(skipped_files)} файлов: {skipped_files}{RESET}")
    return matching_files


def natural_sort_key(s):
    """Функция для натуральной сортировки: разделяет строку на числа и не-числа."""
    parts = re.split(r'(\d+)', s)
    return [int(part) if part.isdigit() else part.lower() for part in parts]