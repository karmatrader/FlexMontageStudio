#!/usr/bin/env python3
"""
Утилиты для работы с путями приложения
"""
import sys
import os
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


def get_app_directory() -> Path:
    """
    Улучшенное определение директории приложения для поиска конфигурационных файлов.
    
    Возвращает:
        Path: Путь к директории, где должны находиться конфигурационные файлы
              - Для .app: рядом с .app файлом  
              - Для .exe: рядом с .exe файлом
              - Для Python скрипта: директория скрипта
    """
    # Проверяем разные способы определения, что это скомпилированное приложение
    is_compiled = (getattr(sys, 'frozen', False) or 
                   hasattr(sys, '_MEIPASS') or  # PyInstaller
                   '__compiled__' in globals() or  # Nuitka
                   sys.executable.endswith('.app/Contents/MacOS/FlexMontageStudio'))  # Прямая проверка
    
    # Дополнительные проверки для Nuitka
    if not is_compiled:
        # Nuitka может не устанавливать sys.frozen
        executable_path = str(sys.executable).lower()
        if any(pattern in executable_path for pattern in ['.app/contents/macos/', '/macos/', 'nuitka']):
            is_compiled = True
            logger.info(f"🔧 Обнаружен Nuitka по пути исполняемого файла: {sys.executable}")
    
    if is_compiled or ('.app' in sys.executable and sys.platform == "darwin"):
        # Скомпилированное приложение или macOS .app
        if sys.platform == "darwin" and '.app' in sys.executable:
            # macOS .app bundle - используем множественные стратегии поиска
            logger.info(f"🍎 macOS .app режим. Executable: {sys.executable}")
            
            # Стратегия 1: Поиск через sys.executable
            app_bundle_path = Path(sys.executable)
            current_path = app_bundle_path
            while current_path.suffix != '.app' and current_path.parent != current_path:
                current_path = current_path.parent
            
            if current_path.suffix == '.app':
                app_dir = current_path.parent
                logger.info(f"✅ Стратегия 1: .app найден через sys.executable")
                logger.info(f"📱 .app bundle: {current_path}")
                logger.info(f"📁 Директория конфигураций: {app_dir}")
                return app_dir
            
            # Стратегия 2: Поиск через переменные окружения
            env_candidates = []
            for env_var in ['RESOURCEPATH', 'PWD', 'BUNDLE_PATH', 'APP_BUNDLE']:
                if env_var in os.environ:
                    env_path = Path(os.environ[env_var])
                    if '.app' in str(env_path):
                        env_candidates.append((env_var, env_path))
            
            for env_var, env_path in env_candidates:
                current = env_path
                while current.suffix != '.app' and current.parent != current:
                    current = current.parent
                if current.suffix == '.app':
                    app_dir = current.parent
                    logger.info(f"✅ Стратегия 2: .app найден через {env_var}")
                    logger.info(f"📱 .app bundle: {current}")
                    logger.info(f"📁 Директория конфигураций: {app_dir}")
                    return app_dir
            
            # Стратегия 3: Поиск через текущую рабочую директорию
            cwd = Path.cwd()
            if '.app' in str(cwd):
                current = cwd
                while current.suffix != '.app' and current.parent != current:
                    current = current.parent
                if current.suffix == '.app':
                    app_dir = current.parent
                    logger.info(f"✅ Стратегия 3: .app найден через cwd")
                    logger.info(f"📱 .app bundle: {current}")
                    logger.info(f"📁 Директория конфигураций: {app_dir}")
                    return app_dir
            
            # Стратегия 4: Анализ структуры Nuitka для macOS
            executable_dir = Path(sys.executable).parent
            
            # Проверяем стандартную структуру .app/Contents/MacOS/
            if executable_dir.name == "MacOS":
                contents_dir = executable_dir.parent
                if contents_dir.name == "Contents":
                    potential_app = contents_dir.parent
                    if potential_app.suffix == '.app':
                        app_dir = potential_app.parent
                        logger.info(f"✅ Стратегия 4: .app найден через структуру MacOS/Contents")
                        logger.info(f"📱 .app bundle: {potential_app}")
                        logger.info(f"📁 Директория конфигураций: {app_dir}")
                        return app_dir
            
            # Стратегия 5: Поиск в стандартных местах macOS
            app_name_patterns = ['FlexMontage', 'FlexMontageStudio']
            search_locations = [
                Path.home() / 'Desktop',
                Path.home() / 'Downloads',
                Path.home() / 'Applications',
                Path('/Applications'),
                Path.cwd()
            ]
            
            for location in search_locations:
                if location.exists():
                    try:
                        for item in location.iterdir():
                            if item.suffix == '.app':
                                for pattern in app_name_patterns:
                                    if pattern in item.name:
                                        app_dir = item.parent
                                        logger.info(f"✅ Стратегия 5: .app найден в {location}")
                                        logger.info(f"📱 .app bundle: {item}")
                                        logger.info(f"📁 Директория конфигураций: {app_dir}")
                                        return app_dir
                    except (PermissionError, OSError):
                        continue
            
            # Стратегия 6: Fallback - создаем директорию рядом с исполняемым файлом
            fallback_dir = executable_dir
            logger.warning(f"⚠️ Все стратегии поиска .app неуспешны")
            logger.warning(f"🔄 Используем fallback: {fallback_dir}")
            logger.warning(f"📝 Конфигурационные файлы будут размещены в: {fallback_dir}")
            
            # Убеждаемся что fallback директория существует и доступна для записи
            try:
                fallback_dir.mkdir(parents=True, exist_ok=True)
                test_file = fallback_dir / '.test_write'
                test_file.touch()
                test_file.unlink()
                logger.info(f"✅ Fallback директория проверена и доступна для записи")
            except (PermissionError, OSError) as e:
                logger.error(f"❌ Fallback директория недоступна для записи: {e}")
                # Последний fallback - домашняя директория пользователя
                home_fallback = Path.home() / 'FlexMontageStudio'
                home_fallback.mkdir(parents=True, exist_ok=True)
                logger.warning(f"🏠 Используем домашнюю директорию: {home_fallback}")
                return home_fallback
            
            return fallback_dir
            
        else:
            # Windows .exe или другие платформы
            executable_path = Path(sys.executable)
            app_dir = executable_path.parent
            
            # Для Nuitka на Windows проверяем что мы не внутри .dist
            if '.dist' in str(app_dir):
                # Если исполняемый файл внутри .dist папки, поднимаемся на уровень выше к .exe
                potential_exe_dir = app_dir.parent
                exe_name = executable_path.stem.replace('.dist', '')
                expected_exe = potential_exe_dir / f"{exe_name}.exe"
                
                if expected_exe.exists():
                    app_dir = potential_exe_dir
                    logger.info(f"🔧 Обнаружен Nuitka .dist, корректируем путь")
                    logger.info(f"📁 .exe файл: {expected_exe}")
                else:
                    logger.warning(f"⚠️ Внутри .dist, но .exe не найден: {expected_exe}")
            
            logger.info(f"💻 Windows/Linux режим")
            logger.info(f"🗂️ Исполняемый файл: {executable_path.name}")
            logger.info(f"📁 Директория для конфигураций: {app_dir}")
            return app_dir
    else:
        # Запущено из Python скрипта (режим разработки)
        current_file = Path(__file__)
        project_root = current_file.parent.parent  # из utils/ поднимаемся в корень
        
        logger.debug(f"🐍 Режим разработки (Python скрипт)")
        logger.debug(f"📁 Корень проекта: {project_root}")
        return project_root


def get_config_file_path(filename: str) -> Path:
    """
    Получение полного пути к конфигурационному файлу.
    
    Args:
        filename: Имя файла (например, 'channels.json', 'license.json')
        
    Returns:
        Path: Полный путь к файлу
    """
    app_dir = get_app_directory()
    config_path = app_dir / filename
    
    logger.info(f"🔍 Поиск {filename} в: {config_path}")
    logger.info(f"   Существует: {'✅' if config_path.exists() else '❌'}")
    
    return config_path


def ensure_config_files_external() -> bool:
    """
    Улучшенная проверка конфигурационных файлов с множественными стратегиями поиска.
    
    Returns:
        bool: True если все файлы найдены, False если что-то отсутствует
    """
    required_files = ['channels.json', 'license.json']
    
    # Стратегия 1: Основная директория приложения
    app_dir = get_app_directory()
    logger.info(f"📁 Основная директория поиска: {app_dir}")
    
    missing_files = []
    found_files = []
    
    for filename in required_files:
        file_path = app_dir / filename
        if file_path.exists():
            found_files.append(filename)
            logger.info(f"✅ Найден {filename}: {file_path}")
        else:
            missing_files.append(filename)
            logger.warning(f"❌ Отсутствует файл: {file_path}")
    
    if not missing_files:
        logger.info(f"✅ Все конфигурационные файлы найдены в: {app_dir}")
        return True
    
    # Стратегия 2: Поиск в альтернативных местах для скомпилированного приложения
    if getattr(sys, 'frozen', False) or '.app' in sys.executable:
        logger.info(f"🔍 Ищем отсутствующие файлы в альтернативных местах...")
        
        alternative_locations = [
            Path.cwd(),                              # Текущая рабочая директория
            Path(sys.executable).parent,             # Директория исполняемого файла
            Path.home() / 'Desktop',                 # Рабочий стол пользователя
            Path.home() / 'Downloads',               # Загрузки
            Path.home() / 'FlexMontageStudio'        # Домашняя папка приложения
        ]
        
        for location in alternative_locations:
            if not location.exists():
                continue
                
            found_in_location = []
            for filename in missing_files:
                alt_file_path = location / filename
                if alt_file_path.exists():
                    found_in_location.append(filename)
                    logger.info(f"✅ Найден {filename} в альтернативном месте: {alt_file_path}")
                    
                    # Попытка скопировать файл в основную директорию
                    try:
                        import shutil
                        target_path = app_dir / filename
                        shutil.copy2(alt_file_path, target_path)
                        logger.info(f"📋 Скопирован {filename} в основную директорию")
                        found_files.append(filename)
                        missing_files.remove(filename)
                    except (PermissionError, OSError) as e:
                        logger.warning(f"⚠️ Не удалось скопировать {filename}: {e}")
            
            if found_in_location:
                logger.info(f"📂 В {location} найдены файлы: {', '.join(found_in_location)}")
    
    # Итоговая проверка
    if missing_files:
        logger.error(f"🚨 Отсутствуют конфигурационные файлы: {', '.join(missing_files)}")
        logger.error(f"📁 Будут созданы в директории: {app_dir}")
        return False
    else:
        logger.info(f"✅ Все конфигурационные файлы найдены")
        return True


def deploy_bundled_testchannel() -> bool:
    """
    Развертывание готовой папки TestChannel из билда при первом запуске.
    Ищет TestChannel внутри приложения и копирует её рядом с приложением.
    
    Returns:
        bool: True если развертывание успешно, False при ошибке
    """
    app_dir = get_app_directory()
    target_test_channel = app_dir / "TestChannel"
    
    if target_test_channel.exists():
        logger.info(f"📁 TestChannel уже существует: {target_test_channel}")
        return True
    
    # Ищем TestChannel внутри приложения
    bundled_test_channel = None
    
    # Определяем где может быть TestChannel в зависимости от платформы
    if getattr(sys, 'frozen', False) or '.app' in sys.executable:
        # Скомпилированное приложение
        if sys.platform == "darwin" and '.app' in sys.executable:
            # macOS .app bundle
            executable_dir = Path(sys.executable).parent
            possible_locations = [
                executable_dir / "TestChannel",  # В Contents/MacOS/
                executable_dir.parent / "Resources" / "TestChannel",  # В Contents/Resources/
            ]
        else:
            # Windows .exe - Nuitka создает структуру .exe и .dist
            executable_dir = Path(sys.executable).parent
            exe_name = Path(sys.executable).stem  # FlexMontageStudio
            dist_dir = executable_dir / f"{exe_name}.dist"
            
            possible_locations = [
                executable_dir / "TestChannel",  # Рядом с .exe (внешний)
                dist_dir / "TestChannel",  # Внутри .dist (встроенный)
                executable_dir.parent / "TestChannel",  # На уровень выше
            ]
    else:
        # Режим разработки - используем исходную папку
        current_file = Path(__file__).parent.parent
        possible_locations = [
            current_file / "TestChannel",
        ]
    
    # Ищем TestChannel
    for location in possible_locations:
        logger.debug(f"🔍 Проверяем расположение TestChannel: {location}")
        if location.exists() and location.is_dir():
            # Проверяем что это действительно наша папка TestChannel
            scenario_file = location / "Scenario.xlsx"
            logo_dir = location / "Logo"
            logger.debug(f"  - Scenario.xlsx: {'✅' if scenario_file.exists() else '❌'}")
            logger.debug(f"  - Logo папка: {'✅' if logo_dir.exists() else '❌'}")
            
            if scenario_file.exists() and logo_dir.exists():
                bundled_test_channel = location
                logger.info(f"🔍 Найден bundled TestChannel: {bundled_test_channel}")
                break
        else:
            logger.debug(f"  - Директория не существует: {location}")
    
    if not bundled_test_channel:
        logger.error(f"❌ TestChannel не найден в приложении! Проверьте сборку.")
        logger.error(f"   Проверяли в: {possible_locations}")
        return False
    
    try:
        import shutil
        # Копируем всю папку TestChannel
        shutil.copytree(bundled_test_channel, target_test_channel)
        logger.info(f"✅ TestChannel успешно развернут из {bundled_test_channel} в {target_test_channel}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка развертывания TestChannel: {e}")
        return False


def create_sample_config_files() -> None:
    """
    Создание готовых конфигурационных файлов с тестовыми данными при первом запуске.
    Теперь использует готовую папку TestChannel из билда вместо создания файлов с нуля.
    """
    app_dir = get_app_directory()
    
    # Готовая конфигурация channels.json с тестовыми данными
    test_channels = {
        "proxy_config": {
            "debug_config": {
                "debug_video_processing": False,
                "debug_audio_processing": False,
                "debug_subtitles_processing": False,
                "debug_final_assembly": False
            },
            "proxy": "",
            "proxy_login": "",
            "proxy_password": "",
            "use_proxy": False
        },
        "channels": {
            "ТЕСТОВЫЙ КАНАЛ": {
                "name": "Тестовый канал",
                "channel_name": "ТЕСТОВЫЙ КАНАЛ",
                "channel_column": "B",
                "base_path": str(app_dir / "TestChannel"),
                "global_xlsx_file_path": str(app_dir / "TestChannel" / "Scenario.xlsx"),
                "csv_file_path": str(app_dir / "TestChannel" / "Apikeys.csv"),
                "output_directory": str(app_dir / "TestChannel" / "Audio"),
                "photo_folder": str(app_dir / "TestChannel" / "Media"),
                "audio_folder": str(app_dir / "TestChannel" / "Audio"),
                "output_folder": str(app_dir / "TestChannel" / "Output"),
                "background_music_path": str(app_dir / "TestChannel" / "background_music.mp3"),
                
                # Настройки по умолчанию
                "num_videos": 1,
                "preserve_clip_audio_videos": "1",
                "default_lang": "ru",
                "standard_voice_id": "pNInz6obpgDQGcFmaJgB",
                "use_library_voice": True,
                "max_retries": 3,
                "ban_retry_delay": 300,
                
                # Настройки аудио
                "audio_bitrate": "192k",
                "audio_sample_rate": 44100,
                "audio_channels": "1",
                "silence_duration": 1,
                "background_music_volume": 15.0,
                "background_music_fade_in": 2.0,
                "background_music_fade_out": 3.0,
                "audio_normalize": True,
                "audio_normalize_method": "lufs",
                "audio_normalize_target": -23,
                
                # Настройки видео
                "video_resolution": "1920:1080",
                "video_preset": "ultrafast",
                "video_crf": 23,
                "frame_rate": 30,
                "photo_order": "order",
                "adjust_videos_to_audio": True,
                "video_transitions_enabled": True,
                
                # Настройки изображений
                "bokeh_intensity": 0.8,
                "bokeh_blur_method": "gaussian",
                "bokeh_blur_kernel": [99, 99],
                "bokeh_blur_sigma": 30,
                "bokeh_image_size": "[1920, 1080]",
                "bokeh_focus_area": "center",
                "bokeh_sides_enabled": True,
                
                # Настройки субтитров
                "subtitle_fontsize": 110,
                "subtitle_font_family": "Arial",
                "subtitle_outline_thickness": 4,
                "subtitle_line_spacing": 1.2,
                "subtitle_margin_v": 20,
                
                # Настройки голоса
                "default_voice_style": "neutral",
                
                # Настройки логотипов
                "logo_path": str(app_dir / "TestChannel" / "Logo" / "logo1.png"),
                "logo2_path": str(app_dir / "TestChannel" / "Logo" / "logo2.png"),
                "subscribe_frames_folder": str(app_dir / "TestChannel" / "Subscribe"),
                "logo_width": 300,
                "logo2_width": 300,
                "subscribe_width": 800,
                "logo_duration": "all",
                "logo2_duration": "all",
                "subscribe_duration": "all",
                "subscribe_display_duration": 5,
                "subscribe_interval_gap": 30
            }
        }
    }
    
    # Определяем пути к файлам
    channels_path = app_dir / 'channels.json'
    
    # НЕ СОЗДАЕМ автоматически файл лицензий - пользователь должен получить лицензию от администратора
    logger.info("🔑 Система лицензирования: лицензии выдаются администратором, не создаем демо-лицензию")
    
    # Создаем файлы с готовыми данными (БЕЗ .sample)
    
    try:
        import json
        import shutil
        
        # Создаем channels.json с готовыми тестовыми данными
        if not channels_path.exists():
            with open(channels_path, 'w', encoding='utf-8') as f:
                json.dump(test_channels, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Создан channels.json с тестовыми данными")
        
        # НЕ создаем файл license.json - пользователь получает лицензию от администратора
        logger.info("📝 Файл лицензий НЕ создается автоматически - получите лицензию от администратора")
        
        
        # Разворачиваем готовую папку TestChannel из билда
        if not deploy_bundled_testchannel():
            logger.warning(f"⚠️ Не удалось развернуть готовую папку TestChannel")
            logger.info(f"📝 Создаем минимальную структуру TestChannel вручную")
            
            # Fallback: создаем минимальную структуру
            test_channel_dir = app_dir / "TestChannel"
            if not test_channel_dir.exists():
                test_channel_dir.mkdir(exist_ok=True)
                logger.info(f"✅ Создана папка TestChannel")
                
                # Создаем подпапки
                for subdir in ["Audio", "Media", "Output", "Logo", "Subscribe"]:
                    (test_channel_dir / subdir).mkdir(exist_ok=True)
        else:
            logger.info(f"🎉 Готовая папка TestChannel успешно развернута!")
            test_channel_dir = app_dir / "TestChannel"
        
        # Проверяем/создаем тестовый Excel файл (только если его нет)
        test_excel_path = test_channel_dir / "Scenario.xlsx"
        if not test_excel_path.exists():
            try:
                import pandas as pd
                
                # Создаем структуру как в оригинальном файле
                # Строка 0: "ВИДЕО 1" в столбце A, остальные NaN
                # Строки 1-10: первый столбец NaN, остальные 5 столбцов с текстом
                
                data = []
                # Строка заголовка
                header_row = ["ВИДЕО 1"] + [None] * 5
                data.append(header_row)
                
                # 10 строк с тестовыми текстами
                test_texts = [
                    "Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка. Первая строка.",
                    "Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка. Вторая строка.",
                    "Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка. Третья строка.",
                    "Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка. Четвертая строка.",
                    "Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка. Пятая строка.",
                    "Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка. Шестая строка.",
                    "Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка. Седьмая строка.",
                    "Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка. Восьмая строка.",
                    "Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка. Девятая строка.",
                    "Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка. Десятая строка."
                ]
                
                for text in test_texts:
                    row = [None, text, text, text, text, text]  # Первый столбец пустой, остальные 5 с текстом
                    data.append(row)
                
                # Создаем DataFrame
                df_ru = pd.DataFrame(data)
                
                # Создаем пустые DataFrames для остальных языков
                empty_df = pd.DataFrame()
                
                # Специальный случай для AR листа
                df_ar = pd.DataFrame(columns=[None, "Текст везде в эту колонку вставляем"])
                
                # Создаем словарь с листами
                sheets = {
                    'RU': df_ru,
                    'EN': empty_df,
                    'DE': empty_df,
                    'FR': empty_df,
                    'ES': empty_df,
                    'PT': empty_df,
                    'KO': empty_df,
                    'JA': empty_df,
                    'IT': empty_df,
                    'PL': empty_df,
                    'AR': df_ar
                }
                
                # Записываем в Excel с множественными листами
                with pd.ExcelWriter(test_excel_path, engine='openpyxl') as writer:
                    for sheet_name, df in sheets.items():
                        df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
                
                logger.info(f"✅ Создан тестовый Excel файл с корректной структурой")
                
            except ImportError:
                logger.warning("Pandas не найден, тестовый Excel файл не создан")
        
        # Проверяем/создаем файл с тестовыми API ключами (только если его нет)
        test_csv_path = test_channel_dir / "Apikeys.csv"
        if not test_csv_path.exists():
            with open(test_csv_path, 'w', encoding='utf-8') as f:
                f.write("API,Date\n")  # Правильные заголовки
                f.write("your_elevenlabs_api_key_here,2024-01-01\n")
            logger.info(f"✅ Создан файл для API ключей")
        
        # Проверяем/создаем тестовые аудиофайлы (только недостающие)
        audio_folder = test_channel_dir / "Audio"
        audio_created = 0
        for i in range(1, 11):
            # Правильный формат имен: 001.mp3, 002.mp3, etc.
            audio_file = audio_folder / f"{i:03d}.mp3"
            if not audio_file.exists():
                # Создаем валидный MP3 файл с правильной структурой
                # MP3 frame header для Layer III, 44.1kHz, 128kbps, mono
                mp3_header = b'\xff\xfb\x90\x00'
                
                # Размер фрейма для 128kbps, 44.1kHz: (144 * bitrate / sample_rate)
                frame_size = int(144 * 128000 / 44100)  # ≈ 418 bytes
                frame_data = b'\x00' * (frame_size - 4)  # -4 для заголовка
                
                # Создаем несколько фреймов для валидного MP3 (≈ 2 секунды)
                frames_per_second = 44100 / 1152  # ≈ 38.28 фреймов/сек
                num_frames = int(frames_per_second * 2)  # 2 секунды
                
                mp3_data = b''
                for _ in range(max(10, num_frames)):  # минимум 10 фреймов
                    mp3_data += mp3_header + frame_data
                with open(audio_file, 'wb') as f:
                    f.write(mp3_data)
                audio_created += 1
        
        if audio_created > 0:
            logger.info(f"✅ Создано {audio_created} тестовых аудиофайлов")
        
        # Проверяем/создаем структуру папок Media (только недостающие)
        media_base = test_channel_dir / "Media"
        
        # Создаем папку для видео 1 (нужна для монтажа)
        media_1_folder = media_base / "1"
        media_1_folder.mkdir(parents=True, exist_ok=True)
        
        # Создаем файлы в папке 1
        test_images_1 = ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"]
        for img_name in test_images_1:
            img_path = media_1_folder / img_name
            if not img_path.exists():
                # Минимальное JPEG изображение
                jpeg_data = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xaa\xff\xd9'
                with open(img_path, 'wb') as f:
                    f.write(jpeg_data)
        
        # Создаем исходную структуру 2-11 для совместимости
        media_folder = media_base / "2-11"
        media_subfolders = {
            "1-2": ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg", "6.jpg", "1 Video test.mov"],
            "3-5": ["7.jpg", "8.jpg", "9.jpg", "10.jpg", "11.jpg", "12.jpg", "13.jpg"],
            "6": ["14.jpg", "15.jpg", "16.jpg", "17.jpg"],
            "7": ["18.jpg", "19.jpg", "20.jpg", "21.jpg"],
            "8-10": ["22.jpg", "23.jpg", "24.jpg", "25.jpg", "26.jpg", "27.jpg", "28.jpg"]
        }
        
        images_created = 0
        for subfolder, files in media_subfolders.items():
            subfolder_path = media_folder / subfolder
            subfolder_path.mkdir(parents=True, exist_ok=True)
            
            for filename in files:
                file_path = subfolder_path / filename
                if not file_path.exists():
                    if filename.endswith('.jpg'):
                        # Создаем минимальное JPEG изображение (1x1 пиксель, черный)
                        jpeg_data = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xaa\xff\xd9'
                        with open(file_path, 'wb') as f:
                            f.write(jpeg_data)
                        images_created += 1
                    elif filename.endswith('.mov'):
                        # Создаем минимальный QuickTime файл
                        mov_data = b'\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  \x00\x00\x00\x08wide\x00\x00\x00\x08mdat'
                        with open(file_path, 'wb') as f:
                            f.write(mov_data)
                        images_created += 1
        
        if images_created > 0:
            logger.info(f"✅ Создано {images_created} тестовых медиафайлов в структуре Media/2-11")
        
        # Проверяем логотипы (при использовании готовой папки они уже должны быть)
        logo_folder = test_channel_dir / "Logo"
        subscribe_folder = test_channel_dir / "Subscribe"
        
        # Проверяем наличие основных файлов логотипов
        required_logo_files = [
            logo_folder / "logo1.png",
            logo_folder / "logo2.png",
            subscribe_folder / "subscribe.png"
        ]
        
        missing_logos = [f for f in required_logo_files if not f.exists()]
        
        if missing_logos:
            logger.info(f"📝 Создаем недостающие логотипы: {len(missing_logos)} файлов")
            # Создаем минимальные PNG файлы для недостающих логотипов
            png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01]\xcc\x18\xdb\x00\x00\x00\x00IEND\xaeB`\x82'
            
            for logo_file in missing_logos:
                logo_file.parent.mkdir(parents=True, exist_ok=True)
                with open(logo_file, 'wb') as f:
                    f.write(png_data)
            
            logger.info(f"✅ Создано {len(missing_logos)} базовых логотипов")
        else:
            logger.info(f"✅ Все логотипы уже существуют в развернутой папке")
        
        logger.info(f"🎉 Приложение готово к использованию!")
        logger.info(f"📁 Все файлы размещены в: {app_dir}")
        logger.info(f"📝 Отредактируйте TestChannel/Apikeys.csv и добавьте свои API ключи ElevenLabs")
        logger.info(f"🖼️ Добавьте свои изображения в TestChannel/Media/ для создания видео")
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания конфигурационных файлов: {e}")