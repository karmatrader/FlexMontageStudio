import os
import random

# Укажите путь к папке с файлами
folder_path = "/Users/mikman/Youtube/Структура/1 ЗВЁЗДНЫЕ ТАЙНЫ TV/Фото/1"  # замените на свой путь

# Укажите начальное число для нумерации
start_number = 111  # меняйте это число перед каждым запуском (111, 221, 331 и т.д.)

# Получаем список всех файлов в папке
files = os.listdir(folder_path)

# Фильтруем только файлы (исключаем папки)
files = [f for f in files if os.path.isfile(os.path.join(folder_path, f))]

# Перемешиваем список файлов случайным образом
random.shuffle(files)

# Счетчик для нумерации
counter = 0

# Перебираем все файлы в случайном порядке
for filename in files:
    # Полный путь к текущему файлу
    old_file_path = os.path.join(folder_path, filename)

    # Получаем расширение файла
    file_extension = os.path.splitext(filename)[1]

    # Формируем новое имя файла
    new_filename = f"{start_number + counter}{file_extension}"
    new_file_path = os.path.join(folder_path, new_filename)

    # Проверяем, существует ли файл с таким именем
    while os.path.exists(new_file_path):
        counter += 1  # Увеличиваем счетчик, если имя занято
        new_filename = f"{start_number + counter}{file_extension}"
        new_file_path = os.path.join(folder_path, new_filename)

    # Переименовываем файл
    os.rename(old_file_path, new_file_path)

    # Увеличиваем счетчик
    counter += 1

    print(f"Переименован: {filename} -> {new_filename}")

print(f"Переименование завершено. Обработано файлов: {counter}")