# Настройки
MAIN_FOLDER = "/Users/mikman/Downloads/МАКИЯЖ ДОДЕЛАТЬ 1-2"  # Укажите главную папку
TARGET_FOLDER = "/Users/mikman/Youtube/Структура/Фото/7"  # Путь к папке, куда переместятся файлы

START_NUMBER_BASE = 111  # Начальный номер для первой папки
INCREMENT = 110  # Шаг для начальных номеров (111, 221, 331 и т.д.)

import os
import random
import shutil
import re
from PIL import Image

# Проверяем, существует ли целевая папка, и создаем её, если не существует
if not os.path.exists(TARGET_FOLDER):
    os.makedirs(TARGET_FOLDER)

# Функция для натуральной сортировки
def natural_sort_key(s):
    # Разбиваем строку на части: числа и не-числа
    parts = re.split(r'(\d+)', s)
    # Преобразуем числовые части в int для правильного сравнения
    return [int(part) if part.isdigit() else part.lower() for part in parts]

def get_all_subfolders(main_folder):
    # Получаем все подпапки рекурсивно
    subfolders = []
    for root, dirs, _ in os.walk(main_folder):
        for dir_name in dirs:
            subfolders.append(os.path.join(root, dir_name))
    # Сортируем подпапки с использованием натуральной сортировки по имени папки
    subfolders.sort(key=lambda x: natural_sort_key(os.path.basename(x)))
    return subfolders

def rename_and_copy_files_in_folder(folder_path, start_number):
    # Получаем список всех файлов в папке
    files = os.listdir(folder_path)
    # Фильтруем только файлы (исключаем папки)
    files = [f for f in files if os.path.isfile(os.path.join(folder_path, f))]
    # Сортируем файлы с использованием натуральной сортировки (без учета расширения)
    files.sort(key=lambda x: natural_sort_key(os.path.splitext(x)[0]))

    # Счетчик для нумерации
    counter = 0

    # Поддерживаемые форматы изображений для конвертации
    image_extensions = {'.png', '.webp', '.jpeg', '.jpg', '.bmp', '.gif', '.tiff'}

    # Обрабатываем каждый файл
    for filename in files:
        # Полный путь к текущему файлу
        old_file_path = os.path.join(folder_path, filename)

        # Получаем расширение файла
        file_extension = os.path.splitext(filename)[1].lower()

        # Определяем новое расширение (по умолчанию .jpg для изображений)
        new_extension = '.jpg' if file_extension in image_extensions else file_extension

        # Формируем новое имя файла
        new_filename = f"{start_number + counter}{new_extension}"
        new_file_path = os.path.join(TARGET_FOLDER, new_filename)

        # Проверяем, существует ли файл с таким именем в целевой папке
        while os.path.exists(new_file_path):
            counter += 1
            new_filename = f"{start_number + counter}{new_extension}"
            new_file_path = os.path.join(TARGET_FOLDER, new_filename)

        # Если файл — изображение, конвертируем его в .jpg
        if file_extension in image_extensions:
            try:
                # Открываем изображение
                with Image.open(old_file_path) as img:
                    # Конвертируем в RGB, если нужно (например, для PNG с прозрачностью)
                    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                        background = Image.new('RGB', img.size, (255, 255, 255))  # Белый фон
                        background.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    # Сохраняем как .jpg с высоким качеством
                    img.save(new_file_path, 'JPEG', quality=95)
                print(f"Папка: {folder_path}, Скопирован и конвертирован: {filename} -> {new_filename}")
            except Exception as e:
                print(f"Ошибка при конвертации {filename}: {e}")
                # Если конвертация не удалась, просто копируем файл
                shutil.copy2(old_file_path, new_file_path)
                print(f"Папка: {folder_path}, Скопирован без конвертации: {filename} -> {new_filename}")
        else:
            # Если это не изображение, просто копируем файл
            shutil.copy2(old_file_path, new_file_path)
            print(f"Папка: {folder_path}, Скопирован: {filename} -> {new_filename}")

        # Увеличиваем счетчик
        counter += 1

    return counter

# Обрабатываем главную папку и все подпапки
total_files_processed = 0

# Сначала обрабатываем файлы в главной папке
print(f"\nОбрабатывается главная папка: {MAIN_FOLDER} с начальным номером: {START_NUMBER_BASE}")
files_processed = rename_and_copy_files_in_folder(MAIN_FOLDER, START_NUMBER_BASE)
total_files_processed += files_processed

# Затем обходим все подпапки
subfolders = get_all_subfolders(MAIN_FOLDER)
for index, folder_path in enumerate(subfolders):
    # Вычисляем начальный номер для этой подпапки (221, 331 и т.д.)
    start_number = START_NUMBER_BASE + ((index + 1) * INCREMENT)
    print(f"\nОбрабатывается подпапка: {folder_path} с начальным номером: {start_number}")

    # Копируем и переименовываем файлы из подпапки
    files_processed = rename_and_copy_files_in_folder(folder_path, start_number)
    total_files_processed += files_processed

print(f"\nКопирование и переименование завершены. Всего обработано файлов: {total_files_processed}")