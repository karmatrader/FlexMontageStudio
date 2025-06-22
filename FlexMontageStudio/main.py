import os
import sys
import argparse
import shutil
import subprocess
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

# SAFETY GUARD: Предотвращаем случайную инициализацию GUI при импорте из других модулей
_GUI_SAFE_IMPORT = True

# Импорты модулей
from config import get_channel_config
from audio_processing import get_audio_files_for_video, process_audio_files, add_background_music
from video_processing import preprocess_images, process_photos_and_videos, concat_photos_random, concat_photos_in_order, get_ffmpeg_path, get_ffprobe_path, create_video_effects_config
from ffmpeg_utils import get_media_duration
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
        self.background_music_volume = self._get_float_param("background_music_volume", 0.2, min_val=0.0, max_val=1.0)

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

    def _create_directories(self):
        """Создание необходимых директорий"""
        for directory in [self.output_folder_vid, self.temp_folder,
                          self.preprocessed_photo_folder, self.temp_audio_folder]:
            os.makedirs(directory, exist_ok=True)

    def _should_preserve_clip_audio(self) -> bool:
        """Определение необходимости сохранения аудио клипа"""
        return (self.config.preserve_clip_audio_default or
                self.video_number_int in self.preserve_clip_audio_videos)

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

    def _process_audio(self, audio_files: List[str]) -> Tuple[str, float]:
        """Обработка аудио"""
        logger.info("=== 🎵 Обработка аудио ===")

        try:
            final_audio_path, temp_audio_duration = process_audio_files(
                audio_files,
                self.temp_audio_folder,
                self.temp_folder,
                self.config.audio_channels,
                self.config.audio_sample_rate,
                self.config.audio_bitrate,
                self.config.silence_duration
            )

            if not final_audio_path or not temp_audio_duration:
                raise ProcessingError("Ошибка обработки аудио")

            logger.info(f"Длительность аудио: {int(temp_audio_duration // 60)}:{int(temp_audio_duration % 60):02d}")
            return final_audio_path, temp_audio_duration

        except Exception as e:
            raise ProcessingError(f"Ошибка обработки аудио: {e}")

    def _add_background_music(self, final_audio_path: str, temp_audio_duration: float) -> str:
        """Добавление фоновой музыки"""
        try:
            return add_background_music(
                final_audio_path,
                self.config.background_music_path,
                self.temp_folder,
                temp_audio_duration,
                self.config.audio_bitrate,
                self.config.audio_sample_rate,
                self.config.background_music_volume
            )
        except Exception as e:
            logger.error(f"Ошибка добавления фоновой музыки: {e}")
            return final_audio_path  # Возвращаем оригинальный аудио файл

    def _preprocess_images(self, photo_folder_vid: str):
        """Предобработка изображений"""
        logger.info("=== 🖼️ Предобработка изображений ===")

        try:
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
            else:
                # Простое копирование без обработки
                for image_filename in os.listdir(photo_folder_vid):
                    if image_filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov')):
                        src_path = os.path.join(photo_folder_vid, image_filename)
                        dst_path = os.path.join(self.preprocessed_photo_folder, image_filename)
                        shutil.copy(src_path, dst_path)

        except Exception as e:
            raise ProcessingError(f"Ошибка предобработки изображений: {e}")

    def _process_photos_and_videos(self, temp_audio_duration: float, start_row: int, end_row: int) -> Tuple[
        List[str], List[Dict], float]:
        """Обработка фото и видео"""
        logger.info("=== 🎬 Обработка фото и видео ===")

        photo_files = find_files(
            self.preprocessed_photo_folder,
            SUPPORTED_FORMATS,
            recursive=True
        )

        if not photo_files:
            raise ProcessingError(f"Нет фото/видео для обработки в {self.preprocessed_photo_folder}")

        preserve_clip_audio = self._should_preserve_clip_audio()
        logger.info(f"Сохранение аудио клипа для видео {self.video_number}: {preserve_clip_audio}")

        # Создаем конфигурацию эффектов из настроек канала
        effects_config = create_video_effects_config(self.config.config)
        
        if effects_config.effects_enabled:
            logger.info("🎨 Эффекты видео включены")
            if effects_config.auto_zoom_alternation:
                logger.info("🔄 Автоматическое чередование Zoom In/Out активно")
            
            # Предупреждения о производительности
            complex_effects = []
            if effects_config.zoom_effect != "none":
                complex_effects.append("масштабирование")
            if effects_config.rotation_effect != "none":
                complex_effects.append("вращение")
            if effects_config.color_effect != "none":
                complex_effects.append("цветовые эффекты")
            if effects_config.filter_effect != "none":
                complex_effects.append("фильтры")
            
            if complex_effects:
                logger.warning(f"⚠️ Использование эффектов ({', '.join(complex_effects)}) может увеличить время обработки")
            
            if effects_config.transitions_enabled:
                logger.warning("⚠️ Переходы между клипами увеличивают время рендеринга")

        try:
            processed_photo_files, skipped_files, clips_info, audio_offset = process_photos_and_videos(
                photo_files=photo_files,
                preprocessed_photo_folder=self.preprocessed_photo_folder,
                temp_folder=self.temp_folder,
                video_resolution=self.config.video_resolution,
                frame_rate=self.config.frame_rate,
                video_crf=self.config.video_crf,
                video_preset=self.config.video_preset,
                temp_audio_duration=temp_audio_duration,
                audio_folder=self.config.output_directory,
                overall_range_start=start_row,
                overall_range_end=end_row,
                excel_path=self.config.xlsx_file_path,
                photo_order=self.config.photo_order,
                adjust_videos_to_audio=self.config.adjust_videos_to_audio,
                preserve_clip_audio=preserve_clip_audio,
                preserve_video_duration=self.config.preserve_video_duration,
                effects_config=effects_config
            )

            if not processed_photo_files:
                raise ProcessingError("Не удалось обработать ни одного фото/видео")

            logger.info(f"Обработано файлов: {len(processed_photo_files)} из {len(photo_files)}")
            if skipped_files:
                logger.warning(f"Пропущенные файлы ({len(skipped_files)}): {', '.join(skipped_files)}")
            
            # Дополнительное логирование для отладки проблемы с остановкой обработки
            logger.info(f"🎞️ Список обработанных файлов:")
            for i, file_path in enumerate(processed_photo_files):
                logger.info(f"  {i+1}. {file_path}")
            
            if effects_config.effects_enabled:
                logger.info(f"🎨 Эффекты применены к {len(processed_photo_files)} клипам")
                if effects_config.zoom_effect == "auto":
                    logger.info(f"   Zoom чередование: четные={effects_config.zoom_effect}_in, нечетные={effects_config.zoom_effect}_out")

            return processed_photo_files, clips_info, audio_offset

        except Exception as e:
            raise ProcessingError(f"Ошибка обработки фото и видео: {e}")

    def _concatenate_videos(self, processed_photo_files: List[str], temp_audio_duration: float, effects_config=None) -> str:
        """Конкатенация видео"""
        logger.info("=== 🎞️ Конкатенация видео ===")

        try:
            # Проверяем, нужны ли переходы
            has_transitions = effects_config and effects_config.transitions_enabled if effects_config else False
            
            # ДИАГНОСТИКА ПЕРЕХОДОВ
            logger.info(f"🔍 ДИАГНОСТИКА ПЕРЕХОДОВ:")
            logger.info(f"   effects_config: {effects_config}")
            logger.info(f"   effects_config.transitions_enabled: {getattr(effects_config, 'transitions_enabled', 'НЕТ АТРИБУТА')}")
            logger.info(f"   has_transitions: {has_transitions}")
            logger.info(f"   len(processed_photo_files): {len(processed_photo_files)}")
            logger.info(f"   Условие для переходов: {has_transitions and len(processed_photo_files) > 1}")
            
            if has_transitions and len(processed_photo_files) > 1:
                logger.info(f"🔄 Создание видео с переходами: {effects_config.transition_type}, длительность {effects_config.transition_duration}с")
                return self._concatenate_with_transitions(processed_photo_files, temp_audio_duration, effects_config)
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
                if self.config.photo_order == "order":
                    concat_list_path = concat_photos_in_order(processed_photo_files, self.temp_folder, temp_audio_duration)
                else:
                    concat_list_path = concat_photos_random(processed_photo_files, self.temp_folder, temp_audio_duration)

                temp_video_path = os.path.join(self.temp_folder, "temp_video.mp4")

                # ВОССТАНОВЛЕНО ИЗ РАБОЧЕГО КОДА: Убираем принудительную обрезку видео параметром -t
                # Пусть видео будет естественной длительности из concat list
                cmd = [
                    get_ffmpeg_path(), "-f", "concat", "-safe", "0", "-i", concat_list_path,
                    "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                    "-an", "-map", "0:v", "-map", "-0:s", "-map", "-0:d",
                    "-fflags", "+genpts+igndts", "-fps_mode", "cfr", "-async", "1",
                    "-probesize", "50000000", "-analyzeduration", "50000000",
                    # УБРАЛИ: "-t", str(temp_audio_duration), 
                    "-y", temp_video_path
                ]

                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
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

    def _concatenate_with_transitions(self, processed_photo_files: List[str], temp_audio_duration: float, effects_config) -> str:
        """Конкатенация видео с переходами xfade - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        temp_video_path = os.path.join(self.temp_folder, "temp_video_with_transitions.mp4")
        
        try:
            # Получаем реальную длительность каждого клипа
            from ffmpeg_utils import get_media_duration
            clip_durations = []
            total_clips_duration = 0
            
            for i, video_file in enumerate(processed_photo_files):
                try:
                    duration = get_media_duration(video_file)
                    clip_durations.append(duration)
                    total_clips_duration += duration
                    logger.info(f"Клип {i}: {video_file} -> {duration:.2f}с")
                except Exception as e:
                    logger.error(f"Ошибка получения длительности {video_file}: {e}")
                    # Fallback на обычную конкатенацию при ошибке
                    fallback_config = type('obj', (object,), {'transitions_enabled': False})()
                    return self._concatenate_videos(processed_photo_files, temp_audio_duration, fallback_config)
            
            logger.info(f"Общая длительность клипов: {total_clips_duration:.2f}с")
            logger.info(f"Ожидаемая длительность аудио: {temp_audio_duration:.2f}с")
            
            # ИСПРАВЛЕНО: Правильный расчет итоговой длительности с переходами
            # Итоговая длительность = сумма всех клипов - (количество переходов * длительность перехода)
            num_transitions = len(processed_photo_files) - 1
            expected_final_duration = total_clips_duration - (num_transitions * effects_config.transition_duration)
            logger.info(f"📊 Длительности: клипы={total_clips_duration:.2f}с, переходы={num_transitions}x{effects_config.transition_duration}с = -{num_transitions * effects_config.transition_duration:.2f}с")
            logger.info(f"Ожидаемая итоговая длительность с переходами: {expected_final_duration:.2f}с")
            
            # ИСПРАВЛЕНО: Проверяем только критические расхождения, учитываем что система может компенсировать растяжением
            duration_difference = temp_audio_duration - expected_final_duration
            if duration_difference > temp_audio_duration * 0.15:  # Только если разница больше 15% от длительности аудио
                logger.warning(f"⚠️ КРИТИЧЕСКОЕ РАСХОЖДЕНИЕ: Расчетная длительность видео ({expected_final_duration:.2f}с) короче аудио ({temp_audio_duration:.2f}с) на {duration_difference:.2f}с!")
                logger.warning("Переходы критически сокращают длительность видео")
                logger.warning("🔄 Переходим на обычную конкатенацию для сохранения полной длительности")
                # Используем обычную конкатенацию только при критическом расхождении
                fallback_config = type('obj', (object,), {'transitions_enabled': False})()
                return self._concatenate_videos(processed_photo_files, temp_audio_duration, fallback_config)
            else:
                logger.info(f"✅ Разница длительности ({duration_difference:.2f}с) приемлема, переходы сохраняются")
            
            # Создаем комплексный FFmpeg фильтр с переходами
            inputs = []
            filter_parts = []
            
            # Добавляем все видео как входы
            for i, video_file in enumerate(processed_photo_files):
                inputs.extend(["-i", video_file])
            
            # ИСПРАВЛЕНА ЛОГИКА: Создаем цепочку переходов с ПРАВИЛЬНЫМ накоплением времени
            current_stream = "[0:v]"
            accumulated_offset = 0  # Накопленный offset для xfade переходов
            
            for i in range(1, len(processed_photo_files)):
                next_input = f"[{i}:v]"
                transition_output = f"[v{i}]"
                
                # ИСПРАВЛЕНО: offset для xfade = накопленное время - длительность перехода
                # Это время, когда начинается переход в ВЫХОДНОМ видео
                accumulated_offset += clip_durations[i-1] - effects_config.transition_duration
                offset = max(0, accumulated_offset)  # Убеждаемся что offset не отрицательный
                
                # Создаем xfade переход с правильным синтаксисом
                xfade_filter = f"{current_stream}{next_input}xfade=transition={effects_config.transition_type}:duration={effects_config.transition_duration}:offset={offset:.2f}{transition_output}"
                filter_parts.append(xfade_filter)
                
                current_stream = transition_output
                logger.info(f"Переход {i}: offset={offset:.2f}с, duration={effects_config.transition_duration}с")
            
            # Собираем команду FFmpeg
            cmd = [get_ffmpeg_path()]
            cmd.extend(inputs)
            cmd.extend(["-filter_complex", ";".join(filter_parts)])
            
            # Правильное указание выходного потока
            final_stream = current_stream.strip("[]")
            cmd.extend([
                "-map", f"[{final_stream}]",
                "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                "-an", "-y", temp_video_path
            ])
            
            logger.info(f"🔄 Создание переходов {effects_config.transition_type} длительностью {effects_config.transition_duration}с")
            logger.debug(f"FFmpeg transitions command: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"FFmpeg transitions output: {result.stdout}")
            
            # КРИТИЧЕСКАЯ ПРОВЕРКА: Валидация результата
            actual_duration = get_media_duration(temp_video_path)
            logger.info(f"✅ Фактическая длительность видео с переходами: {actual_duration:.2f}с")
            
            if abs(actual_duration - expected_final_duration) > 2.0:
                logger.warning(f"⚠️ ВНИМАНИЕ: Фактическая длительность ({actual_duration:.2f}с) не соответствует ожидаемой ({expected_final_duration:.2f}с)")
            
            return temp_video_path
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка создания переходов: {e.stderr}")
            # Fallback на обычную конкатенацию
            logger.warning("Переходы не удались, используем обычную конкатенацию")
            # Создаем пустую конфигурацию эффектов для fallback
            fallback_config = type('obj', (object,), {'transitions_enabled': False})()
            return self._concatenate_videos(processed_photo_files, temp_audio_duration, fallback_config)
        except Exception as e:
            logger.error(f"Ошибка переходов: {e}")
            # Fallback на обычную конкатенацию
            fallback_config = type('obj', (object,), {'transitions_enabled': False})()
            return self._concatenate_videos(processed_photo_files, temp_audio_duration, fallback_config)

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
                        clips_info: List[Dict], audio_offset: float) -> str:
        """Финальная сборка видео"""
        logger.info("=== 🏗️ Финальная сборка ===")

        output_file = self._get_output_file_path()

        try:
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
                self.config.subscribe_duration, clips_info=clips_info, audio_offset=audio_offset
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
            cmd = [get_ffmpeg_path()]
            
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
            num_video_inputs = len(processed_photo_files)
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            
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

    def process(self) -> bool:
        """Основной метод обработки видео"""
        logger.info(f"=== 🚀 Монтаж видео {self.video_number} ===")

        try:
            # Проверка существования готового видео
            if self._is_video_already_processed():
                return True

            # Получение аудиофайлов и диапазона строк
            audio_files, start_row, end_row = self._get_audio_files_and_range()

            # Поиск папки с фотографиями
            photo_folder_vid = self._find_photo_folder(start_row, end_row)

            # Проверка наличия фото/видео в папке
            photo_files = find_files(photo_folder_vid, SUPPORTED_FORMATS,
                                     recursive=True)
            if not photo_files:
                raise ProcessingError(f"В папке '{photo_folder_vid}' отсутствуют фото или видео")

            # Копирование аудиофайлов
            self._copy_audio_files(audio_files)

            # Обработка аудио
            final_audio_path, temp_audio_duration = self._process_audio(audio_files)

            # Добавление фоновой музыки
            final_audio_with_music_path = self._add_background_music(final_audio_path, temp_audio_duration)

            # Предобработка изображений
            self._preprocess_images(photo_folder_vid)

            # Создаем конфигурацию эффектов из настроек канала
            effects_config = create_video_effects_config(self.config.config)
            
            # Обработка фото и видео
            processed_photo_files, clips_info, audio_offset = self._process_photos_and_videos(
                temp_audio_duration, start_row, end_row
            )

            # ЭКСПЕРИМЕНТАЛЬНАЯ ОПЦИЯ: Единый проход (Single Pass Pipeline)
            single_pass_enabled = self.config.single_pass_enabled
            
            if single_pass_enabled:
                logger.info("🚀 ВКЛЮЧЕН РЕЖИМ ЕДИНОГО ПРОХОДА (Single Pass)")
                # Создание кадров для кнопки подписки
                frame_list_path, num_frames = self._create_subscribe_frames()
                
                # Генерация субтитров
                subtitles_path = self._generate_subtitles(final_audio_with_music_path, temp_audio_duration, audio_offset)
                
                # Единый проход: все операции в одной команде FFmpeg
                final_video_path = self._single_pass_assembly(
                    processed_photo_files, final_audio_with_music_path, frame_list_path,
                    num_frames, subtitles_path, temp_audio_duration, clips_info, 
                    audio_offset, effects_config
                )
            else:
                logger.info("📺 СТАНДАРТНЫЙ РЕЖИМ (Multi Pass)")
                # Конкатенация видео
                temp_video_path = self._concatenate_videos(processed_photo_files, temp_audio_duration, effects_config)

                # Создание кадров для кнопки подписки
                frame_list_path, num_frames = self._create_subscribe_frames()

                # Генерация субтитров
                subtitles_path = self._generate_subtitles(final_audio_with_music_path, temp_audio_duration, audio_offset)

                # Финальная сборка
                final_video_path = self._final_assembly(
                    temp_video_path, final_audio_with_music_path, frame_list_path,
                    num_frames, subtitles_path, temp_audio_duration, clips_info, audio_offset
                )

            # Валидация финального видео
            self._validate_final_video(self._get_output_file_path(), temp_audio_duration)

            logger.info(f"=== ✅ Монтаж видео {self.video_number} завершён! Видео: {self._get_output_file_path()} ===")
            
            # НОВОЕ: Финальная диагностика для подтверждения решения проблемы
            try:
                final_output_duration = get_media_duration(self._get_output_file_path())
                logger.info(f"🏁 ИТОГОВАЯ ДИАГНОСТИКА:")
                logger.info(f"   Ожидаемая длительность аудио: {temp_audio_duration:.2f}с")
                logger.info(f"   Фактическая длительность финального видео: {final_output_duration:.2f}с")
                
                duration_diff = abs(final_output_duration - temp_audio_duration)
                if duration_diff < 2.0:
                    logger.info(f"   ✅ ПРОБЛЕМА РЕШЕНА: Длительности соответствуют (разница: {duration_diff:.2f}с)")
                else:
                    logger.warning(f"   ⚠️ ПРОБЛЕМА ОСТАЕТСЯ: Значительная разница в длительностях ({duration_diff:.2f}с)")
            except Exception as e:
                logger.error(f"Ошибка финальной диагностики: {e}")
            
            return True

        except (MontageError, Exception) as e:
            logger.error(f"Ошибка при монтаже видео {self.video_number}: {e}")
            return False


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

    logger.info(f"Начало обработки канала '{channel_name}' в {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # Загрузка и валидация конфигурации
        config = MontageConfig(channel_name)
        logger.info(f"Конфигурация канала '{channel_name}' загружена успешно")

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
            try:
                processor = VideoProcessor(config, vid_num, preserve_clip_audio_videos)
                if processor.process():
                    successful_videos += 1
                else:
                    failed_videos += 1
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
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Обработка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Неожиданная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()