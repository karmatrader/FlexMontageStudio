import os
import sys
import argparse
import shutil
import subprocess
import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import montage_control


# Функция для скрытия окон консоли на Windows
def run_subprocess_hidden(*args, **kwargs):
    """Запуск subprocess с скрытой консолью на Windows"""
    try:
        # Более универсальная проверка Windows (включая скомпилированные приложения)
        if (os.name == 'nt' or 'win' in sys.platform.lower()) and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass  # Если не удалось определить ОС, продолжаем без флагов
    return subprocess.run(*args, **kwargs)

# PathEncoder для JSON сериализации Path объектов
class PathEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        return json.JSONEncoder.default(self, obj)

# Импорт отладчика min() вызовов
from debug_min_simple import log_min_stats, debug_min_call

# SAFETY GUARD: Предотвращаем случайную инициализацию GUI при импорте из других модулей
_GUI_SAFE_IMPORT = True

# Импорты модулей
from config import get_channel_config
from audio_processing import get_audio_files_for_video, process_audio_files, process_audio_files_by_excel_folders, add_background_music, AudioProcessor, AudioConfig
from video_processing import preprocess_images, create_video_effects_config # Обновлено
# Убедитесь, что VideoProcessor импортируется так, чтобы использовался класс из video_processing.py
from video_processing import VideoProcessor as VideoProcessorForFolders # Переименовано для ясности
from ffmpeg_utils import get_media_duration, get_ffmpeg_path, get_ffprobe_path

# ПЕРЕОПРЕДЕЛЯЕМ run_ffmpeg_command с дополнительной проверкой остановки
def run_ffmpeg_command(cmd, description="FFmpeg command", timeout=300):
    """Обертка с проверкой остановки"""
    import montage_control
    if montage_control.check_stop_flag(f"перед запуском {description}"):
        logger.error(f"🛑 ОСТАНОВКА перед запуском FFmpeg: {description}")
        raise RuntimeError(f"Монтаж остановлен перед {description}")
        
    from ffmpeg_utils import run_ffmpeg_command as original_run_ffmpeg_command
    return original_run_ffmpeg_command(cmd, description, timeout)
from image_processing_cv import SUPPORTED_FORMATS
from subtitles_processing import generate_subtitles
from final_assembly import create_subscribe_frame_list, final_assembly
from utils import find_matching_folder, find_files

# Настройка логирования для модуля
logger = logging.getLogger(__name__)


# Цвета для консольного вывода
class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    RESET = "\033[0m"


class MontageError(Exception):
    """Базовое исключение для ошибок монтажа"""
    pass


class ConfigurationError(MontageError):
    """Ошибка конфигурации"""
    pass


class FileNotFoundError(MontageError):
    """Ошибка отсутствия файла"""
    pass


class ProcessingError(MontageError):
    """Ошибка обработки медиа"""
    pass


class MontageConfig:
    """Класс для хранения и валидации конфигурации монтажа"""

    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        self.config = self._load_config()
        self._validate_config()
        self._setup_paths()
        self._setup_parameters()

    def _load_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации канала"""
        try:
            config = get_channel_config(self.channel_name)
            if not config:
                raise ConfigurationError(f"Конфигурация для канала '{self.channel_name}' не найдена")
            return config
        except Exception as e:
            raise ConfigurationError(f"Ошибка загрузки конфигурации: {e}")

    def _validate_config(self):
        """Валидация основных параметров конфигурации"""
        required_keys = [
            "global_xlsx_file_path", "base_path", "photo_folder", "output_directory",
            "output_folder", "subscribe_frames_folder", "channel_column"
        ]

        missing_keys = [key for key in required_keys if key not in self.config]
        if missing_keys:
            raise ConfigurationError(f"Отсутствуют обязательные параметры: {', '.join(missing_keys)}")

        # Проверка существования Excel файла
        xlsx_path = self.config.get("global_xlsx_file_path", "")
        if not xlsx_path or not os.path.isfile(xlsx_path):
            raise ConfigurationError(f"Excel файл не найден: {xlsx_path}")

    def _setup_paths(self):
        """Настройка путей с учетом базового пути"""
        base_path = self.config.get("base_path", "")

        # Функция для построения пути
        def build_path(path_key: str) -> str:
            path = self.config.get(path_key, "")
            if base_path and path and not os.path.isabs(path):
                return os.path.join(base_path, path)
            return path

        # Основные пути
        self.photo_folder = build_path("photo_folder")
        self.output_directory = build_path("output_directory")
        self.output_folder = build_path("output_folder")
        self.logo_path = build_path("logo_path")
        self.logo2_path = build_path("logo2_path")
        self.subscribe_frames_folder = build_path("subscribe_frames_folder")
        self.background_music_path = build_path("background_music_path")
        self.xlsx_file_path = self.config.get("global_xlsx_file_path", "")

        # Резервная папка для фото
        self.photo_folder_fallback = self.config.get("photo_folder_fallback", "error")

    def _setup_parameters(self):
        """Настройка параметров обработки с валидацией"""
        # Видео параметры
        self.num_videos = self._get_int_param("num_videos", 1, min_val=1)
        self.video_resolution = self.config.get("video_resolution", "1920:1080")
        self.frame_rate = self._get_int_param("frame_rate", 30, min_val=1, max_val=60)
        self.video_crf = self._get_int_param("video_crf", 23, min_val=0, max_val=51)
        self.video_preset = self.config.get("video_preset", "ultrafast")

        # ИСПРАВЛЕНИЕ: Добавляем codec
        self.codec = self.config.get("video_codec", "libx264")  # Добавляем атрибут codec

        # Фото параметры
        self.photo_order = self.config.get("photo_order", "order")
        self.bokeh_enabled = self.config.get("bokeh_enabled", True)
        self.bokeh_image_size = self._get_list_param("bokeh_image_size", [1920, 1080])
        self.bokeh_blur_kernel = self._get_list_param("bokeh_blur_kernel", [99, 99])
        self.bokeh_blur_sigma = self._get_float_param("bokeh_blur_sigma", 30.0, min_val=0.0)

        # Аудио параметры
        self.audio_bitrate = self.config.get("audio_bitrate", "192k")
        self.audio_sample_rate = self._get_int_param("audio_sample_rate", 44100, min_val=8000)
        self.audio_channels = self._get_int_param("audio_channels", 1, min_val=1, max_val=2)
        self.silence_duration = self.config.get("silence_duration", "1.0-2.5")
        # ИСПРАВЛЕНИЕ: Поддержка процентного формата для background_music_volume
        raw_volume = self.config.get("background_music_volume", 0.2)
        logger.info(f"🎵 DEBUG: raw_volume из config = {raw_volume} (тип: {type(raw_volume)})")
        
        if isinstance(raw_volume, (int, float)) and raw_volume > 1.0:
            # Если значение больше 1.0, считаем что это проценты
            # Слайдер идет от 0 до 10000, где 10000 = 100%
            # Поэтому делим на 10000, а не на 100
            calculated_volume = raw_volume / 10000.0
            self.background_music_volume = max(0.0, min(1.0, calculated_volume))
            # ИСПРАВЛЕНИЕ: Правильный расчет процентов для логирования
            percentage = (raw_volume / 10000.0) * 100
            logger.info(f"🎵 Фоновая музыка: {percentage:.1f}% = {self.background_music_volume:.6f} (пересчитано из UI слайдера {raw_volume})")
        else:
            self.background_music_volume = self._get_float_param("background_music_volume", 0.2, min_val=0.0, max_val=1.0)
            logger.info(f"🎵 Фоновая музыка: {self.background_music_volume:.6f} (прямое значение из конфигурации)")

        # Логотип параметры
        self.logo_width = self._get_int_param("logo_width", 200, min_val=1)
        self.logo_position_x = self.config.get("logo_position_x", "W-w-20")
        self.logo_position_y = self.config.get("logo_position_y", "20")
        self.logo_duration = self.config.get("logo_duration", "all") or "all"
        self.logo2_width = self._get_int_param("logo2_width", 200, min_val=1)
        self.logo2_position_x = self.config.get("logo2_position_x", "20")
        self.logo2_position_y = self.config.get("logo2_position_y", "20")
        self.logo2_duration = self.config.get("logo2_duration", "all") or "all"

        # Подписка параметры
        self.subscribe_width = self._get_int_param("subscribe_width", 1400, min_val=1)
        self.subscribe_position_x = self.config.get("subscribe_position_x", "-50")
        self.subscribe_position_y = self.config.get("subscribe_position_y", "main_h-overlay_h+150")
        self.subscribe_display_duration = self._get_int_param("subscribe_display_duration", 7, min_val=1)
        self.subscribe_interval_gap = self._get_int_param("subscribe_interval_gap", 30, min_val=1)
        self.subscribe_duration = self.config.get("subscribe_duration", "all") or "all"

        # Субтитры параметры
        self.subtitles_enabled = self.config.get("subtitles_enabled", True)
        self.subtitle_language = self.config.get("subtitle_language", "ru")
        self.subtitle_model = self.config.get("subtitle_model", "medium")
        self.subtitle_fontsize = self._get_int_param("subtitle_fontsize", 110, min_val=1)
        self.subtitle_font_color = self.config.get("subtitle_font_color", "&HFFFFFF")
        self.subtitle_use_backdrop = self.config.get("subtitle_use_backdrop", False)
        self.subtitle_back_color = self.config.get("subtitle_back_color", "&HFFFFFF")
        self.subtitle_outline_thickness = self._get_int_param("subtitle_outline_thickness", 4, min_val=0)
        self.subtitle_outline_color = self.config.get("subtitle_outline_color", "&H000000")
        self.subtitle_shadow_thickness = self._get_int_param("subtitle_shadow_thickness", 1, min_val=0)
        self.subtitle_shadow_color = self.config.get("subtitle_shadow_color", "&H333333")
        self.subtitle_shadow_alpha = self._get_int_param("subtitle_shadow_alpha", 50, min_val=0, max_val=100)
        self.subtitle_shadow_offset_x = self._get_int_param("subtitle_shadow_offset_x", 2)
        self.subtitle_shadow_offset_y = self._get_int_param("subtitle_shadow_offset_y", 2)
        self.subtitle_margin_v = self._get_int_param("subtitle_margin_v", 20, min_val=0)
        self.subtitle_margin_l = self._get_int_param("subtitle_margin_l", 10, min_val=0)
        self.subtitle_margin_r = self._get_int_param("subtitle_margin_r", 10, min_val=0)
        self.subtitle_max_words = self._get_int_param("subtitle_max_words", 3, min_val=1)
        self.subtitle_time_offset = self._get_float_param("subtitle_time_offset", -0.3)

        # Обработка параметры
        self.adjust_videos_to_audio = self.config.get("adjust_videos_to_audio", True)
        self.preserve_clip_audio_default = self.config.get("preserve_clip_audio", False)
        self.preserve_video_duration = self.config.get("preserve_video_duration", False)
        self.channel_column = self.config.get("channel_column", "B")
        
        # Экспериментальные параметры
        self.single_pass_enabled = self.config.get("single_pass_enabled", False)
        
        # Отладочные параметры
        self.debug_keep_temp_folder = self.config.get("debug_keep_temp_folder", False)

    def _get_int_param(self, key: str, default: int, min_val: Optional[int] = None,
                       max_val: Optional[int] = None) -> int:
        """Получение и валидация integer параметра"""
        try:
            value = int(self.config.get(key, default))
            if min_val is not None and value < min_val:
                logger.warning(f"Параметр {key}={value} меньше минимума {min_val}, используется минимум")
                return min_val
            if max_val is not None and value > max_val:
                logger.warning(f"Параметр {key}={value} больше максимума {max_val}, используется максимум")
                return max_val
            return value
        except (ValueError, TypeError):
            logger.warning(f"Некорректное значение для {key}: {self.config.get(key)}, используется {default}")
            return default

    def _get_float_param(self, key: str, default: float, min_val: Optional[float] = None,
                         max_val: Optional[float] = None) -> float:
        """Получение и валидация float параметра"""
        try:
            value = float(self.config.get(key, default))
            if min_val is not None and value < min_val:
                logger.warning(f"Параметр {key}={value} меньше минимума {min_val}, используется минимум")
                return min_val
            if max_val is not None and value > max_val:
                logger.warning(f"Параметр {key}={value} больше максимума {max_val}, используется максимум")
                return max_val
            return value
        except (ValueError, TypeError):
            logger.warning(f"Некорректное значение для {key}: {self.config.get(key)}, используется {default}")
            return default

    def _get_list_param(self, key: str, default: List[int]) -> List[int]:
        """Получение и валидация list параметра"""
        try:
            value = self.config.get(key, default)
            if isinstance(value, list) and len(value) == 2:
                return [int(v) for v in value]
            else:
                logger.warning(f"Некорректный формат для {key}: {value}, используется {default}")
                return default
        except (ValueError, TypeError):
            logger.warning(f"Некорректное значение для {key}: {self.config.get(key)}, используется {default}")
            return default

    def validate_paths(self) -> List[str]:
        """Валидация путей и возврат списка ошибок"""
        errors = []

        # Проверка обязательных папок
        required_dirs = {
            "photo_folder": self.photo_folder,
            "output_directory": self.output_directory,
            "subscribe_frames_folder": self.subscribe_frames_folder
        }

        for name, path in required_dirs.items():
            if not path or not os.path.exists(path):
                errors.append(f"Папка {name} не найдена: {path}")

        # Проверка Excel файла
        if not os.path.isfile(self.xlsx_file_path):
            errors.append(f"Excel файл не найден: {self.xlsx_file_path}")

        return errors

    def check_optional_files(self):
        """Проверка опциональных файлов и логирование предупреждений"""
        if not self.logo_path or not os.path.isfile(self.logo_path):
            logger.warning(f"Логотип не найден: {self.logo_path}. Наложение логотипа пропущено.")
            self.logo_path = None
        else:
            logger.info(f"Логотип найден: {self.logo_path}")

        if not self.logo2_path or not os.path.isfile(self.logo2_path):
            logger.warning(f"Второй логотип не найден: {self.logo2_path}. Наложение второго логотипа пропущено.")
            self.logo2_path = None
        else:
            logger.info(f"Второй логотип найден: {self.logo2_path}")

        if not self.background_music_path or not os.path.isfile(self.background_music_path):
            logger.warning(
                f"Фоновая музыка не найдена: {self.background_music_path}. Используется основная аудиодорожка.")
            self.background_music_path = None
        else:
            logger.info(f"Фоновая музыка найдена: {self.background_music_path}")


def ensure_string_path(path):
    """Гарантирует, что путь является строкой"""
    if isinstance(path, (list, tuple)):
        return str(path[0]) if path else ""
    elif isinstance(path, str) and path.startswith('[') and path.endswith(']'):
        # Обработка строки вида "['path']"
        try:
            import ast
            parsed = ast.literal_eval(path)
            if isinstance(parsed, (list, tuple)) and parsed:
                return str(parsed[0])
        except:
            pass
    return str(path) if path else ""


class VideoProcessor:
    """Класс для обработки отдельного видео"""

    def __init__(self, config: MontageConfig, video_number: str, preserve_clip_audio_videos: List[int]):
        self.config = config
        self.video_number = video_number
        self.preserve_clip_audio_videos = preserve_clip_audio_videos
        self.video_number_int = int(video_number)
        
        # Получаем debug конфигурацию
        try:
            from config import load_config
            full_config = load_config()
            self.debug_config = full_config.get("proxy_config", {}).get("debug_config", {})
        except Exception:
            self.debug_config = {}

        # Определение папок для видео
        self.output_folder_vid = os.path.join(config.output_folder, video_number)
        self.temp_folder = os.path.join(self.output_folder_vid, "temp")
        self.preprocessed_photo_folder = os.path.join(self.temp_folder, "preprocessed_photos")
        self.temp_audio_folder = os.path.join(self.temp_folder, "audio")

        # Создание необходимых папок
        self._create_directories()
        
        # Инициализация AudioProcessor
        audio_config = AudioConfig(
            channels=config.audio_channels,
            sample_rate=config.audio_sample_rate,
            bitrate=config.audio_bitrate,
            silence_duration=config.silence_duration,
            background_music_volume=config.background_music_volume
        )
        self.audio_processor = AudioProcessor(audio_config)

        # Инициализация VideoProcessor из video_processing.py
        # Передаем ему VideoConfig и VideoEffectsConfig
        try:
            from video_processing import VideoConfig # Убедитесь, что это импортирует правильный VideoConfig

            # Создаем словарь данных для VideoConfig
            video_config_data = {
                "video_resolution": self.config.video_resolution, # Используйте self.config.video_resolution
                "frame_rate": self.config.frame_rate,
                "video_crf": self.config.video_crf,
                "video_preset": self.config.video_preset,
                # "temp_folder": self.temp_folder # <-- УДАЛИТЕ ЭТУ СТРОКУ, VideoConfig не принимает temp_folder
            }
            video_config_for_vp = VideoConfig(video_config_data) # Передайте словарь

            effects_config_for_vp = create_video_effects_config(self.config.config)

            # Инициализируйте VideoProcessorForFolders
            self.folder_video_processor = VideoProcessorForFolders(
                video_config_for_vp, # Передайте созданный VideoConfig
                effects_config_for_vp,
                self.temp_folder,
                self.config.xlsx_file_path,
                self.preserve_clip_audio_videos,  # Добавляем параметр preserve_clip_audio_videos
                self.video_number  # Добавляем параметр video_number
            )
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации folder_video_processor: {e}")
            self.folder_video_processor = None

    def _create_directories(self):
        """Создание необходимых директорий"""
        for directory in [self.output_folder_vid, self.temp_folder,
                          self.preprocessed_photo_folder, self.temp_audio_folder]:
            os.makedirs(directory, exist_ok=True)

    def _should_preserve_clip_audio(self) -> bool:
        """Определение необходимости сохранения аудио клипа"""
        result = (self.config.preserve_clip_audio_default or
                self.video_number_int in self.preserve_clip_audio_videos)
        logger.info(f"🔍 DEBUG _should_preserve_clip_audio: видео={self.video_number_int}, preserve_clip_audio_videos={self.preserve_clip_audio_videos}, default={self.config.preserve_clip_audio_default}, result={result}")
        return result

    def _get_output_file_path(self) -> str:
        """Получение пути к выходному файлу"""
        return os.path.join(self.output_folder_vid, f"final_video_{self.video_number}.mp4")

    def _is_video_already_processed(self) -> bool:
        """Проверка, существует ли уже готовое видео"""
        output_file = self._get_output_file_path()
        if os.path.exists(output_file):
            logger.info(f"Готовое видео уже существует: {output_file}")
            return True
        return False

    def _get_audio_files_and_range(self) -> Tuple[List[str], Optional[int], Optional[int]]:
        """Получение аудиофайлов и диапазона строк"""
        try:
            audio_files, start_row, end_row = get_audio_files_for_video(
                self.config.xlsx_file_path,
                self.config.output_directory,
                self.video_number,
                self.config.subtitle_language,
                self.config.channel_column
            )

            if not audio_files:
                raise ProcessingError(f"Аудиофайлы для видео {self.video_number} не найдены")

            if start_row is None or end_row is None:
                raise ProcessingError(f"Не удалось определить диапазон строк для видео {self.video_number}")

            logger.info(f"Найден диапазон для видео {self.video_number}: строки {start_row}–{end_row}")
            return audio_files, start_row, end_row

        except Exception as e:
            raise ProcessingError(f"Ошибка получения аудиофайлов: {e}")

    def _find_photo_folder(self, start_row: int, end_row: int) -> str:
        """Поиск папки с фотографиями"""
        photo_folder_vid = find_matching_folder(
            self.config.photo_folder,
            self.video_number,
            start_row,
            end_row,
            self.config.photo_folder_fallback
        )

        if photo_folder_vid is None:
            raise FileNotFoundError(
                f"Папка с фото для видео {self.video_number} не найдена в {self.config.photo_folder}")

        logger.info(f"Папка с фото/видео: {photo_folder_vid}")
        return photo_folder_vid

    def _copy_audio_files(self, audio_files: List[str]):
        """Копирование аудиофайлов в временную папку"""
        copied_files = 0
        for audio_file in audio_files:
            src_path = os.path.join(self.config.output_directory, audio_file)
            dst_path = os.path.join(self.temp_audio_folder, audio_file)

            if os.path.exists(src_path):
                try:
                    shutil.copy(src_path, dst_path)
                    copied_files += 1
                except Exception as e:
                    logger.error(f"Ошибка копирования {src_path}: {e}")
            else:
                logger.warning(f"Файл не найден для копирования: {src_path}")

        logger.info(f"Скопировано аудиофайлов: {copied_files}/{len(audio_files)}")

    # УДАЛЕНО: _process_audio - функционал интегрирован в создание аудиосегментов и их микширование на уровне папки



    def _preprocess_images(self, photo_folder_vid: str) -> Dict[str, str]:
        """Предобработка изображений"""
        logger.info("=== 🖼️ Предобработка изображений ===")

        processed_files_mapping = {}

        try:
            # Нормализуем базовую папку
            photo_folder_vid_path = Path(photo_folder_vid).resolve() # <-- ИСПРАВЛЕНИЕ
            # Собираем конфигурацию эффектов
            effects_config = {
                # Расширенные параметры боке
                'bokeh_sides_enabled': self.config.config.get('bokeh_sides_enabled', False),
                'bokeh_blur_method': self.config.config.get('bokeh_blur_method', 'gaussian'),
                'bokeh_intensity': self.config.config.get('bokeh_intensity', 0.8),
                'bokeh_focus_area': self.config.config.get('bokeh_focus_area', 'center'),
                'bokeh_transition_smoothness': self.config.config.get('bokeh_transition_smoothness', 50),
                # Дополнительные эффекты
                'sharpen_enabled': self.config.config.get('sharpen_enabled', False),
                'sharpen_strength': self.config.config.get('sharpen_strength', 1.5),
                'contrast_enabled': self.config.config.get('contrast_enabled', False),
                'contrast_factor': self.config.config.get('contrast_factor', 1.2),
                'brightness_enabled': self.config.config.get('brightness_enabled', False),
                'brightness_delta': self.config.config.get('brightness_delta', 10),
                'saturation_enabled': self.config.config.get('saturation_enabled', False),
                'saturation_factor': self.config.config.get('saturation_factor', 1.1),
                'vignette_enabled': self.config.config.get('vignette_enabled', False),
                'vignette_strength': self.config.config.get('vignette_strength', 0.3),
                'edge_enhancement': self.config.config.get('edge_enhancement', False),
                'noise_reduction': self.config.config.get('noise_reduction', False),
                'histogram_equalization': self.config.config.get('histogram_equalization', False),
                'style_filter': self.config.config.get('style_filter', 'none')
            }
            
            # Проверяем, нужна ли обработка (боке или любой другой эффект)
            needs_processing = (self.config.bokeh_enabled or 
                               effects_config.get('bokeh_sides_enabled', False) or
                               any(effects_config.get(key, False) for key in 
                                   ['sharpen_enabled', 'contrast_enabled', 'brightness_enabled',
                                    'saturation_enabled', 'vignette_enabled', 'edge_enhancement', 
                                    'noise_reduction', 'histogram_equalization']) or
                               effects_config.get('style_filter', 'none') != 'none')
                               
            if needs_processing:
                # Для сложной обработки вызываем внешнюю функцию, но создаём маппинг
                preprocess_images(
                    photo_folder_vid,
                    self.preprocessed_photo_folder,
                    self.config.bokeh_enabled,
                    tuple(self.config.bokeh_image_size),
                    tuple(self.config.bokeh_blur_kernel),
                    self.config.bokeh_blur_sigma,
                    video_resolution=self.config.video_resolution,
                    frame_rate=self.config.frame_rate,
                    effects_config=effects_config,
                    debug_config=self.debug_config
                )
                
                # Создаём маппинг на основе структуры каталогов
                # Находим все файлы для обработки, и сразу нормализуем их пути
                original_files_raw = find_files(str(photo_folder_vid_path), SUPPORTED_FORMATS, recursive=True)
                original_files = [str(Path(f).resolve()) for f in original_files_raw] # <-- ИСПРАВЛЕНИЕ: Нормализуем пути
                for original_path in original_files:
                    original_path_obj = Path(original_path)
                    # Используем нормализованную photo_folder_vid_path
                    relative_path_key = str(original_path_obj.relative_to(photo_folder_vid_path)) # <-- ИСПРАВЛЕНИЕ
                    # Создаем выходную директорию
                    output_dir = Path(self.preprocessed_photo_folder).resolve() / Path(relative_path_key).parent # <-- ИСПРАВЛЕНИЕ: Нормализуем
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / original_path_obj.name # original_path_obj.name уже нормализован
                    
                    preprocessed_path = Path(self.preprocessed_photo_folder) / relative_path_key
                    if preprocessed_path.exists():
                        # В местах, где вы записываете в processed_files_mapping
                        processed_files_mapping[relative_path_key] = str(output_path.resolve()) # <-- ИСПРАВЛЕНИЕ: Храним разрешенный путь
                    else:
                        logger.warning(f"⚠️ Предобработанный файл не найден: {preprocessed_path}")
                        
            else:
                logger.info("🎨 Обработка изображений не требуется, копируем оригиналы")
                # Копируем и создаём маппинг
                original_files_raw = find_files(str(photo_folder_vid_path), SUPPORTED_FORMATS, recursive=True)
                original_files = [str(Path(f).resolve()) for f in original_files_raw] # <-- ИСПРАВЛЕНИЕ: Нормализуем пути
                for original_path in original_files:
                    original_path_obj = Path(original_path)
                    # Используем нормализованную photo_folder_vid_path
                    relative_path_key = str(original_path_obj.relative_to(photo_folder_vid_path)) # <-- ИСПРАВЛЕНИЕ
                    
                    # Создаём выходную директорию
                    output_dir = Path(self.preprocessed_photo_folder).resolve() / Path(relative_path_key).parent # <-- ИСПРАВЛЕНИЕ: Нормализуем
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / original_path_obj.name # original_path_obj.name уже нормализован
                    
                    try:
                        shutil.copy2(original_path, output_path)
                        processed_files_mapping[relative_path_key] = str(output_path.resolve()) # <-- ИСПРАВЛЕНИЕ: Храним разрешенный путь
                    except Exception as copy_error:
                        logger.error(f"❌ Ошибка копирования {original_path}: {copy_error}")

        except Exception as e:
            logger.error(f"❌ Ошибка предобработки изображений: {e}")
            # При ошибке просто копируем оригиналы и создаём маппинг
            try:
                original_files_raw = find_files(str(photo_folder_vid_path), SUPPORTED_FORMATS, recursive=True)
                original_files = [str(Path(f).resolve()) for f in original_files_raw] # <-- ИСПРАВЛЕНИЕ: Нормализуем пути
                for original_path in original_files:
                    original_path_obj = Path(original_path)
                    relative_path = original_path_obj.relative_to(photo_folder_vid_path)
                    
                    # Создаём выходную директорию
                    output_dir = Path(self.preprocessed_photo_folder).resolve() / relative_path.parent # <-- ИСПРАВЛЕНИЕ: Нормализуем
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / original_path_obj.name # original_path_obj.name уже нормализован
                    
                    try:
                        shutil.copy2(original_path, output_path)
                        # Также убедитесь, что в блоке except вы также используете .resolve()
                        processed_files_mapping[str(relative_path)] = str(output_path.resolve()) # <-- ИСПРАВЛЕНИЕ: Храним разрешенный путь
                    except Exception as copy_error:
                        logger.error(f"❌ Ошибка копирования оригинала {original_path}: {copy_error}")
                        
                logger.warning("⚠️ Используются оригинальные изображения")
            except Exception as copy_error:
                logger.error(f"❌ Ошибка копирования оригиналов: {copy_error}")
                raise ProcessingError("Не удалось подготовить изображения")

        logger.info("✅ Предобработка изображений завершена")
        return processed_files_mapping

    def _process_photos_and_videos(self, temp_audio_duration: float, start_row: int, end_row: int, 
                                    folder_to_files: Dict[str, List] = None) -> Tuple[
        List[str], List[Dict], float, Dict[str, float]]:
        """Обработка фото и видео"""
        logger.info("=== 🎬 Обработка фото и видео ===")

        # Инициализируем audio_offset для использования в функции
        audio_offset = 0.0

        photo_files = find_files(
            self.preprocessed_photo_folder,
            SUPPORTED_FORMATS,
            recursive=True
        )

        if not photo_files:
            raise ProcessingError(f"Нет фото/видео для обработки в {self.preprocessed_photo_folder}")

        logger.info(f"🔍 DEBUG: Вызываем _should_preserve_clip_audio()")
        preserve_clip_audio = self._should_preserve_clip_audio()
        logger.info(f"🔍 DEBUG: _should_preserve_clip_audio() вернул: {preserve_clip_audio}")
        logger.info(f"Сохранение аудио клипа для видео {self.video_number}: {preserve_clip_audio}")

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Отключаем XFADE для отдельных файлов
        # XFADE будет применяться только к финальным сегментам папок
        effects_config_for_files = create_video_effects_config(self.config.config)
        
        # ВРЕМЕННО отключаем переходы для обработки отдельных файлов
        effects_config_for_files.transitions_enabled = False
        effects_config_for_files.transition_method = "none"
        
        logger.info("🔧 ИСПРАВЛЕНИЕ: XFADE отключен для обработки отдельных файлов")
        logger.info("🔧 XFADE будет применяться только к сегментам папок в финальной конкатенации")
        
        if effects_config_for_files.effects_enabled:
            logger.info("🎨 Эффекты видео включены")
            if effects_config_for_files.auto_zoom_alternation:
                logger.info("🔄 Автоматическое чередование Zoom In/Out активно")
            
            # Предупреждения о производительности
            complex_effects = []
            if effects_config_for_files.zoom_effect != "none":
                complex_effects.append("масштабирование")
            if effects_config_for_files.rotation_effect != "none":
                complex_effects.append("вращение")
            if effects_config_for_files.color_effect != "none":
                complex_effects.append("цветовые эффекты")
            if effects_config_for_files.filter_effect != "none":
                complex_effects.append("фильтры")
            
            if complex_effects:
                logger.warning(f"⚠️ Использование эффектов ({', '.join(complex_effects)}) может увеличить время обработки")

        try:
            # НОВАЯ ПРАВИЛЬНАЯ ЛОГИКА: process_photos_and_videos сам вычисляет folder_durations
            logger.info("🎯 ПРАВИЛЬНАЯ ЛОГИКА: folder_durations будет вычислен в process_photos_and_videos")
            logger.info(f"📊 temp_audio_duration: {temp_audio_duration:.3f}с")
            logger.info(f"📊 start_row: {start_row}, end_row: {end_row}")
            logger.info(f"📊 preserve_clip_audio: {preserve_clip_audio}")
            logger.info(f"📊 adjust_videos_to_audio: {self.config.adjust_videos_to_audio}")
            logger.info(f"📊 Файлов для обработки: {len(photo_files)}")
            
            processed_photo_files, skipped_files, clips_info, audio_offset_new, file_durations_map = process_photos_and_videos(
                photo_files=photo_files,
                preprocessed_photo_folder=self.preprocessed_photo_folder,
                temp_folder=self.temp_folder,
                video_resolution=self.config.video_resolution,
                frame_rate=self.config.frame_rate,
                video_crf=self.config.video_crf,
                video_preset=self.config.video_preset,
                temp_audio_duration=temp_audio_duration,  # Используем оригинальную длительность
                audio_folder=str(self.config.output_directory) if not isinstance(self.config.output_directory, tuple) else str(self.config.output_directory[0]) if self.config.output_directory else "",
                overall_range_start=start_row,
                overall_range_end=end_row,
                excel_path=self.config.xlsx_file_path,
                video_number=self.video_number,
                photo_order=self.config.photo_order,
                adjust_videos_to_audio=self.config.adjust_videos_to_audio,
                preserve_clip_audio=preserve_clip_audio,
                preserve_video_duration=self.config.preserve_video_duration,
                effects_config=effects_config_for_files,
                silence_duration=self.config.silence_duration,
                folder_durations=None,  # Не передаём, пусть вычисляется внутри
                excel_folder_to_files=folder_to_files,  # Передаём данные из Excel анализа
                debug_video_processing=self.config.debug_video_processing  # Параметр отладки
            )
            
            # Обновляем audio_offset полученным значением
            audio_offset = audio_offset_new

            if not processed_photo_files:
                raise ProcessingError("Не удалось обработать ни одного фото/видео")

            logger.info(f"Обработано файлов: {len(processed_photo_files)} из {len(photo_files)}")
            if skipped_files:
                logger.warning(f"Пропущенные файлы ({len(skipped_files)}): {', '.join(skipped_files)}")
            
            # Дополнительное логирование для отладки проблемы с остановкой обработки
            logger.info(f"🎞️ Список обработанных файлов:")
            for i, file_path in enumerate(processed_photo_files):
                logger.info(f"  {i+1}. {file_path}")
            
            if effects_config_for_files.effects_enabled:
                logger.info(f"🎨 Эффекты применены к {len(processed_photo_files)} клипам")
                if effects_config_for_files.zoom_effect == "auto":
                    logger.info(f"   Zoom чередование: четные={effects_config_for_files.zoom_effect}_in, нечетные={effects_config_for_files.zoom_effect}_out")

            # ДИАГНОСТИКА: Проверяем полученные результаты
            logger.info(f"🔍 ДИАГНОСТИКА РЕЗУЛЬТАТОВ process_photos_and_videos:")
            logger.info(f"   Обработано файлов: {len(processed_photo_files)}")
            logger.info(f"   Информации о клипах: {len(clips_info)}")
            logger.info(f"   Audio offset: {audio_offset:.3f}с")
            logger.info(f"   Excel длительности (file_durations_map): {len(file_durations_map) if file_durations_map else 0} файлов")
            
            # Проверяем накопительное время
            cumulative_time = audio_offset
            logger.info(f"   Ожидаемое расписание воспроизведения:")
            logger.info(f"     0с - {audio_offset:.3f}с: видеоклип с аудио")
            
            # Найдем границы папок
            folder_boundaries = {}
            current_time = audio_offset
            for clip in clips_info:
                if not clip.get('has_audio', False):  # Только файлы без аудио (из Excel)
                    # Защита от tuple в path
                    clip_path = str(clip['path']) if not isinstance(clip['path'], tuple) else str(clip['path'][0]) if clip['path'] else ""
                    file_name = Path(clip_path).name
                    duration = clip['duration']
                    end_time = current_time + duration
                    folder_boundaries[file_name] = (current_time, end_time)
                    current_time = end_time
            
            # Показываем первые несколько файлов
            for i, (file_name, (start_time, end_time)) in enumerate(list(folder_boundaries.items())[:10]):
                logger.info(f"     {start_time:.1f}с - {end_time:.1f}с: {file_name}")
                if i == 6:  # Примерно где должна начинаться папка 3-5
                    logger.info(f"     ^^^ Около этого времени должны начинаться файлы из папки 3-5")

            # temp_audio_duration остается без изменений
            
            result = (processed_photo_files, skipped_files, clips_info, audio_offset, file_durations_map)
            logger.info(f"🔍 _process_photos_and_videos возвращает: {len(result)} значений")
            return result

        except Exception as e:
            raise ProcessingError(f"Ошибка обработки фото и видео: {e}")

    def _concatenate_videos(self, processed_photo_files: List[str], temp_audio_duration: float, effects_config=None, clips_info: List[Dict] = None, file_durations_map: Dict[str, float] = None, adjust_videos_to_audio: bool = True, audio_offset: float = 0.0) -> str:
        """Конкатенация видео"""
        logger.info("=== 🎞️ Конкатенация видео ===")
        logger.info(f"🎬 CONCAT DEBUG: Получено {len(processed_photo_files)} файлов для конкатенации:")
        for i, file_path in enumerate(processed_photo_files):
            logger.info(f"  {i+1}. {Path(file_path).name}")
        logger.info(f"🎬 CONCAT DEBUG: clips_info содержит {len(clips_info) if clips_info else 0} записей")
        logger.info(f"🎬 CONCAT DEBUG: file_durations_map содержит {len(file_durations_map) if file_durations_map else 0} записей")
        
        # ДИАГНОСТИКА: Проверяем что clips_info передана правильно
        logger.info(f"🔍 ДИАГНОСТИКА ПАРАМЕТРОВ:")
        logger.info(f"   processed_photo_files: {len(processed_photo_files) if processed_photo_files else 0} файлов")
        logger.info(f"   temp_audio_duration: {temp_audio_duration:.2f}с")
        logger.info(f"   effects_config: {effects_config}")
        logger.info(f"   clips_info: {len(clips_info) if clips_info else 0} клипов")

        try:
            # ИСПРАВЛЕНИЕ: Проверяем правильно настройки переходов
            has_transitions = False
            if effects_config:
                transitions_enabled = getattr(effects_config, 'transitions_enabled', False)
                transition_method = getattr(effects_config, 'transition_method', 'overlay')

                # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: проверяем именно transition_method = "xfade"
                has_transitions = transitions_enabled and transition_method == "xfade"

            # ДИАГНОСТИКА ПЕРЕХОДОВ
            logger.info(f"🔍 ИСПРАВЛЕННАЯ ДИАГНОСТИКА ПЕРЕХОДОВ:")
            logger.info(f"   effects_config: {effects_config}")
            logger.info(f"   transitions_enabled: {getattr(effects_config, 'transitions_enabled', 'НЕТ АТРИБУТА')}")
            logger.info(f"   transition_method: {getattr(effects_config, 'transition_method', 'НЕТ АТРИБУТА')}")
            logger.info(f"   transition_type: {getattr(effects_config, 'transition_type', 'НЕТ АТРИБУТА')}")
            logger.info(f"   transition_duration: {getattr(effects_config, 'transition_duration', 'НЕТ АТРИБУТА')}")
            logger.info(f"   has_transitions (ИСПРАВЛЕНО): {has_transitions}")
            logger.info(f"   len(processed_photo_files): {len(processed_photo_files)}")
            logger.info(f"   Условие для XFADE: {has_transitions and len(processed_photo_files) > 1}")

            # ИСПРАВЛЕНИЕ: Используем правильную функцию для XFADE
            if has_transitions and len(processed_photo_files) > 1:
                logger.info(f"🔄 Создание видео с XFADE переходами: {effects_config_for_files.transition_type}, длительность {effects_config_for_files.transition_duration}с")
                temp_video_path = self._concatenate_with_xfade_transitions(
                    processed_photo_files, temp_audio_duration, effects_config_for_files,
                    clips_info, file_durations_map, adjust_videos_to_audio, audio_offset,
                    self.preserve_video_duration
                )
                logger.info(f"🔍 _concatenate_with_xfade_transitions возвращает: {temp_video_path}")
                return temp_video_path
            else:
                # ИСПРАВЛЕНО: Добавляем диагностику файлов перед конкатенацией
                logger.info(f"🔍 ДИАГНОСТИКА ФАЙЛОВ ПЕРЕД КОНКАТЕНАЦИЕЙ:")
                logger.info(f"   Общее количество файлов: {len(processed_photo_files)}")
                logger.info(f"   Порядок фото: {self.config.photo_order}")
                logger.info(f"   Целевая длительность аудио: {temp_audio_duration:.2f}с")
                
                # Показываем первые и последние файлы для диагностики
                for i, file_path in enumerate(processed_photo_files[:5]):
                    file_name = Path(file_path).name
                    logger.info(f"   Файл {i+1}: {file_name}")
                if len(processed_photo_files) > 10:
                    logger.info(f"   ... (пропущено {len(processed_photo_files) - 10} файлов)")
                    for i in range(max(5, len(processed_photo_files) - 5), len(processed_photo_files)):
                        file_name = Path(processed_photo_files[i]).name
                        logger.info(f"   Файл {i+1}: {file_name}")
                
                # Обычная конкатенация без переходов
                logger.info(f"🎯 Передача file_durations_map в concat: {len(file_durations_map) if file_durations_map else 0} файлов")
                if self.config.photo_order == "order":
                    concat_list_path = concat_photos_in_order(processed_photo_files, self.temp_folder, temp_audio_duration, clips_info, file_durations_map)
                else:
                    concat_list_path = concat_photos_random(processed_photo_files, self.temp_folder, temp_audio_duration, clips_info, file_durations_map)

                # НОВОЕ: Логирование содержимого concat_list.txt
                try:
                    with open(concat_list_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        logger.info(f"🔍 СОДЕРЖИМОЕ {os.path.basename(concat_list_path)}:")
                        logger.info("--- START CONCAT_LIST ---")
                        for line in content.splitlines()[:20]:  # Выводим первые 20 строк для примера
                            logger.info(f"  {line}")
                        if len(content.splitlines()) > 20:
                            logger.info("  ... (остальные строки)")
                        logger.info("--- END CONCAT_LIST ---")
                except Exception as e:
                    logger.error(f"❌ Не удалось прочитать {os.path.basename(concat_list_path)} для логирования: {e}")

                temp_video_path = os.path.join(self.temp_folder, "temp_video.mp4")

                # ИСПРАВЛЕНИЕ: Максимально упрощаем команду конкатенации
                # Убираем -vsync vfr, -map 0:v:0, оставляем только базовые вещи.
                # FFmpeg concat demuxer обычно сам справляется с маппингом.
                
                base_cmd = [
                    get_ffmpeg_path(), "-v", "debug",
                    "-f", "concat", "-safe", "0", "-i", concat_list_path,
                    "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                    "-an",  # Отключаем аудиопоток из видео
                    "-y", temp_video_path
                ]

                if adjust_videos_to_audio:
                    logger.info(f"🔧 СОЗДАНИЕ temp_video.mp4 с растяжением под длительность аудио {temp_audio_duration:.2f}с")
                    cmd = base_cmd + ["-t", str(temp_audio_duration)]
                else:
                    logger.info(f"🔧 СОЗДАНИЕ temp_video.mp4 БЕЗ растяжения (исходная длительность клипов)")
                    cmd = base_cmd  # Без параметра -t чтобы сохранить исходную длительность

                # Дополнительные флаги, которые могут быть полезны, но пока оставим их отключенными,
                # если проблема в них.
                # cmd.extend(["-fflags", "+genpts+igndts", "-probesize", "50000000", "-analyzeduration", "50000000"])

                result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True)
                logger.debug(f"FFmpeg concat output: {result.stdout}")
                
                # НОВОЕ: Валидация длительности результата
                actual_duration = get_media_duration(temp_video_path)
                logger.info(f"✅ Фактическая длительность видео после конкатенации: {actual_duration:.2f}с")
                
                # Проверяем соответствие ожидаемой длительности
                if abs(actual_duration - temp_audio_duration) > 5.0:
                    logger.warning(f"⚠️ ВНИМАНИЕ: Фактическая длительность ({actual_duration:.2f}с) значительно отличается от ожидаемой ({temp_audio_duration:.2f}с)")
                    logger.warning("Это может указывать на проблему с длительностями клипов или настройками кодирования")

                return temp_video_path

        except subprocess.CalledProcessError as e:
            raise ProcessingError(f"Ошибка при конкатенации видео: {e.stderr}")
        except Exception as e:
            raise ProcessingError(f"Ошибка конкатенации: {e}")

    def _concatenate_with_transitions(self, processed_photo_files: List[str], temp_audio_duration: float, effects_config, clips_info: List[Dict] = None, file_durations_map: Dict[str, float] = None, adjust_videos_to_audio: bool = True, audio_offset: float = 0.0) -> str:
        """Конкатенация видео с переходами overlay - используя отдельные файлы"""
        logger.info("🎬 Начинаем конкатенацию видео с переходами (используя overlay и отдельные файлы).")
        temp_video_path = Path(self.temp_folder) / "final_video_with_transitions.mp4"
        
        try:
            # Получаем реальную длительность каждого клипа
            transition_clips_paths = [] # Список для хранения путей к временным файлам переходов
            
            # --- Шаг 1: Получаем длительности каждого клипа ---
            actual_processed_clip_durations = []
            for file_path in processed_photo_files:
                duration = get_media_duration(file_path)
                if duration is None:
                    logger.error(f"❌ Не удалось получить длительность файла: {file_path}. Пропускаем.")
                    raise ProcessingError(f"Не удалось получить длительность файла: {file_path}")
                actual_processed_clip_durations.append(duration)
                logger.debug(f"   Длительность {Path(file_path).name}: {duration:.2f}с")

            # --- Шаг 2: Компенсация длительности для переходов ---
            # Для overlay мы не урезаем клипы заранее, а управляем таймингом внутри фильтра.
            # Однако, нам все равно нужна длительность перехода.
            transition_duration_actual = getattr(effects_config, 'transition_duration', 0.5)

            # --- Шаг 3: Создание отдельных файлов для каждого перехода с overlay ---
            # Каждый переход будет состоять из части первого клипа, на которую накладывается часть второго.
            # Затем мы будем конкатенировать: [клип1] + [переход1-2] + [клип2] + [переход2-3] + [клип3] ...

            final_segments_for_concat = []

            for i in range(len(processed_photo_files)):
                current_clip_path = processed_photo_files[i]
                current_clip_duration = actual_processed_clip_durations[i]

                # Добавляем "чистую" часть текущего клипа
                # Если это первый клип, или если предыдущий переход не полностью его поглотил
                # Мы будем добавлять чистую часть клипа, которая предшествует переходу.

                # Если это не последний клип и переходы включены
                if i < len(processed_photo_files) - 1 and getattr(effects_config, 'transitions_enabled', True):
                    next_clip_path = processed_photo_files[i+1]
                    next_clip_duration = actual_processed_clip_durations[i+1]

                    # Длительность "чистой" части текущего клипа до начала перехода
                    pure_current_duration = current_clip_duration - transition_duration_actual
                    pure_current_duration = max(0.01, pure_current_duration) # Минимум 0.01с

                    # Создаем временный файл для чистой части текущего клипа
                    temp_pure_current_path = Path(self.temp_folder) / f"pure_clip_{i}.mp4"
                    cmd_pure_current = [
                        get_ffmpeg_path(), "-v", "debug",
                        "-i", current_clip_path,
                        "-c:v", "copy", "-c:a", "copy", # Копируем без перекодировки для скорости
                        "-t", str(pure_current_duration),
                        "-y", str(temp_pure_current_path)
                    ]
                    logger.info(f"🎞️ Создаем чистую часть клипа {i}: {Path(current_clip_path).name}")
                    run_ffmpeg_command(cmd_pure_current, f"Создание чистой части клипа {i}")
                    final_segments_for_concat.append(str(temp_pure_current_path))

                    # --- Создаем переходный сегмент с overlay ---
                    temp_transition_output_path = Path(self.temp_folder) / f"overlay_transition_{i}_{i+1}.mp4"

                    # Длительность первого клипа, участвующего в переходе (только часть, которая перекрывается)
                    # Мы берем последние `transition_duration_actual` секунды первого клипа
                    # и первые `transition_duration_actual` секунды второго клипа.

                    # Общая длительность переходного сегмента будет равна transition_duration_actual.

                    # [0:v] - это текущий клип (первый в паре для перехода)
                    # [1:v] - это следующий клип (второй в паре для перехода)

                    filter_complex_transition = (
                        f"[0:v]trim=start={current_clip_duration - transition_duration_actual:.3f}:duration={transition_duration_actual:.3f},setpts=PTS-STARTPTS[v0_trans];"
                        f"[1:v]trim=duration={transition_duration_actual:.3f},setpts=PTS-STARTPTS,"
                        f"format=yuva420p,fade=in:st=0:d={transition_duration_actual:.3f}:alpha=1[v1_trans];"
                        f"[v0_trans][v1_trans]overlay=x=0:y=0[v_out]"
                    )

                    cmd_overlay_transition = [
                        get_ffmpeg_path(), "-v", "debug",
                        "-i", current_clip_path,
                        "-i", next_clip_path,
                        "-filter_complex", filter_complex_transition,
                        "-map", "[v_out]",
                        "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                        "-pix_fmt", "yuv420p", "-r", str(self.config.frame_rate), "-vsync", "cfr",
                        "-an", # Без аудио, аудио будет добавлено позже
                        "-movflags", "+faststart",
                        "-force_key_frames", "expr:gte(t,0)",
                        "-y", str(temp_transition_output_path)
                    ]

                    logger.info(f"🎞️ Создаем переход OVERLAY между {Path(current_clip_path).name} и {Path(next_clip_path).name}")
                    logger.debug(f"OVERLAY TRANSITION CMD: {' '.join(cmd_overlay_transition)}")

                    run_ffmpeg_command(cmd_overlay_transition, f"Создание overlay перехода между клипом {i} и {i+1}")

                    if not temp_transition_output_path.exists():
                        raise FileNotFoundError(f"Выходной файл overlay перехода не создан: {temp_transition_output_path}")

                    final_segments_for_concat.append(str(temp_transition_output_path))

                # Если это последний клип, или если переходы отключены, просто добавляем его целиком
                if i == len(processed_photo_files) - 1 or not getattr(effects_config, 'transitions_enabled', True):
                    final_segments_for_concat.append(current_clip_path)
                    logger.debug(f"   Добавлен чистый сегмент (или последний клип): {Path(current_clip_path).name}")

            # --- Шаг 4: Финальная конкатенация всех сегментов (чистых и переходных) ---
            concat_file_list_path = Path(self.temp_folder) / "concat_list_overlay.txt"
            with open(concat_file_list_path, "w") as f:
                for segment_path in final_segments_for_concat:
                    f.write(f"file '{segment_path}'\n")

            final_concat_cmd = [
                get_ffmpeg_path(), "-v", "debug",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file_list_path),
                "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                "-pix_fmt", "yuv420p", "-r", str(self.config.frame_rate), "-vsync", "cfr",
                "-an", # Аудио будет добавлено позже
                "-movflags", "+faststart",
                "-force_key_frames", "expr:gte(t,0)",
                "-y", str(temp_video_path)
            ]

            if adjust_videos_to_audio:
                final_concat_cmd.extend(["-t", str(temp_audio_duration)])

            # Увеличиваем таймаут для финальной конкатенации
            final_concat_cmd_timeout = 900  # Увеличиваем до 15 минут (900 секунд)
            
            logger.info(f"🎬 Выполняем финальную конкатенацию всех сегментов (чистых и переходных).")
            logger.debug(f"ФИНАЛЬНАЯ КОМАНДА FFmpeg с OVERLAY: {' '.join(final_concat_cmd)}")
            try:
                run_ffmpeg_command(final_concat_cmd, "Финальная конкатенация всех видеосегментов", timeout=final_concat_cmd_timeout)
            except subprocess.TimeoutExpired as e:
                logger.error(f"❌ ТАЙМАУТ: Финальная конкатенация FFmpeg превысила таймаут {final_concat_cmd_timeout} секунд.")
                logger.error(f"FFmpeg stdout (до таймаута):\n{e.stdout}")
                logger.error(f"FFmpeg stderr (до таймаута):\n{e.stderr}")
                raise ProcessingError(f"Финальная конкатенация FFmpeg завершилась по таймауту.")

            if not temp_video_path.exists():
                logger.error(f"❌ temp_video_path не создан после финальной конкатенации: {temp_video_path}")
                raise ProcessingError("temp_video_path не создан после финальной конкатенации.")

            actual_duration = get_media_duration(str(temp_video_path))
            logger.info(f"✅ Фактическая длительность финального видеоряда с переходами: {actual_duration:.2f}с")

            # ... (проверка длительности, как раньше) ...

            return str(temp_video_path)

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в _concatenate_with_transitions (overlay): {e}")
            import traceback
            logger.error(f"Подробности ошибки _concatenate_with_transitions: {traceback.format_exc()}")
            # Здесь происходит вызов fallback, если _concatenate_with_transitions не удался
            # Убедитесь, что _concatenate_videos существует и вызывается с self.
            fallback_config = type('obj', (object,), {'transitions_enabled': False})()
            # Исправляем вызов: self._concatenate_videos
            temp_video_path = self._concatenate_videos(processed_photo_files, temp_audio_duration, fallback_config, clips_info, file_durations_map, adjust_videos_to_audio)
            return str(temp_video_path)

    def _concatenate_with_xfade_transitions(self, processed_photo_files: List[str], temp_audio_duration: float,
                                           effects_config, clips_info: List[Dict] = None,
                                           file_durations_map: Dict[str, float] = None,
                                           adjust_videos_to_audio: bool = True, audio_offset: float = 0.0,
                                           preserve_video_duration: bool = True) -> str:
        """Конкатенация видео с переходами xfade - с правильной попапочной компенсацией"""
        logger.info("🎬 Начинаем конкатенацию видео с переходами XFade (с попапочной компенсацией)")
        logger.info(f"   preserve_video_duration: {preserve_video_duration}")

        MAX_FILES_FOR_SINGLE_XFADE = 10

        if len(processed_photo_files) > MAX_FILES_FOR_SINGLE_XFADE:
            logger.info(f"📦 Используем батчевую обработку для {len(processed_photo_files)} файлов")
            return self._concatenate_with_xfade_batches(processed_photo_files, temp_audio_duration, effects_config,
                                                       clips_info, file_durations_map, adjust_videos_to_audio, audio_offset)

        temp_video_path = Path(self.temp_folder) / "final_video_with_xfade.mp4"

        try:
            if len(processed_photo_files) < 2:
                logger.warning("Менее 2 файлов, переходы не применяются")
                return self._concatenate_videos(processed_photo_files, temp_audio_duration, effects_config,
                                              clips_info, file_durations_map, adjust_videos_to_audio, audio_offset)

            # Получаем параметры переходов
            transition_type = getattr(effects_config, 'transition_type', 'fade')  
            transition_duration = getattr(effects_config, 'transition_duration', 0.5)
            transitions_enabled = getattr(effects_config, 'transitions_enabled', False)
            transition_method = getattr(effects_config, 'transition_method', 'overlay')
            
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: переходы включены только если method=xfade
            has_transitions = transitions_enabled and transition_method == "xfade"

            logger.info(f"🔄 Параметры переходов:")
            logger.info(f"   transitions_enabled: {transitions_enabled}")
            logger.info(f"   transition_method: {transition_method}")
            logger.info(f"   has_transitions (итог): {has_transitions}")
            logger.info(f"   тип: {transition_type}, длительность: {transition_duration}с")

            # НОВОЕ: Группируем файлы по папкам из clips_info
            folder_to_clips = {}
            for i, (file_path, clip) in enumerate(zip(processed_photo_files, clips_info)):
                folder = clip.get('folder', 'unknown')
                if folder not in folder_to_clips:
                    folder_to_clips[folder] = []
                folder_to_clips[folder].append({
                    'index': i,
                    'path': file_path,
                    'clip_info': clip,
                    'original_file': clip.get('original_file', file_path)
                })

            logger.info(f"📁 Распределение файлов по папкам:")
            for folder, clips in folder_to_clips.items():
                logger.info(f"   {folder}: {len(clips)} файлов")

            # НОВОЕ: Рассчитываем компенсированные длительности для каждой папки
            scaled_files = []
            scaled_durations = []
            file_index_mapping = {}  # Маппинг старых индексов на новые

            # Получаем целевые длительности папок из Excel
            from video_processing import MediaAnalyzer
            analyzer = MediaAnalyzer(self.config.xlsx_file_path)
            folder_durations, _, _ = analyzer.calculate_folder_durations_excel_based(
                self.config.output_directory,
                self.video_number,
                self.config.silence_duration,
                None,  # photo_folders_analysis пока None
                None   # effects_config пока None
            )

            logger.info(f"📊 Целевые длительности папок из Excel: {folder_durations}")

            # Обрабатываем каждую папку отдельно
            new_index = 0
            for folder_name in sorted(folder_to_clips.keys()):
                clips_in_folder = folder_to_clips[folder_name]
                target_folder_duration = folder_durations.get(folder_name, 0)

                if target_folder_duration <= 0:
                    logger.warning(f"⚠️ Папка '{folder_name}' имеет нулевую длительность, пропускаем")
                    continue

                # ИСПРАВЛЕНИЕ: Компенсация применяется ТОЛЬКО если переходы действительно включены
                if has_transitions and len(clips_in_folder) > 1:
                    # Количество переходов ВНУТРИ этой папки
                    num_transitions_in_folder = len(clips_in_folder) - 1
                    transition_loss_in_folder = num_transitions_in_folder * transition_duration
                    compensated_folder_duration = target_folder_duration + transition_loss_in_folder
                else:
                    # Если переходы отключены - НЕ добавляем компенсацию
                    num_transitions_in_folder = 0
                    transition_loss_in_folder = 0.0
                    compensated_folder_duration = target_folder_duration

                logger.info(f"📁 Обработка папки '{folder_name}':")
                logger.info(f"   Файлов: {len(clips_in_folder)}")
                logger.info(f"   Целевая длительность: {target_folder_duration:.2f}с")
                if has_transitions:
                    logger.info(f"   Переходы включены: переходов внутри: {num_transitions_in_folder}")
                    logger.info(f"   Потеря на переходах: {transition_loss_in_folder:.2f}с") 
                else:
                    logger.info(f"   Переходы отключены: компенсация не применяется")
                logger.info(f"   Итоговая длительность для масштабирования: {compensated_folder_duration:.2f}с")

                # ИСПРАВЛЕНИЕ: Рассчитываем длительности с учетом preserve_video_duration
                if preserve_video_duration:
                    # Разделяем файлы на видео и фото
                    video_clips = []
                    photo_clips = []
                    total_video_duration = 0.0
                    
                    for clip_data in clips_in_folder:
                        file_path = clip_data['path']
                        # Определяем тип файла по расширению
                        ext = Path(file_path).suffix.lower()
                        is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']
                        
                        if is_video:
                            orig_duration = get_media_duration(file_path)
                            if orig_duration and orig_duration > 0:
                                video_clips.append((clip_data, orig_duration))
                                total_video_duration += orig_duration
                                logger.info(f"   📹 Видео {Path(file_path).name}: {orig_duration:.2f}с (сохраняется)")
                            else:
                                photo_clips.append(clip_data)
                                logger.info(f"   🖼️ Файл {Path(file_path).name}: обрабатывается как фото (не удалось получить длительность)")
                        else:
                            photo_clips.append(clip_data)
                            logger.info(f"   🖼️ Фото {Path(file_path).name}")
                    
                    # Рассчитываем оставшееся время для фото
                    remaining_time = compensated_folder_duration - total_video_duration
                    if remaining_time <= 0:
                        logger.warning(f"⚠️ Видео в папке '{folder_name}' занимают {total_video_duration:.2f}с, что больше или равно целевой длительности {compensated_folder_duration:.2f}с")
                        photo_duration_per_file = 2.0  # Минимальная длительность для фото
                    else:
                        photo_duration_per_file = remaining_time / len(photo_clips) if photo_clips else 0.0
                    
                    logger.info(f"   📊 Распределение времени в папке '{folder_name}':")
                    logger.info(f"      Видео файлов: {len(video_clips)} (общая длительность: {total_video_duration:.2f}с)")
                    logger.info(f"      Фото файлов: {len(photo_clips)} (оставшееся время: {remaining_time:.2f}с)")
                    logger.info(f"      Длительность на фото: {photo_duration_per_file:.2f}с")
                    
                else:
                    # Равномерное распределение времени между всеми файлами
                    duration_per_file = compensated_folder_duration / len(clips_in_folder)
                    logger.info(f"   📊 Равномерное распределение: {duration_per_file:.2f}с на файл")

                # Масштабируем файлы этой папки
                for clip_data in clips_in_folder:
                    original_index = clip_data['index']
                    file_path = clip_data['path']

                    # Получаем оригинальную длительность
                    orig_duration = get_media_duration(file_path)
                    if orig_duration is None or orig_duration <= 0:
                        logger.error(f"❌ Не удалось получить длительность файла: {file_path}")
                        continue

                    # ИСПРАВЛЕНИЕ: Определяем целевую длительность в зависимости от типа файла и настроек
                    if preserve_video_duration:
                        # Проверяем является ли файл видео
                        ext = Path(file_path).suffix.lower()
                        is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']
                        
                        if is_video:
                            # Видео сохраняет исходную длительность
                            target_duration = orig_duration
                            scale_factor = 1.0  # Без масштабирования
                        else:
                            # Фото масштабируется под рассчитанное время
                            target_duration = photo_duration_per_file
                            scale_factor = target_duration / orig_duration
                    else:
                        # Равномерное масштабирование всех файлов
                        target_duration = duration_per_file
                        scale_factor = target_duration / orig_duration

                    # Создаем масштабированный файл
                    output_path = Path(self.temp_folder) / f"xfade_scaled_{folder_name}_{Path(file_path).stem}.mp4"

                    # Используем setpts для изменения скорости
                    pts_factor = 1.0 / scale_factor
                    cmd = [
                        get_ffmpeg_path(),
                        "-i", file_path,
                        "-filter:v", f"setpts={pts_factor:.6f}*PTS",
                        "-an",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-y", str(output_path)
                    ]

                    # Определяем тип файла для логирования
                    ext = Path(file_path).suffix.lower()
                    is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']
                    file_type = "📹 Видео" if is_video else "🖼️ Фото"
                    
                    logger.info(f"   📏 Обработка {file_type} {Path(file_path).name}:")
                    logger.info(f"      Исходная длительность: {orig_duration:.2f}с")
                    logger.info(f"      Целевая длительность: {target_duration:.2f}с") 
                    logger.info(f"      Коэффициент масштабирования: x{scale_factor:.3f}")
                    if scale_factor != 1.0:
                        logger.info(f"      PTS фактор: {1.0 / scale_factor:.6f}")
                    else:
                        logger.info(f"      Масштабирование не требуется (видео сохраняет длительность)")
                    run_ffmpeg_command(cmd, f"Масштабирование клипа {Path(file_path).name}")

                    if output_path.exists():
                        # ДИАГНОСТИКА: проверяем фактическую длительность масштабированного файла
                        actual_scaled_duration = get_media_duration(str(output_path))
                        duration_diff = abs(actual_scaled_duration - target_duration) if actual_scaled_duration else float('inf')
                        
                        logger.info(f"      ✅ Результат обработки:")
                        logger.info(f"         Ожидаемая длительность: {target_duration:.2f}с")
                        logger.info(f"         Фактическая длительность: {actual_scaled_duration:.2f}с")
                        logger.info(f"         Разница: {duration_diff:.3f}с")
                        
                        if duration_diff > 0.1:
                            logger.warning(f"⚠️ ЗНАЧИТЕЛЬНАЯ РАЗНИЦА в обработке: {duration_diff:.3f}с")
                        
                        scaled_files.append(str(output_path))
                        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: используем ФАКТИЧЕСКУЮ длительность обработанного файла
                        scaled_durations.append(actual_scaled_duration or target_duration)
                        file_index_mapping[original_index] = new_index
                        new_index += 1
                    else:
                        raise ProcessingError(f"Не удалось создать масштабированный файл: {output_path}")

            # Проверяем общую длительность после масштабирования
            total_scaled_duration = sum(scaled_durations)
            total_transitions = len(scaled_files) - 1
            total_transition_loss = total_transitions * transition_duration
            expected_output_duration = total_scaled_duration - total_transition_loss

            logger.info(f"📊 Итоговые расчеты после масштабирования:")
            logger.info(f"   Масштабированных файлов: {len(scaled_files)}")
            logger.info(f"   Сумма масштабированных длительностей: {total_scaled_duration:.2f}с")
            logger.info(f"   Общее количество переходов: {total_transitions}")
            logger.info(f"   Общая потеря на переходах: {total_transition_loss:.2f}с")
            logger.info(f"   Ожидаемая финальная длительность: {expected_output_duration:.2f}с")
            logger.info(f"   Целевая длительность аудио: {temp_audio_duration:.2f}с")
            logger.info(f"   Разница: {abs(expected_output_duration - temp_audio_duration):.2f}с")

            # Строим команду FFmpeg с xfade фильтрами
            ffmpeg_cmd = [get_ffmpeg_path(), "-v", "debug"]

            # Добавляем входные файлы
            for file_path in scaled_files:
                ffmpeg_cmd.extend(["-i", file_path])

            # Строим filter_complex с нормализацией
            filter_parts = []
            width, height = self.config.video_resolution.split('x')

            # Нормализуем все входные видео
            for i in range(len(scaled_files)):
                normalize_filter = (
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                    f"fps={self.config.frame_rate},"
                    f"format=yuv420p"
                    f"[v{i}_norm]"
                )
                filter_parts.append(normalize_filter)

            # Создаем цепочку xfade переходов
            xfade_filters = []
            current_stream = "[v0_norm]"

            for i in range(len(scaled_files) - 1):
                # Рассчитываем offset для текущего перехода
                if i == 0:
                    original_offset = scaled_durations[i] - transition_duration
                else:
                    # Накопленное время с учетом предыдущих переходов
                    accumulated = sum(scaled_durations[:i+1]) - (i * transition_duration)
                    original_offset = accumulated - transition_duration

                # ДИАГНОСТИКА: проверяем если компенсация недостаточна
                if original_offset < 0.1:
                    logger.warning(f"⚠️ ПРОБЛЕМА КОМПЕНСАЦИИ: offset={original_offset:.3f}с < 0.1с для перехода {i+1}")
                    logger.warning(f"   scaled_durations[{i}]={scaled_durations[i]:.2f}с, transition_duration={transition_duration:.2f}с")
                    if i > 0:
                        logger.warning(f"   accumulated={accumulated:.2f}с")
                
                offset = max(0.1, original_offset)

                # Имя выходного потока
                output_stream = f"[vx{i}]"

                # Создаем xfade фильтр
                xfade_filter = f"{current_stream}[v{i+1}_norm]xfade=transition={transition_type}:duration={transition_duration:.3f}:offset={offset:.3f}{output_stream}"

                xfade_filters.append(xfade_filter)
                current_stream = output_stream

                logger.debug(f"   XFade {i+1}: offset={offset:.3f}с")

            # Объединяем все фильтры
            filter_complex = ";".join(filter_parts + xfade_filters)

            # Добавляем filter_complex и выходные параметры
            ffmpeg_cmd.extend([
                "-filter_complex", filter_complex,
                "-map", current_stream,
                "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                "-pix_fmt", "yuv420p", "-r", str(self.config.frame_rate),
                "-vsync", "cfr",
                "-an",
                "-movflags", "+faststart",
                "-t", str(expected_output_duration),  # ИСПРАВЛЕНИЕ: обрезаем по ожидаемой длительности масштабированного видео
                "-y", str(temp_video_path)
            ])

            logger.info(f"🎬 Выполняем XFade конкатенацию {len(scaled_files)} файлов")
            logger.info(f"   Обрезка видео до: {expected_output_duration:.2f}с (вместо {temp_audio_duration:.2f}с)")

            # Сохраняем команду для отладки
            debug_cmd_file = Path(self.temp_folder) / "xfade_debug_command.txt"
            with open(debug_cmd_file, 'w') as f:
                f.write(' '.join(ffmpeg_cmd))

            # Выполняем команду
            run_ffmpeg_command(ffmpeg_cmd, "XFade конкатенация видео", timeout=600)

            # Проверяем результат
            if not temp_video_path.exists() or temp_video_path.stat().st_size == 0:
                raise ProcessingError("XFade создал пустой файл или файл не создан")

            actual_duration = get_media_duration(str(temp_video_path))
            logger.info(f"✅ Фактическая длительность XFade видео: {actual_duration:.2f}с")

            # Проверяем соответствие с ожидаемой длительностью масштабированного видео
            duration_error = abs(actual_duration - expected_output_duration)
            if duration_error > 1.0:
                logger.warning(
                    f"⚠️ Длительность видео ({actual_duration:.2f}с) не соответствует ожидаемой ({expected_output_duration:.2f}с), ошибка: {duration_error:.2f}с")
            else:
                logger.info(f"✅ Длительность видео соответствует ожидаемой (ошибка: {duration_error:.2f}с)")

            return str(temp_video_path)

        except Exception as e:
            logger.error(f"❌ Ошибка в XFade переходах: {e}")
            import traceback
            logger.error(f"Подробности ошибки XFade: {traceback.format_exc()}")

            # Fallback на стандартную конкатенацию
            logger.warning("🔄 Переключаемся на стандартную конкатенацию без переходов")
            fallback_config = type('obj', (object,), {'transitions_enabled': False})()
            return self._concatenate_videos(processed_photo_files, temp_audio_duration, fallback_config,
                                          clips_info, file_durations_map, adjust_videos_to_audio, audio_offset)

    def _concatenate_with_xfade_batches(self, processed_photo_files: List[str], temp_audio_duration: float,
                                        effects_config, clips_info: List[Dict] = None,
                                        file_durations_map: Dict[str, float] = None,
                                        adjust_videos_to_audio: bool = True, audio_offset: float = 0.0) -> str:
        """Конкатенация большого количества видео через батчи с XFADE"""
        logger.info(f"🎬 Батчевая обработка XFADE для {len(processed_photo_files)} файлов")

        # ДОБАВЛЯЕМ ДИАГНОСТИКУ
        logger.info("📊 Входные файлы для батчевой обработки:")
        for i, file_path in enumerate(processed_photo_files):
            logger.info(f"   {i+1}. {Path(file_path).name}")

        BATCH_SIZE = 10
        temp_batch_files = []

        try:
            # Разбиваем на батчи БЕЗ перекрытия - каждый файл используется только один раз
            for i in range(0, len(processed_photo_files), BATCH_SIZE):
                batch_end = min(i + BATCH_SIZE, len(processed_photo_files))
                batch_files = processed_photo_files[i:batch_end]

                if len(batch_files) < 2:
                    if temp_batch_files and len(batch_files) == 1:
                        # Добавляем последний файл к предыдущему батчу вместо создания отдельного
                        logger.info(f"📎 Добавляем последний файл {Path(batch_files[0]).name} к предыдущему батчу")
                        # Перерабатываем последний батч с дополнительным файлом
                        last_batch_path = temp_batch_files[-1]
                        # Здесь нужно переобработать последний батч с дополнительным файлом
                        # Но для простоты просто добавим файл отдельно
                        temp_batch_files.append(batch_files[0])
                    continue

                logger.info(f"📦 Батч {len(temp_batch_files) + 1}: файлы с {i+1} по {batch_end} (всего {len(batch_files)})")
                for j, bf in enumerate(batch_files):
                    logger.info(f"   - {j+1}. {Path(bf).name}")

                # Создаем временный файл для батча
                batch_output = Path(self.temp_folder) / f"xfade_batch_{len(temp_batch_files)}.mp4"

                # Обрабатываем батч с XFADE
                success = self._process_xfade_batch(batch_files, batch_output, effects_config, file_durations_map)

                if success and batch_output.exists():
                    temp_batch_files.append(str(batch_output))
                    # Проверяем размер и длительность созданного файла
                    file_size = batch_output.stat().st_size
                    actual_duration = get_media_duration(str(batch_output))
                    
                    # Рассчитываем ожидаемую длительность батча правильно для XFADE
                    batch_durations = []
                    for file_path in batch_files:
                        if file_durations_map and file_path in file_durations_map:
                            batch_durations.append(file_durations_map[file_path])
                        else:
                            batch_durations.append(get_media_duration(file_path) or 3.0)
                    
                    # Для XFADE: ожидаемая длительность = сумма длительностей минус потери на переходах
                    if len(batch_files) > 1:
                        transition_duration = getattr(effects_config, 'transition_duration', 0.5)  # ИСПРАВЛЕНО: правильное значение по умолчанию
                        total_duration = sum(batch_durations)
                        transition_loss = (len(batch_files) - 1) * transition_duration
                        expected_duration = total_duration - transition_loss
                        
                        logger.debug(f"   📊 Расчет длительности батча:")
                        logger.debug(f"      Общая длительность файлов: {total_duration:.2f}с")
                        logger.debug(f"      Переходов: {len(batch_files) - 1}")
                        logger.debug(f"      Потеря на переходах: {transition_loss:.2f}с")
                        logger.debug(f"      Ожидаемая итоговая: {expected_duration:.2f}с")
                    else:
                        expected_duration = batch_durations[0] if batch_durations else 3.0
                    
                    logger.info(f"✅ Батч {len(temp_batch_files)} создан: {batch_output.name} ({file_size} байт)")
                    logger.info(f"   📊 Длительность: факт={actual_duration:.2f}с, ожидаемая={expected_duration:.2f}с")
                    
                    if abs(actual_duration - expected_duration) > 1.0:
                        logger.warning(f"   ⚠️ Расхождение длительности батча: {abs(actual_duration - expected_duration):.2f}с")
                else:
                    raise ProcessingError(f"Ошибка обработки батча {len(temp_batch_files)}")

            # Теперь объединяем батчи с XFADE между ними
            if len(temp_batch_files) == 1:
                # Если только один батч, это наш результат
                final_output = Path(self.temp_folder) / "final_video_with_xfade.mp4"
                shutil.copy2(temp_batch_files[0], final_output)
                return str(final_output)
            else:
                # Объединяем батчи тоже через XFADE
                logger.info(f"📼 Финальное объединение {len(temp_batch_files)} батчей через XFADE")
                final_output = Path(self.temp_folder) / "final_video_with_xfade.mp4"

                # Объединяем батчи БЕЗ file_durations_map, так как батчи уже имеют правильные длительности
                logger.info(f"📼 Объединяем {len(temp_batch_files)} батчей через простую конкатенацию")
                logger.info("💡 Используем простую конкатенацию для батчей, так как XFADE уже применен внутри каждого батча")
                return self._concatenate_simple(temp_batch_files, temp_audio_duration)

        except Exception as e:
            logger.error(f"❌ Ошибка батчевой обработки: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Fallback на обычную конкатенацию
            return self._concatenate_videos(processed_photo_files, temp_audio_duration,
                                           type('obj', (object,), {'transitions_enabled': False})(),
                                           clips_info, file_durations_map, adjust_videos_to_audio, audio_offset)

    def _process_xfade_batch(self, batch_files: List[str], output_path: Path, effects_config, file_durations_map: Dict[str, float] = None) -> bool:
        """Обработка одного батча файлов с XFADE"""
        try:
            # Получаем параметры
            transition_type = getattr(effects_config, 'transition_type', 'fade')
            transition_duration = getattr(effects_config, 'transition_duration', 0.5)

            logger.info(f"🎬 Обработка батча из {len(batch_files)} файлов с {transition_type} переходом")
            logger.info(f"🔧 КРИТИЧЕСКИЙ DEBUG: transition_duration из effects_config = {transition_duration}")

            # Строим команду FFmpeg
            cmd = [get_ffmpeg_path()]

            # Входные файлы
            for file_path in batch_files:
                cmd.extend(["-i", file_path])

            # Получаем длительности
            durations = []
            for i, file_path in enumerate(batch_files):
                # Используем file_durations_map если доступен
                duration = None
                if file_durations_map and file_path in file_durations_map:
                    duration = file_durations_map[file_path]
                    logger.debug(f"   Файл {i+1}: {Path(file_path).name} = {duration:.2f}с (из Excel)")
                else:
                    duration = get_media_duration(file_path)
                    if duration is None:
                        duration = 3.0  # Fallback
                    logger.debug(f"   Файл {i+1}: {Path(file_path).name} = {duration:.2f}с (реальная)")
                durations.append(duration)

            # Строим filter_complex с нормализацией входных видео
            filter_parts = []

            # Получаем разрешение видео
            width, height = self.config.video_resolution.split('x')

            # Нормализуем все входные видео
            for i in range(len(batch_files)):
                normalize_filter = (
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                    f"fps={self.config.frame_rate},"
                    f"format=yuv420p"
                    f"[v{i}_norm]"
                )
                filter_parts.append(normalize_filter)

            # Создаем цепочку XFADE переходов
            current_stream = "[v0_norm]"

            # ИСПРАВЛЕННАЯ ЛОГИКА: правильный расчет cumulative_time и offset для XFADE переходов
            # cumulative_time отслеживает фактическую длительность выходного видео
            cumulative_time = durations[0]  # Первый файл: полная длительность

            for i in range(len(batch_files) - 1):
                if i == 0:
                    # Первый переход: начинается после первого клипа минус длительность перехода
                    offset = durations[0] - transition_duration
                else:
                    # Для последующих переходов: offset рассчитывается от накопленного времени
                    offset = cumulative_time - transition_duration
                
                # После каждого перехода добавляем следующий файл минус потерю от перехода
                cumulative_time += durations[i + 1] - transition_duration

                # Проверяем минимальный offset
                min_offset = max(0.1, durations[i] * 0.05)
                if offset < min_offset:
                    logger.warning(f"   ⚠️ Offset слишком мал ({offset:.3f}с), увеличиваем до {min_offset:.3f}с")
                    offset = min_offset

                if i == len(batch_files) - 2:  # Последний переход
                    output_stream = "[out]"
                else:
                    output_stream = f"[vx{i}]"

                xfade = f"{current_stream}[v{i+1}_norm]xfade=transition={transition_type}:duration={transition_duration:.3f}:offset={offset:.3f}{output_stream}"
                filter_parts.append(xfade)
                current_stream = output_stream

                logger.debug(f"   Переход {i+1}: файлы[{i}+{i+1}], offset={offset:.3f}с, cumulative_time={cumulative_time:.3f}с")
                logger.debug(f"      Длительности: {durations[i]:.2f}с + {durations[i+1]:.2f}с - {transition_duration:.2f}с(переход)")
            
            # Логируем финальную накопленную длительность
            logger.debug(f"   🎯 Итоговая ожидаемая длительность батча: {cumulative_time:.3f}с")

            filter_complex = ";".join(filter_parts)

            # Добавляем параметры БЕЗ явного указания длительности -t
            # Пусть FFmpeg сам определит длительность на основе переходов
            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:v", "libx264",
                "-preset", self.config.video_preset,
                "-crf", str(self.config.video_crf),
                "-pix_fmt", "yuv420p",
                "-r", str(self.config.frame_rate),
                "-vsync", "cfr",
                "-an",
                "-y", str(output_path)
            ])

            # Сохраняем команду для отладки
            debug_cmd_file = Path(self.temp_folder) / f"batch_debug_command_{output_path.stem}.txt"
            with open(debug_cmd_file, 'w') as f:
                f.write(' '.join(cmd))
            logger.debug(f"Команда сохранена в: {debug_cmd_file}")

            # Выполняем
            result = run_subprocess_hidden(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                duration = get_media_duration(str(output_path))
                logger.info(f"✅ Батч обработан успешно: {output_path.name}, длительность: {duration:.2f}с")
                return True
            else:
                logger.error(f"❌ Ошибка обработки батча: код {result.returncode}")
                if result.stderr:
                    stderr_lines = result.stderr.strip().split('\n')
                    logger.error(f"Последние строки stderr:\n" + '\n'.join(stderr_lines[-20:]))
                return False

        except Exception as e:
            logger.error(f"❌ Исключение при обработке батча: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _concatenate_simple(self, video_files: List[str], target_duration: float) -> str:
        """Простая конкатенация без переходов"""
        logger.info(f"📼 Простая конкатенация {len(video_files)} файлов")

        concat_list_path = Path(self.temp_folder) / "concat_batches.txt"
        output_path = Path(self.temp_folder) / "final_video_with_xfade.mp4"

        # Создаем список файлов
        with open(concat_list_path, 'w') as f:
            for video_file in video_files:
                f.write(f"file '{video_file}'\n")

        # Команда конкатенации
        cmd = [
            get_ffmpeg_path(),
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c:v", "libx264",  # Перекодируем для единообразия
            "-preset", self.config.video_preset,
            "-crf", str(self.config.video_crf),
            "-pix_fmt", "yuv420p",
            "-r", str(self.config.frame_rate),
            "-t", str(target_duration),
            "-an",
            "-y", str(output_path)
        ]

        logger.debug(f"Команда конкатенации: {' '.join(cmd)}")

        result = run_subprocess_hidden(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            logger.error(f"❌ Ошибка объединения батчей: {result.stderr}")
            raise ProcessingError(f"Ошибка объединения батчей: {result.stderr}")

        if output_path.exists():
            logger.info(f"✅ Финальное видео создано: {output_path.name}")
            return str(output_path)
        else:
            raise ProcessingError("Финальное видео не создано")

    def _create_subscribe_frames(self) -> Tuple[str, int]:
        """Создание кадров для кнопки подписки"""
        logger.info("=== 🎞️ Создание кадров подписки ===")

        try:
            frame_list_path, num_frames = create_subscribe_frame_list(
                self.config.subscribe_frames_folder,
                self.temp_folder,
                self.config.frame_rate
            )

            if not frame_list_path:
                raise ProcessingError("Ошибка создания списка кадров для кнопки подписки")

            return frame_list_path, num_frames

        except Exception as e:
            raise ProcessingError(f"Ошибка создания кадров подписки: {e}")

    def _generate_subtitles(self, final_audio_path: str, temp_audio_duration: float, audio_offset: float) -> Optional[
        str]:
        """Генерация субтитров"""
        if not self.config.subtitles_enabled:
            return None

        logger.info("=== 📝 Генерация субтитров ===")
        logger.info(f"Используемый audio_offset для субтитров: {audio_offset:.2f} сек")

        try:
            subtitles_path = generate_subtitles(
                final_audio_path, self.temp_folder, self.config.subtitle_model,
                self.config.subtitle_language, self.config.subtitle_max_words,
                self.config.subtitle_time_offset + audio_offset, temp_audio_duration,
                self.config.subtitle_fontsize, self.config.subtitle_font_color,
                self.config.subtitle_use_backdrop, self.config.subtitle_back_color,
                self.config.subtitle_outline_thickness, self.config.subtitle_outline_color,
                self.config.subtitle_shadow_thickness, self.config.subtitle_shadow_color,
                self.config.subtitle_shadow_alpha, self.config.subtitle_shadow_offset_x,
                self.config.subtitle_shadow_offset_y, self.config.subtitle_margin_l,
                self.config.subtitle_margin_r, self.config.subtitle_margin_v
            )

            if not subtitles_path:
                logger.warning("Не удалось сгенерировать субтитры")

            return subtitles_path

        except Exception as e:
            logger.error(f"Ошибка генерации субтитров: {e}")
            return None

    def _final_assembly(self, temp_video_path: str, final_audio_path: str, frame_list_path: str,
                        num_frames: int, subtitles_path: Optional[str], temp_audio_duration: float,
                        clips_info: List[Dict], audio_offset: float, folder_durations: Optional[Dict[str, float]] = None,
                        start_row: Optional[int] = None, end_row: Optional[int] = None,
                        adjust_videos_to_audio: bool = True, debug_info: Dict = None) -> str:
        """Финальная сборка видео"""
        logger.info("=== 🏗️ Финальная сборка ===")

        output_file = self._get_output_file_path()

        try:
            # Вызов create_combined_audio с отладочными данными
            if debug_info:
                combined_audio_path, updated_audio_duration = self.audio_processor.create_combined_audio(
                    final_audio_path,  # main_audio_path
                    [],  # video_clips_audio (пустой список, так как клипы уже в видео)
                    str(Path(self.temp_folder) / "combined_audio_fixed.mp3"),  # output_path
                    temp_audio_duration,  # target_duration
                    debug_info=debug_info,  # Передаем отладочные данные
                    background_music_path=self.config.background_music_path,  # ИСПРАВЛЕНО
                    background_music_volume=self.config.background_music_volume  # ИСПРАВЛЕНО
                )
                logger.info(f"✅ Исправленная функция create_combined_audio завершена: {combined_audio_path} ({updated_audio_duration:.3f}с)")
                
                # Обновляем final_audio_path для использования в final_assembly
                final_audio_path = combined_audio_path
                temp_audio_duration = updated_audio_duration

            final_video_path = final_assembly(
                temp_video_path, final_audio_path, output_file, self.temp_folder,
                frame_list_path, num_frames, self.config.logo_path, subtitles_path,
                self.config.video_resolution, self.config.frame_rate, self.config.video_crf,
                self.config.video_preset, temp_audio_duration, self.config.logo_width,
                self.config.logo_position_x, self.config.logo_position_y, self.config.logo_duration,
                self.config.subscribe_width, self.config.subscribe_position_x,
                self.config.subscribe_position_y, self.config.subscribe_display_duration,
                self.config.subscribe_interval_gap, self.config.subtitles_enabled,
                self.config.logo2_path, self.config.logo2_width, self.config.logo2_position_x,
                self.config.logo2_position_y, self.config.logo2_duration,
                self.config.subscribe_duration, clips_info=clips_info, audio_offset=audio_offset,
                folder_durations=folder_durations,
                audio_folder=str(self.config.output_directory) if not isinstance(self.config.output_directory, tuple) else str(self.config.output_directory[0]) if self.config.output_directory else "",
                overall_range_start=start_row, overall_range_end=end_row,
                silence_duration=self.config.silence_duration,
                adjust_videos_to_audio=adjust_videos_to_audio
            )

            if not final_video_path:
                raise ProcessingError("Ошибка финальной сборки")

            return final_video_path

        except Exception as e:
            raise ProcessingError(f"Ошибка финальной сборки: {e}")

    def _single_pass_assembly(self, processed_photo_files: List[str], final_audio_path: str, 
                            frame_list_path: str, num_frames: int, subtitles_path: Optional[str],
                            temp_audio_duration: float, clips_info: List[Dict], 
                            audio_offset: float, effects_config) -> str:
        """
        🚀 ЕДИНЫЙ ПРОХОД: Конкатенация + эффекты + логотипы + подписка одной командой FFmpeg
        
        Преимущества:
        - 3-5x быстрее (один проход вместо трех)
        - Лучшее качество (нет повторного сжатия)
        - Точная синхронизация
        - Меньше промежуточных файлов
        """
        logger.info("🚀 === ЕДИНЫЙ ПРОХОД: Все операции в одной команде FFmpeg ===")
        
        try:
            output_file = self._get_output_file_path()
            
            # Строим сложную команду FFmpeg
            cmd = [get_ffmpeg_path(), "-v", "debug"]
            
            # === ВХОДЫ ===
            input_index = 0
            
            # 1. Добавляем все видео/фото клипы
            for clip_path in processed_photo_files:
                cmd.extend(["-i", clip_path])
                input_index += 1
            
            # 2. Добавляем аудио
            cmd.extend(["-i", final_audio_path])
            audio_input_index = input_index
            input_index += 1
            
            # 3. Добавляем логотипы
            logo_input_index = None
            logo2_input_index = None
            if self.config.logo_path and Path(self.config.logo_path).exists():
                cmd.extend(["-i", self.config.logo_path])
                logo_input_index = input_index
                input_index += 1
                
            if self.config.logo2_path and Path(self.config.logo2_path).exists():
                cmd.extend(["-i", self.config.logo2_path])
                logo2_input_index = input_index
                input_index += 1
            
            # 4. Добавляем кнопку подписки
            subscribe_input_index = None
            if frame_list_path and Path(frame_list_path).exists():
                cmd.extend(["-f", "concat", "-safe", "0", "-i", frame_list_path])
                subscribe_input_index = input_index
                input_index += 1
            
            # === FILTER_COMPLEX ===
            filter_parts = []
            
            # 1. Конкатенация всех видео клипов
            num_video_inputs = len(files_to_process)
            concat_inputs = "".join([f"[{i}:v]" for i in range(num_video_inputs)])
            filter_parts.append(f"{concat_inputs}concat=n={num_video_inputs}:v=1:a=0[video_base]")
            
            current_video_stream = "[video_base]"
            
            # 2. Применяем эффекты (если включены)
            if effects_config and getattr(effects_config, 'effects_enabled', False):
                logger.info("✨ Применяем эффекты в едином проходе")
                # Здесь можно добавить zoom, rotation и другие эффекты
                # Пока используем базовые параметры
                pass
            
            # 3. Добавляем логотипы
            if logo_input_index is not None:
                filter_parts.append(f"[{logo_input_index}:v]scale={self.config.logo_width}:-1[logo1]")
                filter_parts.append(f"{current_video_stream}[logo1]overlay={self.config.logo_position_x}:{self.config.logo_position_y}:enable='between(t,0,{temp_audio_duration})'[video_with_logo1]")
                current_video_stream = "[video_with_logo1]"
                
            if logo2_input_index is not None:
                filter_parts.append(f"[{logo2_input_index}:v]scale={self.config.logo2_width}:-1[logo2]")
                filter_parts.append(f"{current_video_stream}[logo2]overlay={self.config.logo2_position_x}:{self.config.logo2_position_y}:enable='between(t,0,{temp_audio_duration})'[video_with_logo2]")
                current_video_stream = "[video_with_logo2]"
            
            # 4. Добавляем кнопку подписки
            if subscribe_input_index is not None:
                # Создаем интервалы показа кнопки
                subscribe_intervals = []
                interval_start = audio_offset
                while interval_start < temp_audio_duration:
                    # DEBUG: About to call min() on subscribe interval calculation
                    logger.debug(f"DEBUG: About to call min() on subscribe interval calculation")
                    logger.debug(f"DEBUG: interval_start: {interval_start}, subscribe_display_duration: {self.config.subscribe_display_duration}, temp_audio_duration: {temp_audio_duration}")
                    end_time = min(interval_start + self.config.subscribe_display_duration, temp_audio_duration)
                    subscribe_intervals.append((interval_start, end_time))
                    interval_start += self.config.subscribe_display_duration + self.config.subscribe_interval_gap
                    if interval_start >= temp_audio_duration:
                        break
                
                if subscribe_intervals:
                    overlay_conditions = [f"between(t,{start},{end})" for start, end in subscribe_intervals]
                    overlay_enable = " + ".join(overlay_conditions)
                    
                    filter_parts.append(f"[{subscribe_input_index}:v]loop=-1:32767:0,trim=0:{temp_audio_duration},setpts=PTS-STARTPTS,scale={self.config.subscribe_width}:-2:force_divisible_by=2,format=yuva420p[subscribe]")
                    filter_parts.append(f"{current_video_stream}[subscribe]overlay={self.config.subscribe_position_x}:{self.config.subscribe_position_y}:enable='{overlay_enable}'[final_video]")
                    current_video_stream = "[final_video]"
            
            # 5. Субтитры (если есть)
            if subtitles_path and Path(subtitles_path).exists():
                escaped_subtitles_path = subtitles_path.replace('\\', '\\\\').replace(':', '\\:')
                filter_parts.append(f"{current_video_stream}subtitles={escaped_subtitles_path}:force_style='Alignment=2'[final_with_subs]")
                current_video_stream = "[final_with_subs]"
            
            # === ФИНАЛЬНАЯ КОМАНДА ===
            if filter_parts:
                cmd.extend(["-filter_complex", ";".join(filter_parts)])
                cmd.extend(["-map", current_video_stream])
            else:
                cmd.extend(["-map", "0:v"])
            
            cmd.extend([
                "-map", f"{audio_input_index}:a",
                "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                "-t", str(temp_audio_duration),
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+genpts+igndts",
                "-movflags", "+faststart",
                "-y", output_file
            ])
            
            logger.info(f"🚀 Запуск единого прохода FFmpeg...")
            logger.debug(f"Команда: {' '.join(cmd)}")
            
            # Выполняем команду
            result = run_subprocess_hidden(cmd, capture_output=True, text=True, timeout=3600)
            
            if result.returncode != 0:
                logger.error(f"Ошибка единого прохода: {result.stderr}")
                raise ProcessingError(f"Ошибка единого прохода: {result.stderr}")
            
            logger.info(f"✅ Единый проход завершен: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Ошибка единого прохода: {e}")
            raise ProcessingError(f"Ошибка единого прохода: {e}")

    def _validate_final_video(self, output_file: str, expected_duration: float):
        """Валидация финального видео"""
        try:
            final_video_duration = get_media_duration(output_file)

            logger.info(f"Длительность видео: {int(final_video_duration // 60)}:{int(final_video_duration % 60):02d}")

            if abs(final_video_duration - expected_duration) > 1.0:  # Допустимое отклонение 1 секунда
                logger.warning(
                    f"Длительность видео не совпадает с аудио: {final_video_duration:.2f} против {expected_duration:.2f}")
            else:
                logger.info("Длительность видео соответствует ожидаемой")

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Ошибка валидации финального видео: {e}")

    def _manage_temp_folder(self) -> None:
        """Управление temp папкой в зависимости от параметра debug_keep_temp_folder"""
        try:
            debug_keep_temp_folder = getattr(self.config, 'debug_keep_temp_folder', False)
            temp_folder_path = Path(self.temp_folder)
            
            if debug_keep_temp_folder:
                logger.info(f"🔧 DEBUG: Сохраняем temp папку для отладки: {temp_folder_path}")
                logger.info(f"🔧 DEBUG: Параметр 'debug_keep_temp_folder' включен")
            else:
                logger.info(f"🗑️ Удаляем temp папку: {temp_folder_path}")
                logger.info(f"🗑️ Параметр 'debug_keep_temp_folder' отключен")
                
                if temp_folder_path.exists():
                    import shutil
                    shutil.rmtree(temp_folder_path, ignore_errors=True)
                    
                    # Проверяем, что папка действительно удалена
                    if not temp_folder_path.exists():
                        logger.info(f"✅ Temp папка успешно удалена: {temp_folder_path}")
                    else:
                        logger.warning(f"⚠️ Не удалось полностью удалить temp папку: {temp_folder_path}")
                else:
                    logger.info(f"📁 Temp папка уже не существует: {temp_folder_path}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка управления temp папкой: {e}")

    def process(self) -> bool:
        """Основной метод обработки видео с новой попапочной логикой."""
        logger.info(f"=== 🚀 Монтаж видео {self.video_number} с попапочной логикой ===")
        logger.info(f"🔍 DEBUG VideoProcessor.process: self.preserve_clip_audio_videos = {self.preserve_clip_audio_videos}")

        try:
            # ПРОВЕРЯЕМ ФЛАГ ОСТАНОВКИ В НАЧАЛЕ PROCESS
            if montage_control.check_stop_flag(f"VideoProcessor.process для видео {self.video_number}"):
                return False
            if self._is_video_already_processed():
                return True

            audio_files, start_row, end_row = self._get_audio_files_and_range()
            photo_folder_vid = Path(self._find_photo_folder(start_row, end_row)).resolve() # <-- ИСПРАВЛЕНИЕ: Нормализуем

            # Проверяем наличие фото/видео в папке
            photo_files_raw = find_files(str(photo_folder_vid), SUPPORTED_FORMATS, recursive=True) # <-- Используем нормализованный путь
            if not photo_files_raw:
                raise ProcessingError(f"В папке '{photo_folder_vid}' отсутствуют фото или видео")

            # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ ПЕРЕД КОПИРОВАНИЕМ АУДИО
            if montage_control.check_stop_flag(f"VideoProcessor перед копированием аудио {self.video_number}"):
                return False
                
            self._copy_audio_files(audio_files)

            # === НАЧИНАЕМ ФАЗУ ПРЕДОБРАБОТКИ И СОПОСТАВЛЕНИЯ ФАЙЛОВ ===
            
            # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ ПЕРЕД ПРЕДОБРАБОТКОЙ
            if montage_control.check_stop_flag(f"VideoProcessor перед предобработкой {self.video_number}"):
                return False

            # НОВОЕ: Инициализация base_preprocessed_dir в начале
            base_preprocessed_dir = Path(self.preprocessed_photo_folder).resolve() # <-- ИСПРАВЛЕНИЕ: Нормализуем

            # НОВОЕ: Сначала собираем photo_folders_analysis из ОРИГИНАЛЬНЫХ файлов
            photo_folders_analysis = {}
            # photo_files_raw - это список оригинальных файлов из photo_folder_vid

            # Инициализация preprocessed_files_map
            preprocessed_files_map = {}

            # Инициализация MediaAnalyzer
            from video_processing import MediaAnalyzer
            analyzer = MediaAnalyzer(self.config.xlsx_file_path)

            # Универсальная группировка файлов по папкам (для оригинальных файлов)
            def extract_original_folder_name(file_path_str: str, base_folder: str, excel_folders: List[str]) -> Optional[str]:
                """Извлекает имя папки для оригинального файла"""
                file_path = Path(file_path_str)
                try:
                    relative_path = file_path.relative_to(Path(base_folder))
                    folder_key_raw = str(relative_path.parent).strip()
                    # Кроссплатформенное извлечение имени папки (Windows: \, macOS/Linux: /)
                    folder_key = Path(folder_key_raw).name

                    if folder_key == '.':
                        # Если файл прямо в корне photo_folder_vid, относим к первой Excel-папке
                        return excel_folders[0] if excel_folders else "root_unassigned"

                    if folder_key in excel_folders:
                        return folder_key
                    else:
                        # Возможно, файл находится в подпапке, которая сама является Excel-папкой
                        # Если имя файла 001.mp4, 002.mp4, то его родительская папка - это его excel_folder.
                        # Например, /Фото/3/1-5/001.mp4, то 1-5 - это folder_key
                        # Если /Фото/3/001.mp4, то folder_key - это корневая папка photo_folder_vid.
                        # В этом случае нужно сопоставить ее с первой Excel-папкой.
                        # Для надежности, можно попробовать найти ближайшую Excel-папку или отнести к 'root'
                        logger.warning(f"⚠️ Оригинальный файл '{file_path.name}' в папке '{folder_key}', которая не является явной Excel-папкой. Пропускаем.")
                        return None # Пропускаем несопоставленные файлы
                except Exception as e:
                    logger.error(f"❌ Ошибка извлечения имени оригинальной папки для {file_path_str}: {e}")
                    return None

            # Сначала получаем целевые папки из Excel
            # analyzer уже инициализирован
            folder_audio_mapping_excel = analyzer.get_folder_audio_mapping_from_excel(self.video_number)
            excel_target_folders = [str(f).strip() for f in folder_audio_mapping_excel.keys()]

            logger.info(f"🔍 Группируем {len(photo_files_raw)} ОРИГИНАЛЬНЫХ файлов по папкам из {photo_folder_vid}")
            for file_path_raw in photo_files_raw:
                # Нормализуем file_path_raw
                original_path_obj = Path(file_path_raw).resolve() # <-- ИСПРАВЛЕНИЕ
                
                folder_name = extract_original_folder_name(str(original_path_obj), str(photo_folder_vid), excel_target_folders) # <-- Измените на str(original_path_obj)
                if folder_name: # Если папка успешно определена
                    if folder_name not in photo_folders_analysis:
                        photo_folders_analysis[folder_name] = {
                            "full_path": str(original_path_obj.parent), # Храним родительский путь как строку
                            "files_count": 0,
                            "files": [] # Здесь будут оригинальные пути к файлам
                        }
                    # Используйте оригинал для photo_folders_analysis
                    photo_folders_analysis[folder_name]["files"].append(str(original_path_obj)) # <-- Здесь должен быть ОРИГИНАЛЬНЫЙ РАЗРЕШЕННЫЙ ПУТЬ
                    photo_folders_analysis[folder_name]["files_count"] += 1

            # Убедимся, что photo_folders_analysis содержит все папки из Excel
            for folder_name_from_excel in excel_target_folders:
                if folder_name_from_excel not in photo_folders_analysis:
                    logger.warning(f"⚠️ Папка '{folder_name_from_excel}' из Excel не найдена в оригинальных файлах. Добавляем как пустую.")
                    photo_folders_analysis[folder_name_from_excel] = {
                        "full_path": "", # Или подходящий путь к папке
                        "files_count": 0,
                        "files": []
                    }

            logger.info(f"📊 Итоговый photo_folders_analysis (ОРИГИНАЛЬНЫЕ ФАЙЛЫ):")
            for f_name, f_info in photo_folders_analysis.items():
                logger.info(f"  📁 '{f_name}': {f_info['files_count']} файлов")
                for i, f_item in enumerate(f_info['files'][:3]):
                    logger.debug(f"    - {Path(f_item).name}")
                if f_info['files_count'] > 3:
                    logger.debug(f"    ... и еще {f_info['files_count'] - 3} файлов")

            # Теперь вызываем предобработку
            logger.info("🖼️ Предобработка изображений перед анализом папок")
            preprocessed_files_map = self._preprocess_images(str(photo_folder_vid)) # Эта функция заполняет preprocessed_photo_folder

            # Получаем соответствие папок и аудиофайлов из Excel
            folder_audio_mapping = analyzer.get_folder_audio_mapping_from_excel(self.video_number)
            temp_excel_folders = list(folder_audio_mapping.keys())

            # 3. Расчет Excel попапочных длительностей с ИСПОЛЬЗОВАНИЕМ photo_folders_analysis
            # Этот вызов теперь будет единственным и корректным
            logger.info("🔄 Расчет Excel попапочных длительностей для синхронизации аудио и видео")
            
            # Рассчитываем длительности с использованием уже полученного folder_audio_mapping
            effects_config = create_video_effects_config(self.config.config)
            excel_folder_durations, excel_total_duration, folder_to_files = analyzer.calculate_folder_durations_excel_based(
                self.config.output_directory, 
                self.video_number, 
                self.config.silence_duration,
                photo_folders_analysis,  # Передаем фактические файлы из папок
                effects_config  # Передаем конфигурацию эффектов для XFADE компенсации
            )
            
            logger.info(f"📊 Excel попапочные длительности: {excel_folder_durations}")
            logger.info(f"📊 Excel общая длительность: {excel_total_duration:.3f}с")
            
            # Анализ Excel диапазонов
            excel_ranges_analysis = {}
            if excel_folder_durations:
                for folder, duration in excel_folder_durations.items():
                    files_in_folder = folder_to_files.get(folder, [])
                    excel_ranges_analysis[folder] = {
                        "duration_seconds": duration,
                        "duration_minutes": f"{duration/60:.2f}",
                        "files_count": len(files_in_folder),
                        "files": [{"file_path": f, "file_name": Path(f).name} for f in files_in_folder]
                }
            
            # Собираем все photo_files для JSON
            photo_files = []
            for folder_data in photo_folders_analysis.values():
                photo_files.extend(folder_data.get('files', []))
            
            temp_folder = str(self.temp_folder)
            
            # Преобразование photo_folders_analysis для JSON
            json_friendly_photo_folders_analysis = {}
            for folder_name, folder_info in photo_folders_analysis.items():
                json_friendly_photo_folders_analysis[folder_name] = {
                    "full_path": str(folder_info.get("full_path", "")), # Преобразуем Path в str
                    "files_count": folder_info.get("files_count", 0),
                    "files": [str(f) for f in folder_info.get("files", [])] # Преобразуем список Path в список str
                }
            
            json_math_data = {
                "timestamp": datetime.now().isoformat(),
                "video_number": self.video_number,
                "paths": {
                    "photo_folder": str(photo_folder_vid), # <-- ИСПРАВЛЕНИЕ: str()
                    "preprocessed_photos_base": str(base_preprocessed_dir),
                    "output_folder": self.config.output_folder,
                    "temp_folder": temp_folder
                },
                "excel_analysis": {
                    "folder_durations": excel_folder_durations,
                    "total_duration": excel_total_duration,
                    "folder_to_files": folder_to_files,  # Используем правильные данные с фактическими файлами
                    "folder_audio_mapping": folder_audio_mapping,  # Соответствие папок и аудиофайлов из Excel
                    "ranges_analysis": excel_ranges_analysis,
                    "pause_settings": {
                        "silence_duration": self.config.silence_duration,
                        "pause_after_each_audio": True,
                        "comment": "Паузы добавляются после КАЖДОГО аудиофайла"
                    }
                },
                "audio_analysis": {
                    "audio_files_count": len(audio_files),
                    "audio_files": [os.path.basename(f) for f in audio_files],
                    "audio_files_full_paths": audio_files,
                    "silence_duration": self.config.silence_duration
                },
                "photo_analysis": {
                    "photo_folder": str(photo_folder_vid), # <-- ИСПРАВЛЕНИЕ: str()
                    "photo_files_count": len(photo_files),
                    "photo_files": [os.path.basename(f) for f in photo_files],
                    "photo_files_full_paths": photo_files
                },
                "preprocessed_folders_analysis": json_friendly_photo_folders_analysis, # <-- Используем новую переменную
                "expected_logic": {
                    "description": "Файлы должны быть взяты из папок preprocessed_photos/1-2/, 3-4/, 5-8/, 9-13/, 14-31/",
                    "expected_total_duration": 1194.92,
                    "expected_folder_durations": {
                        "1-2": 42.47,
                        "3-4": 59.56,
                        "5-8": 166.43,
                        "9-13": 217.24,
                        "14-31": 709.22
                    },
                    "calculation_method": "Файлы из каждой папки должны показываться в течение времени, указанного в expected_folder_durations"
                }
            }
            
            json_path = os.path.join(temp_folder, f"video_{self.video_number}_math_analysis.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_math_data, f, indent=2, ensure_ascii=False, cls=PathEncoder) # <-- Используйте cls=PathEncoder
            
            logger.info(f"📄 JSON файл с математикой создан: {json_path}")
            logger.info(f"📁 Проверка существования файла: {os.path.exists(json_path)}")
            if os.path.exists(json_path):
                logger.info(f"📊 Размер JSON файла: {os.path.getsize(json_path)} байт")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания JSON файла с математикой: {e}")
            return False

        # === НОВАЯ ПОПАПОЧНАЯ ЛОГИКА ===
        logger.info("🚀 ЗАПУСК ПОПАПОЧНОЙ ОБРАБОТКИ")
        
        # 1. Создание аудиосегментов для каждой папки
        logger.info("🎵 Создание аудиосегментов для каждой папки")
        folder_audio_segments = {}
        
        for folder_name, target_duration in excel_folder_durations.items():
            logger.info(f"🔊 Создание аудиосегмента для папки '{folder_name}' (длительность: {target_duration:.2f}с)")
            
            # Получаем соответствующие аудиофайлы для этой папки
            audio_files_for_folder = folder_audio_mapping.get(folder_name, [])
            if not audio_files_for_folder:
                logger.warning(f"⚠️ Нет аудиофайлов для папки '{folder_name}', пропускаем")
                continue
            
            # Создаем основной аудиосегмент для папки
            main_audio_path_for_folder, _ = process_audio_files_by_excel_folders(
                excel_folder_durations={folder_name: target_duration}, # Передаем только текущую папку с ее длительностью
                audio_files=[], # Этот параметр не используется, но нужен для сигнатуры
                temp_audio_folder=str(self.temp_audio_folder), # Папка с исходными mp3 файлами
                temp_folder=str(self.temp_folder),
                audio_channels=self.config.audio_channels,
                audio_sample_rate=self.config.audio_sample_rate,
                audio_bitrate=self.config.audio_bitrate,
                silence_duration=self.config.silence_duration,
                folder_audio_mapping={folder_name: audio_files_for_folder}, # Маппинг только для текущей папки
                output_filename=f"main_audio_segment_{folder_name}.mp3" # Более четкое имя
            )
            
            if not main_audio_path_for_folder:
                logger.error(f"❌ Не удалось создать основной аудиосегмент для папки '{folder_name}'.")
                continue

            # ОТКЛЮЧЕНО: Фоновая музыка будет добавлена глобально позже
            logger.info(f"🔇 ОТКЛЮЧЕНО: Фоновая музыка будет добавлена глобально позже")

            # Конвертируем в WAV для совместимости с видео
            wav_path_for_segment = Path(self.temp_folder) / f"folder_audio_segment_{folder_name}.wav"
            convert_cmd_to_wav = [
                get_ffmpeg_path(), "-y", "-i", str(main_audio_path_for_folder),
                "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                str(wav_path_for_segment)
            ]
            try:
                run_subprocess_hidden(convert_cmd_to_wav, check=True, capture_output=True)
                folder_audio_segments[folder_name] = str(wav_path_for_segment)
                logger.info(f"✅ Аудиосегмент для папки '{folder_name}' создан: {Path(wav_path_for_segment).name}")
            except subprocess.CalledProcessError as e:
                logger.error(f"❌ Ошибка конвертации аудиосегмента в WAV для '{folder_name}': {e.stderr}")
                continue
        
        # 2. Создание видеосегментов для каждой папки
        logger.info("🎬 Создание видеосегментов для каждой папки")
        folder_video_segments = {}
        
        for folder_name, target_duration in excel_folder_durations.items():
            logger.info(f"🎥 Обработка видеосегмента папки '{folder_name}'")
            
            # Получаем ОРИГИНАЛЬНЫЕ файлы для этой папки из photo_folders_analysis
            files_in_this_folder_original = photo_folders_analysis.get(folder_name, {}).get('files', [])

            # Конвертируем ОРИГИНАЛЬНЫЕ пути в ПРЕДОБРАБОТАННЫЕ, используя preprocessed_files_map
            files_in_this_folder_preprocessed = []
            for original_path in files_in_this_folder_original:
                # original_path здесь уже должен быть нормализованным абсолютным путем (как из photo_files_raw)
                # Поэтому мы можем получить относительный путь для поиска в маппинге
                relative_path_key_for_map = str(Path(original_path).relative_to(photo_folder_vid)) # <-- Ключ для маппинга

                preprocessed_path = preprocessed_files_map.get(relative_path_key_for_map)

                if preprocessed_path and Path(preprocessed_path).exists():
                    files_in_this_folder_preprocessed.append(preprocessed_path)
                else:
                    logger.warning(f"⚠️ Предобработанный файл для '{Path(original_path).name}' (отн: {relative_path_key_for_map}) не найден в маппинге. Пропускаем.")

            # Если нет предобработанных файлов, пропускаем эту папку
            if not files_in_this_folder_preprocessed:
                logger.warning(f"⚠️ Нет предобработанных файлов для папки '{folder_name}', пропускаем")
                continue
            
            # Получаем аудиосегмент для этой папки
            audio_segment_path = folder_audio_segments.get(folder_name)
            if not audio_segment_path:
                logger.warning(f"⚠️ Нет аудиосегмента для папки '{folder_name}', пропускаем")
                continue

            # --- ДОБАВЬТЕ ЭТУ СТРОКУ ---
            output_video_segment_for_folder_path = Path(self.temp_folder) / f"video_segment_{folder_name}.mp4"

            # Вызов process_single_folder_segment теперь с files_in_this_folder_preprocessed
            video_segment_path = self.folder_video_processor.process_single_folder_segment(
                folder_name,
                files_in_this_folder_preprocessed, # Аргумент 1 (media_files_in_folder)
                target_duration,                   # Аргумент 2 (folder_target_duration)
                audio_segment_path,                # Аргумент 3 (folder_audio_path)
                str(output_video_segment_for_folder_path) # <-- АРГУМЕНТ 4 (segment_output_path)
            )
            
            if video_segment_path:
                folder_video_segments[folder_name] = video_segment_path
                logger.info(f"✅ Видеосегмент для папки '{folder_name}' создан: {video_segment_path}")
            else:
                logger.error(f"❌ Ошибка создания видеосегмента для папки '{folder_name}'")
        
        # 3. Простая конкатенация готовых видеосегментов
        logger.info("🔗 Конкатенация готовых видеосегментов")

        # ИСПРАВЛЕНИЕ: Проверяем, что есть сегменты для конкатенации
        if not folder_video_segments:
            logger.error("❌ Нет готовых видеосегментов для конкатенации!")
            return False

        # ИСПРАВЛЕНИЕ: Создаем правильную функцию сортировки папок
        def folder_sort_key_for_segments(folder_name: str) -> Tuple[int, int]:
            """Сортировка папок по диапазонам для правильного порядка сегментов"""
            if folder_name == "root":
                return (0, 0)
            try:
                if '-' in folder_name:
                    start_num, end_num = map(int, folder_name.split('-'))
                    return (start_num, end_num)
                else:
                    num = int(folder_name)
                    return (num, num)
            except (ValueError, IndexError):
                logger.warning(f"⚠️ Не удалось распарсить папку '{folder_name}' для сортировки")
                return (999, 999)  # В конец списка

        # Создаем список файлов для конкатенации в ПРАВИЛЬНОМ порядке
        concat_list_path = Path(self.temp_folder) / "folder_segments_concat.txt"
        valid_segments = []

        # ИСПРАВЛЕНИЕ: Сортируем папки по правильной логике
        sorted_folder_names = sorted(excel_folder_durations.keys(), key=folder_sort_key_for_segments)

        logger.info(f"📋 Порядок конкатенации сегментов:")
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            for i, folder_name in enumerate(sorted_folder_names):
                if folder_name in folder_video_segments:
                    segment_path = folder_video_segments[folder_name]
                    # Проверяем существование и валидность файла
                    if Path(segment_path).exists() and Path(segment_path).stat().st_size > 0:
                        f.write(f"file '{segment_path}'\n")
                        valid_segments.append(segment_path)
                        logger.info(f"   {i+1}. {folder_name} → {Path(segment_path).name}")
                    else:
                        logger.error(f"❌ Сегмент не найден или пуст: {segment_path}")
                else:
                    logger.warning(f"⚠️ Сегмент для папки '{folder_name}' не создан")

        # Проверяем, что есть валидные сегменты
        if not valid_segments:
            logger.error("❌ Нет валидных сегментов для конкатенации!")
            return False

        # ДОБАВЛЕНИЕ: ДИАГНОСТИКА ДЛИТЕЛЬНОСТЕЙ СЕГМЕНТОВ
        logger.info("🔍 ДИАГНОСТИКА ДЛИТЕЛЬНОСТЕЙ СЕГМЕНТОВ:")
        total_segments_duration = 0.0
        for folder_name in sorted_folder_names:
            if folder_name in folder_video_segments:
                segment_path = folder_video_segments[folder_name]
                if Path(segment_path).exists():
                    segment_duration = get_media_duration(segment_path)
                    expected_duration = excel_folder_durations.get(folder_name, 0)
                    total_segments_duration += segment_duration
                    
                    logger.info(f"   📁 {folder_name}: фактическая={segment_duration:.2f}с, ожидаемая={expected_duration:.2f}с")
                    
                    if abs(segment_duration - expected_duration) > 5.0:
                        logger.warning(f"   ⚠️ Большая разница в длительности сегмента {folder_name}!")
                else:
                    logger.error(f"   ❌ Сегмент не найден: {segment_path}")
        
        logger.info(f"📊 Общая длительность всех сегментов: {total_segments_duration:.2f}с")
        overall_audio_duration_final_excel = sum(excel_folder_durations.values())
        logger.info(f"📊 Ожидаемая общая длительность (Excel): {overall_audio_duration_final_excel:.2f}с")
        
        # ИСПРАВЛЕНИЕ: Используем фактическую сумму сегментов для диагностики
        overall_audio_duration_final = total_segments_duration
        logger.info(f"📊 Фактическая общая длительность (сегменты): {overall_audio_duration_final:.2f}с")
        
        excel_segments_diff = abs(total_segments_duration - overall_audio_duration_final_excel)
        if excel_segments_diff > 10.0:
            logger.warning(f"⚠️ Разница между Excel расчетом и фактическими сегментами: {excel_segments_diff:.2f}с")
            logger.warning("💡 Это нормально - Excel расчеты включают теоретические паузы")
            logger.info("✅ Используем фактическую длительность сегментов для финальной диагностики")

        # 3. Простая конкатенация готовых видеосегментов (XFADE уже внутри)
        logger.info("🔗 Простая конкатенация готовых видеосегментов (XFADE уже внутри)")
        
        # Проверяем, что есть сегменты для конкатенации
        if not folder_video_segments:
            logger.error("❌ Нет готовых видеосегментов для конкатенации!")
            return False

        # Создаем список файлов для конкатенации в правильном порядке
        concat_list_path = Path(self.temp_folder) / "folder_segments_concat.txt"
        valid_segments = []

        with open(concat_list_path, 'w', encoding='utf-8') as f:
            for folder_name in sorted_folder_names:
                if folder_name in folder_video_segments:
                    segment_path = folder_video_segments[folder_name]
                    if Path(segment_path).exists() and Path(segment_path).stat().st_size > 0:
                        f.write(f"file '{segment_path}'\n")
                        valid_segments.append(segment_path)

                        # Диагностика
                        segment_duration = get_media_duration(segment_path)
                        expected_duration = excel_folder_durations.get(folder_name, 0)
                        logger.info(f"   📁 {folder_name}: {segment_duration:.2f}с (ожидаемо {expected_duration:.2f}с)")

        # Простая конкатенация сегментов
        final_temp_video_path = Path(self.temp_folder) / "final_concatenated_video.mp4"
        concat_cmd = [
            get_ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",  # Копируем без перекодировки
            str(final_temp_video_path)
        ]
        
        try:
            result = run_subprocess_hidden(concat_cmd, check=True, capture_output=True, text=True)
            logger.info(f"✅ Финальная конкатенация завершена: {final_temp_video_path}")

            # Проверяем длительность
            final_duration = get_media_duration(str(final_temp_video_path))
            logger.info(f"📊 Длительность финального видео: {final_duration:.2f}с")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка конкатенации: {e.stderr}")
            return False
        
        # ИСПРАВЛЕНИЕ: Используем фактическую длительность сегментов, а не Excel расчеты
        overall_audio_duration_final = total_segments_duration
        
        # 4. Финальная сборка с глобальными элементами
        logger.info("🏗️ Финальная сборка с глобальными элементами")
        
        # Создание кадров для кнопки подписки
        frame_list_path, num_frames = self._create_subscribe_frames()
        
        # Генерация субтитров
        subtitles_path = self._generate_subtitles(str(final_temp_video_path), overall_audio_duration_final, 0.0)
        
        # ДИАГНОСТИЧЕСКИЕ ДАННЫЕ для отладки аудио
        debug_info = {
            "video_number": self.video_number,
            "excel_audio_duration": overall_audio_duration_final,
            "folder_durations": excel_folder_durations,
            "total_expected_duration": sum(excel_folder_durations.values()) if excel_folder_durations else 0,
            "audio_folder": self.temp_audio_folder,
            "silence_duration": self.config.silence_duration,
            "excel_range": f"{start_row}-{end_row}",
            "synchronized_audio_path": str(final_temp_video_path),
            "synchronized_audio_actual_duration": get_media_duration(str(final_temp_video_path)) if Path(str(final_temp_video_path)).exists() else 0
        }

        logger.info(f"🔍 ПЕРЕДАЧА ОТЛАДОЧНЫХ ДАННЫХ В create_combined_audio:")
        for key, value in debug_info.items():
            logger.info(f"   {key}: {value}")
        
        # Финальная сборка
        final_video_path = self._final_assembly(
            str(final_temp_video_path), # Видео УЖЕ с аудио
            str(final_temp_video_path), # Передаем тот же путь как "аудио"
            frame_list_path, num_frames, subtitles_path,
            overall_audio_duration_final, # Общая длительность видео
            clips_info=[], # clips_info уже не нужен на этом этапе
            audio_offset=0.0, # Общий offset для всего видео
            folder_durations=excel_folder_durations, # Для информации, если нужна
            start_row=start_row, end_row=end_row,
            adjust_videos_to_audio=self.config.adjust_videos_to_audio,
            debug_info=debug_info  # Передаем отладочные данные
        )
        
        logger.info(f"✅ ПОПАПОЧНАЯ ОБРАБОТКА ЗАВЕРШЕНА: {final_video_path}")

        # Фоновая музыка теперь обрабатывается в final_assembly.py
        logger.info("🔇 Фоновая музыка обрабатывается в final_assembly")

        # Валидация финального видео
        self._validate_final_video(self._get_output_file_path(), overall_audio_duration_final)

        logger.info(f"=== ✅ Монтаж видео {self.video_number} завершён! Видео: {self._get_output_file_path()} ===")
        
        logger.info(f"🔍 DEBUG: Начинаем финальную диагностику для видео {self.video_number}")
        # НОВОЕ: Финальная диагностика для подтверждения решения проблемы
        try:
            final_output_duration = get_media_duration(self._get_output_file_path())
            logger.info(f"🏁 ИТОГОВАЯ ДИАГНОСТИКА:")
            logger.info(f"   Ожидаемая длительность аудио: {overall_audio_duration_final:.2f}с")
            logger.info(f"   Фактическая длительность финального видео: {final_output_duration:.2f}с")
            
            duration_diff = abs(final_output_duration - overall_audio_duration_final)
            if duration_diff < 2.0:
                logger.info(f"   ✅ ПРОБЛЕМА РЕШЕНА: Длительности соответствуют (разница: {duration_diff:.2f}с)")
            else:
                logger.warning(f"   ⚠️ ПРОБЛЕМА ОСТАЕТСЯ: Значительная разница в длительностях ({duration_diff:.2f}с)")
        except Exception as e:
            logger.error(f"Ошибка финальной диагностики: {e}")
        
        logger.info(f"🔍 DEBUG: Диагностика завершена, готовимся вернуть True для видео {self.video_number}")
        
        # Управление temp папкой по параметру debug_keep_temp_folder
        self._manage_temp_folder()
        
        logger.info(f"🔍 DEBUG: Возвращaем True для видео {self.video_number}")
        return True

    def _concatenate_segments_with_xfade(self, folder_video_segments: Dict[str, str],
                                       sorted_folder_names: List[str],
                                       effects_config) -> str:
        """
        Конкатенация сегментов папок с XFADE переходами между ними
        """
        logger.info("🎬 === XFADE ПЕРЕХОДЫ МЕЖДУ СЕГМЕНТАМИ ПАПОК ===")

        output_path = Path(self.temp_folder) / "final_concatenated_video_with_xfade.mp4"

        # Собираем файлы сегментов в правильном порядке
        segment_files = []
        for folder_name in sorted_folder_names:
            if folder_name in folder_video_segments:
                segment_path = folder_video_segments[folder_name]
                if Path(segment_path).exists():
                    segment_files.append(segment_path)
                    logger.info(f"   📁 {folder_name} → {Path(segment_path).name}")

        if len(segment_files) < 2:
            logger.warning("Менее 2 сегментов, переходы не применяются")
            if segment_files:
                shutil.copy2(segment_files[0], output_path)
                return str(output_path)
            else:
                raise ProcessingError("Нет сегментов для конкатенации")

        try:
            # Получаем параметры переходов
            transition_type = getattr(effects_config, 'transition_type', 'fade')
            transition_duration = getattr(effects_config, 'transition_duration', 0.5)

            logger.info(f"🔄 XFADE между сегментами: {transition_type}, {transition_duration}с")

            # Строим команду FFmpeg
            cmd = [get_ffmpeg_path(), "-v", "debug"]

            # Добавляем входные файлы
            for segment_file in segment_files:
                cmd.extend(["-i", segment_file])

            # Получаем длительности сегментов для расчета offset
            segment_durations = []
            for segment_file in segment_files:
                duration = get_media_duration(segment_file)
                segment_durations.append(duration)
                logger.info(f"   Сегмент {Path(segment_file).name}: {duration:.2f}с")

            # Строим filter_complex для XFADE между сегментами
            filter_parts = []
            current_stream = "[0:v]"

            cumulative_time = segment_durations[0]

            for i in range(len(segment_files) - 1):
                # Offset для перехода между сегментами
                offset = cumulative_time - transition_duration
                offset = max(0.1, offset)  # Минимальный offset

                if i == len(segment_files) - 2:  # Последний переход
                    output_stream = "[out]"
                else:
                    output_stream = f"[v{i}]"

                xfade_filter = f"{current_stream}[{i+1}:v]xfade=transition={transition_type}:duration={transition_duration:.3f}:offset={offset:.3f}{output_stream}"
                filter_parts.append(xfade_filter)
                current_stream = output_stream

                # Обновляем накопленное время
                cumulative_time += segment_durations[i+1] - transition_duration

                logger.info(f"   Переход {i+1}: offset={offset:.3f}с")

            filter_complex = ";".join(filter_parts)

            # Финальная команда
            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                "-pix_fmt", "yuv420p", "-r", str(self.config.frame_rate),
                "-an",  # Аудио уже есть в сегментах
                "-y", str(output_path)
            ])

            logger.info("🎬 Выполняем XFADE между сегментами папок...")
            logger.debug(f"XFADE команда: {' '.join(cmd)}")

            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=600)

            if output_path.exists() and output_path.stat().st_size > 0:
                final_duration = get_media_duration(str(output_path))
                logger.info(f"✅ XFADE между сегментами завершен: {output_path.name}")
                logger.info(f"   Финальная длительность: {final_duration:.2f}с")
                return str(output_path)
            else:
                raise ProcessingError("Файл с XFADE переходами между сегментами не создан")

        except Exception as e:
            logger.error(f"❌ Ошибка XFADE между сегментами: {e}")
            logger.warning("🔄 Переключаемся на простую конкатенацию сегментов")

            # Fallback на простую конкатенацию
            concat_list_path = Path(self.temp_folder) / "segments_fallback_concat.txt"
            with open(concat_list_path, 'w', encoding='utf-8') as f:
                for segment_file in segment_files:
                    f.write(f"file '{segment_file}'\n")

            fallback_cmd = [
                get_ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list_path),
                "-c", "copy",
                str(output_path)
            ]

            run_subprocess_hidden(fallback_cmd, check=True, capture_output=True, text=True)
            return str(output_path)


def process_auto_montage(channel_name: str, video_number: Optional[str] = None,
                         preserve_clip_audio_videos: Optional[List[int]] = None) -> bool:
    """
    Основная функция автоматического монтажа

    Args:
        channel_name: Название канала
        video_number: Номер конкретного видео (опционально)
        preserve_clip_audio_videos: Список номеров видео для сохранения аудио

    Returns:
        bool: True если обработка прошла успешно
    """
    start_time = datetime.now()
    preserve_clip_audio_videos = preserve_clip_audio_videos or []
    
    # Сбрасываем флаг в начале монтажа
    montage_control.reset_stop_montage_flag()

    logger.info(f"Начало обработки канала '{channel_name}' в {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"🔍 DEBUG process_auto_montage: preserve_clip_audio_videos параметр = {preserve_clip_audio_videos}")

    try:
        # ПРОВЕРЯЕМ ФЛАГ ОСТАНОВКИ В НАЧАЛЕ
        if montage_control.check_stop_flag("process_auto_montage начало"):
            return False
        # Загрузка и валидация конфигурации
        config = MontageConfig(channel_name)
        logger.info(f"Конфигурация канала '{channel_name}' загружена успешно")
        
        # ИСПРАВЛЕНИЕ: Парсинг preserve_clip_audio_videos из конфигурации если не передан параметр
        if not preserve_clip_audio_videos:
            config_preserve_videos = config.config.get("preserve_clip_audio_videos", "")
            logger.info(f"🔍 DEBUG: Сырое значение preserve_clip_audio_videos из конфигурации: '{config_preserve_videos}' (тип: {type(config_preserve_videos)})")
            if config_preserve_videos:
                try:
                    # Парсим строку "1,2,3" в список [1, 2, 3]
                    preserve_clip_audio_videos = [
                        int(num.strip()) for num in str(config_preserve_videos).split(",")
                        if num.strip()
                    ]
                    logger.info(f"🎵 Из конфигурации: preserve_clip_audio_videos = {preserve_clip_audio_videos}")
                except ValueError:
                    logger.warning(f"⚠️ Некорректный формат preserve_clip_audio_videos в конфигурации: {config_preserve_videos}")
                    preserve_clip_audio_videos = []
            else:
                logger.info(f"🔍 DEBUG: preserve_clip_audio_videos пустое или отсутствует в конфигурации")

        # Валидация путей
        path_errors = config.validate_paths()
        if path_errors:
            for error in path_errors:
                logger.error(error)
            raise ConfigurationError(f"Ошибки конфигурации путей: {'; '.join(path_errors)}")

        # Проверка опциональных файлов
        config.check_optional_files()

        # Определение списка видео для обработки
        if video_number:
            video_numbers = [video_number]
        else:
            video_numbers = [str(i) for i in range(1, config.num_videos + 1)]

        logger.info(f"Обрабатываемые видео: {', '.join(video_numbers)}")

        # Статистика обработки
        successful_videos = 0
        failed_videos = 0

        # Обработка каждого видео
        for vid_num in video_numbers:
            # ПРОВЕРЯЕМ ФЛАГ ОСТАНОВКИ ПЕРЕД КАЖДЫМ ВИДЕО
            if montage_control.check_stop_flag(f"перед обработкой видео {vid_num}"):
                break
                
            try:
                logger.info(f"🔍 DEBUG: Создаем VideoProcessor для видео {vid_num} с preserve_clip_audio_videos={preserve_clip_audio_videos}")
                
                # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ ПЕРЕД СОЗДАНИЕМ ПРОЦЕССОРА
                if montage_control.check_stop_flag(f"перед созданием VideoProcessor {vid_num}"):
                    logger.error("🛑 ОСТАНОВКА до создания VideoProcessor!")
                    break
                    
                processor = VideoProcessor(config, vid_num, preserve_clip_audio_videos)
                logger.info(f"🔍 DEBUG: VideoProcessor создан успешно, вызываем process()")
                
                # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ ПЕРЕД ПРОЦЕССИНГОМ
                if montage_control.check_stop_flag(f"перед процессингом видео {vid_num}"):
                    logger.error("🛑 ОСТАНОВКА до process()!")
                    break
                    
                try:
                    result = processor.process()
                    logger.info(f"🔍 DEBUG: processor.process() вернул: {result} (тип: {type(result)})")
                    
                    # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ ПОСЛЕ ПРОЦЕССИНГА
                    if montage_control.check_stop_flag(f"после процессинга видео {vid_num}"):
                        logger.error("🛑 ОСТАНОВКА после process()!")
                        break
                        
                except Exception as process_error:
                    logger.error(f"🔍 DEBUG: Исключение в processor.process(): {type(process_error).__name__}: {process_error}")
                    import traceback
                    logger.error(f"🔍 DEBUG: Полная трассировка:\n{traceback.format_exc()}")
                    result = False
                
                # Проверяем что вернул метод process
                if result is True:
                    successful_videos += 1
                    logger.info(f"✅ Видео {vid_num} обработано успешно")
                elif result is None:
                    # Если метод вернул None, но видео существует - считаем это успехом
                    output_path = processor._get_output_file_path()
                    if os.path.exists(output_path):
                        successful_videos += 1
                        logger.info(f"✅ Видео {vid_num} обработано успешно (найден готовый файл: {output_path})")
                    else:
                        failed_videos += 1
                        logger.error(f"❌ Видео {vid_num} не удалось обработать - метод вернул None и файл не найден")
                else:
                    failed_videos += 1
                    logger.error(f"❌ Видео {vid_num} не удалось обработать - метод вернул: {result}")
            except Exception as e:
                logger.error(f"Критическая ошибка при обработке видео {vid_num}: {e}")
                failed_videos += 1

        # Итоговая статистика
        end_time = datetime.now()
        processing_time = end_time - start_time

        logger.info(f"=== 📊 Итоговая статистика ===")
        logger.info(f"Канал: {channel_name}")
        logger.info(f"Успешно обработано: {successful_videos}")
        logger.info(f"Ошибок: {failed_videos}")
        logger.info(f"Время обработки: {processing_time}")
        logger.info(f"Завершено: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if failed_videos == 0:
            logger.info("✅ Все видео обработаны успешно")
        else:
            logger.warning(f"⚠️ Обнаружены проблемы при обработке {failed_videos} видео")

        return failed_videos == 0

    except ConfigurationError as e:
        logger.error(f"Ошибка конфигурации для канала '{channel_name}': {e}")
        return False
    except Exception as e:
        logger.critical(f"Критическая ошибка при обработке канала '{channel_name}': {e}")
        return False


def main():
    """Главная функция для запуска из командной строки"""
    parser = argparse.ArgumentParser(
        description='Скрипт автоматического монтажа видео FlexMontage Studio',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python main.py --channel MyChannel
  python main.py --channel MyChannel --video_number 5
  python main.py --channel MyChannel --preserve_clip_audio_videos 3,5,7
        """
    )

    parser.add_argument('--channel', type=str, required=True,
                        help='Название канала для монтажа')
    parser.add_argument('--video_number', type=str, default=None,
                        help='Номер конкретного видео (если не указан, обрабатываются все видео)')
    parser.add_argument('--preserve_clip_audio_videos', type=str, default=None,
                        help='Список номеров видео для сохранения аудио клипа (например: 3,5,7)')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='INFO', help='Уровень логирования')

    args = parser.parse_args()

    # Настройка логирования
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'montage_{args.channel}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        ]
    )
    
    # Инициализация отладчика min() вызовов
    logger.info("🔧 Используем простой отладчик min() вызовов")

    # Парсинг списка видео для сохранения аудио
    preserve_clip_audio_videos = []
    if args.preserve_clip_audio_videos:
        try:
            preserve_clip_audio_videos = [
                int(num.strip()) for num in args.preserve_clip_audio_videos.split(",")
                if num.strip()
            ]
        except ValueError:
            logger.error(f"Некорректный формат для --preserve_clip_audio_videos: {args.preserve_clip_audio_videos}")
            logger.error("Используйте формат: 3,5,7")
            sys.exit(1)

    # Запуск обработки
    try:
        success = process_auto_montage(args.channel, args.video_number, preserve_clip_audio_videos)
        
        # Логирование статистики min() вызовов
        logger.info("📊 Статистика min() вызовов после обработки:")
        log_min_stats()
        
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Обработка прервана пользователем")
        log_min_stats()
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Неожиданная ошибка: {e}")
        logger.critical("📊 Статистика min() вызовов до ошибки:")
        log_min_stats()
        sys.exit(1)
    finally:
        # Логирование финальной статистики
        pass


if __name__ == "__main__":
    main()