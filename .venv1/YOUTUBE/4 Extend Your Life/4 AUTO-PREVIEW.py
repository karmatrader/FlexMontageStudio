import os
import random
import logging
import importlib
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import pandas as pd

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Настройки
OUTPUT_DIR = "/Users/mikman/Youtube/Структура/4 Extend your life/Готовая обложка"
BACKGROUND_DIR = "/Users/mikman/Youtube/Структура/4 Extend your life/AUTO-PREVIEW/backgrounds"
FACES_DIR = "/Users/mikman/Youtube/Структура/4 Extend your life/AUTO-PREVIEW/faces"
DOCTOR_DIR = "/Users/mikman/Youtube/Структура/4 Extend your life/AUTO-PREVIEW/doctors"
EXCEL_FILE = "/Users/mikman/Youtube/Структура/4 Extend your life/Название на обложку.xlsx"
RESOLUTION = (1280, 720)
FONT_PATH = "/Users/mikman/Library/Fonts/GrtskPeta-Bold.ttf"
FONT_SIZE = 100  # Начальный размер шрифта
MIN_FONT_SIZE = 40  # Минимальный размер шрифта
TEXT_COLOR = (255, 255, 255)
HIGHLIGHT_COLOR = (255, 255, 0)
OUTLINE_COLOR = (0, 0, 0)
DARKEN_AMOUNT = 0.75  # Затемнение на 23%
MAX_TEXT_WIDTH = int(RESOLUTION[0] * 0.75)  # 75% ширины
BLUR_RADIUS = 15
LINE_SPACING = 10
OUTLINE_THICKNESS = 10
TOP_MARGIN = 20
DOCTOR_SCALE_MIN = 1.3  # Минимальный масштаб врача
DOCTOR_SCALE_MAX = 1.7  # Максимальный масштаб врача
DOCTOR_OVERLAP = 0.1  # Доля ширины врача, которая заходит за край (10%)

# Выводим настройки затемнения
logging.info(f"Настройки затемнения: DARKEN_AMOUNT = {DARKEN_AMOUNT} (затемнение на {int((1 - DARKEN_AMOUNT) * 100)}%)")

# Проверка, существует ли шрифт
if not os.path.exists(FONT_PATH):
    logging.error(f"Шрифт не найден по пути: {FONT_PATH}")
    raise FileNotFoundError(f"Шрифт не найден по пути: {FONT_PATH}")

# Создаём выходную папку, если её нет
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
    logging.info(f"Создана выходная папка: {OUTPUT_DIR}")

# Проверяем, существует ли папка с изображениями врача
if not os.path.exists(DOCTOR_DIR):
    logging.error(f"Папка с изображениями врача не найдена: {DOCTOR_DIR}")
    raise FileNotFoundError(f"Папка с изображениями врача не найдена: {DOCTOR_DIR}")

# Функция для определения движка на основе расширения файла
def get_excel_engine(file_path):
    _, ext = os.path.splitext(file_path)
    if ext.lower() == '.xls':
        try:
            importlib.import_module('xlrd')
            return 'xlrd'
        except ImportError:
            logging.error("Модуль xlrd не установлен. Установи xlrd >= 2.0.1: pip install xlrd")
            raise
    elif ext.lower() == '.xlsx':
        try:
            importlib.import_module('openpyxl')
            return 'openpyxl'
        except ImportError:
            logging.error("Модуль openpyxl не установлен. Установи openpyxl: pip install openpyxl")
            raise
    else:
        logging.error(f"Неизвестное расширение файла: {ext}. Поддерживаются только .xls и .xlsx")
        raise ValueError(f"Неизвестное расширение файла: {ext}")

# Читаем заголовки из Excel
logging.info(f"Чтение файла Excel: {EXCEL_FILE}")
try:
    engine = get_excel_engine(EXCEL_FILE)
    logging.info(f"Используемый движок: {engine}")
    df = pd.read_excel(EXCEL_FILE, engine=engine)
    if 'Title' not in df.columns:
        logging.error("Столбец 'Title' не найден в файле Excel")
        raise KeyError("Столбец 'Title' не найден в файле Excel")

    titles = df['Title'].dropna().astype(str).tolist()
    for i, title in enumerate(titles):
        titles[i] = title.encode('utf-8', errors='replace').decode('utf-8')
        logging.info(f"Заголовок #{i + 1}: {titles[i]}")

    logging.info(f"Считано {len(titles)} заголовков из файла Excel: {titles}")
except Exception as e:
    logging.error(f"Ошибка при чтении файла Excel: {e}")
    raise

# Функция для зумирования и смещения фона
def zoom_image(image):
    width, height = image.size
    logging.info(f"Зумирование фона: исходный размер {width}x{height}")

    max_offset_x = int(RESOLUTION[0] * 0.1)
    max_offset_y = int(RESOLUTION[1] * 0.1)

    min_width_needed = RESOLUTION[0] + 2 * max_offset_x
    min_height_needed = RESOLUTION[1] + 2 * max_offset_y

    zoom_factor_x = min_width_needed / width
    zoom_factor_y = min_height_needed / height
    min_zoom_factor = max(zoom_factor_x, zoom_factor_y, 1.01)

    zoom_factor = max(min_zoom_factor, 1 + random.uniform(0.01, 0.20))
    new_width = int(width * zoom_factor)
    new_height = int(height * zoom_factor)
    image = image.resize((new_width, new_height), Image.LANCZOS)
    logging.info(f"Фон зумирован: новый размер {new_width}x{new_height}, zoom_factor={zoom_factor}")

    offset_x = random.randint(-max_offset_x, max_offset_x)
    offset_y = random.randint(-max_offset_y, max_offset_y)

    left = offset_x
    top = offset_y
    right = left + RESOLUTION[0]
    bottom = top + RESOLUTION[1]

    if left < 0:
        left = 0
        right = RESOLUTION[0]
    elif right > new_width:
        right = new_width
        left = new_width - RESOLUTION[0]

    if top < 0:
        top = 0
        bottom = RESOLUTION[1]
    elif bottom > new_height:
        bottom = new_height
        top = new_height - RESOLUTION[1]

    image = image.crop((left, top, right, bottom))
    logging.info(f"Фон обрезан: left={left}, top={top}, right={right}, bottom={bottom}")

    image = image.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
    logging.info("Фон размыт")

    return image

# Функция для наложения затемнения
def darken_image(image, amount):
    enhancer = ImageEnhance.Brightness(image)
    image = enhancer.enhance(amount)
    logging.info(f"Фон затемнён на {amount}")
    return image

# Функция для масштабирования изображения врача
def scale_doctor_image(image):
    width, height = image.size
    scale_factor = random.uniform(DOCTOR_SCALE_MIN, DOCTOR_SCALE_MAX)
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)
    image = image.resize((new_width, new_height), Image.LANCZOS)
    logging.info(f"Изображение врача масштабировано: новый размер {new_width}x{new_height}, scale_factor={scale_factor}")
    return image

# Функция для наложения текста с переносом строк и рандомным выделением слов
def draw_text_with_highlights(draw, text, initial_font_size):
    font_size = initial_font_size
    font = ImageFont.truetype(FONT_PATH, font_size)
    logging.info(f"Обработка текста: {text}")

    while True:
        # Разбиваем текст на строки
        words = text.split()
        lines = []
        current_line = []
        current_width = 0

        for word in words:
            word_bbox = draw.textbbox((0, 0), word, font=font)
            word_width = word_bbox[2] - word_bbox[0]
            space_width = draw.textbbox((0, 0), " ", font=font)[2]

            if current_width + word_width + (space_width if current_line else 0) > MAX_TEXT_WIDTH:
                lines.append(current_line)
                current_line = [word]
                current_width = word_width
            else:
                current_line.append(word)
                current_width += word_width + space_width

        if current_line:
            lines.append(current_line)

        # Вычисляем размеры текста
        line_heights = []
        line_widths = []
        for line in lines:
            line_text = " ".join(line)
            bbox = draw.textbbox((0, 0), line_text, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_height = (bbox[3] - bbox[1]) + 2 * OUTLINE_THICKNESS
            line_heights.append(line_height)

        total_height = sum(line_heights) + (len(lines) - 1) * LINE_SPACING

        # Проверяем, помещается ли текст по высоте
        available_height = RESOLUTION[1] - TOP_MARGIN
        if total_height <= available_height or font_size <= MIN_FONT_SIZE:
            break

        # Уменьшаем шрифт, если текст не помещается
        font_size -= 5
        font = ImageFont.truetype(FONT_PATH, font_size)
        logging.info(f"Текст не помещается (высота {total_height} > {available_height}), уменьшаем шрифт до {font_size}")

    logging.info(f"Текст разбит на {len(lines)} строк: {[' '.join(line) for line in lines]}")
    logging.info(f"Итоговая высота текста: {total_height} пикселей")

    # Размещаем текст с отступом сверху
    start_y = TOP_MARGIN
    for i, line in enumerate(lines):
        line_text = " ".join(line)
        line_width = line_widths[i]
        start_x = (RESOLUTION[0] - line_width) // 2
        y = start_y + sum(line_heights[:i]) + i * LINE_SPACING

        x = start_x
        for word in line:
            color = HIGHLIGHT_COLOR if random.random() < 0.3 else TEXT_COLOR
            word_bbox = draw.textbbox((0, 0), word, font=font)
            word_width = word_bbox[2] - word_bbox[0]

            for dx in range(-OUTLINE_THICKNESS, OUTLINE_THICKNESS + 1, 2):
                for dy in range(-OUTLINE_THICKNESS, OUTLINE_THICKNESS + 1, 2):
                    draw.text((x + dx, y + dy), word, font=font, fill=OUTLINE_COLOR)
            draw.text((x, y), word, font=font, fill=color)
            x += word_width + draw.textbbox((0, 0), " ", font=font)[2]

    logging.info("Текст наложен на изображение")

# Основной цикл
file_counter = 1
for title in titles:
    logging.info(f"\n--- Обработка заголовка #{file_counter}: {title} ---")

    # 1. Выбираем случайный фон
    background_files = [f for f in os.listdir(BACKGROUND_DIR) if f.endswith(('.png', '.jpg', '.jpeg'))]
    background_file = random.choice(background_files)
    logging.info(f"Выбран фон: {background_file}")
    background = Image.open(os.path.join(BACKGROUND_DIR, background_file)).convert("RGBA")

    # Зумим и смещаем фон
    background = zoom_image(background)

    # 2. Выбираем случайное изображение лица
    face_files = [f for f in os.listdir(FACES_DIR) if f.endswith(('.png', '.jpg', '.jpeg'))]
    face_file = random.choice(face_files)
    logging.info(f"Выбрано изображение лица: {face_file}")
    face = Image.open(os.path.join(FACES_DIR, face_file)).convert("RGBA")

    # Определяем, куда пристыковать лицо (left или right) и выбираем изображение врача
    face_width, face_height = face.size
    if "left" in face_file.lower():
        face_position = (0, (RESOLUTION[1] - face_height) // 2)
        doctor_file = "right_DOCTOR.png"
        logging.info("Лицо размещено слева")
    elif "right" in face_file.lower():
        face_position = (RESOLUTION[0] - face_width, (RESOLUTION[1] - face_height) // 2)
        doctor_file = "left_DOCTOR.png"
        logging.info("Лицо размещено справа")
    else:
        face_position = (0, (RESOLUTION[1] - face_height) // 2)
        doctor_file = "right_DOCTOR.png"
        logging.info("Лицо размещено слева (по умолчанию)")

    # 3. Загружаем и масштабируем изображение врача
    doctor_path = os.path.join(DOCTOR_DIR, doctor_file)
    if not os.path.exists(doctor_path):
        logging.error(f"Изображение врача не найдено: {doctor_path}")
        raise FileNotFoundError(f"Изображение врача не найдено: {doctor_path}")

    doctor = Image.open(doctor_path).convert("RGBA")
    doctor = scale_doctor_image(doctor)
    doctor_width, doctor_height = doctor.size

    # Определяем позицию врача, выравнивая по нижнему краю
    if doctor_file == "left_DOCTOR.png":
        # Размещаем слева, с заходом за край
        doctor_x = -int(doctor_width * DOCTOR_OVERLAP)
        doctor_y = RESOLUTION[1] - doctor_height  # Выравниваем по нижнему краю
        doctor_position = (doctor_x, doctor_y)
        logging.info(f"Врач размещён слева: позиция {doctor_position}")
    else:  # right_DOCTOR.png
        # Размещаем справа, с заходом за край
        doctor_x = RESOLUTION[0] - doctor_width + int(doctor_width * DOCTOR_OVERLAP)
        doctor_y = RESOLUTION[1] - doctor_height  # Выравниваем по нижнему краю
        doctor_position = (doctor_x, doctor_y)
        logging.info(f"Врач размещён справа: позиция {doctor_position}")

    # 4. Создаём итоговое изображение
    result = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
    result.paste(background, (0, 0))
    result.paste(face, face_position, face)
    result.paste(doctor, doctor_position, doctor)
    logging.info("Фон, лицо и врач объединены в итоговое изображение")

    # 5. Затемняем изображение
    result = darken_image(result, DARKEN_AMOUNT)

    # 6. Накладываем текст
    draw = ImageDraw.Draw(result)
    draw_text_with_highlights(draw, title.upper(), FONT_SIZE)

    # 7. Сохраняем результат с уникальным именем
    output_file = os.path.join(OUTPUT_DIR, f"preview_{file_counter:03d}.png")
    result.save(output_file, "PNG")
    logging.info(f"Файл сохранён: {output_file}")
    file_counter += 1

logging.info("Обработка завершена!")
print("Готово!")