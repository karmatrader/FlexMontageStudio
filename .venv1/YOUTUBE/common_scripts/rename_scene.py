# Настройки
FOLDERS = [
    "/Users/mikman/Downloads/6 Флоринская/1-10",  # Замените на ваши пути к папкам
    "/Users/mikman/Downloads/6 Флоринская/11-20",
    "/Users/mikman/Downloads/6 Флоринская/21-40",
    # Добавьте больше папок при необходимости
]
TARGET_FOLDER = "/Users/mikman/Youtube/Структура/Фото/5"  # Путь к папке, куда переместятся файлы
START_NUMBER_BASE = 111  # Начальный номер для первой папки
INCREMENT = 110  # Шаг для начальных номеров (221, 331 и т.д.)

import os
import random
import shutil

# Проверяем, существует ли целевая папка, и создаем её, если не существует
if not os.path.exists(TARGET_FOLDER):
    os.makedirs(TARGET_FOLDER)


def rename_and_move_files_in_folder(folder_path, start_number):
    # Получаем список всех файлов в папке
    files = os.listdir(folder_path)
    # Фильтруем только файлы (исключаем папки)
    files = [f for f in files if os.path.isfile(os.path.join(folder_path, f))]
    # Перемешиваем файлы случайным образом
    random.shuffle(files)

    # Счетчик для нумерации
    counter = 0

    # Обрабатываем каждый файл
    for filename in files:
        # Полный путь к текущему файлу
        old_file_path = os.path.join(folder_path, filename)

        # Получаем расширение файла
        file_extension = os.path.splitext(filename)[1]

        # Формируем новое имя файла
        new_filename = f"{start_number + counter}{file_extension}"
        new_file_path = os.path.join(TARGET_FOLDER, new_filename)

        # Проверяем, существует ли файл с таким именем в целевой папке
        while os.path.exists(new_file_path):
            counter += 1
            new_filename = f"{start_number + counter}{file_extension}"
            new_file_path = os.path.join(TARGET_FOLDER, new_filename)

        # Перемещаем и переименовываем файл
        shutil.move(old_file_path, new_file_path)

        # Увеличиваем счетчик
        counter += 1

        print(f"Папка: {folder_path}, Переименован и перемещен: {filename} -> {new_filename}")

    return counter


# Обрабатываем каждую папку
total_files_processed = 0
for index, folder_path in enumerate(FOLDERS):
    # Вычисляем начальный номер для этой папки (111, 221, 331 и т.д.)
    start_number = START_NUMBER_BASE + (index * INCREMENT)
    print(f"\nОбрабатывается папка: {folder_path} с начальным номером: {start_number}")

    # Переименовываем и перемещаем файлы из папки
    files_processed = rename_and_move_files_in_folder(folder_path, start_number)
    total_files_processed += files_processed

print(f"\nПереименование и перемещение завершены. Всего обработано файлов: {total_files_processed}")