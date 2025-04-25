# config.py

import glob
import os

""" Конфигурация для каналов YouTube. Содержит настройки путей, параметров видео, озвучки и субтитров для каждого канала."""

# Настройки прокси, общие для всех каналов
PROXY_CONFIG = {
    "proxy": "http://65.109.79.15:25100",  # URL прокси-сервера для HTTP/HTTPS запросов (без логина и пароля, только адрес)
    "proxy_login": "3dKtYukPUMgl",  # Логин для доступа к прокси-серверу
    "proxy_password": "ezZiiHxC8S",  # Пароль для доступа к прокси-серверу
}

# Словарь с настройками для каждого канала
CHANNELS = {
    "1 ЗВЁЗДНЫЕ ТАЙНЫ TV": {
        # --- Основные переменные канала ---
        "channel_folder": "1 ЗВЁЗДНЫЕ ТАЙНЫ TV",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "1 ЗВЁЗДНЫЕ ТАЙНЫ TV",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "ZVEZDNYE_TAINY_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE1.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "RU",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "AB9XsbSA4eLG12t2myjN",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "AB9XsbSA4eLG12t2myjN",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d0fd99854e7517a8890c2f536b4fb89a9408d2dfa8cd7c7be15e4692e72a2a57",  # ID публичного владельца голоса для доступа к библиотеке голосов
        "max_retries": 10,  # Максимальное количество попыток для запросов в text_to_speech

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "use_subfolders": True,# True = использовать подпапки (Фото/1, Фото/2, ...), или False = общая папка (Настройка указывает использовать ли подпапки для фото/видео или общую папку со стоками/футажами)
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": True, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "2 ЗВЁЗДЫ TV": {
        # --- Основные переменные канала ---
        "channel_folder": "2 ЗВЁЗДЫ TV",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "2 ЗВЁЗДЫ TV",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "ZVEZDY_TV_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE2.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "RU",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "MWyJiWDobXN8FX3CJTdE",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "MWyJiWDobXN8FX3CJTdE",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "b97690a95ddc81ce0522763133e91ad14a3058d8fd44c9c84a31e29e740ce403",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": True,# True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "3 ЗВЕЗДЫ В ШОКЕ! TV": {
        # --- Основные переменные канала ---
        "channel_folder": "3 ЗВЕЗДЫ В ШОКЕ! TV",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "3 ЗВЕЗДЫ В ШОКЕ! TV",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "ZVEZDY_V_SHOCKE_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE3.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "RU",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "gJEfHTTiifXEDmO687lC",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "gJEfHTTiifXEDmO687lC",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "810035bb0570f7b4d2c167d14d8ea5bde595b042e89a96e29991818087d29c29",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": True, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---



    "4 Extend your life": {
        # --- Основные переменные канала ---
        "channel_folder": "4 Extend your life",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "4 Extend your life",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "EXTEND_U_LIFE",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 0.8,  # Скорость речи (speed double Optional >=0.7 <=1.2 [Defaults to 1] The speed of generated speech)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d2b2fc4b1d41c28f6b46a115009893a06d445c417b0c2c738bc7667284df1fe2",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "5 Prolongar la Vida": {
        # --- Основные переменные канала ---
        "channel_folder": "5 Prolongar la Vida",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 11,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "5 Prolongar la Vida",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "PROLONGAR_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "D7fO4LMKxU3UYXGDpTnA",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "D7fO4LMKxU3UYXGDpTnA",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "af2ecc51f2bbbec884b9d4f9dd0db2d8371afc8579f3664d7974f28dbd545875",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        "use_subfolders": False, # True = использовать подпапки (Фото/1, Фото/2, ...), или False = общая папка (Настройка указывает использовать ли подпапки для фото/видео или общую папку со стоками/футажами)

        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/FOOTAGE/Processed",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовое видео",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"
        "background_music_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Sound/Sound.mp3" if os.path.exists(f"{c['base_path']}/{c['channel_folder']}/Sound/Sound.mp3") else "", #

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False,  # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "medium",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "random",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": False,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 700,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+10",  # Позиция кнопки по оси Y (от нижнего края)
        "subscribe_display_duration": 4,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "es",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "6 Verlängern Sie Ihr Leben": {
        # --- Основные переменные канала ---
        "channel_folder": "6 Verlängern Sie Ihr Leben",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "6 Verlängern Sie Ihr Leben",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "VERLANGERN_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "GE",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "EQIVtVkE7IWwwaRgwyPi",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "EQIVtVkE7IWwwaRgwyPi",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "9909e6e455922bcd1008862807c17ff3c0e4403f73886de561215d74cb4044d2",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.8,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "7 КИНО-СЕКРЕТЫ TV": {
        # --- Основные переменные канала ---
        "channel_folder": "7 КИНО-СЕКРЕТЫ TV",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "7 КИНО-СЕКРЕТЫ TV",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "KINO-SEKRETI_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE4.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "RU",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "FzF9ACIefsb6wbrYVjf1",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "FzF9ACIefsb6wbrYVjf1",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "4e120f88d43f125a4c1f56885db63990e17568c80c5cca2f9f3a6459230fbeb1",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": True, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "8 КИНО! ТВ": {
        # --- Основные переменные канала ---
        "channel_folder": "8 КИНО! ТВ",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "8 КИНО! ТВ",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "KINO-TV_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE5.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "RU",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "3EuKHIEZbSzrHGNmdYsx",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "3EuKHIEZbSzrHGNmdYsx",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "3ab20ab8564639791969cc67bb092b3f7492e9f622463792af92d2b35ae2c1aa",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": True,
        # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },

# ---====РАЗДЕЛЕНИЕ====---

    "9 КИНОТАЙНА ТВ": {
        # --- Основные переменные канала ---
        "channel_folder": "9 КИНОТАЙНА ТВ",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "9 КИНОТАЙНА ТВ",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "KINOTAINA_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE6.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка", # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx", # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "RU",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "GzE4TcXfh9rYCU9gVgPp",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "GzE4TcXfh9rYCU9gVgPp",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "cbf7badb008f587437f77fdd73d7d6784defb551b36888c85b27383dd6fffd0e", # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": True,
        # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast", # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },

# ---====РАЗДЕЛЕНИЕ====---

    "INACTIVE 10 Здоровье 60+": {
        # --- Основные переменные канала ---
        "channel_folder": "INACTIVE 10 Здоровье 60+",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "INACTIVE 10 Здоровье 60+",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "INACTIVE_10_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка", # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx", # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d2b2fc4b1d41c28f6b46a115009893a06d445c417b0c2c738bc7667284df1fe2", # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",  # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",  # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",  # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.8,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False,
        # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast", # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50",  # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "INACTIVE 11 Живи долго!": {
        # --- Основные переменные канала ---
        "channel_folder": "INACTIVE 11 Живи долго!",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "INACTIVE 11 Живи долго!",
        # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "INACTIVE_10_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",
        # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",
        # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d2b2fc4b1d41c28f6b46a115009893a06d445c417b0c2c738bc7667284df1fe2",
        # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",# Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",# Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "", # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo",# Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast", # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50", # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "INACTIVE 12 Формула здоровья!": {
        # --- Основные переменные канала ---
        "channel_folder": "INACTIVE 12 Формула здоровья!",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "INACTIVE 12 Формула здоровья!", # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "INACTIVE_10_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка", # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d2b2fc4b1d41c28f6b46a115009893a06d445c417b0c2c738bc7667284df1fe2",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",   # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",   # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo", # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False, # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50", # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "ru",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---

    "13 Formula Salud!": {
        # --- Основные переменные канала ---
        "channel_folder": "13 Formula Salud!",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 11,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "13 Formula Salud!",  # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "FORMULA_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",
        # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",
        # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "ZCh4e9eZSUf41K4cmCEL",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "ZCh4e9eZSUf41K4cmCEL",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d97eb7b2d527bfd6f9f645acee9f059e3658a3a214c7f73d34032d608fa7c01b",
        # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        "use_subfolders": False, # True = использовать подпапки (Фото/1, Фото/2, ...), или False = общая папка (Настройка указывает использовать ли подпапки для фото/видео или общую папку со стоками/футажами)

        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/FOOTAGE/Processed", # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовое видео",# Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "", # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo", # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"
        "background_music_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Sound/Sound.mp3" if os.path.exists(f"{c['base_path']}/{c['channel_folder']}/Sound/Sound.mp3") else "",  #

        # Настройка громкости фоновой музыки
        "background_music_volume": 0.3,  # Громкость фоновой музыки (0.0–1.0)

        # Настройки обработки фото и видео
        "adjust_videos_to_audio": False,  # True = масштабировать во времени клипы, False = исходная длительность + обрезка
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "medium",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "random",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": False,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 700,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50", # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+10",  # Позиция кнопки по оси Y (от нижнего края)
        "subscribe_display_duration": 4,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "es",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "14 Secretos de longevidad": {
        # --- Основные переменные канала ---
        "channel_folder": "14 Secretos de longevidad",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "14 Secretos de longevidad", # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "SECRETOS_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка", # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d2b2fc4b1d41c28f6b46a115009893a06d445c417b0c2c738bc7667284df1fe2",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",   # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",   # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo", # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройки обработки фото и видео
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50", # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "es",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },


# ---====РАЗДЕЛЕНИЕ====---


    "15 Vida activa despues de los 60": {
        # --- Основные переменные канала ---
        "channel_folder": "15 Vida activa despues de los 60",  # Название папки канала, используется для формирования всех путей
        "base_path": "/Users/mikman/Youtube/Структура",  # Базовый путь к структуре каналов, общий для всех путей
        "num_videos": 10,  # Количество видео для обработки (определяет диапазон video_number от 1 до num_videos)

        # --- Параметры для voice_proxy.py (генерация озвучки) ---
        "folder_path": lambda c: c["channel_folder"],  # Путь к рабочей папке канала (берётся из channel_folder)
        "channel_name": "15 Vida activa despues de los 60", # Отображаемое имя канала, используется для логов и вывода информации
        "audio_prefix": "VIDA_",  # Префикс для именования аудиофайлов (для уникальности файлов канала)
        "csv_file_path": "/Users/mikman/Youtube/BASE.csv",  # Путь к CSV-файлу с API-ключами для ElevenLabs
        "output_directory": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка", # Путь для сохранения сгенерированных аудиофайлов (папка Озвучка)
        "xlsx_file_path": lambda c: f"{c['base_path']}/{c['channel_folder']}/Сценарий.xlsx",  # Путь к Excel-файлу со сценарием (Сценарий.xlsx)
        "default_lang": "ES",  # Код языка по умолчанию для выбора вкладки в Excel-файле (RU для русского)
        "default_stability": 1.0,  # Параметр стабильности голоса (0.0–1.0), влияет на консистентность голоса
        "default_similarity": 1.0,  # Параметр схожести с оригинальным голосом (0.0–1.0), влияет на точность копирования
        "default_voice_speed": 1.0,  # Скорость речи (зарезервировано, пока не используется в API ElevenLabs)
        "default_voice_style": None,  # Стиль голоса (например, "excited", если доступно, иначе None)
        "standard_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID стандартного голоса для генерации речи
        "use_library_voice": True,  # Флаг, указывающий, использовать ли голос из библиотеки (True/False)
        "original_voice_id": "Hd8mWkf5kvyBZB0S7yXU",  # ID оригинального голоса, который копируется из библиотеки
        "public_owner_id": "d2b2fc4b1d41c28f6b46a115009893a06d445c417b0c2c738bc7667284df1fe2",  # ID публичного владельца голоса для доступа к библиотеке голосов

        # --- Параметры для auto_montage.py (автоматический монтаж видео) ---
        # Пути к папкам и файлам
        "photo_folder": lambda c: "/Users/mikman/Youtube/Структура/Фото",   # Общая папка с фото/видео, содержит подпапки 1, 2, ..., 10
        "audio_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Озвучка",  # Папка с аудиофайлами (озвучка)
        "output_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Готовый ролик",  # Папка для сохранения финального видео
        "logo_path": lambda c: glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png")[0] if glob.glob(f"{c['base_path']}/{c['channel_folder']}/Logo/*.png") else "",   # Путь к логотипу: берёт первый PNG-файл из папки Logo
        "subscribe_frames_folder": lambda c: f"{c['base_path']}/{c['channel_folder']}/Scene_logo", # Папка с кадрами анимации кнопки "ПОДПИСАТЬСЯ"

        # Настройки обработки фото и видео
        "video_resolution": "1920:1080",  # Разрешение финального видео (ширина:высота), стандарт Full HD
        "frame_rate": 30,  # Частота кадров видео (кадров в секунду), стандартное значение для плавного воспроизведения
        "video_crf": 23,  # Качество видео (0–51), меньшее значение = лучше качество, большее = меньший размер файла
        "video_preset": "fast",  # Пресет кодирования видео (ultrafast, veryfast, fast, medium, slow), влияет на скорость/качество
        "photo_order": "order",  # Порядок склейки фото/видео: "order" (по порядку) или "random" (случайно)

        # Настройки обработки боке (размытия фона)
        "bokeh_enabled": True,  # Включить эффект боке для изображений (True/False)
        "bokeh_image_size": [1920, 1080],  # Размер изображений после обработки (ширина, высота)
        "bokeh_blur_kernel": [99, 99],  # Размер ядра размытия GaussianBlur (должно быть нечетным)
        "bokeh_blur_sigma": 30,  # Сила размытия GaussianBlur (чем больше, тем сильнее размытие)

        # Настройки логотипа
        "logo_width": 200,  # Ширина логотипа в пикселях (высота масштабируется пропорционально)
        "logo_position_x": "W-w-20",  # Позиция логотипа по оси X (W-w-20 = 20 пикселей от правого края)
        "logo_position_y": "20",  # Позиция логотипа по оси Y (20 пикселей от верхнего края)
        "logo_duration": "all",  # Длительность показа логотипа: "all" (всё видео) или число в секундах

        # Настройки кнопки "ПОДПИСЫВАЙТЕСЬ"
        "subscribe_width": 1400,  # Ширина анимации кнопки в пикселях (высота масштабируется пропорционально)
        "subscribe_position_x": "-50", # Позиция кнопки по оси X (-50 пикселей от левого края, частично за пределами экрана)
        "subscribe_position_y": "main_h-overlay_h+150",  # Позиция кнопки по оси Y (150 пикселей от нижнего края)
        "subscribe_display_duration": 7,  # Длительность показа кнопки (в секундах)
        "subscribe_interval_gap": 30,  # Интервал между появлениями кнопки (в секундах)

        # Настройки аудио
        "audio_bitrate": "192k",  # Битрейт финального аудио (например, "128k", "192k", "320k")
        "audio_sample_rate": 44100,  # Частота дискретизации аудио (Гц), стандартное значение для MP3
        "audio_channels": 1,  # Количество аудиоканалов: 1 (моно) или 2 (стерео)

        # Настройки субтитров
        "subtitles_enabled": True,  # Включить/выключить субтитры (True/False)
        "subtitle_language": "es",  # Язык для транскрибирования аудио (например, "ru" для русского)
        "subtitle_model": "medium",  # Модель Whisper для транскрибирования ("small", "medium", "large")
        "subtitle_fontsize": 110,  # Размер шрифта субтитров
        "subtitle_font_color": "&HFFFFFF",  # Цвет шрифта субтитров (белый, формат: &HBBGGRR)
        "subtitle_use_backdrop": False,  # Использовать подложку для субтитров (True/False)
        "subtitle_back_color": "&HFFFFFF",  # Цвет подложки субтитров (белый, формат: &HBBGGRR)
        "subtitle_outline_thickness": 4,  # Толщина обводки текста субтитров
        "subtitle_outline_color": "&H000000",  # Цвет обводки (черный, формат: &HBBGGRR)
        "subtitle_shadow_thickness": 1,  # Толщина тени субтитров
        "subtitle_shadow_color": "&H333333",  # Базовый цвет тени (графитовый, формат: &HBBGGRR)
        "subtitle_shadow_alpha": 50,  # Интенсивность тени (0–255)
        "subtitle_shadow_offset_x": 2,  # Смещение тени по оси X
        "subtitle_shadow_offset_y": 2,  # Смещение тени по оси Y
        "subtitle_margin_v": 20,  # Вертикальный отступ субтитров от нижнего края
        "subtitle_margin_l": 10,  # Левый отступ субтитров
        "subtitle_margin_r": 10,  # Правый отступ субтитров
        "subtitle_max_words": 3,  # Максимальное количество слов в одном субтитре
        "subtitle_time_offset": -0.3,  # Сдвиг времени субтитров (в секундах, -0.3 = на 0.3 сек раньше)
    },
}


def get_channel_config(channel_name):
    """Получает конфигурацию канала из CHANNELS, разрешая лямбда-функции.

    Args:
        channel_name (str): Название канала для получения конфигурации.

    Returns:
        dict: Конфигурация канала с разрешёнными значениями (строками вместо функций).
    """
    config = CHANNELS.get(channel_name, {})
    if not config:
        return {}

    # Создаём копию конфигурации, заменяя лямбда-функции их значениями
    resolved_config = {}
    for key, value in config.items():
        if callable(value):  # Если значение — это лямбда-функция
            try:
                resolved_config[key] = value(config)  # Вызываем её, чтобы получить строку
            except Exception as e:
                print(f"⚠️ Ошибка при разрешении лямбда-функции для ключа '{key}' в канале '{channel_name}': {str(e)}")
                resolved_config[key] = ""  # Устанавливаем пустую строку в случае ошибки
        else:
            resolved_config[key] = value
    return resolved_config