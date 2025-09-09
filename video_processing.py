import os
import random
import subprocess
import json
import logging
import shutil
import math
import time
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

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

import numpy as np
import cv2
from tqdm import tqdm
import pandas as pd

from utils import filter_hidden_files, natural_sort_key, find_files
from audio_processing import AudioProcessor, AudioConfig  # НОВЫЙ ИМПОРТ ДЛЯ АУДИО
from ffmpeg_utils import get_ffmpeg_path as ffmpeg_utils_get_ffmpeg_path, \
    get_ffprobe_path as ffmpeg_utils_get_ffprobe_path, _test_ffmpeg_working, get_media_duration
from image_processing_cv import ImageProcessorCV, SUPPORTED_FORMATS
from debug_min_simple import debug_min_call, log_min_stats

# Настройка логгера для модуля
logger = logging.getLogger(__name__)

# Image processing backend - используем OpenCV
CV2_AVAILABLE = True
logger.debug("🎨 Используется OpenCV для обработки изображений")

# Инициализация процессора изображений
image_processor = ImageProcessorCV()


def check_disk_space(path: Path, required_gb: float = 1.0) -> bool:
    """
    Проверка свободного места на диске

    Args:
        path: Путь для проверки
        required_gb: Требуемое место в ГБ

    Returns:
        bool: True если места достаточно
    """
    try:
        stat = shutil.disk_usage(path)
        free_gb = stat.free / (1024 ** 3)

        logger.info(f"💾 Свободное место: {free_gb:.2f} ГБ (требуется: {required_gb:.2f} ГБ)")

        if free_gb < required_gb:
            logger.error(f"❌ Недостаточно места на диске! Свободно: {free_gb:.2f} ГБ, требуется: {required_gb:.2f} ГБ")
            return False

        return True
    except Exception as e:
        logger.error(f"❌ Ошибка проверки дискового пространства: {e}")
        return False


# Переопределяем функции для правильных путей FFmpeg
def get_ffmpeg_path() -> str:
    """Получение пути к ffmpeg с исправленной логикой"""
    from ffmpeg_utils import get_ffmpeg_path as ffmpeg_utils_get_ffmpeg_path
    return ffmpeg_utils_get_ffmpeg_path()


def get_ffprobe_path() -> str:
    """Получение пути к ffprobe с исправленной логикой"""
    from ffmpeg_utils import get_ffprobe_path as ffmpeg_utils_get_ffprobe_path
    return ffmpeg_utils_get_ffprobe_path()


@dataclass
class VideoConfig:
    """Конфигурация для обработки видео"""

    def __init__(self, data: Dict = None):
        """Инициализация конфигурации видео из словаря"""
        if data is None:
            data = {}

        raw_resolution = data.get("video_resolution", "1920:1080")
        # Убедимся, что разрешение всегда хранится в формате "ШИРИНА:ВЫСОТА"
        if 'x' in raw_resolution:
            self.resolution = raw_resolution.replace('x', ':')
        else:
            self.resolution = raw_resolution

        self.frame_rate = data.get("frame_rate", 30)
        self.crf = data.get("video_crf", 23)
        self.preset = data.get("video_preset", "fast")
        self.codec = data.get("video_codec", "libx264")
        self.pixel_format = "yuv420p"

        # Дополнительные атрибуты для совместимости
        self.video_preset = self.preset  # Алиас для обратной совместимости
        self.video_crf = self.crf  # Алиас для обратной совместимости

    @property
    def width(self) -> int:
        # Убедитесь, что self.resolution действительно является строкой перед split
        if not isinstance(self.resolution, str):
            logger.error(
                f"❌ VideoConfig.width: resolution не строка, тип: {type(self.resolution)}, значение: {self.resolution}")
            return 1920  # Fallback
        try:
            # Поддерживаем форматы "1920:1080" и "1920x1080"
            if 'x' in self.resolution:
                return int(self.resolution.split('x')[0])
            else:
                return int(self.resolution.split(':')[0])
        except (ValueError, IndexError):
            logger.error(
                f"❌ VideoConfig.width: Не удалось распарсить ширину из '{self.resolution}'. Использовано 1920.")
            return 1920  # Fallback

    @property
    def height(self) -> int:
        # Убедитесь, что self.resolution действительно является строкой перед split
        if not isinstance(self.resolution, str):
            logger.error(
                f"❌ VideoConfig.height: resolution не строка, тип: {type(self.resolution)}, значение: {self.resolution}")
            return 1080  # Fallback
        try:
            # Поддерживаем форматы "1920:1080" и "1920x1080"
            if 'x' in self.resolution:
                return int(self.resolution.split('x')[1])
            else:
                return int(self.resolution.split(':')[1])
        except (ValueError, IndexError):
            logger.error(
                f"❌ VideoConfig.height: Не удалось распарсить высоту из '{self.resolution}'. Использовано 1080.")
            return 1080  # Fallback

    @property
    def size_tuple(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def expected_codec_name(self) -> str:
        """Возвращает ожидаемое имя кодека для FFprobe"""
        codec_mapping = {
            'libx264': 'h264',
            'libx265': 'hevc',
            'libvpx': 'vp8',
            'libvpx-vp9': 'vp9'
        }
        return codec_mapping.get(self.codec, self.codec.replace('lib', ''))


@dataclass
class BokehConfig:
    """Конфигурация эффекта боке"""
    enabled: bool = True
    image_size: Tuple[int, int] = (1920, 1080)
    blur_kernel: Tuple[int, int] = (99, 99)
    blur_sigma: float = 30.0


@dataclass
class ClipInfo:
    """Информация о видеоклипе"""
    path: str
    duration: float
    has_audio: bool
    original_duration: Optional[float] = None


class VideoProcessingError(Exception):
    """Базовое исключение для ошибок обработки видео"""
    pass


class FFmpegError(VideoProcessingError):
    """Ошибки FFmpeg"""
    pass


class ImageProcessingError(VideoProcessingError):
    """Ошибки обработки изображений"""
    pass


class FFmpegValidator:
    """Класс для проверки и валидации FFmpeg"""

    @staticmethod
    def check_availability(debug: bool = False) -> bool:
        """Проверка доступности FFmpeg"""
        ffmpeg_path = get_ffmpeg_path()
        logger.info(f"🔍 Проверка FFmpeg по пути: {ffmpeg_path}")

        # Используем улучшенную функцию проверки из ffmpeg_utils
        if _test_ffmpeg_working(ffmpeg_path, debug=debug):
            logger.info(f"✅ FFmpeg доступен по пути: {ffmpeg_path}")
            return True
        else:
            logger.error(f"❌ FFmpeg недоступен по пути: {ffmpeg_path}")
            return False

    @staticmethod
    def get_media_duration(file_path: str) -> float:
        """Получение длительности медиафайла с защитой от ошибок"""
        if not Path(file_path).exists():
            logger.warning(f"FFmpegValidator: Файл не найден для получения длительности: {file_path}")
            return 0.5  # Возвращаем минимальную длительность вместо 0

        try:
            original_duration = get_media_duration(file_path)  # Вызов из ffmpeg_utils

            # НОВАЯ ЗАЩИТА: Проверяем корректность полученной длительности
            if original_duration is None or original_duration != original_duration:  # NaN проверка
                logger.error(f"❌ Получена None/NaN длительность для {Path(file_path).name}")
                return 0.5

            if original_duration <= 0:
                logger.error(
                    f"❌ Получена нулевая/отрицательная длительность для {Path(file_path).name}: {original_duration}с")
                return 0.5

            return original_duration

        except Exception as e:
            logger.error(f"❌ Ошибка получения длительности для {file_path}: {e}")
            return 0.5  # Возвращаем безопасное значение

    @staticmethod
    def has_audio_stream(file_path: str) -> bool:
        """Проверка наличия аудиодорожки"""
        if not Path(file_path).exists():
            logger.warning(f"FFmpegValidator: Файл не найден для проверки аудио: {file_path}")
            return False

        try:
            cmd = [ffmpeg_utils_get_ffprobe_path(), "-v", "error", "-select_streams", "a", "-show_entries",
                   "stream=codec_type", "-of", "json", file_path]
            logger.debug(f"Проверка аудиодорожки (ffprobe): {' '.join(cmd)}")
            result = run_subprocess_hidden(cmd, capture_output=True, text=True, timeout=30, check=False)  # Увеличиваем таймаут

            if result.returncode != 0:
                logger.warning(f"FFprobe вернул ошибку при проверке аудио для {Path(file_path).name}: {result.stderr}")
                # Если ffprobe не смог проанализировать, это может быть файл без аудио или битый.
                # Для надежности, лучше считать, что аудио нет при ошибке анализа.
                return False

            data = json.loads(result.stdout)
            has_audio = bool(data.get('streams'))  # Если список streams не пуст, значит есть аудиопоток

            logger.debug(f"Аудиодорожка в {Path(file_path).name}: {'есть' if has_audio else 'нет'} (по ffprobe)")
            return has_audio

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Ошибка проверки аудиодорожки {file_path} (ffprobe): {e}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от ffprobe для {file_path}: {e}. stderr: {result.stderr}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка в has_audio_stream для {file_path}: {e}")
            return False

    @staticmethod
    def check_video_params(file_path: str, config: VideoConfig) -> Tuple[bool, List[str]]:
        """Проверка параметров видео"""
        if not Path(file_path).exists():
            return False, ["file not found"]

        try:
            # Используем FFmpeg вместо ffprobe для совместимости с imageio_ffmpeg
            cmd = [ffmpeg_utils_get_ffmpeg_path(), "-i", file_path, "-f", "null", "-"]
            result = run_subprocess_hidden(cmd, capture_output=True, text=True,
                                    timeout=120)  # Увеличиваем таймаут для больших файлов

            # Парсим информацию о видео из stderr
            stderr = result.stderr

            # Инициализируем значения по умолчанию
            codec = ""
            width = 0
            height = 0
            pix_fmt = ""
            fps = 0

            # Ищем информацию о видеопотоке
            for line in stderr.split('\n'):
                if 'Stream #' in line and 'Video:' in line:
                    # Парсим строку вида: Stream #0:0: Video: h264 (High), yuv420p(tv, bt709), 1920x1080, 30 fps
                    parts = line.split('Video:')[1].strip()

                    # Извлекаем кодек
                    codec_part = parts.split(',')[0].strip()
                    if '(' in codec_part:
                        codec = codec_part.split('(')[0].strip()
                    else:
                        codec = codec_part.strip()

                    # Ищем разрешение
                    import re
                    resolution_match = re.search(r'(\d+)x(\d+)', parts)
                    if resolution_match:
                        width = int(resolution_match.group(1))
                        height = int(resolution_match.group(2))

                    # Ищем FPS
                    fps_match = re.search(r'(\d+\.?\d*)\s+fps', parts)
                    if fps_match:
                        fps = float(fps_match.group(1))

                    # Ищем pixel format
                    pix_fmt_match = re.search(r',\s*([a-z0-9]+)\s*\(', parts)
                    if pix_fmt_match:
                        pix_fmt = pix_fmt_match.group(1)

                    break

            # Проверка соответствия параметрам
            reasons = []
            expected_codec = config.expected_codec_name
            if codec != expected_codec:
                reasons.append(f"codec={codec} (expected {expected_codec})")
            if pix_fmt and pix_fmt != config.pixel_format:
                reasons.append(f"pixel_format={pix_fmt} (expected {config.pixel_format})")
            if width != config.width or height != config.height:
                reasons.append(f"resolution={width}x{height} (expected {config.width}x{config.height})")
            if abs(fps - config.frame_rate) >= 0.1:
                reasons.append(f"fps={fps:.2f} (expected {config.frame_rate})")

            is_match = len(reasons) == 0

            if not is_match:
                logger.debug(f"Видео {Path(file_path).name} не соответствует параметрам: {', '.join(reasons)}")
            else:
                logger.debug(f"Видео {Path(file_path).name} соответствует параметрам")

            return is_match, reasons

        except (
                subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError,
                subprocess.TimeoutExpired) as e:
            logger.error(f"Ошибка проверки параметров {file_path}: {e}")
            return False, [f"error={str(e)}"]


@dataclass
class VideoEffectsConfig:
    """Конфигурация эффектов видео"""
    effects_enabled: bool = False
    zoom_effect: str = "none"  # none, zoom_in, zoom_out, auto
    zoom_intensity: float = 1.1
    rotation_effect: str = "none"  # none, sway, rotate_left, rotate_right
    rotation_angle: float = 5.0
    color_effect: str = "none"  # none, sepia, grayscale, invert, vintage
    filter_effect: str = "none"  # none, blur, sharpen, noise, vignette

    # Переходы
    transitions_enabled: bool = False
    transition_method: str = "xfade"  # ИСПРАВЛЕНО: по умолчанию xfade
    transition_type: str = "fade"  # fade, dissolve, wipeleft, wiperight, etc.
    transition_duration: float = 0.5
    auto_zoom_alternation: bool = True

    def __post_init__(self):
        """Проверка корректности настроек после инициализации"""
        if self.transitions_enabled:
            if self.transition_method not in ["xfade", "overlay"]:
                logger.warning(f"⚠️ Неизвестный transition_method: {self.transition_method}, используем 'xfade'")
                self.transition_method = "xfade"

            if self.transition_duration <= 0 or self.transition_duration > 5.0:
                logger.warning(f"⚠️ Некорректная transition_duration: {self.transition_duration}, используем 0.5")
                self.transition_duration = 0.5

            logger.info(f"✅ XFADE переходы настроены: {self.transition_type}, {self.transition_duration}с")


class VideoEffectsProcessor:
    """Класс для обработки эффектов видео"""

    def __init__(self, config: VideoEffectsConfig, video_config: VideoConfig = None):
        self.config = config
        self.video_config = video_config or VideoConfig()
        self._zoom_counter = 0  # Счетчик для чередования зума

    def get_video_effects_filter(self, clip_index: int = 0, total_duration: float = 1.0) -> str:
        """
        Генерация FFmpeg фильтров для эффектов видео

        Args:
            clip_index: Индекс текущего клипа (для чередования эффектов)
            total_duration: Длительность клипа в секундах

        Returns:
            str: Строка фильтров FFmpeg
        """
        if not self.config.effects_enabled:
            return ""

        filters = []

        # Эффект зума
        zoom_filter = self._get_zoom_filter(clip_index, total_duration)
        if zoom_filter:
            filters.append(zoom_filter)

        # Эффект вращения
        rotation_filter = self._get_rotation_filter(total_duration)
        if rotation_filter:
            filters.append(rotation_filter)

        # Цветовые эффекты
        color_filter = self._get_color_filter()
        if color_filter:
            filters.append(color_filter)

        # Фильтры
        filter_effect = self._get_filter_effect()
        if filter_effect:
            filters.append(filter_effect)

        return ",".join(filters) if filters else ""

    def _get_zoom_filter(self, clip_index: int, duration: float) -> str:
        """ИСПРАВЛЕННАЯ РЕАЛИЗАЦИЯ ZOOM масштабированного под длительность клипа"""
        if self.config.zoom_effect == "none":
            return ""

        # Определяем тип зума
        zoom_type = self.config.zoom_effect
        if zoom_type == "auto" and self.config.auto_zoom_alternation:
            # Чередование zoom_in и zoom_out
            zoom_type = "zoom_in" if clip_index % 2 == 0 else "zoom_out"

        # Параметры для плавного зума
        # DEBUG: About to call min() on zoom_intensity calculation
        logger.debug(f"DEBUG: About to call min() on zoom_intensity calculation")
        logger.debug(f"DEBUG: zoom_intensity config: {self.config.zoom_intensity}, max bound: 1.3")
        zoom_intensity = max(1.01, min(self.config.zoom_intensity, 1.3))
        fps = self.video_config.frame_rate  # ИСПРАВЛЕНО: используем config.frame_rate
        width, height = self.video_config.width, self.video_config.height  # ИСПРАВЛЕНО: используем config.resolution

        # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: используем time-based формулы для обоих направлений зума
        zoom_range = zoom_intensity - 1.0  # Диапазон изменения зума

        # ИСПРАВЛЕНИЕ #1: Защита от деления на ноль или очень маленькой длительности
        if duration <= 0.001:  # Если длительность клипа слишком мала (например, 0.03с)
            logger.warning(
                f"⚠️ ZOOM: Длительность клипа ({duration:.3f}с) слишком мала для зума. Применяем статический масштаб.")
            # Вернуть просто масштабирование до целевого разрешения без zoompan
            return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps={fps}"

        # ИСПРАВЛЕНИЕ #2: Если zoom_intensity очень близко к 1.0 (нет зума)
        if zoom_range < 0.001:  # Если диапазон зума меньше 0.1%
            logger.warning(
                f"⚠️ ZOOM: Интенсивность зума ({self.config.zoom_intensity}) слишком близка к 1.0. Применяем статический масштаб.")
            # Вернуть просто масштабирование без zoompan
            return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps={fps}"

        # Рассчитываем коэффициент масштабирования времени на основе длительности клипа
        time_scale = zoom_range / duration

        logger.info(
            f"🔍 ZOOM клип {clip_index}: длительность={duration:.2f}с, time_scale={time_scale:.6f}, zoom_range={zoom_range:.3f}")

        if zoom_type == "zoom_in":
            # Zoom In: от 1.0 до zoom_intensity за всю длительность клипа
            # Используем time-based формулу: 1.0 + (zoom_range * t / duration)
            # DEBUG: About to call min() in zoom formula
            logger.debug(f"DEBUG: About to call min() in zoom formula")
            logger.debug(f"DEBUG: zoom_intensity: {zoom_intensity}, time_scale: {time_scale}")
            return f"scale=4000:-1,zoompan=z='min(1.0+{time_scale:.6f}*t,{zoom_intensity})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        elif zoom_type == "zoom_out":
            # Zoom Out: от zoom_intensity к 1.0 за всю длительность клипа
            # Используем time-based формулу: zoom_intensity - (zoom_range * t / duration)
            return f"scale=4000:-1,zoompan=z='max({zoom_intensity:.3f}-{time_scale:.6f}*t,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"

        return ""

    def _get_rotation_filter(self, duration: float) -> str:
        """Генерация фильтра вращения"""
        if self.config.rotation_effect == "none":
            return ""

        # Получаем угол в радианах
        angle_deg = self.config.rotation_angle
        if angle_deg == 0:  # Если угол 0, используем значение по умолчанию
            angle_deg = 5.0

        angle_rad = round(math.radians(angle_deg), 4)

        if self.config.rotation_effect == "sway":
            # Динамическое покачивание: используем числовое значение PI
            sway_frequency = 2.0  # Частота покачивания (циклов за duration)
            freq_calc = round(sway_frequency / duration, 4)
            pi_value = 3.14159265359
            return f"rotate={angle_rad}*sin(2*{pi_value}*t*{freq_calc}):bilinear=0"
        elif self.config.rotation_effect == "rotate_left":
            # Постоянное вращение влево
            rotation_speed = round(angle_rad / duration, 4)  # Скорость вращения
            return f"rotate=-{rotation_speed}*t:bilinear=0"
        elif self.config.rotation_effect == "rotate_right":
            # Постоянное вращение вправо
            rotation_speed = round(angle_rad / duration, 4)
            return f"rotate={rotation_speed}*t:bilinear=0"

        return ""

    def _get_color_filter(self) -> str:
        """Генерация цветового фильтра"""
        if self.config.color_effect == "none":
            return ""
        elif self.config.color_effect == "sepia":
            return "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"
        elif self.config.color_effect == "grayscale":
            return "hue=s=0"
        elif self.config.color_effect == "invert":
            return "negate"
        elif self.config.color_effect == "vintage":
            return "curves=vintage"

        return ""

    def _get_filter_effect(self) -> str:
        """Генерация дополнительных фильтров"""
        if self.config.filter_effect == "none":
            return ""
        elif self.config.filter_effect == "blur":
            return "boxblur=2:1"
        elif self.config.filter_effect == "sharpen":
            return "unsharp=5:5:1.0:5:5:0.0"
        elif self.config.filter_effect == "noise":
            return "noise=alls=20:allf=t"
        elif self.config.filter_effect == "vignette":
            return "vignette=angle=PI/4"

        return ""

    def get_transition_filter(self, duration: float) -> str:
        """
        Генерация фильтра перехода между клипами

        Args:
            duration: Длительность перехода в секундах

        Returns:
            str: FFmpeg фильтр перехода
        """
        # Проверяем типы и валидность входных данных
        if not isinstance(duration, (int, float)) or duration <= 0:
            logger.warning(f"⚠️ Некорректная длительность перехода: {duration}, возвращаем пустую строку")
            return ""

        # Проверяем конфигурацию переходов
        if not self.config or not getattr(self.config, 'transitions_enabled', False):
            logger.debug("🔄 Переходы отключены в конфигурации")
            return ""

        transition_type = getattr(self.config, 'transition_type', 'fade')

        # Проверяем тип перехода
        if not isinstance(transition_type, str):
            logger.warning(f"⚠️ Некорректный тип перехода: {transition_type}, используем 'fade'")
            transition_type = 'fade'

        # Различные типы переходов xfade
        valid_transitions = ["fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown",
                             "slideleft", "slideright", "slideup", "slidedown"]

        if transition_type in valid_transitions:
            filter_str = f"xfade=transition={transition_type}:duration={duration:.3f}"
            logger.debug(f"🔄 Генерирован фильтр перехода: {filter_str}")
            return filter_str
        else:
            logger.warning(f"⚠️ Неизвестный тип перехода: {transition_type}, используем 'fade'")
            return f"xfade=transition=fade:duration={duration:.3f}"


def create_video_effects_config(channel_config: Dict[str, Any]) -> VideoEffectsConfig:
    """
    Создание конфигурации эффектов из настроек канала

    Args:
        channel_config: Словарь с настройками канала

    Returns:
        VideoEffectsConfig: Конфигурация эффектов
    """
    effects_config = VideoEffectsConfig(
        effects_enabled=channel_config.get("video_effects_enabled", False),
        zoom_effect=channel_config.get("video_zoom_effect", "none"),
        zoom_intensity=float(channel_config.get("video_zoom_intensity", 1.1)),
        rotation_effect=channel_config.get("video_rotation_effect", "none"),
        rotation_angle=float(channel_config.get("video_rotation_angle", 5.0)),
        color_effect=channel_config.get("video_color_effect", "none"),
        filter_effect=channel_config.get("video_filter_effect", "none"),
        transitions_enabled=channel_config.get("video_transitions_enabled", False),
        transition_method=channel_config.get("transition_method", "overlay"),
        transition_type=channel_config.get("transition_type", "fade"),
        transition_duration=float(channel_config.get("transition_duration", 0.5)),
        auto_zoom_alternation=channel_config.get("auto_zoom_alternation", True)
    )

    # КРИТИЧЕСКАЯ ПРОВЕРКА И ИСПРАВЛЕНИЕ
    logger.info("🔧 КРИТИЧЕСКАЯ ПРОВЕРКА effects_config:")
    logger.info(f"   transitions_enabled: {effects_config.transitions_enabled}")
    logger.info(f"   transition_method: {effects_config.transition_method}")

    # ПРИНУДИТЕЛЬНОЕ ИСПРАВЛЕНИЕ если нужно
    if effects_config.transitions_enabled and not hasattr(effects_config, 'transition_method'):
        effects_config.transition_method = "xfade"
        logger.info("🔧 ПРИНУДИТЕЛЬНО установлен transition_method = 'xfade'")

    if effects_config.transitions_enabled and effects_config.transition_method != "xfade":
        logger.warning(f"⚠️ transition_method = '{effects_config.transition_method}', принудительно меняем на 'xfade'")
        effects_config.transition_method = "xfade"

    return effects_config


class VideoProcessor:
    """Основной класс для обработки видео"""

    def __init__(self, config: VideoConfig, effects_config: VideoEffectsConfig = None, temp_folder: str = None,
                 excel_path: str = None, preserve_clip_audio_videos: List[int] = None, video_number: int = None):
        self.config = config
        self.effects_config = effects_config or VideoEffectsConfig()
        self.effects_processor = VideoEffectsProcessor(self.effects_config, self.config)
        self.validator = FFmpegValidator()
        self.temp_folder = Path(temp_folder) if temp_folder else Path("./temp_video_proc")
        self.preserve_clip_audio_videos = preserve_clip_audio_videos or []
        self.video_number = video_number

        # Инициализация analyzer для process_single_folder_segment
        if excel_path:
            self.analyzer = MediaAnalyzer(excel_path)
        else:
            self.analyzer = MediaAnalyzer("dummy_excel.xlsx")  # Fallback

        if not self.validator.check_availability():
            raise FFmpegError("FFmpeg недоступен")

    def _should_preserve_clip_audio(self) -> bool:
        """Проверяет, нужно ли сохранять аудио из клипов
        
        Returns:
            True - если video_number есть в preserve_clip_audio_videos
            False - аудио из клипов не сохраняется, используется аудио из папки
        """
        if self.video_number and self.preserve_clip_audio_videos:
            # Приводим video_number к int для корректного сравнения
            try:
                video_number_int = int(self.video_number)
                result = video_number_int in self.preserve_clip_audio_videos
                logger.info(f"🔍 DEBUG VideoProcessor._should_preserve_clip_audio: video_number={self.video_number} -> {video_number_int}, preserve_list={self.preserve_clip_audio_videos}, result={result}")
                return result
            except (ValueError, TypeError):
                logger.warning(f"❌ Не удалось преобразовать video_number в int: {self.video_number}")
                return False
        return False

    def _create_cyclic_extension(self, base_video_path: Path, source_clips: List[str],
                               missing_duration: float, folder_name: str) -> Path:
        """
        Циклично дублирует видео из папки для заполнения недостающего времени
        """
        if not source_clips:
            logger.warning(f"Нет исходных клипов для дублирования в папке {folder_name}")
            return base_video_path

        # Список для конкатенации: исходное видео + повторения
        concat_list = [str(base_video_path)]

        remaining_time = missing_duration
        cycle_index = 0

        logger.info(f"🔄 Папка '{folder_name}': дублируем клипы для заполнения {missing_duration:.2f}с")

        while remaining_time > 0.1:  # Пока есть значимое время для заполнения
            # Берем следующий клип циклично
            source_clip = source_clips[cycle_index % len(source_clips)]
            clip_duration = self.validator.get_media_duration(source_clip)

            if remaining_time >= clip_duration:
                # Добавляем клип целиком
                concat_list.append(source_clip)
                remaining_time -= clip_duration
                logger.debug(f"   Добавлен полный клип: {Path(source_clip).name} ({clip_duration:.2f}с)")
            else:
                # Обрезаем последний клип под оставшееся время
                trimmed_clip_path = Path(self.temp_folder) / f"trimmed_{folder_name}_{cycle_index}.mp4"

                trim_cmd = [
                    ffmpeg_utils_get_ffmpeg_path(), "-i", source_clip,
                    "-t", str(remaining_time),
                    "-c", "copy", "-y", str(trimmed_clip_path)
                ]

                try:
                    run_subprocess_hidden(trim_cmd, check=True, capture_output=True)
                    concat_list.append(str(trimmed_clip_path))
                    logger.debug(f"   Добавлен обрезанный клип: {Path(source_clip).name} ({remaining_time:.2f}с)")
                    remaining_time = 0
                except subprocess.CalledProcessError as e:
                    logger.error(f"❌ Ошибка обрезания клипа {source_clip}: {e}")
                    break

            cycle_index += 1

        # Создаем финальное видео через конкатенацию
        extended_video_path = Path(self.temp_folder) / f"extended_{folder_name}.mp4"

        # Создаем concat файл
        concat_file_path = Path(self.temp_folder) / f"extend_concat_{folder_name}.txt"
        try:
            with open(concat_file_path, 'w') as f:
                for video_path in concat_list:
                    f.write(f"file '{video_path}'\n")

            # Выполняем конкатенацию
            concat_cmd = [
                ffmpeg_utils_get_ffmpeg_path(), "-f", "concat", "-safe", "0",
                "-i", str(concat_file_path),
                "-c", "copy", "-y", str(extended_video_path)
            ]

            run_subprocess_hidden(concat_cmd, check=True, capture_output=True)
            logger.info(f"🔄 Папка '{folder_name}': добавлено {missing_duration:.2f}с через дублирование клипов")
            return extended_video_path
        
        except (subprocess.CalledProcessError, IOError) as e:
            logger.error(f"❌ Ошибка создания расширенного видео для папки '{folder_name}': {e}")
            return base_video_path

    def reencode_video(self, input_path: str, output_path: str, preserve_audio: bool = False,
                       target_duration: Optional[float] = None, clip_index: int = 0) -> bool:
        """
        Перекодирование видео

        Args:
            input_path: Входной файл
            output_path: Выходной файл
            preserve_audio: Сохранять аудио
            target_duration: Целевая длительность

        Returns:
            bool: Успешность операции
        """
        if not Path(input_path).exists():
            logger.error(f"Входной файл не найден: {input_path}")
            return False

        # Создаем директорию для выходного файла
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Получаем длительность входного видео для эффектов
        try:
            input_duration = self.validator.get_media_duration(input_path)
            if target_duration is not None:
                # DEBUG: About to call min() on input_duration calculation
                logger.debug(f"DEBUG: About to call min() on input_duration calculation")
                logger.debug(f"DEBUG: input_duration: {input_duration}, target_duration: {target_duration}")
                input_duration = min(input_duration, target_duration)
        except Exception:
            input_duration = target_duration or 1.0

        # --- ВОССТАНОВЛЕНИЕ КАЧЕСТВЕННЫХ НАСТРОЕК ВИДЕО ---
        # Возвращаем все настройки качества с сохранением совместимости для xfade.
        cmd = [
            get_ffmpeg_path(), "-i", input_path,
            "-vf", self._get_video_filter(clip_index, input_duration),  # ВОССТАНОВЛЕНО: видеофильтр
            "-c:v", self.config.codec,  # ИСПРАВЛЕНО
            "-preset", self.config.preset,  # ИСПРАВЛЕНО
            "-crf", str(self.config.crf),  # ИСПРАВЛЕНО
            "-pix_fmt", "yuv420p",  # Принудительный пиксельный формат для xfade
            "-r", str(self.config.frame_rate),  # ИСПРАВЛЕНО
            "-vsync", "cfr",  # Принудительная постоянная частота кадров для xfade
            "-g", str(self.config.frame_rate * 2),  # ВОССТАНОВЛЕНО: GOP
            "-keyint_min", str(self.config.frame_rate),  # ВОССТАНОВЛЕНО: ключевой кадр
            "-fflags", "+genpts",  # ВОССТАНОВЛЕНО: генерировать PTS
            "-movflags", "+faststart",  # ВОССТАНОВЛЕНО: перемещает moov atom в начало
            "-force_key_frames", "expr:gte(t,0)",  # ВОССТАНОВЛЕНО: принудительные ключевые кадры
            "-probesize", "50M", "-analyzeduration", "50M"  # ВОССТАНОВЛЕНО: анализ входных файлов
        ]

        # Настройки аудио
        if preserve_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.append("-an")

        # Целевая длительность
        if target_duration is not None:
            cmd.extend(["-t", str(target_duration)])

        cmd.extend(["-y", output_path])

        try:
            logger.debug(f"Перекодирование: {Path(input_path).name} -> {Path(output_path).name}")
            result = run_subprocess_hidden(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=600  # 10 минут таймаут
            )

            logger.debug(f"FFmpeg output: {result.stderr}")

            # Проверяем, что файл создан
            if not Path(output_path).exists():
                logger.error(f"❌ Выходной файл не создан: {output_path}")
                return False

            # DEBUG: FFprobe FPS check
            try:
                ffprobe_fps_cmd = [get_ffprobe_path(), "-v", "error", "-show_entries",
                                   "stream=r_frame_rate,avg_frame_rate", "-of", "json", output_path]
                ffprobe_fps_result = run_subprocess_hidden(ffprobe_fps_cmd, capture_output=True, text=True, timeout=10,
                                                    check=False)
                logger.debug(f"DEBUG: FFprobe FPS check for {Path(output_path).name}:\n{ffprobe_fps_result.stdout}")
            except Exception as e:
                logger.debug(f"DEBUG: Failed to check FPS for {Path(output_path).name}: {e}")

            # КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем валидность MP4 после создания
            try:
                # Используем ffprobe для быстрой проверки потоков
                ffprobe_cmd = [get_ffprobe_path(), "-v", "error", "-select_streams", "v", "-show_entries",
                               "stream=codec_type", "-of", "json", output_path]
                ffprobe_result = run_subprocess_hidden(ffprobe_cmd, capture_output=True, text=True, timeout=10, check=False)
                ffprobe_data = json.loads(ffprobe_result.stdout)

                if not ffprobe_data.get('streams'):
                    logger.error(
                        f"❌ FFPROBE ВАЛИДАЦИЯ ПРОВАЛЕНА: Файл {Path(output_path).name} не содержит видеопотоков после перекодирования.")
                    logger.debug(f"FFPROBE stderr для {Path(output_path).name}:\n{ffprobe_result.stderr}")
                    return False

                duration = self.validator.get_media_duration(output_path)
                if duration <= 0:
                    logger.error(
                        f"❌ Некорректная длительность выходного файла: {duration} для {Path(output_path).name}")
                    return False
            except (json.JSONDecodeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                logger.error(f"❌ FFPROBE ВАЛИДАЦИЯ ОШИБКА: Не удалось проверить файл {Path(output_path).name}: {e}")
                logger.debug(
                    f"FFPROBE stderr для {Path(output_path).name}:\n{ffprobe_result.stderr if 'ffprobe_result' in locals() else 'N/A'}")
                return False
            except Exception as e:
                logger.error(f"❌ Общая ошибка валидации выходного файла {Path(output_path).name}: {e}")
                return False

            logger.info(f"✅ Видео успешно перекодировано и валидно: {Path(output_path).name}")
            logger.debug(f"⏳ Ждем 0.1 секунды для завершения записи файла: {Path(output_path).name}")
            time.sleep(0.1)  # Задержка 100 миллисекунд
            return True

        except subprocess.CalledProcessError as e:
            logger.error(
                f"❌ Ошибка перекодирования {input_path}: FFmpeg returned non-zero exit status {e.returncode}. Stderr: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Таймаут при перекодировании {input_path}")
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при перекодировании {input_path}: {e}")
            return False

    def _get_video_filter(self, clip_index: int = 0, total_duration: float = 1.0) -> str:
        """
        Получение фильтра для видео с эффектами

        Args:
            clip_index: Индекс клипа для чередования эффектов
            total_duration: Длительность клипа в секундах
        """
        # Получаем фильтры эффектов
        effects_filter = self.effects_processor.get_video_effects_filter(clip_index, total_duration)

        # Правильный порядок фильтров для zoompan
        base_filters = []

        # Добавляем все эффекты (zoom, rotation, color, filter)
        if effects_filter:
            base_filters.append(effects_filter)
            # После zoompan добавляем format
            base_filters.append(f"format={self.config.pixel_format}")
        else:
            # Если нет эффектов, добавляем стандартное масштабирование
            # ИСПРАВЛЕНИЕ: Используем свойства width и height
            width, height = self.config.width, self.config.height
            base_filters.extend([
                f"fps={self.config.frame_rate}",
                f"format={self.config.pixel_format}",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",  # Используем переменные width, height
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
            ])

        return ",".join(base_filters)

    def extract_first_frame(self, video_path: str, output_path: str) -> bool:
        """Извлечение первого кадра из видео"""
        if not Path(video_path).exists():
            logger.error(f"Видеофайл не найден: {video_path}")
            return False

        cmd = [
            get_ffmpeg_path(), "-i", video_path, "-vf", "select=eq(n\\,0)", "-vframes", "1",
            "-y", output_path
        ]

        try:
            result = run_subprocess_hidden(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=60
            )

            success = Path(output_path).exists()
            if success:
                logger.debug(f"Первый кадр извлечен: {Path(output_path).name}")
            else:
                logger.error(f"Не удалось извлечь первый кадр из {video_path}")

            return success

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Ошибка извлечения первого кадра: {e}")
            return False

    def create_video_from_image(self, image_path: str, output_path: str, duration: float, clip_index: int = 0) -> bool:
        """Создание видео из изображения"""
        logger.debug(
            f"Создание видео из изображения: {Path(image_path).name} -> {Path(output_path).name}, длительность={duration:.2f}с, clip_index={clip_index}")

        if not Path(image_path).exists():
            logger.error(f"Изображение не найдено: {image_path}")
            return False

        # ИСПРАВЛЕНИЕ: Более строгая проверка длительности
        MIN_DURATION = 0.1
        if duration <= 0 or duration != duration:  # Проверка на NaN
            logger.error(f"Некорректная длительность: {duration}. Устанавливаем минимальную: {MIN_DURATION}с")
            duration = MIN_DURATION
        elif duration < MIN_DURATION:
            logger.warning(f"Слишком короткая длительность {duration:.2f}с, увеличиваем до {MIN_DURATION}с")
            duration = MIN_DURATION

        # Создаем директорию для выходного файла
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        video_filter = self._get_video_filter(clip_index, duration)
        logger.debug(f"Используемый видео фильтр: {video_filter}")

        # ОТЛАДКА: проверяем фильтр на наличие проблемных символов
        if "zoom2" in video_filter:
            logger.error(f"ОБНАРУЖЕНА ОШИБКА zoom2 в фильтре: {video_filter}")

        # --- ВОССТАНОВЛЕНИЕ КАЧЕСТВЕННЫХ НАСТРОЕК ВИДЕО ИЗ ИЗОБРАЖЕНИЯ ---
        # Возвращаем все настройки качества с сохранением совместимости для xfade.
        cmd = [
            get_ffmpeg_path(), "-loop", "1", "-i", image_path,
            "-vf", video_filter,  # ВОССТАНОВЛЕНО: ваш видеофильтр
            "-c:v", self.config.codec,  # ИСПРАВЛЕНО
            "-preset", self.config.preset,  # ИСПРАВЛЕНО
            "-crf", str(self.config.crf),  # ИСПРАВЛЕНО
            "-an",  # Без аудио
            "-t", str(duration),  # Длительность из фото/Excel
            "-r", str(self.config.frame_rate),  # ИСПРАВЛЕНО
            "-pix_fmt", "yuv420p",  # Принудительный пиксельный формат для xfade
            "-vsync", "cfr",  # Принудительная постоянная частота кадров для xfade
            "-g", str(self.config.frame_rate * 2),  # ВОССТАНОВЛЕНО: GOP
            "-keyint_min", str(self.config.frame_rate),  # ВОССТАНОВЛЕНО: ключевой кадр
            "-map", "0:v:0", "-map", "-0:s", "-map", "-0:d",  # ВОССТАНОВЛЕНО: маппинг
            "-fflags", "+genpts",  # ВОССТАНОВЛЕНО: генерировать PTS
            "-movflags", "+faststart",  # ВОССТАНОВЛЕНО: перемещает moov atom в начало
            "-force_key_frames", "expr:gte(t,0)",  # ВОССТАНОВЛЕНО: принудительные ключевые кадры
            "-y", output_path
        ]

        # ОТЛАДКА: логируем полную команду
        logger.debug(f"FFmpeg команда: {' '.join(cmd)}")

        try:
            # ИСПРАВЛЕНИЕ: Увеличиваем timeout в зависимости от длительности
            timeout_seconds = max(120, int(duration * 10))  # Минимум 2 минуты, или 10 секунд на каждую секунду видео
            logger.debug(f"Создание видео из изображения с timeout={timeout_seconds}с для duration={duration:.1f}с")

            result = run_subprocess_hidden(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )

            # Проверяем, что файл создан
            if not Path(output_path).exists():
                logger.error(f"❌ Выходной файл не создан: {output_path}")
                return False

            # DEBUG: FFprobe FPS check
            try:
                ffprobe_fps_cmd = [get_ffprobe_path(), "-v", "error", "-show_entries",
                                   "stream=r_frame_rate,avg_frame_rate", "-of", "json", output_path]
                ffprobe_fps_result = run_subprocess_hidden(ffprobe_fps_cmd, capture_output=True, text=True, timeout=10,
                                                    check=False)
                logger.debug(f"DEBUG: FFprobe FPS check for {Path(output_path).name}:\n{ffprobe_fps_result.stdout}")
            except Exception as e:
                logger.debug(f"DEBUG: Failed to check FPS for {Path(output_path).name}: {e}")

            # КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем валидность MP4 после создания
            try:
                ffprobe_cmd = [get_ffprobe_path(), "-v", "error", "-select_streams", "v", "-show_entries",
                               "stream=codec_type", "-of", "json", output_path]
                ffprobe_result = run_subprocess_hidden(ffprobe_cmd, capture_output=True, text=True, timeout=10, check=False)
                ffprobe_data = json.loads(ffprobe_result.stdout)

                if not ffprobe_data.get('streams'):
                    logger.error(
                        f"❌ FFPROBE ВАЛИДАЦИЯ ПРОВАЛЕНА: Файл {Path(output_path).name} не содержит видеопотоков после создания.")
                    logger.debug(f"FFPROBE stderr для {Path(output_path).name}:\n{ffprobe_result.stderr}")
                    return False

                actual_duration = self.validator.get_media_duration(output_path)
                if actual_duration <= 0:
                    logger.error(
                        f"❌ Некорректная длительность выходного файла: {actual_duration} для {Path(output_path).name}")
                    return False
            except (json.JSONDecodeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                logger.error(f"❌ FFPROBE ВАЛИДАЦИЯ ОШИБКА: Не удалось проверить файл {Path(output_path).name}: {e}")
                logger.debug(
                    f"FFPROBE stderr для {Path(output_path).name}:\n{ffprobe_result.stderr if 'ffprobe_result' in locals() else 'N/A'}")
                return False
            except Exception as e:
                logger.error(f"❌ Общая ошибка валидации выходного файла {Path(output_path).name}: {e}")
                return False

            logger.debug(
                f"✅ Видео создано из изображения и валидно: {Path(image_path).name} -> {Path(output_path).name}")
            logger.debug(f"⏳ Ждем 0.1 секунды для завершения записи файла: {Path(output_path).name}")
            time.sleep(0.1)  # Задержка 100 миллисекунд
            return True

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"❌ Ошибка создания видео из изображения {image_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при создании видео из изображения {image_path}: {e}")
            return False

    def process_single_folder_segment(self,
                                      folder_name: str,
                                      media_files_in_folder: List[str],
                                      folder_target_duration: float,
                                      folder_audio_path: str,  # Путь к готовому аудиофайлу для этой папки
                                      segment_output_path: str  # Куда сохранить готовый сегмент
                                      ) -> Optional[str]:
        """
        Полностью обрабатывает один сегмент папки (видеоряд + эффекты + переходы + микширование аудио).

        Args:
            folder_name: Имя папки (например, "1-5").
            media_files_in_folder: Список путей к медиафайлам (фото/видео) в этой папке.
            folder_target_duration: Целевая длительность этого сегмента из Excel/аудио.
            folder_audio_path: Путь к объединенному аудиофайлу, предназначенному для этой папки.
            segment_output_path: Путь для сохранения финального видеосегмента с аудио.

        Returns:
            Путь к готовому видеофайлу сегмента (MP4) или None в случае ошибки.
        """
        try:
            logger.info(f"🎬 Обработка сегмента папки '{folder_name}' (цель: {folder_target_duration:.2f}с)")
            logger.info(f"   Медиафайлов: {len(media_files_in_folder)}")
            logger.info(f"   Аудио для папки: {folder_audio_path}")

            # ДОБАВИТЬ: Диагностика входящих файлов
            logger.info(f"📋 Входящие файлы для папки '{folder_name}':")
            for i, file_path in enumerate(media_files_in_folder):
                # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ!
                try:
                    import montage_control
                    if montage_control.check_stop_flag(f"video_processing цикл медиафайлов {i+1}"):
                        logger.error("🛑 ОСТАНОВКА МОНТАЖА в video_processing!")
                        return None
                except:
                    pass
                    
                logger.info(f"   {i + 1}. {Path(file_path).name}")

            # НОВАЯ ПРОВЕРКА: Валидация входных данных
            if not media_files_in_folder:
                logger.error(f"❌ Нет медиафайлов для папки '{folder_name}'")
                return None

            if folder_target_duration <= 0:
                logger.error(
                    f"❌ Некорректная целевая длительность для папки '{folder_name}': {folder_target_duration}с")
                return None

            if not Path(folder_audio_path).exists():
                logger.error(f"❌ Аудиофайл не найден для папки '{folder_name}': {folder_audio_path}")
                return None

            # НОВАЯ ПРОВЕРКА: Убеждаемся что все медиафайлы существуют
            existing_media_files = []
            for file_path in media_files_in_folder:
                if Path(file_path).exists():
                    existing_media_files.append(file_path)
                else:
                    logger.warning(f"⚠️ Медиафайл не найден: {file_path}")

            if not existing_media_files:
                logger.error(f"❌ Ни одного существующего медиафайла не найдено для папки '{folder_name}'")
                return None

            media_files_in_folder = existing_media_files
            logger.info(f"✅ Проверка медиафайлов: {len(media_files_in_folder)} файлов существует")

            # НОВАЯ ПРОВЕРКА: Проверяем длительность аудиофайла
            audio_duration = self.validator.get_media_duration(folder_audio_path)
            if audio_duration <= 0:
                logger.error(f"❌ Некорректная длительность аудиофайла для папки '{folder_name}': {audio_duration}с")
                return None

            # ДИАГНОСТИКА: сравниваем длительности
            logger.info(f"📊 Сравнение длительностей для папки '{folder_name}':")
            logger.info(f"   Целевая длительность (из Excel): {folder_target_duration:.2f}с")
            logger.info(f"   Длительность аудиофайла: {audio_duration:.2f}с")
            logger.info(f"   Разница: {abs(folder_target_duration - audio_duration):.2f}с")

            # 1. Рассчитываем последовательность медиафайлов (длительность каждого клипа)
            # Эта функция теперь будет возвращать скорреректированные длительности
            media_sequence = self.analyzer.calculate_media_sequence_for_folder(
                media_files_in_folder,
                folder_target_duration,
                folder_name,
                transitions_enabled=self.effects_config.transitions_enabled,
                transition_duration=self.effects_config.transition_duration
            )

            if not media_sequence:
                logger.error(f"❌ Не удалось рассчитать последовательность медиа для '{folder_name}'.")
                return None

            # 2. Обрабатываем каждый клип в последовательности (фото -> видео, перекодировка видео)
            processed_clips_paths = []
            clips_info_for_folder = []  # Информация для ConcatenationHelper

            for i, seq_item in enumerate(media_sequence):
                file_path = seq_item['file']
                target_clip_duration = seq_item['duration']
                seq_type = seq_item['type']

                ext = Path(file_path).suffix.lower()
                # Используем уникальное имя для обработанного клипа
                output_clip_path = Path(self.temp_folder) / f"processed_{folder_name}_{i}_{Path(file_path).stem}.mp4"

                has_audio = False
                success = False

                if ext in ('.mp4', '.mov'):
                    has_audio = self.validator.has_audio_stream(file_path)  # Проверяем оригинальный файл
                    should_preserve_clip_audio = self._should_preserve_clip_audio()
                    
                    if has_audio and not should_preserve_clip_audio:  # Если аудио есть, но его не надо сохранять
                        logger.info(f"   Видео '{Path(file_path).name}' содержит аудио, но оно не сохраняется (preserve_clip_audio=False).")
                        has_audio = False  # Отключаем флаг для рекодирования
                    elif has_audio and should_preserve_clip_audio:
                        logger.info(f"   Видео '{Path(file_path).name}' содержит аудио, оно будет сохранено (preserve_clip_audio=True).")

                    # При рекодировании видео из папки, решаем сохранять ли аудио клипа
                    success = self.reencode_video(
                        file_path, str(output_clip_path),
                        preserve_audio=should_preserve_clip_audio,  # Сохраняем аудио клипа если preserve_clip_audio=True
                        target_duration=target_clip_duration,
                        clip_index=i  # Используем i как clip_index для эффектов
                    )
                else:  # Фото
                    success = self.create_video_from_image(
                        file_path, str(output_clip_path),
                        target_clip_duration, i  # Используем i как clip_index для эффектов
                    )

                if success and output_clip_path.exists():
                    processed_clips_paths.append(str(output_clip_path))
                    actual_duration = self.validator.get_media_duration(str(output_clip_path))
                    clips_info_for_folder.append({
                        "path": str(output_clip_path),
                        "duration": actual_duration,
                        "has_audio": False,  # Аудио будет добавлено на следующем этапе
                        "original_file": str(file_path),
                        "folder": folder_name,
                        "type": seq_type
                    })
                    logger.debug(
                        f"   ✅ Обработан клип {Path(file_path).name} -> {Path(output_clip_path).name} ({actual_duration:.2f}с, целевая {target_clip_duration:.2f}с)")
                else:
                    logger.error(f"❌ Не удалось обработать клип: {Path(file_path).name}. Пропускаем.")
                    return None  # Critical error, stop processing this folder

            if not processed_clips_paths:
                logger.error(f"❌ Нет обработанных клипов для сегмента '{folder_name}'.")
                return None

            # 3. Конкатенация обработанных клипов для этой папки (с переходами или без)
            temp_video_segment_no_audio = Path(self.temp_folder) / f"temp_video_segment_{folder_name}.mp4"
            should_preserve_clip_audio = self._should_preserve_clip_audio()

            # 3. ПРИМЕНЯЕМ XFADE ВНУТРИ ЭТОЙ ПАПКИ ТОЛЬКО ЕСЛИ ПЕРЕХОДЫ ВКЛЮЧЕНЫ
            # ДИАГНОСТИКА настроек переходов
            logger.info(f"🔍 ДИАГНОСТИКА переходов для папки '{folder_name}':")
            logger.info(f"   effects_config существует: {self.effects_config is not None}")
            if self.effects_config:
                transitions_enabled_value = getattr(self.effects_config, 'transitions_enabled', None)
                transition_method_value = getattr(self.effects_config, 'transition_method', None)
                logger.info(f"   transitions_enabled: {transitions_enabled_value} (тип: {type(transitions_enabled_value)})")
                logger.info(f"   transition_method: '{transition_method_value}' (тип: {type(transition_method_value)})")
                logger.info(f"   transition_method == 'xfade': {transition_method_value == 'xfade'}")
            
            transitions_enabled = (
                self.effects_config and 
                getattr(self.effects_config, 'transitions_enabled', False) and
                getattr(self.effects_config, 'transition_method', '') == 'xfade'
            )
            
            logger.info(f"   Итоговое решение - transitions_enabled: {transitions_enabled}")
            
            if len(processed_clips_paths) > 1 and transitions_enabled:
                logger.info(
                    f"🔄 Применяем XFADE переходы внутри папки '{folder_name}' ({len(processed_clips_paths)} файлов)")
                success = self._concatenate_folder_with_xfade(
                    processed_clips_paths,
                    temp_video_segment_no_audio,
                    folder_target_duration,
                    folder_name
                )
            elif len(processed_clips_paths) > 1:
                logger.info(f"📼 Простая конкатенация в папке '{folder_name}' (переходы отключены)")
                try:
                    if should_preserve_clip_audio:
                        result = self._concatenate_simple_with_audio(processed_clips_paths, temp_video_segment_no_audio, folder_target_duration)
                    else:
                        result = self._concatenate_simple_no_audio(processed_clips_paths, temp_video_segment_no_audio, folder_target_duration)
                    success = result is not None and temp_video_segment_no_audio.exists()
                except Exception as e:
                    logger.error(f"❌ Ошибка простой конкатенации: {e}")
                    success = False
            else:
                # Один файл - просто копируем
                logger.info(f"📄 Один файл в папке '{folder_name}' - копируем")
                shutil.copy2(processed_clips_paths[0], temp_video_segment_no_audio)
                success = True
                
            # Обработка fallback'ов для XFade
            if len(processed_clips_paths) > 1 and transitions_enabled and not success:
                logger.warning(f"⚠️ XFADE не удался для папки '{folder_name}', используем простую конкатенацию")
                if should_preserve_clip_audio:
                    self._concatenate_simple_with_audio(processed_clips_paths, temp_video_segment_no_audio, folder_target_duration)
                else:
                    self._concatenate_simple_no_audio(processed_clips_paths, temp_video_segment_no_audio, folder_target_duration)

            if not temp_video_segment_no_audio.exists():
                logger.error(f"❌ Видеоряд для сегмента '{folder_name}' не создан.")
                return None

            # 4. Микширование видеоряда сегмента с его аудио
            logger.info(f"🎵 Микшируем видеоряд сегмента '{folder_name}' с аудио: {folder_audio_path}")

            # Ensure folder_audio_path exists and has duration
            if not Path(folder_audio_path).exists() or self.validator.get_media_duration(folder_audio_path) <= 0:
                logger.error(
                    f"❌ Аудиофайл для папки '{folder_name}' недействителен или отсутствует: {folder_audio_path}")
                # Если нет аудио, то просто копируем видеофайл и возвращаем его
                shutil.copy2(str(temp_video_segment_no_audio), str(segment_output_path))
                logger.warning(f"⚠️ Сегмент '{folder_name}' будет без аудио из-за ошибки.")
                return str(segment_output_path)

            # Перекодируем видеоряд в temp_video_segment_no_audio, чтобы он имел аудиодорожку.
            # Если видеоряд слишком короткий, то его нужно будет расширить до длительности аудио.
            actual_video_segment_duration = self.validator.get_media_duration(str(temp_video_segment_no_audio))
            actual_audio_segment_duration = self.validator.get_media_duration(str(folder_audio_path))

            # ИСПРАВЛЕНИЕ: используем целевую длительность папки, которая уже включает компенсацию fade-переходов
            # вместо фактической длительности аудио, которая может не учитывать видео-компенсацию
            desired_output_segment_duration = folder_target_duration
            
            logger.info(f"📏 ДЛИТЕЛЬНОСТИ сегмента '{folder_name}':")
            logger.info(f"   Целевая длительность папки (с компенсацией): {folder_target_duration:.2f}с")
            logger.info(f"   Фактическая длительность аудио: {actual_audio_segment_duration:.2f}с")
            logger.info(f"   Используем для видео: {desired_output_segment_duration:.2f}с")

            # Проверяем, что выходной файл аудио не нулевой.
            if actual_audio_segment_duration == 0.0:
                logger.error(f"❌ Аудиофайл {folder_audio_path} имеет нулевую длительность. Невозможно микшировать.")
                shutil.copy2(str(temp_video_segment_no_audio), str(segment_output_path))
                return str(segment_output_path)

            video_filter_parts = [f"[0:v]setpts=PTS-STARTPTS"]  # Сбрасываем временные метки для видео

            # ДИАГНОСТИКА: проверяем необходимость повторения
            duration_diff = desired_output_segment_duration - actual_video_segment_duration
            logger.info(f"🔍 ДИАГНОСТИКА повторения сегмента '{folder_name}':")
            logger.info(f"   Желаемая длительность: {desired_output_segment_duration:.2f}с")
            logger.info(f"   Фактическая длительность: {actual_video_segment_duration:.2f}с") 
            logger.info(f"   Разница: {duration_diff:.2f}с")
            
            # ИСПРАВЛЕНИЕ: Увеличиваем толерантность для fade-переходов (было 0.1, стало 0.5)
            # Это предотвратит ненужное повторение из-за небольших неточностей компенсации
            if actual_video_segment_duration < desired_output_segment_duration - 0.5:  # Видео короче, дублируем клипы
                logger.warning(f"⚠️ АКТИВИРОВАНО ПОВТОРЕНИЕ: недостаток {duration_diff:.2f}с превышает толерантность 0.5с")
                # ВМЕСТО фриза - циклично дублируем видео из папки
                missing_duration = desired_output_segment_duration - actual_video_segment_duration
                
                # Берем processed_clips_paths (уже обработанные видео этой папки)
                clips_to_repeat = processed_clips_paths.copy()
                
                # Создаем цикличную последовательность до заполнения времени
                extended_video_path = self._create_cyclic_extension(
                    temp_video_segment_no_audio,
                    clips_to_repeat,
                    missing_duration,
                    folder_name
                )
                
                # Заменяем исходное видео на расширенное
                temp_video_segment_no_audio = extended_video_path
                
                # Пересчитываем длительность
                actual_video_segment_duration = self.validator.get_media_duration(str(temp_video_segment_no_audio))
                
                logger.info(
                    f"🔄 Видеоряд папки '{folder_name}' расширен через дублирование клипов на {missing_duration:.3f}с")
                
                # Очистка video_filter_parts - больше не нужно
                video_filter_parts = [f"[0:v]setpts=PTS-STARTPTS"]
            elif actual_video_segment_duration > desired_output_segment_duration + 0.1:  # Видео длиннее, обрезаем
                trim_duration = desired_output_segment_duration
                video_filter_parts.append(f"trim=end={trim_duration:.3f}")
                logger.info(
                    f"🔧 Видеоряд папки '{folder_name}' ({actual_video_segment_duration:.2f}с) длиннее аудио. Обрезано до: {trim_duration:.3f}с")

            # Микширование с учетом preserve_clip_audio
            should_preserve_clip_audio = self._should_preserve_clip_audio()
            
            if should_preserve_clip_audio and self.validator.has_audio_stream(str(temp_video_segment_no_audio)):
                # Микшируем аудио клипов с аудио папки
                logger.info(f"🎵 Микшируем аудио клипов с аудио папки для сегмента '{folder_name}'")
                cmd_mix = [
                    ffmpeg_utils_get_ffmpeg_path(),
                    "-i", str(temp_video_segment_no_audio),  # Видео с аудио клипов
                    "-i", str(folder_audio_path),  # Аудио для этой папки
                    "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=shortest:dropout_transition=2[aout]",  # Микшируем аудио
                    "-map", "0:v",  # Маппим видеопоток
                    "-map", "[aout]",  # Маппим смикшированное аудио
                    "-c:v", "libx264",  # Кодек видео
                    "-preset", self.config.preset,
                    "-crf", str(self.config.crf),
                    "-c:a", "aac", "-b:a", "128k",  # Кодек аудио
                    "-shortest",  # Обрезаем по самому короткому
                    "-y", str(segment_output_path)
                ]
            else:
                # Простое замещение - используем только аудио папки
                logger.info(f"🎵 Используем только аудио папки для сегмента '{folder_name}'")
                cmd_mix = [
                    ffmpeg_utils_get_ffmpeg_path(),
                    "-i", str(temp_video_segment_no_audio),  # Видео (может быть с аудио или без)
                    "-i", str(folder_audio_path),  # Аудио для этой папки
                    "-map", "0:v",  # Маппим видеопоток
                    "-map", "1:a",  # Маппим только аудио папки
                    "-c:v", "libx264",  # Кодек видео
                    "-preset", self.config.preset,
                    "-crf", str(self.config.crf),
                    "-c:a", "aac", "-b:a", "128k",  # Кодек аудио
                    "-shortest",  # Обрезаем по самому короткому
                    "-y", str(segment_output_path)
                ]

            logger.debug(f"Микширование сегмента {folder_name} (команда): {' '.join(cmd_mix)}")

            try:
                run_subprocess_hidden(cmd_mix, check=True, capture_output=True, text=True, timeout=600)  # Увеличен таймаут для микширования
            except subprocess.CalledProcessError as e:
                logger.error(f"❌ Ошибка микширования видеоряда с аудио для сегмента '{folder_name}': {e.stderr}")
                return None
            except subprocess.TimeoutExpired:
                logger.error(f"❌ Таймаут при микшировании видеоряда с аудио для сегмента '{folder_name}'.")
                return None

            if Path(segment_output_path).exists() and self.validator.get_media_duration(str(segment_output_path)) > 0:
                final_actual_duration = self.validator.get_media_duration(str(segment_output_path))
                logger.info(
                    f"✅ Сегмент папки '{folder_name}' успешно создан: {Path(segment_output_path).name} ({final_actual_duration:.2f}с)")
                return str(segment_output_path)
            else:
                logger.error(f"❌ Финальный файл сегмента '{folder_name}' не создан или пуст: {segment_output_path}")
                return None

        # Обработка исключений - широкий блок для отлова критических ошибок
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при обработке сегмента папки '{folder_name}': {e}")
            logger.error(f"   Папка: {folder_name}, целевая длительность: {folder_target_duration}с")
            logger.error(f"   Медиафайлов: {len(media_files_in_folder) if media_files_in_folder else 0}")
            logger.error(f"   Аудиофайл: {folder_audio_path}")
            import traceback
            logger.error(f"   Детали ошибки: {traceback.format_exc()}")
            return None

    def _concatenate_with_xfade_transitions(self, video_files: List[str], output_path: Path,
                                            target_duration: float) -> bool:
        """ИСПРАВЛЕННАЯ конкатенация с XFADE переходами"""
        logger.info(f"🚀 XFADE конкатенация {len(video_files)} файлов")

        # РАСШИРЕННАЯ ДИАГНОСТИКА
        logger.info("🔍 РАСШИРЕННАЯ ДИАГНОСТИКА XFADE:")
        logger.info(f"   effects_config type: {type(self.effects_config)}")
        logger.info(f"   effects_config is None: {self.effects_config is None}")

        if self.effects_config:
            logger.info(f"   effects_config.__dict__: {self.effects_config.__dict__}")
            logger.info(f"   transitions_enabled: {getattr(self.effects_config, 'transitions_enabled', 'ОТСУТСТВУЕТ')}")
            logger.info(f"   transition_method: {getattr(self.effects_config, 'transition_method', 'ОТСУТСТВУЕТ')}")
            logger.info(f"   transition_type: {getattr(self.effects_config, 'transition_type', 'ОТСУТСТВУЕТ')}")
            logger.info(f"   transition_duration: {getattr(self.effects_config, 'transition_duration', 'ОТСУТСТВУЕТ')}")

        try:
            if len(video_files) < 2:
                # Если файл один, просто копируем
                shutil.copy2(video_files[0], str(output_path))
                logger.info("✅ Один файл - копируем без переходов")
                return True

            # Получаем параметры переходов
            transition_type = getattr(self.effects_config, 'transition_type', 'fade')
            transition_duration = getattr(self.effects_config, 'transition_duration', 0.5)

            logger.info(f"🎯 XFADE параметры: тип={transition_type}, длительность={transition_duration}с")

            # Строим filter_complex для xfade переходов
            filter_parts = []
            inputs = []

            # Добавляем все входные файлы
            for i, video_file in enumerate(video_files):
                # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ!
                try:
                    import montage_control
                    if montage_control.check_stop_flag(f"video_processing xfade цикл {i+1}"):
                        logger.error("🛑 ОСТАНОВКА МОНТАЖА в xfade обработке!")
                        return False
                except:
                    pass
                    
                inputs.extend(["-i", video_file])

            # Строим цепочку xfade переходов
            if len(video_files) == 2:
                # Простой случай - два видео
                filter_parts.append(
                    f"[0:v][1:v]xfade=transition={transition_type}:duration={transition_duration:.3f}[out]")
                final_output = "[out]"
            else:
                # Множественные переходы
                current_input = "[0:v]"
                for i in range(1, len(video_files)):
                    if i == len(video_files) - 1:
                        # Последний переход
                        filter_parts.append(
                            f"{current_input}[{i}:v]xfade=transition={transition_type}:duration={transition_duration:.3f}[out]")
                        final_output = "[out]"
                    else:
                        # Промежуточный переход
                        filter_parts.append(
                            f"{current_input}[{i}:v]xfade=transition={transition_type}:duration={transition_duration:.3f}[v{i}]")
                        current_input = f"[v{i}]"

            filter_complex = ";".join(filter_parts)
            logger.info(f"🎞️ XFADE filter_complex: {filter_complex}")

            # Строим команду FFmpeg
            cmd = [get_ffmpeg_path(), "-y"] + inputs + [
                "-filter_complex", filter_complex,
                "-map", final_output,
                "-c:v", "libx264",
                "-preset", self.config.video_preset,
                "-crf", str(self.config.video_crf),
                "-pix_fmt", "yuv420p",
                "-r", str(self.config.frame_rate),
                "-t", str(target_duration),
                "-an",  # Без аудио
                str(output_path)
            ]

            logger.info("🎬 Запускаем XFADE обработку...")
            logger.debug(f"XFADE команда: {' '.join(cmd)}")

            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=600)

            if output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"✅ XFADE переходы созданы: {output_path.name}")
                return True
            else:
                logger.error(f"❌ XFADE файл не создан: {output_path}")
                return False

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ XFADE FFmpeg ошибка: код {e.returncode}")
            logger.error(f"❌ stderr: {e.stderr}")
            logger.error(f"❌ stdout: {e.stdout}")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка XFADE переходов: {e}")
            return False

    def _concatenate_with_simple_transitions(self, video_files: List[str], output_path: Path,
                                             target_duration: float) -> bool:
        """Fallback простая конкатенация если XFADE не работает"""
        logger.warning(f"⚠️ Используем простую конкатенацию вместо XFADE для {len(video_files)} файлов")

        # Сначала пробуем XFADE
        if self.effects_config and getattr(self.effects_config, 'transition_method', '') == 'xfade':
            logger.info("🔄 Пробуем XFADE переходы...")
            if self._concatenate_with_xfade_transitions(video_files, output_path, target_duration):
                return True
            logger.warning("⚠️ XFADE не удался, используем простую конкатенацию")

        try:
            if len(video_files) < 2:
                shutil.copy2(video_files[0], str(output_path))
                return True

            # Создаем список для concat
            concat_list_path = Path(self.temp_folder) / f"simple_transitions_{output_path.stem}.txt"

            with open(concat_list_path, 'w') as f:
                for video_file in video_files:
                    f.write(f"file '{video_file}'\n")

            # Простая конкатенация без переходов
            cmd = [
                get_ffmpeg_path(),
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list_path),
                "-c:v", "libx264",
                "-preset", self.config.video_preset,
                "-crf", str(self.config.video_crf),
                "-pix_fmt", "yuv420p",
                "-r", str(self.config.frame_rate),
                "-t", str(target_duration),
                "-an",  # Без аудио
                "-y", str(output_path)
            ]

            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=900)  # Увеличен таймаут для XFADE

            if output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"✅ Простые переходы созданы: {output_path.name}")
                return True
            else:
                logger.error(f"❌ Файл с переходами не создан: {output_path}")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка создания простых переходов: {e}")
            return False

    def _concatenate_simple_no_audio(self, video_files: List[str], output_path: Path, target_duration: float) -> str:
        """Простая конкатенация видео без аудио, БЕЗ принудительного ограничения длительности."""
        logger.info(f"📼 Простая конкатенация видеоряда ({len(video_files)} файлов) без аудио для: {output_path.name}")

        concat_list_path = Path(self.temp_folder) / f"concat_list_{output_path.stem}.txt"
        with open(concat_list_path, 'w') as f:
            for video_file in video_files:
                f.write(f"file '{video_file}'\n")

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
            # ИСПРАВЛЕНИЕ: НЕ ДОБАВЛЯЕМ -t target_duration здесь!
            # "-t", str(target_duration), # <-- УБИРАЕМ ЭТУ СТРОКУ
            "-an",  # Без аудио
            "-y", str(output_path)
        ]

        logger.debug(f"Простая конкатенация видеоряда CMD: {' '.join(cmd)}")
        try:
            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=600)  # Увеличен таймаут для конкатенации
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка простой конкатенации видеоряда: {e.stderr}")
            raise VideoProcessingError(f"Ошибка простой конкатенации видеоряда: {e.stderr}")
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Таймаут при простой конкатенации видеоряда.")
            raise VideoProcessingError(f"Таймаут при простой конкатенации видеоряда.")

        if output_path.exists():
            actual_duration = get_media_duration(str(output_path))
            logger.info(f"✅ Видеоряд сегмента создан: {output_path.name} (длительность: {actual_duration:.2f}с)")
            return str(output_path)
        else:
            raise VideoProcessingError(f"Видеоряд сегмента не создан: {output_path.name}")

    def _concatenate_simple_with_audio(self, video_files: List[str], output_path: Path, target_duration: float) -> str:
        """Простая конкатенация видео С СОХРАНЕНИЕМ аудио клипов."""
        logger.info(f"📼 Простая конкатенация видеоряда ({len(video_files)} файлов) С АУДИО для: {output_path.name}")

        concat_list_path = Path(self.temp_folder) / f"concat_list_{output_path.stem}_with_audio.txt"
        with open(concat_list_path, 'w') as f:
            for video_file in video_files:
                f.write(f"file '{video_file}'\n")

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
            "-c:a", "aac",  # Кодируем аудио в AAC
            "-b:a", "128k",  # Битрейт аудио
            # НЕ добавляем -an, чтобы сохранить аудио клипов
            "-y", str(output_path)
        ]

        logger.debug(f"Простая конкатенация видеоряда С АУДИО CMD: {' '.join(cmd)}")
        try:
            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=600)  # Увеличен таймаут для конкатенации
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка простой конкатенации видеоряда с аудио: {e.stderr}")
            raise VideoProcessingError(f"Ошибка простой конкатенации видеоряда с аудио: {e.stderr}")
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Таймаут при простой конкатенации видеоряда с аудио.")
            raise VideoProcessingError(f"Таймаут при простой конкатенации видеоряда с аудио.")

        if output_path.exists():
            actual_duration = get_media_duration(str(output_path))
            logger.info(f"✅ Видеоряд сегмента С АУДИО создан: {output_path.name} (длительность: {actual_duration:.2f}с)")
            return str(output_path)
        else:
            raise VideoProcessingError(f"Видеоряд сегмента с аудио не создан: {output_path.name}")

    def _concatenate_folder_with_xfade(self, video_files: List[str], output_path: Path,
                                       target_duration: float, folder_name: str) -> bool:
        """
        ИСПРАВЛЕННАЯ конкатенация файлов внутри папки с XFADE
        """
        logger.info(f"🎬 XFADE внутри папки '{folder_name}': {len(video_files)} файлов")
        logger.info(f"   Целевая длительность: {target_duration:.2f}с")

        try:
            # ИСПРАВЛЕНИЕ: Получаем параметры переходов из конфигурации
            transition_type = getattr(self.effects_config, 'transition_type', 'fade')
            transition_duration = getattr(self.effects_config, 'transition_duration', 0.5)
            
            logger.info(f"   Параметры переходов: тип={transition_type}, длительность={transition_duration}с")

            # Получаем длительности файлов
            file_durations = []
            total_input_duration = 0
            for video_file in video_files:
                duration = self.validator.get_media_duration(video_file)
                file_durations.append(duration)
                total_input_duration += duration
                logger.debug(f"   {Path(video_file).name}: {duration:.2f}с")

            # ПРАВИЛЬНЫЙ расчет ожидаемой длительности после XFADE
            num_transitions = len(video_files) - 1
            total_transition_loss = num_transitions * transition_duration
            expected_output_duration = total_input_duration - total_transition_loss

            logger.info(f"🔄 XFADE расчеты:")
            logger.info(f"   Входная длительность: {total_input_duration:.2f}с")
            logger.info(f"   Переходов: {num_transitions}")
            logger.info(f"   Потеря на переходах: {total_transition_loss:.2f}с")
            logger.info(f"   Ожидаемая выходная: {expected_output_duration:.2f}с")
            logger.info(f"   Целевая длительность: {target_duration:.2f}с")

            # ПРОВЕРКА: соответствует ли ожидаемая длительность целевой
            duration_difference = abs(expected_output_duration - target_duration)
            if duration_difference > 1.0:
                logger.debug(
                    f"Разница между ожидаемой ({expected_output_duration:.2f}с) и целевой ({target_duration:.2f}с) длительностями: {duration_difference:.2f}с")
                logger.debug(
                    f"Возможно, компенсация была применена неправильно в calculate_media_sequence_for_folder")

            # Строим команду FFmpeg
            cmd = [get_ffmpeg_path(), "-v", "error"]  # Убираем debug для производительности

            # Добавляем входные файлы
            for video_file in video_files:
                cmd.extend(["-i", video_file])

            # Получаем разрешение
            width = self.config.width
            height = self.config.height

            # Строим filter_complex
            filter_parts = []

            # Нормализуем входные видео
            for i in range(len(video_files)):
                normalize_filter = (
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                    f"fps={self.config.frame_rate},"
                    f"format=yuv420p"
                    f"[v{i}_norm]"
                )
                filter_parts.append(normalize_filter)

            # Создаем цепочку XFADE с ПРАВИЛЬНЫМИ offset'ами
            current_stream = "[v0_norm]"
            cumulative_time = file_durations[0]

            for i in range(len(video_files) - 1):
                # ПРАВИЛЬНЫЙ расчет offset: когда начинать переход
                # Переход должен начинаться за transition_duration секунд до конца текущего клипа
                offset = cumulative_time - transition_duration
                offset = max(0.1, offset)  # Минимальный offset

                if i == len(video_files) - 2:
                    output_stream = "[out]"
                else:
                    output_stream = f"[vx{i}]"

                xfade_filter = f"{current_stream}[v{i + 1}_norm]xfade=transition={transition_type}:duration={transition_duration:.3f}:offset={offset:.3f}{output_stream}"
                filter_parts.append(xfade_filter)
                current_stream = output_stream

                # Обновляем cumulative_time для следующего перехода
                cumulative_time += file_durations[i + 1] - transition_duration
                logger.debug(f"   Переход {i + 1}: offset={offset:.3f}с, cumulative={cumulative_time:.3f}с")

            filter_complex = ";".join(filter_parts)

            # НЕ добавляем -t для ограничения длительности!
            # Пусть XFADE сам определит финальную длительность
            should_preserve_clip_audio = self._should_preserve_clip_audio()
            
            if should_preserve_clip_audio:
                # Сохраняем аудио при XFADE
                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[out]",
                    "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                    "-pix_fmt", "yuv420p", "-r", str(self.config.frame_rate),
                    "-c:a", "aac", "-b:a", "128k",  # Сохраняем аудио клипов
                    "-y", str(output_path)
                ])
                logger.info(f"🎵 XFADE с сохранением аудио клипов для папки '{folder_name}'")
            else:
                # Удаляем аудио при XFADE
                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[out]",
                    "-c:v", "libx264", "-preset", self.config.video_preset, "-crf", str(self.config.video_crf),
                    "-pix_fmt", "yuv420p", "-r", str(self.config.frame_rate),
                    "-an",  # Без аудио
                    "-y", str(output_path)
                ])
                logger.info(f"🎵 XFADE без аудио клипов для папки '{folder_name}'")

            logger.info(f"🎬 Выполняем XFADE для папки '{folder_name}'...")
            logger.debug(f"XFADE команда: {' '.join(cmd)}")

            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=900)  # Увеличен таймаут для XFADE

            if output_path.exists() and output_path.stat().st_size > 0:
                actual_output_duration = self.validator.get_media_duration(str(output_path))
                logger.info(f"✅ XFADE внутри папки '{folder_name}' завершен:")
                logger.info(f"   Фактическая длительность: {actual_output_duration:.2f}с")
                logger.info(f"   Ожидалось: {expected_output_duration:.2f}с")
                logger.info(f"   Целевая: {target_duration:.2f}с")

                # Анализ точности
                diff_expected = abs(actual_output_duration - expected_output_duration)
                diff_target = abs(actual_output_duration - target_duration)

                if diff_expected < 1.0:
                    logger.info(f"   ✅ XFADE работает точно (разница с ожидаемой: {diff_expected:.2f}с)")
                else:
                    logger.warning(f"   ⚠️ XFADE неточный (разница с ожидаемой: {diff_expected:.2f}с)")

                if diff_target < 1.0:
                    logger.info(f"   ✅ Цель достигнута (разница с целевой: {diff_target:.2f}с)")
                else:
                    logger.warning(f"   ⚠️ Цель не достигнута (разница с целевой: {diff_target:.2f}с)")
                    logger.warning(f"   💡 Проверьте компенсацию в calculate_media_sequence_for_folder")

                return True
            else:
                logger.error(f"❌ XFADE файл не создан для папки '{folder_name}'")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка XFADE внутри папки '{folder_name}': {e}")
            return False


class ImageProcessor:
    """Класс для обработки изображений"""

    def __init__(self, bokeh_config: BokehConfig, effects_config: dict = None):
        self.bokeh_config = bokeh_config
        self.effects_config = effects_config or {}

    def process_image(self, image_path: str, output_path: str) -> bool:
        """
        Обработка изображения с эффектом боке

        Args:
            image_path: Путь к исходному изображению
            output_path: Путь для сохранения

        Returns:
            bool: Успешность операции
        """
        if not Path(image_path).exists():
            logger.error(f"Изображение не найдено: {image_path}")
            return False

        try:
            # Создаем директорию для выходного файла
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # Проверяем, нужно ли применить любой тип боке
            bokeh_sides_enabled = self.effects_config.get('bokeh_sides_enabled',
                                                          False) if self.effects_config else False

            if self.bokeh_config.enabled or bokeh_sides_enabled:
                processed_image = self._apply_bokeh_effect(image_path, self.effects_config)
                if processed_image is None:
                    return False
            else:
                # Применяем только дополнительные эффекты без боке
                img = image_processor.load_image(image_path)
                if img is not None and self.effects_config:
                    processed_image = image_processor.apply_image_effects(img, self.effects_config)
                elif img is not None:
                    # Простое копирование без обработки
                    shutil.copy2(image_path, output_path)
                    logger.debug(f"Изображение скопировано: {Path(image_path).name}")
                    return True
                else:
                    return False

            # Сохраняем обработанное изображение
            success = self._save_image(processed_image, output_path)
            if success:
                logger.debug(f"Изображение обработано: {Path(image_path).name}")

            return success

        except Exception as e:
            logger.error(f"Ошибка обработки изображения {image_path}: {e}")
            return False

    def _apply_bokeh_effect(self, image_path: str, effects_config: dict = None) -> Optional[np.ndarray]:
        """Применение эффекта боке и дополнительных эффектов с использованием OpenCV"""
        try:
            # Преобразуем конфигурацию в словарь для передачи в OpenCV процессор
            bokeh_config_dict = {
                'bokeh_image_size': list(self.bokeh_config.image_size),
                'bokeh_blur_kernel': list(self.bokeh_config.blur_kernel),
                'bokeh_blur_sigma': self.bokeh_config.blur_sigma,
                'bokeh_enabled': True
            }

            # Добавляем дополнительные параметры боке из effects_config
            if effects_config:
                for key in ['bokeh_blur_method', 'bokeh_intensity', 'bokeh_focus_area', 'bokeh_transition_smoothness',
                            'bokeh_sides_enabled']:
                    if key in effects_config:
                        bokeh_config_dict[key] = effects_config[key]

            # Временный файл для промежуточного результата
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                temp_output = tmp_file.name

            # Проверяем, какой тип боке применить
            try:
                bokeh_sides_enabled = effects_config.get('bokeh_sides_enabled', False) if effects_config else False
                regular_bokeh_enabled = self.bokeh_config.enabled

                if bokeh_sides_enabled and regular_bokeh_enabled:
                    # Оба эффекта включены - применяем сначала обычный боке, потом боке по бокам
                    logger.debug("Применяем сначала обычный боке, затем боке по бокам")
                    success = image_processor.apply_bokeh_effect(image_path, temp_output, bokeh_config_dict)
                    if success:
                        # Применяем боке по бокам поверх обычного боке
                        success = image_processor.apply_bokeh_sides_effect(temp_output, temp_output, bokeh_config_dict)
                elif bokeh_sides_enabled:
                    # Только боке по бокам
                    logger.debug("Применяем только боке по бокам")
                    success = image_processor.apply_bokeh_sides_effect(image_path, temp_output, bokeh_config_dict)
                elif regular_bokeh_enabled:
                    # Только обычный боке
                    logger.debug("Применяем только обычный боке")
                    success = image_processor.apply_bokeh_effect(image_path, temp_output, bokeh_config_dict)
                else:
                    # Ни одно боке не включено - просто копируем изображение
                    import shutil
                    shutil.copy2(image_path, temp_output)
                    success = True
            except Exception as bokeh_error:
                logger.warning(f"Ошибка применения боке эффекта, переходим к стандартному боке: {bokeh_error}")
                # Fallback на стандартный эффект боке
                success = image_processor.apply_bokeh_effect(image_path, temp_output, bokeh_config_dict)
                logger.debug(f"Применен резервный эффект боке: {success}")

            if success:
                # Загружаем результат
                result_img = image_processor.load_image(temp_output)

                # Применяем дополнительные эффекты, если они указаны
                if effects_config and result_img is not None:
                    result_img = image_processor.apply_image_effects(result_img, effects_config)

                # Удаляем временный файл
                Path(temp_output).unlink(missing_ok=True)
                return result_img
            else:
                # Удаляем временный файл в случае ошибки
                Path(temp_output).unlink(missing_ok=True)
                return None

        except Exception as e:
            logger.error(f"Ошибка применения эффектов: {e}")
            return None

    def _create_blurred_background(self, img: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
        """Создание размытого фона с использованием OpenCV"""
        # Изменяем размер изображения для фона
        img_resized = image_processor.resize_image(img, (target_width, target_height))

        # Применяем размытие через OpenCV
        logger.debug("🎨 Применяем размытие через OpenCV")
        blur_radius = self.bokeh_config.blur_sigma
        logger.debug(f"🎨 OpenCV размытие с радиусом: {blur_radius}")
        blurred = image_processor.apply_gaussian_blur(img_resized, blur_radius)
        return blurred

    def _save_image(self, image: np.ndarray, output_path: str) -> bool:
        """Сохранение изображения с использованием OpenCV"""
        return image_processor.save_image(image, output_path)


class MediaAnalyzer:
    """Класс для анализа медиафайлов"""

    def __init__(self, excel_path: str):
        self.excel_path = Path(excel_path)
        self.validator = FFmpegValidator()

    def _parse_silence_duration(self, silence_duration: str) -> Tuple[float, float]:
        """Парсинг настроек длительности тишины"""
        if isinstance(silence_duration, str) and '-' in silence_duration:
            try:
                min_dur, max_dur = map(float, silence_duration.split('-'))
                if min_dur < 0 or max_dur < 0 or min_dur > max_dur:
                    logger.warning(f"Некорректный диапазон тишины: {silence_duration}, используется 0")
                    return 0.0, 0.0
                return min_dur, max_dur
            except ValueError:
                logger.warning(f"Некорректный формат тишины: {silence_duration}, используется 0")
                return 0.0, 0.0

        elif isinstance(silence_duration, (int, float)):
            if silence_duration < 0:
                logger.warning("Отрицательная длительность тишины, используется 0")
                return 0.0, 0.0
            return float(silence_duration), float(silence_duration)

        else:
            logger.warning(f"Некорректный тип silence_duration: {type(silence_duration)}, используется 0")
            return 0.0, 0.0

    def get_folder_audio_mapping_from_excel(self, video_number: str) -> Dict[str, List[int]]:
        """
        Получает соответствие папок и аудиофайлов из Excel структуры.

        Для видео 2:
        - Папка "1-5": аудиофайлы 033-037
        - Папка "6-10": аудиофайлы 038-042
        - И так далее...

        Returns:
            Dict[str, List[int]]: Словарь {папка: [список номеров аудиофайлов]}
        """
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel файл не найден: {self.excel_path}")

        try:
            df = pd.read_excel(self.excel_path, header=None)
            target_video = f"ВИДЕО {video_number}"

            folder_audio_mapping = {}
            current_folder = None
            current_audio_files = []

            found_video = False

            for idx, row in df.iterrows():
                video_col = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                folder_col = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""

                # Если нашли целевое видео, начинаем сбор данных
                if video_col == target_video:
                    found_video = True

                # Если уже нашли видео и встретили другое видео - останавливаемся
                if found_video and video_col.startswith("ВИДЕО ") and video_col != target_video:
                    # Сохраняем последнюю папку
                    if current_folder and current_audio_files:
                        folder_audio_mapping[current_folder] = current_audio_files
                    break

                # Обрабатываем строки после нахождения видео
                if found_video:
                    # Номер аудиофайла = номер строки Excel
                    audio_number = idx + 1  # idx+1 потому что строки Excel начинаются с 1

                    # Если есть новая папка в столбце B
                    if folder_col:
                        # Сохраняем предыдущую папку
                        if current_folder and current_audio_files:
                            folder_audio_mapping[current_folder] = current_audio_files

                        # Начинаем новую папку
                        current_folder = folder_col
                        current_audio_files = [audio_number]
                    else:
                        # Добавляем аудио к текущей папке
                        if current_folder:
                            current_audio_files.append(audio_number)

            # Сохраняем последнюю папку
            if current_folder and current_audio_files:
                folder_audio_mapping[current_folder] = current_audio_files

            # Логирование для отладки
            logger.info(f"📊 Соответствие папок и аудиофайлов для видео {video_number}:")
            for folder, audio_files in folder_audio_mapping.items():
                logger.info(
                    f"   Папка '{folder}': аудиофайлы {audio_files[0]:03d}-{audio_files[-1]:03d} ({len(audio_files)} файлов)")

            return folder_audio_mapping

        except Exception as e:
            raise VideoProcessingError(f"Ошибка чтения Excel файла: {e}")

    def get_folder_ranges_from_excel(self, video_number: str) -> Tuple[int, int, List[str]]:
        """
        Извлечение диапазонов строк и папок из Excel по новой структуре
        Столбец A = номер видео, Столбец B = папки

        Args:
            video_number: Номер видео

        Returns:
            Tuple[int, int, List[str]]: Начальная строка, конечная строка, список папок
        """
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel файл не найден: {self.excel_path}")

        try:
            df = pd.read_excel(self.excel_path, header=None)
            target_video = f"ВИДЕО {video_number}"
            video_rows = []
            folders = []

            # Ищем все строки для заданного видео
            for idx, row in df.iterrows():
                video_col = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""  # Столбец A
                folder_col = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""  # Столбец B

                if video_col == target_video:
                    # Нашли строку с меткой видео, теперь собираем все строки до следующего видео
                    start_idx = idx

                    # Ищем конец диапазона (до следующего видео или до конца файла)
                    end_idx = len(df)
                    for next_idx in range(idx + 1, len(df)):
                        next_video_col = str(df.iloc[next_idx][0]).strip() if not pd.isna(df.iloc[next_idx][0]) else ""
                        if next_video_col.startswith("ВИДЕО "):
                            end_idx = next_idx
                            break

                    # ИСПРАВЛЕНИЕ: Аудиофайлы начинаются ВМЕСТе с меткой видео
                    # Строка с меткой "ВИДЕО 1" содержит данные для 001.mp3
                    # Каждая строка соответствует одному аудиофайлу: строка 1 = 001.mp3, строка 2 = 002.mp3, и т.д.

                    # Собираем все строки ОТ метки видео до следующего видео (включая строку с меткой)
                    for data_idx in range(start_idx, end_idx):  # Включаем строку с меткой!
                        video_rows.append(data_idx + 1)  # +1 для Excel нумерации
                        data_folder_col = str(df.iloc[data_idx][1]).strip() if not pd.isna(df.iloc[data_idx][1]) else ""
                        if data_folder_col:  # Если в столбце B есть папка
                            folders.append(data_folder_col)
                    break

            if not video_rows:
                # Подробная диагностика для лучшего понимания проблемы
                available_videos = []
                for idx, row in df.iterrows():
                    video_col = str(row[0]).strip() if not pd.isna(row[0]) else ""
                    if video_col.startswith("ВИДЕО "):
                        available_videos.append(video_col)

                logger.error(f"Видео {video_number} не найдено в столбце A или нет данных после метки видео")
                if available_videos:
                    logger.error(f"Доступные видео: {', '.join(available_videos)}")
                else:
                    logger.error("В Excel файле не найдено видео с метками 'ВИДЕО N'")

                raise VideoProcessingError(
                    f"Видео {video_number} не найдено в столбце A или нет данных после метки. Доступные видео: {', '.join(available_videos) if available_videos else 'отсутствуют'}")

            # DEBUG: About to call min() on video_rows
            logger.debug(f"DEBUG: About to call min() on video_rows")
            logger.debug(
                f"DEBUG: Type: {type(video_rows)}, Length: {len(video_rows) if hasattr(video_rows, '__len__') else 'N/A'}")
            logger.debug(f"DEBUG: Contents: {video_rows}")
            if not video_rows:
                logger.error(f"ERROR: Empty sequence passed to min() at video_processing.py:926")
                raise ValueError(f"Empty sequence passed to min() at video_processing.py:926")

            # DEBUG: About to call max() on video_rows
            logger.debug(f"DEBUG: About to call max() on video_rows")
            logger.debug(
                f"DEBUG: Type: {type(video_rows)}, Length: {len(video_rows) if hasattr(video_rows, '__len__') else 'N/A'}")
            logger.debug(f"DEBUG: Contents: {video_rows}")
            if not video_rows:
                logger.error(f"ERROR: Empty sequence passed to max() at video_processing.py:926")
                raise ValueError(f"Empty sequence passed to max() at video_processing.py:926")

            start_row = debug_min_call(video_rows, context="video_processing._find_video_range")
            end_row = max(video_rows) + 1  # +1 для range
            folders = self._sort_folders(folders)

            logger.info(f"Диапазон для видео {video_number}: строки {start_row}–{end_row - 1}")
            logger.debug(f"Папки для видео {video_number}: {folders}")

            return start_row, end_row, folders

        except Exception as e:
            raise VideoProcessingError(f"Ошибка чтения Excel файла: {e}")

    def _sort_folders(self, folders: List[str]) -> List[str]:
        """Сортировка папок по номерам"""

        def folder_sort_key(folder_name: str) -> Tuple[int, int]:
            if folder_name == "root":
                return (0, 0)
            try:
                if '-' in folder_name:
                    parts = folder_name.split('-')
                    start = int(parts[0])
                    end = int(parts[1])
                else:
                    start = end = int(folder_name)
                return (start, end)
            except (ValueError, IndexError):
                return (float('inf'), float('inf'))

        return sorted(folders, key=folder_sort_key)

    def calculate_folder_durations_new(self, audio_folder: str, folders: List[str],
                                       start_row: int, end_row: int,
                                       silence_duration: str = "1.0-2.5") -> Tuple[Dict[str, float], float]:
        """
        Расчет длительности для каждой папки на основе аудиофайлов с учетом пауз

        Args:
            audio_folder: Папка с аудиофайлами
            folders: Список папок
            start_row: Начальная строка
            end_row: Конечная строка
            silence_duration: Длительность пауз между файлами (формат "min-max" или число)

        Returns:
            Tuple[Dict[str, float], float]: Длительности папок и общая длительность
        """
        audio_folder_path = Path(audio_folder)
        if not audio_folder_path.exists():
            raise FileNotFoundError(f"Папка с аудио не найдена: {audio_folder}")

        # Парсим настройки пауз
        min_silence, max_silence = self._parse_silence_duration(silence_duration)
        avg_silence = (min_silence + max_silence) / 2.0

        # Собираем длительности всех аудиофайлов
        audio_durations = {}
        total_duration = 0.0

        logger.info(f"🔍 ДИАГНОСТИКА calculate_folder_durations:")
        logger.info(f"   audio_folder: {audio_folder}")
        logger.info(f"   audio_folder_path: {audio_folder_path}")
        logger.info(f"   folders: {folders}")
        logger.info(f"   start_row: {start_row}, end_row: {end_row}")
        logger.info(f"   silence_duration: {silence_duration} (среднее: {avg_silence:.2f}с)")

        # Сначала найдем все существующие аудиофайлы в папке
        existing_audio_files = []
        for audio_file_path in audio_folder_path.glob("*.mp3"):
            if audio_file_path.name.endswith('.mp3') and audio_file_path.name[:3].isdigit():
                file_num = int(audio_file_path.name[:3])
                existing_audio_files.append(file_num)

        existing_audio_files.sort()
        logger.info(f"   📁 Найденные аудиофайлы: {existing_audio_files}")

        # Ограничиваем диапазон только существующими файлами
        # DEBUG: About to call min() on existing_audio_files
        logger.debug(f"DEBUG: About to call min() on existing_audio_files")
        logger.debug(
            f"DEBUG: Type: {type(existing_audio_files)}, Length: {len(existing_audio_files) if hasattr(existing_audio_files, '__len__') else 'N/A'}")
        logger.debug(f"DEBUG: Contents: {existing_audio_files}")
        if existing_audio_files and not existing_audio_files:
            logger.error(f"ERROR: Empty sequence passed to min() at video_processing.py:1003")
            raise ValueError(f"Empty sequence passed to min() at video_processing.py:1003")

        # DEBUG: About to call max() on existing_audio_files
        logger.debug(f"DEBUG: About to call max() on existing_audio_files")
        logger.debug(
            f"DEBUG: Type: {type(existing_audio_files)}, Length: {len(existing_audio_files) if hasattr(existing_audio_files, '__len__') else 'N/A'}")
        logger.debug(f"DEBUG: Contents: {existing_audio_files}")
        if existing_audio_files and not existing_audio_files:
            logger.error(f"ERROR: Empty sequence passed to max() at video_processing.py:1003")
            raise ValueError(f"Empty sequence passed to max() at video_processing.py:1003")

        actual_start = max(start_row, debug_min_call(existing_audio_files,
                                                     context="video_processing.get_folder_durations_start") if existing_audio_files else start_row)
        actual_end = min(end_row, max(existing_audio_files) if existing_audio_files else end_row)

        logger.info(f"   📊 Исходный диапазон: {start_row}-{end_row}")
        logger.info(f"   📊 Фактический диапазон: {actual_start}-{actual_end}")

        for line_num in range(actual_start, actual_end + 1):
            audio_filename = f"{str(line_num).zfill(3)}.mp3"
            audio_file = audio_folder_path / audio_filename

            logger.info(f"   🎵 Проверяем файл: {audio_file}")

            if audio_file.exists():
                try:
                    duration = self.validator.get_media_duration(str(audio_file))
                    audio_durations[line_num] = duration
                    total_duration += duration
                    logger.info(f"   ✅ Длительность {audio_filename}: {duration:.2f}с")
                except Exception as e:
                    logger.warning(f"Ошибка получения длительности {audio_file}: {e}")
                    audio_durations[line_num] = 0.0
            else:
                # Файл должен существовать в этом диапазоне, поэтому это странная ситуация
                audio_durations[line_num] = 0.0
                logger.warning(f"   ❌ Аудиофайл не найден в ожидаемом диапазоне: {audio_file}")

        # Рассчитываем длительность для каждой папки
        folder_durations = {}

        logger.info(f"🔍 ДИАГНОСТИКА расчета длительностей папок:")
        logger.info(f"   audio_durations: {audio_durations}")

        for folder in folders:
            logger.info(f"   📁 Обрабатываем папку: '{folder}'")

            if folder == "root":
                # В backup версии root папка имеет 0.0 длительность - это правильно!
                folder_durations[folder] = 0.0
                logger.info(f"   ✅ Длительность папки root: 0.0 сек")
                continue

            try:
                # Убираем префикс папки если он есть (например "2-11/1-2" -> "1-2")
                folder_name = folder.split('/')[-1] if '/' in folder else folder
                logger.info(f"   📝 Имя папки после обработки: '{folder_name}'")

                if '-' in folder_name:
                    folder_start, folder_end = map(int, folder_name.split('-'))
                else:
                    folder_start = folder_end = int(folder_name)

                logger.info(f"   📊 Диапазон папки: {folder_start}-{folder_end}")

                # Абсолютные номера строк
                abs_start = start_row + folder_start - 1
                abs_end = start_row + folder_end - 1

                logger.info(f"   🔢 Абсолютные номера строк: {abs_start}-{abs_end}")

                folder_duration = 0.0
                file_count = 0
                for line_num in range(abs_start, abs_end + 1):
                    line_duration = audio_durations.get(line_num, 0.0)
                    if line_duration > 0:  # Считаем только существующие файлы
                        folder_duration += line_duration
                        file_count += 1
                        logger.info(f"   🎵 Строка {line_num}: {line_duration:.2f}с")

                # Добавляем паузы между файлами (на 1 меньше количества файлов)
                if file_count > 1 and avg_silence > 0:
                    silence_count = file_count - 1
                    total_silence = silence_count * avg_silence
                    folder_duration += total_silence
                    logger.info(f"   🔇 Паузы: {silence_count} × {avg_silence:.2f}с = {total_silence:.2f}с")

                folder_durations[folder] = folder_duration
                logger.info(f"   ✅ Итоговая длительность папки '{folder}': {folder_duration:.2f} сек (файлы + паузы)")

            except (ValueError, IndexError) as e:
                logger.warning(f"Не удалось разобрать диапазон для папки {folder}: {e}")
                folder_durations[folder] = 0.0

        logger.info(f"Общая длительность аудио: {total_duration:.2f} сек")
        return folder_durations, total_duration

    def calculate_folder_durations_excel_based(self, audio_folder: str, video_number: str,
                                               silence_duration: str = "1.0-2.5",
                                               photo_folders_analysis: Dict[str, Dict] = None,
                                               effects_config: 'VideoEffectsConfig' = None) -> Tuple[
        Dict[str, float], float, Dict[str, List[int]]]:
        """
        Расчет длительности для каждой папки на основе Excel структуры
        С учетом пауз ПОСЛЕ КАЖДОГО аудиофайла И компенсации XFADE переходов
        """
        audio_folder_path = Path(audio_folder)
        if not audio_folder_path.exists():
            raise FileNotFoundError(f"Папка с аудио не найдена: {audio_folder}")

        # Парсим настройки пауз
        min_silence, max_silence = self._parse_silence_duration(silence_duration)
        avg_silence = (min_silence + max_silence) / 2.0

        logger.info(f"🔍 Расчет длительностей папок для видео {video_number}")
        logger.info(f"   Средняя пауза: {avg_silence:.2f}с")

        # Получаем соответствие папок и аудиофайлов из Excel
        folder_audio_mapping = self.get_folder_audio_mapping_from_excel(video_number)

        folder_durations = {}
        folder_to_audio_numbers = folder_audio_mapping
        total_duration = 0.0

        # Проверяем настройки XFADE переходов
        xfade_enabled = False
        transition_duration = 0.5
        inter_folder_xfade_enabled = False

        if effects_config:
            xfade_enabled = (
                    getattr(effects_config, 'transitions_enabled', False) and
                    getattr(effects_config, 'transition_method', '') == 'xfade'
            )
            transition_duration = getattr(effects_config, 'transition_duration', 0.5)
            # Проверяем, есть ли XFADE между папками (сегментами)
            inter_folder_xfade_enabled = xfade_enabled  # По умолчанию такой же как внутри папок

        logger.info(f"🔄 XFADE настройки:")
        logger.info(f"   XFADE внутри папок: {'включен' if xfade_enabled else 'отключен'}")
        logger.info(f"   XFADE между папками: {'включен' if inter_folder_xfade_enabled else 'отключен'}")
        logger.info(f"   Длительность перехода: {transition_duration:.2f}с")

        # Обрабатываем каждую папку согласно Excel структуре
        for folder, audio_numbers in folder_audio_mapping.items():
            logger.info(f"📁 Обработка папки '{folder}'")

            # Считаем длительность аудио для папки
            folder_duration = 0.0
            audio_count = 0

            for num in audio_numbers:
                audio_filename = f"{num:03d}.mp3"
                audio_path = audio_folder_path / audio_filename

                if audio_path.exists():
                    try:
                        duration = self.validator.get_media_duration(str(audio_path))
                        folder_duration += duration
                        audio_count += 1
                        logger.info(f"   🎵 {audio_filename}: {duration:.2f}с")

                        # Добавляем паузу ПОСЛЕ каждого аудио
                        folder_duration += avg_silence
                        logger.info(f"   🔇 + пауза: {avg_silence:.2f}с")

                    except Exception as e:
                        logger.error(f"   ❌ Ошибка чтения {audio_filename}: {e}")
                else:
                    logger.warning(f"   ❌ Файл не найден: {audio_filename}")

            # КОМПЕНСАЦИЯ XFADE ВНУТРИ ПАПКИ
            if xfade_enabled and photo_folders_analysis:
                folder_info = photo_folders_analysis.get(folder, {})
                files_count = folder_info.get("files_count", 0)

                if files_count > 1:
                    # Количество переходов внутри папки = количество файлов - 1
                    internal_transitions = files_count - 1
                    internal_xfade_compensation = internal_transitions * transition_duration

                    # ПРАВИЛЬНАЯ КОМПЕНСАЦИЯ: точно на время fade-переходов
                    folder_duration += internal_xfade_compensation

                    logger.info(f"   🔄 XFADE компенсация внутри папки '{folder}':")
                    logger.info(f"      Файлов: {files_count}")
                    logger.info(f"      Внутренних переходов: {internal_transitions}")
                    logger.info(f"      Компенсация: +{internal_xfade_compensation:.2f}с")

            folder_durations[folder] = folder_duration
            total_duration += folder_duration
            logger.info(f"   ✅ Итого для папки '{folder}': {folder_duration:.2f}с ({audio_count} файлов)")

        # КОМПЕНСАЦИЯ XFADE МЕЖДУ ПАПКАМИ (СЕГМЕНТАМИ)
        if inter_folder_xfade_enabled and len(folder_durations) > 1:
            # Количество переходов между папками = количество папок - 1
            inter_folder_transitions = len(folder_durations) - 1
            inter_folder_xfade_compensation = inter_folder_transitions * transition_duration

            # ПРАВИЛЬНАЯ КОМПЕНСАЦИЯ: точно на время fade-переходов между папками
            total_duration += inter_folder_xfade_compensation

            logger.info(f"🔄 XFADE компенсация между папками:")
            logger.info(f"   Папок (сегментов): {len(folder_durations)}")
            logger.info(f"   Переходов между папками: {inter_folder_transitions}")
            logger.info(f"   Компенсация: +{inter_folder_xfade_compensation:.2f}с")
            logger.info(f"   Общая длительность с компенсацией: {total_duration:.2f}с")

        logger.info(f"📊 Общая длительность: {total_duration:.2f}с")

        # Подготовка данных о файлах (без изменений)
        folder_to_files = {}
        logger.info(
            f"🔍 calculate_folder_durations_excel_based получил photo_folders_analysis: {photo_folders_analysis is not None}")

        if photo_folders_analysis:
            logger.info(
                f"🔍 photo_folders_analysis содержит {len(photo_folders_analysis)} папок: {list(photo_folders_analysis.keys())}")
            for folder_name, folder_info in photo_folders_analysis.items():
                logger.info(f"🔍 Обрабатываем папку '{folder_name}' из photo_folders_analysis")

                files_from_analysis = folder_info.get("files", [])
                existing_files_from_analysis = []
                base_folder_for_check = Path(folder_info.get("full_path", ""))

                for file_path_item in files_from_analysis:
                    file_path_obj = Path(file_path_item)
                    if file_path_obj.is_absolute() and file_path_obj.exists():
                        existing_files_from_analysis.append(str(file_path_item))
                        logger.debug(f"   ✅ Найден по абсолютному пути: {file_path_obj.name}")
                    elif base_folder_for_check.exists():
                        full_path_candidate = base_folder_for_check / Path(file_path_item).name
                        if full_path_candidate.exists():
                            existing_files_from_analysis.append(str(full_path_candidate))
                            logger.debug(f"   ✅ Найден через базовую папку: {full_path_candidate.name}")
                        else:
                            logger.warning(f"   ❌ Файл из photo_folders_analysis не найден: {file_path_item}")
                    else:
                        logger.warning(f"   ❌ Файл из photo_folders_analysis не найден: {file_path_item}")

                if existing_files_from_analysis:
                    folder_to_files[folder_name] = existing_files_from_analysis
                    logger.info(
                        f"   ✅ Папка '{folder_name}': {len(existing_files_from_analysis)} файлов взято из photo_folders_analysis")
                else:
                    logger.warning(f"   ⚠️ Папка '{folder_name}': нет существующих файлов")
                    folder_to_files[folder_name] = []
        else:
            logger.warning("⚠️ photo_folders_analysis пуст или None в calculate_folder_durations_excel_based!")

        return folder_durations, total_duration, folder_to_files

    def calculate_media_sequence_for_folder(self, media_files: List[str],
                                            target_duration: float,
                                            folder_name: str,
                                            transitions_enabled: bool = False,
                                            transition_duration: float = 0.5) -> List[Dict[str, Any]]:
        """Рассчитывает последовательность медиафайлов с ТОЧНОЙ компенсацией XFADE"""

        if not media_files or target_duration <= 0:
            return []

        MIN_CLIP_DURATION = 0.5
        if target_duration < MIN_CLIP_DURATION:
            logger.warning(f"⚠️ Папка '{folder_name}': целевая длительность {target_duration:.2f}с слишком мала.")
            target_duration = MIN_CLIP_DURATION

        # Сортировка файлов
        def extract_number_from_filename(file_path: str) -> int:
            try:
                filename = Path(file_path).stem
                import re
                match = re.search(r'(\d+)', filename)
                return int(match.group(1)) if match else 0
            except:
                return 0

        sorted_media_files = sorted(media_files, key=extract_number_from_filename)

        logger.info(f"📁 Папка '{folder_name}': сортируем {len(sorted_media_files)} файлов")
        logger.info(f"   Целевая длительность: {target_duration:.2f}с")
        logger.info(f"   XFADE переходы: {'включены' if transitions_enabled else 'отключены'}")

        sequence = []

        # НОВАЯ ЛОГИКА: ВИДЕО ИГРАЮТ ПОЛНОСТЬЮ, ФОТО ЗАПОЛНЯЮТ ОСТАВШЕЕСЯ ВРЕМЯ
        if transitions_enabled and len(sorted_media_files) > 1:
            # Количество переходов = количество файлов - 1
            num_transitions = len(sorted_media_files) - 1
            total_transition_loss = num_transitions * transition_duration

            logger.info(f"🔄 ТОЧНАЯ XFADE компенсация для папки '{folder_name}':")
            logger.info(f"   Файлов: {len(sorted_media_files)}")
            logger.info(f"   Переходов: {num_transitions}")
            logger.info(f"   Длительность перехода: {transition_duration:.2f}с")
            logger.info(f"   Общая потеря времени: {total_transition_loss:.2f}с")

            base_duration_estimate = target_duration

            logger.info(f"   Используем целевую длительность: {base_duration_estimate:.2f}с")
            logger.info(f"   (компенсация уже учтена в расчете папки)")

            # НОВАЯ ЛОГИКА: Разделяем видео и фото
            video_files = []
            photo_files = []
            total_video_duration = 0.0

            for file_path in sorted_media_files:
                ext = Path(file_path).suffix.lower()
                if ext in ('.mp4', '.mov', '.avi', '.mkv'):
                    # Получаем реальную длительность видео
                    try:
                        real_duration = get_video_duration(file_path)
                        if real_duration and real_duration > 0:
                            video_files.append((file_path, real_duration))
                            total_video_duration += real_duration
                            logger.info(f"   📹 Видео {Path(file_path).name}: {real_duration:.2f}с (полная длительность)")
                        else:
                            photo_files.append(file_path)
                            logger.info(f"   📷 Файл {Path(file_path).name}: обрабатываем как фото (нет длительности)")
                    except Exception as e:
                        photo_files.append(file_path)
                        logger.warning(f"   ⚠️ Ошибка получения длительности {Path(file_path).name}: {e}, обрабатываем как фото")
                else:
                    photo_files.append(file_path)
                    logger.info(f"   📷 Фото {Path(file_path).name}")

            # Вычисляем оставшееся время для фото
            remaining_time = base_duration_estimate - total_video_duration
            logger.info(f"   Общая длительность видео: {total_video_duration:.2f}с")
            logger.info(f"   Оставшееся время для фото: {remaining_time:.2f}с")

            # Создаем последовательность
            for file_path, duration in video_files:
                sequence.append({
                    'file': file_path,
                    'start': 0.0,
                    'duration': duration,
                    'type': 'video_full_duration'
                })

            # Распределяем оставшееся время между фото
            if photo_files and remaining_time > 0:
                photo_duration = max(MIN_CLIP_DURATION, remaining_time / len(photo_files))
                logger.info(f"   Длительность на фото: {photo_duration:.2f}с")
                
                for file_path in photo_files:
                    sequence.append({
                        'file': file_path,
                        'start': 0.0,
                        'duration': photo_duration,
                        'type': 'photo_fill_remaining'
                    })
            elif photo_files:
                logger.warning(f"   ⚠️ Нет времени для фото (всё время заняли видео)")

            # Сортируем последовательность по исходному порядку файлов
            file_order = {file_path: i for i, file_path in enumerate(sorted_media_files)}
            sequence.sort(key=lambda x: file_order.get(x['file'], 999))

            # ПРОВЕРКА ФИНАЛЬНОЙ МАТЕМАТИКИ
            total_actual_duration = total_video_duration + (len(photo_files) * (remaining_time / len(photo_files) if photo_files and remaining_time > 0 else 0))
            expected_after_xfade = total_actual_duration - total_transition_loss

            logger.info(f"📊 Финальная проверка для папки '{folder_name}':")
            logger.info(f"   Общая длительность (видео + фото): {total_actual_duration:.2f}с")
            logger.info(f"   Потеря на переходах: {total_transition_loss:.2f}с")
            logger.info(f"   Ожидаемая длительность после XFADE: {expected_after_xfade:.2f}с")
            logger.info(f"   Целевая длительность: {target_duration:.2f}с")

            # Рассчитываем точность
            accuracy = abs(expected_after_xfade - (target_duration - total_transition_loss))

            if accuracy < 0.1:
                logger.info(f"   ✅ Высокая точность: {accuracy:.3f}с")
            elif accuracy < 0.5:
                logger.info(f"   ⚠️ Приемлемая точность: {accuracy:.3f}с")
            else:
                logger.warning(f"   ❌ Низкая точность: {accuracy:.3f}с")

        else:
            # Без переходов - НОВАЯ ЛОГИКА: видео полностью, фото заполняют оставшееся время
            logger.info(f"   Без переходов - применяем новую логику распределения")
            
            # Разделяем видео и фото
            video_files = []
            photo_files = []
            total_video_duration = 0.0

            for file_path in sorted_media_files:
                ext = Path(file_path).suffix.lower()
                if ext in ('.mp4', '.mov', '.avi', '.mkv'):
                    # Получаем реальную длительность видео
                    try:
                        real_duration = get_video_duration(file_path)
                        if real_duration and real_duration > 0:
                            video_files.append((file_path, real_duration))
                            total_video_duration += real_duration
                            logger.info(f"   📹 Видео {Path(file_path).name}: {real_duration:.2f}с (полная длительность)")
                        else:
                            photo_files.append(file_path)
                            logger.info(f"   📷 Файл {Path(file_path).name}: обрабатываем как фото (нет длительности)")
                    except Exception as e:
                        photo_files.append(file_path)
                        logger.warning(f"   ⚠️ Ошибка получения длительности {Path(file_path).name}: {e}, обрабатываем как фото")
                else:
                    photo_files.append(file_path)
                    logger.info(f"   📷 Фото {Path(file_path).name}")

            # Вычисляем оставшееся время для фото
            remaining_time = target_duration - total_video_duration
            logger.info(f"   Общая длительность видео: {total_video_duration:.2f}с")
            logger.info(f"   Оставшееся время для фото: {remaining_time:.2f}с")

            # Создаем последовательность
            for file_path, duration in video_files:
                sequence.append({
                    'file': file_path,
                    'start': 0.0,
                    'duration': duration,
                    'type': 'video_full_duration_no_transitions'
                })

            # Распределяем оставшееся время между фото
            if photo_files and remaining_time > 0:
                photo_duration = max(MIN_CLIP_DURATION, remaining_time / len(photo_files))
                logger.info(f"   Длительность на фото: {photo_duration:.2f}с")
                
                for file_path in photo_files:
                    sequence.append({
                        'file': file_path,
                        'start': 0.0,
                        'duration': photo_duration,
                        'type': 'photo_fill_remaining_no_transitions'
                    })
            elif photo_files:
                logger.warning(f"   ⚠️ Нет времени для фото (всё время заняли видео)")

            # Сортируем последовательность по исходному порядку файлов
            file_order = {file_path: i for i, file_path in enumerate(sorted_media_files)}
            sequence.sort(key=lambda x: file_order.get(x['file'], 999))

        return sequence

    def _validate_and_fix_duration(self, duration: float, file_path: str, min_duration: float = 0.5) -> float:
        """
        Проверяет и исправляет длительность файла

        Args:
            duration: Исходная длительность
            file_path: Путь к файлу для логирования
            min_duration: Минимальная допустимая длительность

        Returns:
            float: Исправленная длительность
        """
        if duration is None or duration != duration:  # Проверка на None и NaN
            logger.error(f"❌ Обнаружена None/NaN длительность для {Path(file_path).name}")
            return min_duration

        if duration <= 0:
            logger.error(f"❌ Обнаружена нулевая/отрицательная длительность для {Path(file_path).name}: {duration}с")
            logger.warning(f"🔧 Исправлено на минимальную длительность: {min_duration}с")
            return min_duration

        if duration < min_duration:
            logger.warning(
                f"⚠️ Слишком короткая длительность для {Path(file_path).name}: {duration}с, увеличиваем до {min_duration}с")
            return min_duration

        return duration


class ConcatenationHelper:
    """Вспомогательный класс для создания списков конкатенации"""

    @staticmethod
    def create_concat_list(files: List[str], output_path: str, shuffle: bool = False, clips_info: List[Dict] = None,
                           file_durations_map: Dict[str, float] = None) -> str:
        """
        Создание файла списка для конкатенации

        Args:
            files: Список файлов
            output_path: Путь для сохранения списка
            shuffle: Перемешать файлы
            clips_info: Информация о клипах (для обратной совместимости)
            file_durations_map: ПРИОРИТЕТНАЯ карта длительностей согласно Excel логике

        Returns:
            str: Путь к созданному файлу списка
        """
        if shuffle:
            files = files.copy()
            random.shuffle(files)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # ИСПРАВЛЕНИЕ: Строим duration_map, используя ОБРАБОТАННЫЕ ПУТИ (clip["path"]) как ключи
        # Это обеспечивает, что ключи в duration_map будут совпадать с элементами в files
        duration_map = {}

        if clips_info:
            for clip in clips_info:
                processed_path = clip["path"]  # Путь к processed_X_original.mp4
                original_file_path = clip.get("original_file", processed_path)  # Оригинальный путь

                # Приоритет: сначала file_durations_map (из Excel), затем clip["duration"]
                if file_durations_map and original_file_path in file_durations_map:
                    duration_map[processed_path] = file_durations_map[original_file_path]
                    logger.debug(
                        f"🎯 CONCAT_MAP: {Path(processed_path).name} = {duration_map[processed_path]:.3f}с (из Excel)")
                else:
                    duration_map[processed_path] = clip["duration"]
                    logger.debug(
                        f"🎯 CONCAT_MAP: {Path(processed_path).name} = {duration_map[processed_path]:.3f}с (из clips_info)")

        if file_durations_map:
            logger.info(f"🎯 Применяем Excel длительности: {len(file_durations_map)} файлов")
            total_duration_from_map = sum(file_durations_map.values())
            logger.info(f"📊 Общая длительность из Excel карты: {total_duration_from_map:.2f}с")
            logger.info("✅ Excel логика: file_durations_map применен для правильного масштабирования")

        # Отладочный вывод, чтобы убедиться в правильности file_path_processed
        logger.debug(f"🔍 CONCAT_HELPER: Начало создания списка {output_path}")
        logger.debug(f"🔍 CONCAT_HELPER: Первый файл в списке 'files': {files[0] if files else 'N/A'}")
        total_duration_check = 0.0

        with open(output_file, "w", encoding="utf-8") as f:
            for i, file_path_processed in enumerate(files):
                abs_path = Path(file_path_processed).resolve()
                cleaned_path = abs_path.as_posix()

                # КРИТИЧЕСКАЯ ПРОВЕРКА ПЕРЕД ЗАПИСЬЮ В СПИСОК
                if not abs_path.exists():
                    logger.error(f"🚨 КРИТИЧЕСКИЙ ПРОПУСК: Файл {i + 1} НЕ СУЩЕСТВУЕТ для конкатенации: {abs_path}")
                    # Вместо того чтобы падать, можно добавить пустой файл или заполнитель
                    # Это позволит конкатенации продолжиться, но нужно знать, как вы хотите обрабатывать отсутствующие файлы
                    # Сейчас мы добавим его, и FFmpeg выдаст ошибку, но это будет явно в логе.
                    # Если проблема в задержке, то этот блок не будет вызываться.
                    # Для отладки пока оставим, чтобы FFmpeg упал.
                    # f.write(f"file 'dummy_black_frame.mp4'\n") # Можно добавить черный кадр
                    # f.write(f"duration 1.0\n") # Длительность заглушки
                    continue  # Пропускаем файл, если он не существует

                # Проверяем, что путь не пустой
                if not cleaned_path:
                    logger.error(f"❌ CONCAT_HELPER: Пустой путь файла на итерации {i}. Пропускаем.")
                    continue

                f.write(f"file '{cleaned_path}'\n")  # Используем очищенный путь

                # ИСПРАВЛЕНИЕ: Теперь просто ищем file_path_processed в duration_map
                duration_used = None

                if file_path_processed in duration_map:
                    duration_used = duration_map[file_path_processed]
                    logger.debug(f"✅ НАЙДЕНО: {Path(file_path_processed).name} = {duration_used:.3f}с")
                else:
                    # Этот блок должен срабатывать КРАЙНЕ редко, только если файл не был в clips_info
                    try:
                        duration_used = get_media_duration(file_path_processed)
                        logger.error(
                            f"❌ КРИТИЧЕСКАЯ ОШИБКА: Длительность для {Path(file_path_processed).name} не найдена в карте! Используем фактическую длительность: {duration_used:.3f}с")
                    except Exception as e:
                        logger.error(
                            f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить длительность для {Path(file_path_processed).name}: {e}. Устанавливаем 3.0с.")
                        duration_used = 3.0

                f.write(f"duration {duration_used:.6f}\n")
                total_duration_check += duration_used
                logger.debug(f"🎬 CONCAT ФАЙЛ {i + 1}: {Path(file_path_processed).name} = {duration_used:.3f}с")

        logger.info(
            f"🔍 CONCAT_HELPER: Список конкатенации создан. Общая длительность по duration_map: {total_duration_check:.3f}с")
        logger.debug(f"Создан список конкатенации: {output_file} ({len(files)} файлов)")
        return str(output_file)


# Функции для обратной совместимости
def check_ffmpeg_version() -> bool:
    """Обратная совместимость: проверка FFmpeg"""
    return FFmpegValidator.check_availability()


def get_audio_duration(input_path: str) -> float:
    """Обратная совместимость: получение длительности аудио"""
    try:
        return FFmpegValidator.get_media_duration(input_path)
    except Exception as e:
        logger.error(f"Ошибка получения длительности аудио: {e}")
        return 0.0


def get_video_duration(input_path: str) -> float:
    """Обратная совместимость: получение длительности видео"""
    try:
        return FFmpegValidator.get_media_duration(input_path)
    except Exception as e:
        logger.error(f"Ошибка получения длительности видео: {e}")
        return 0.0


def has_audio_stream(input_path: str) -> bool:
    """Обратная совместимость: проверка аудиодорожки"""
    return FFmpegValidator.has_audio_stream(input_path)


def check_video_params(input_path: str, target_resolution: str, target_fps: int,
                       target_codec: str, target_pix_fmt: str) -> Tuple[bool, List[str]]:
    """Обратная совместимость: проверка параметров видео"""

    config = VideoConfig({
        "video_resolution": target_resolution,  # Просто передаем как есть
        "frame_rate": target_fps,
        "video_codec": f"lib{target_codec}" if not target_codec.startswith('lib') else target_codec,
        "pixel_format": target_pix_fmt
    })
    return FFmpegValidator.check_video_params(input_path, config)


def reencode_video(input_path: str, output_path: str, video_resolution: str, frame_rate: int,
                   video_crf: int, video_preset: str, preserve_audio: bool = False,
                   target_duration: Optional[float] = None) -> bool:
    """Обратная совместимость: перекодирование видео"""
    try:
        # Теперь просто используем video_resolution как есть, оно будет обработано в VideoConfig.__init__

        config = VideoConfig({
            "video_resolution": video_resolution,  # Просто передаем как есть
            "frame_rate": frame_rate,
            "video_crf": video_crf,
            "video_preset": video_preset
        })
        processor = VideoProcessor(config)
        return processor.reencode_video(input_path, output_path, preserve_audio, target_duration)
    except Exception as e:
        logger.error(f"Ошибка перекодирования: {e}")
        return False


def extract_first_frame(video_path: str, output_path: str) -> bool:
    """Обратная совместимость: извлечение первого кадра"""
    try:
        config = VideoConfig()  # Используем настройки по умолчанию
        processor = VideoProcessor(config)
        return processor.extract_first_frame(video_path, output_path)
    except Exception as e:
        logger.error(f"Ошибка извлечения кадра: {e}")
        return False


def resize_and_blur(img: np.ndarray, image_size: Tuple[int, int],
                    bokeh_blur_kernel: Tuple[int, int], bokeh_blur_sigma: float) -> np.ndarray:
    """Обратная совместимость: изменение размера и размытие с использованием OpenCV"""
    try:
        # Изменяем размер
        img_resized = image_processor.resize_image(img, image_size)

        # Применяем размытие через OpenCV
        logger.debug("🎨 resize_and_blur: применяем OpenCV размытие")
        logger.debug(f"🎨 OpenCV resize_and_blur с радиусом: {bokeh_blur_sigma}")
        blurred = image_processor.apply_gaussian_blur(img_resized, bokeh_blur_sigma)
        return blurred
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        return img


def process_image_fixed_height(img_path: str, desired_size: Tuple[int, int],
                               bokeh_blur_kernel: Tuple[int, int], bokeh_blur_sigma: float) -> Optional[np.ndarray]:
    """Обратная совместимость: обработка изображения с фиксированной высотой"""
    try:
        bokeh_config = BokehConfig(
            enabled=True,
            image_size=desired_size,
            blur_kernel=bokeh_blur_kernel,
            blur_sigma=bokeh_blur_sigma
        )
        processor = ImageProcessor(bokeh_config)

        # Применяем эффект боке и возвращаем Image объект
        return processor._apply_bokeh_effect(img_path)
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        return None


def concat_photos_random(processed_photo_files: List[str], temp_folder: str,
                         temp_audio_duration: float, clips_info: List[Dict] = None,
                         file_durations_map: Dict[str, float] = None) -> str:
    """Обратная совместимость: создание списка конкатенации (случайный порядок)"""
    concat_list_path = Path(temp_folder) / "concat_list.txt"

    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем порядок файлов из clips_info для включения видео с аудио
    if clips_info:
        # Извлекаем пути файлов из clips_info в правильном порядке
        files_from_clips_info = [clip["path"] for clip in clips_info]
        logger.info(f"🔧 Используем порядок файлов из clips_info для случайного: {len(files_from_clips_info)} файлов")
        return ConcatenationHelper.create_concat_list(files_from_clips_info, str(concat_list_path), shuffle=True,
                                                      clips_info=clips_info, file_durations_map=file_durations_map)
    else:
        # Fallback к старому поведению если clips_info недоступно
        logger.warning("⚠️ clips_info недоступно, используем processed_photo_files для случайного")
        return ConcatenationHelper.create_concat_list(processed_photo_files, str(concat_list_path), shuffle=True,
                                                      clips_info=clips_info, file_durations_map=file_durations_map)


def concat_photos_in_order(processed_photo_files: List[str], temp_folder: str,
                           temp_audio_duration: float, clips_info: List[Dict] = None,
                           file_durations_map: Dict[str, float] = None) -> str:
    """Обратная совместимость: создание списка конкатенации (по порядку)"""
    concat_list_path = Path(temp_folder) / "concat_list.txt"

    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем порядок файлов из clips_info для включения видео с аудио
    if clips_info:
        # Извлекаем пути файлов из clips_info в правильном порядке
        files_from_clips_info = [clip["path"] for clip in clips_info]
        logger.info(f"🔧 Используем порядок файлов из clips_info: {len(files_from_clips_info)} файлов")
        logger.debug(f"   Первые файлы: {[Path(f).name for f in files_from_clips_info[:5]]}")
        return ConcatenationHelper.create_concat_list(files_from_clips_info, str(concat_list_path), shuffle=False,
                                                      clips_info=clips_info, file_durations_map=file_durations_map)
    else:
        # Fallback к старому поведению если clips_info недоступно
        logger.warning("⚠️ clips_info недоступно, используем processed_photo_files")
        return ConcatenationHelper.create_concat_list(processed_photo_files, str(concat_list_path), shuffle=False,
                                                      clips_info=clips_info, file_durations_map=file_durations_map)


def get_folder_ranges_from_excel(excel_path: str, video_number: str) -> Tuple[int, int, List[str]]:
    """Обратная совместимость: получение диапазонов из Excel"""
    try:
        analyzer = MediaAnalyzer(excel_path)
        return analyzer.get_folder_ranges_from_excel(video_number)
    except Exception as e:
        logger.error(f"Ошибка анализа Excel: {e}")
        return 0, 0, []


def get_folder_durations(audio_folder: str, sorted_folders: List[str],
                         overall_range_start: int, overall_range_end: int,
                         silence_duration: str = "1.0-2.5") -> Tuple[
    Dict[str, float], float, Dict[int, float]]:
    """Обратная совместимость: получение длительностей папок (СТАРАЯ ЛОГИКА)"""
    try:
        # Создаем пустой временный Excel для совместимости
        import tempfile
        import pandas as pd

        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
            # Создаем простой Excel файл для совместимости
            df = pd.DataFrame({'A': ['ВИДЕО 1'], 'B': ['dummy']})
            df.to_excel(temp_file.name, index=False, header=False)

            analyzer = MediaAnalyzer(temp_file.name)
            folder_durations, total_duration = analyzer.calculate_folder_durations_new(
                audio_folder, sorted_folders, overall_range_start, overall_range_end, silence_duration
            )

        # Создаем словарь аудио длительностей для обратной совместимости
        audio_durations = {}
        validator = FFmpegValidator()
        for line_num in range(overall_range_start, overall_range_end + 1):
            audio_filename = f"{str(line_num).zfill(3)}.mp3"
            audio_file = Path(audio_folder) / audio_filename
            if audio_file.exists():
                try:
                    audio_durations[line_num] = validator.get_media_duration(str(audio_file))
                except:
                    audio_durations[line_num] = 0.0
            else:
                audio_durations[line_num] = 0.0

        return folder_durations, total_duration, audio_durations

    except Exception as e:
        logger.error(f"Ошибка получения длительностей папок: {e}")
        return {}, 0.0, {}


def preprocess_images(photo_folder_vid: str, preprocessed_photo_folder: str, bokeh_enabled: bool,
                      bokeh_image_size: Union[List[int], Tuple[int, int]],
                      bokeh_blur_kernel: Union[List[int], Tuple[int, int]],
                      bokeh_blur_sigma: float, video_resolution: Optional[str] = None,
                      frame_rate: Optional[int] = None, effects_config: dict = None,
                      debug_config: dict = None):
    """Обратная совместимость: предобработка изображений"""
    try:
        # Конвертируем списки в кортежи если необходимо
        if isinstance(bokeh_image_size, list):
            bokeh_image_size = tuple(bokeh_image_size)
        if isinstance(bokeh_blur_kernel, list):
            bokeh_blur_kernel = tuple(bokeh_blur_kernel)

        bokeh_config = BokehConfig(
            enabled=bokeh_enabled,
            image_size=bokeh_image_size,
            blur_kernel=bokeh_blur_kernel,
            blur_sigma=bokeh_blur_sigma
        )

        video_config = VideoConfig()
        if video_resolution:
            video_config.resolution = video_resolution  # Просто присваиваем
        if frame_rate:
            video_config.frame_rate = frame_rate

        # Находим все файлы для обработки
        image_files = find_files(photo_folder_vid, SUPPORTED_FORMATS, recursive=True)

        # Инициализируем процессоры
        image_processor_class = ImageProcessor(bokeh_config, effects_config)
        video_processor = VideoProcessor(video_config)
        validator = FFmpegValidator()

        # Счетчик для progress bar
        from image_processing_cv import SUPPORTED_IMAGE_FORMATS
        image_files_only = [f for f in image_files if Path(f).suffix.lower() in SUPPORTED_IMAGE_FORMATS]

        logger.info(f"Найдено файлов для предобработки: {len(image_files)} (изображений: {len(image_files_only)})")

        with tqdm(total=len(image_files_only), desc="🖼️ Обработка изображений", ncols=80) as pbar:
            for image_path in image_files:
                try:
                    image_path_obj = Path(image_path)
                    relative_path = image_path_obj.relative_to(Path(photo_folder_vid))

                    # Создаем выходную директорию
                    output_dir = Path(preprocessed_photo_folder) / relative_path.parent
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / image_path_obj.name

                    ext = image_path_obj.suffix.lower()

                    if ext in ('.png', '.jpg', '.jpeg', '.webp'):
                        # Обрабатываем изображение
                        success = image_processor_class.process_image(str(image_path), str(output_path))
                        if success:
                            logger.debug(f"Обработано изображение: {image_path_obj.name}")
                        else:
                            logger.warning(f"Не удалось обработать изображение: {image_path_obj.name}")
                        pbar.update(1)

                    elif ext in ('.mp4', '.mov'):
                        # Копируем видео (возможно с проверкой параметров)
                        if video_resolution and frame_rate:
                            is_match, _ = validator.check_video_params(str(image_path), video_config)
                            if not is_match:
                                logger.debug(f"Видео {image_path_obj.name} требует перекодирования")

                        shutil.copy2(image_path, output_path)
                        logger.debug(f"Скопировано видео: {image_path_obj.name}")

                except Exception as e:
                    logger.error(f"Ошибка обработки файла {image_path}: {e}")
                    continue

        logger.info("Предобработка изображений завершена")

    except Exception as e:
        logger.error(f"Ошибка предобработки изображений: {e}")


def process_photos_and_videos(photo_files: List[str], preprocessed_photo_folder: str, temp_folder: str,
                              video_resolution: str, frame_rate: int, video_crf: int, video_preset: str,
                              temp_audio_duration: float, audio_folder: str, overall_range_start: int,
                              overall_range_end: int, excel_path: str, video_number: str = "1",
                              photo_order: str = "order", adjust_videos_to_audio: bool = True,
                              preserve_clip_audio: bool = False, preserve_video_duration: bool = True,
                              effects_config: VideoEffectsConfig = None, silence_duration: str = "1.0-2.5",
                              folder_durations: Dict[str, float] = None,
                              excel_folder_to_files: Dict[str, List] = None,
                              debug_video_processing: bool = False) -> Tuple[
    List[str], List[str], List[Dict[str, Any]], float, Dict[str, float]]:
    """
    Обратная совместимость: основная функция обработки фото и видео

    Эта функция сохраняет оригинальную сигнатуру, но использует новые классы внутри
    """
    try:
        # Инициализируем все переменные в начале функции
        audio_offset = 0.0
        processed_files = []
        skipped_files = []
        clips_info = []
        file_durations_map = {}

        logger.info("=== 🎬 Начало обработки фото и видео ===")

        if not photo_files:
            logger.warning("Нет файлов для обработки")
            return [], [], [], 0.0, {}

        # Дополнительная диагностика входных файлов
        logger.info(f"📁 Получено файлов для обработки: {len(photo_files)}")
        existing_files = []
        missing_files = []

        for file_path in photo_files:
            if os.path.exists(file_path):
                existing_files.append(file_path)
                logger.debug(f"✅ Файл существует: {file_path}")
            else:
                missing_files.append(file_path)
                logger.error(f"❌ Файл не найден: {file_path}")

        logger.info(f"📊 Существующих файлов: {len(existing_files)}")
        logger.info(f"📊 Отсутствующих файлов: {len(missing_files)}")

        if not existing_files:
            logger.error("❌ Ни одного существующего файла не найдено!")
            raise VideoProcessingError("Все входные файлы отсутствуют")

        # Обновляем список файлов только существующими
        photo_files = existing_files

        # Инициализация
        # ИСПРАВЛЕНИЕ: Конвертируем формат разрешения из "1920x1080" в "1920:1080"
        if 'x' in video_resolution:
            resolution_fixed = video_resolution.replace('x', ':')
        else:
            resolution_fixed = video_resolution

        video_config = VideoConfig({
            "video_resolution": resolution_fixed,
            "frame_rate": frame_rate,
            "video_crf": video_crf,
            "video_preset": video_preset
        })

        # Используем переданную конфигурацию эффектов или создаем пустую
        if effects_config is None:
            effects_config = VideoEffectsConfig()

        video_processor = VideoProcessor(video_config, effects_config)
        validator = FFmpegValidator()
        analyzer = MediaAnalyzer(excel_path)

        # Проверяем свободное место на диске
        if not check_disk_space(Path(temp_folder), required_gb=2.0):
            logger.error("❌ Недостаточно свободного места на диске!")
            raise VideoProcessingError("Недостаточно свободного места на диске")

        # Проверяем работоспособность FFmpeg
        ffmpeg_path = ffmpeg_utils_get_ffmpeg_path()
        if not _test_ffmpeg_working(ffmpeg_path, debug=debug_video_processing):
            logger.error("❌ FFmpeg не работает!")
            raise VideoProcessingError("FFmpeg недоступен или не работает")

        # Результаты
        processed_files = []
        skipped_files = []
        clips_info = []

        # ДИАГНОСТИКА: проверяем доступные файлы
        logger.info(f"📊 ДИАГНОСТИКА ДОСТУПНЫХ ФАЙЛОВ:")
        logger.info(f"   Путь: {preprocessed_photo_folder}")
        logger.info(f"   Всего файлов в photo_files: {len(photo_files)}")

        # Показываем первые 10 файлов для диагностики
        for i, file_path in enumerate(photo_files[:10]):
            logger.info(f"   {i + 1}. {Path(file_path).name} -> {file_path}")

        if len(photo_files) > 10:
            logger.info(f"   ... и еще {len(photo_files) - 10} файлов")

        # Универсальная группировка файлов по папкам (с фильтрацией скрытых файлов)
        def extract_folder_name(file_path: str, base_folder: str) -> Optional[str]:
            """Универсальная функция извлечения имени папки из пути файла"""
            try:
                file_name = Path(file_path).name
                if file_name.startswith('.'):
                    return None  # Скрытые файлы пропускаем

                relative_path = Path(file_path).relative_to(Path(base_folder))
                raw_folder_name = str(relative_path.parent) if str(relative_path.parent) != "." else "root"

                # Убираем префикс папки если он есть (например "1-10/1-2" -> "1-2")
                folder_name = raw_folder_name.split('/')[-1] if '/' in raw_folder_name else raw_folder_name

                return folder_name
            except Exception as e:
                logger.error(f"❌ Ошибка извлечения имени папки для {file_path}: {e}")
                return "unknown"

        folder_files = {}
        logger.info(f"🔍 ЕДИНЫЙ АЛГОРИТМ: Группируем {len(photo_files)} файлов по папкам")
        logger.info(f"   preprocessed_photo_folder: {preprocessed_photo_folder}")

        for i, file_path in enumerate(photo_files):
            folder_name = extract_folder_name(file_path, preprocessed_photo_folder)
            if folder_name is None:
                logger.debug(f"🚫 Пропускаем скрытый файл: {Path(file_path).name}")
                continue

            if folder_name not in folder_files:
                folder_files[folder_name] = []
            folder_files[folder_name].append(file_path)

            # Показываем первые 5 файлов для диагностики
            if i < 5:
                logger.info(f"   Файл {i + 1}: {Path(file_path).name} → папка '{folder_name}'")

        # КРИТИЧЕСКАЯ ПРОВЕРКА: если folder_files пуст, это серьезная проблема
        if not folder_files:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: folder_files пуст!")
            logger.error(f"   photo_files: {len(photo_files)} файлов")
            logger.error(f"   preprocessed_photo_folder: {preprocessed_photo_folder}")
            logger.error(f"   Первые 3 файла: {[Path(f).name for f in photo_files[:3]]}")
            # Не переходим к равномерному распределению, а создаем папки принудительно
            # Создаем папки на основе структуры на диске
            base_path = os.path.dirname(preprocessed_photo_folder)
            for possible_folder in ["1-2", "3-4", "5-8", "9-13", "14-31"]:
                folder_path = os.path.join(base_path, possible_folder)
                if os.path.exists(folder_path):
                    from utils import find_files
                    from image_processing_cv import SUPPORTED_FORMATS
                    files_in_folder = find_files(folder_path, SUPPORTED_FORMATS, recursive=True)
                    if files_in_folder:
                        folder_files[possible_folder] = files_in_folder
                        logger.info(f"✅ Принудительно создали папку '{possible_folder}': {len(files_in_folder)} файлов")

        # ДИАГНОСТИКА: показываем структуру папок
        logger.info(f"📁 ДИАГНОСТИКА СТРУКТУРЫ ПАПОК:")
        total_files_in_folders = 0
        for folder_name, files in folder_files.items():
            logger.info(f"   Папка '{folder_name}': {len(files)} файлов")
            total_files_in_folders += len(files)
        logger.info(f"   Итого файлов в папках: {total_files_in_folders}")

        # Универсальная сортировка папок
        def universal_folder_sort_key(folder_name: str) -> Tuple[int, int]:
            """Универсальная функция сортировки папок с улучшенной обработкой ошибок"""
            if folder_name == "root":
                return (0, 0)
            try:
                # Имена папок уже очищены при создании folder_files
                logger.debug(f"Сортировка папки: '{folder_name}'")

                if '-' in folder_name:
                    parts = folder_name.split('-')
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        start = int(parts[0])
                        end = int(parts[1])
                    else:
                        logger.warning(f"⚠️ Неправильный формат папки: {folder_name}")
                        return (999, 999)
                else:
                    if folder_name.isdigit():
                        start = end = int(folder_name)
                    else:
                        logger.warning(f"⚠️ Неправильный формат папки: {folder_name}")
                        return (999, 999)

                logger.debug(f"Ключ сортировки для '{folder_name}': ({start}, {end})")
                return (start, end)
            except (ValueError, IndexError, AttributeError) as e:
                logger.error(f"❌ Ошибка парсинга папки '{folder_name}': {e}")
                return (999, 999)

        # Проверяем, что folder_files не пуст
        if not folder_files:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: folder_files пуст, невозможно продолжить!")
            return [], [], [], 0.0, {}

        sorted_folders = sorted(folder_files.keys(), key=universal_folder_sort_key)
        logger.info(f"Найдено папок: {sorted_folders}")

        # НОВАЯ ЛОГИКА: Используем переданный temp_audio_duration, который уже содержит Excel расчёты из main.py
        logger.info(f"📊 Получена готовая temp_audio_duration из main.py: {temp_audio_duration:.3f}с")
        logger.info(f"📊 Отсортированные папки: {sorted_folders}")
        logger.info(f"📊 Диапазон Excel: {overall_range_start}-{overall_range_end}")
        logger.info(f"⚙️ Подстраивать видео под аудио: {'✅ Включено' if adjust_videos_to_audio else '❌ Отключено'}")

        # Используем переданную длительность напрямую (она уже содержит Excel логику)
        excel_audio_duration = temp_audio_duration
        logger.info(f"🎯 НОВАЯ ЛОГИКА: Используем переданную длительность {temp_audio_duration:.2f}с")

        # Инициализируем словарь для хранения длительностей файлов в самом начале
        file_durations = {}

        # ИСПРАВЛЕННАЯ ЛОГИКА: Используем фиксированные диапазоны аудиофайлов из Excel
        if adjust_videos_to_audio:
            logger.info("📊 Расчет длительностей папок из Excel")

            # Сначала получаем список ожидаемых папок из Excel
            temp_folder_durations, _, _ = analyzer.calculate_folder_durations_excel_based(
                audio_folder, video_number, silence_duration
            )

            # Получаем информацию о папках на диске
            photo_folders_analysis = {}
            base_folder = Path(preprocessed_photo_folder)

            # Проверяем папки на двух уровнях вложенности
            for folder_path in base_folder.iterdir():
                if folder_path.is_dir() and not folder_path.name.startswith('.'):
                    # Проверяем, содержит ли эта папка медиафайлы
                    from utils import find_files
                    from image_processing_cv import SUPPORTED_FORMATS
                    files = find_files(str(folder_path), SUPPORTED_FORMATS, recursive=False)

                    if files:
                        # Если есть файлы на этом уровне, добавляем папку
                        folder_name = folder_path.name
                        # Проверяем, что эта папка соответствует одной из папок из Excel
                        if temp_folder_durations and folder_name in temp_folder_durations:
                            photo_folders_analysis[folder_name] = {
                                "full_path": str(folder_path),
                                "files_count": len(files),
                                "files": files
                            }
                            logger.info(f"✅ Найдена папка '{folder_name}' с {len(files)} файлами")
                    else:
                        # Если нет файлов, проверяем вложенные папки
                        for subfolder_path in folder_path.iterdir():
                            if subfolder_path.is_dir() and not subfolder_path.name.startswith('.'):
                                subfolder_name = subfolder_path.name
                                # Проверяем, что эта папка соответствует одной из папок из Excel
                                if temp_folder_durations and subfolder_name in temp_folder_durations:
                                    subfiles = find_files(str(subfolder_path), SUPPORTED_FORMATS, recursive=True)

                                    if subfiles:
                                        photo_folders_analysis[subfolder_name] = {
                                            "full_path": str(subfolder_path),
                                            "files_count": len(subfiles),
                                            "files": subfiles
                                        }
                                        logger.info(
                                            f"✅ Найдена вложенная папка '{subfolder_name}' с {len(subfiles)} файлами")

            folder_durations, total_excel_duration, folder_to_files = analyzer.calculate_folder_durations_excel_based(
                audio_folder, video_number, silence_duration, photo_folders_analysis
            )

            logger.info(f"📊 Длительности папок: {folder_durations}")
            logger.info(f"📊 Общая длительность: {total_excel_duration:.2f}с")
        else:
            folder_durations = {}
            folder_to_files = {}

        if not folder_durations:
            logger.warning("⚠️ folder_durations пустой! Будет использована равномерная распределение.")
        else:
            logger.info(f"✅ Найдено {len(folder_durations)} папок с длительностями")
            # Дополнительная диагностика нулевых длительностей
            zero_durations = [f for f, d in folder_durations.items() if d <= 0.0]
            if zero_durations:
                logger.warning(f"⚠️ Обнаружены папки с нулевой длительностью: {zero_durations}")
                logger.warning(f"⚠️ Обрезка видео будет отключена для всех файлов из этих папок")

        # Сортировка файлов внутри папок
        all_sorted_files = []

        # Дополнительная проверка безопасности
        if not sorted_folders:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: sorted_folders пуст!")
            return [], [], [], 0.0, {}

        for folder in sorted_folders:
            if folder not in folder_files:
                logger.warning(f"⚠️ Папка '{folder}' отсутствует в folder_files")
                continue

            files_in_folder = folder_files[folder]
            if not files_in_folder:
                logger.warning(f"⚠️ Папка '{folder}' не содержит файлов")
                continue

            if photo_order == "random":
                random.shuffle(files_in_folder)
            else:
                files_in_folder.sort(key=lambda x: natural_sort_key(Path(x).stem))
            all_sorted_files.extend(files_in_folder)

        # Проверяем что у нас есть файлы для обработки
        if not all_sorted_files:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: all_sorted_files пуст после сортировки!")
            return [], [], [], 0.0, {}

        # ДОБАВЛЕНО: Вызываем функцию для вычисления длительностей файлов после определения all_sorted_files
        logger.info(f"📊 Вызываем calculate_file_durations_properly с {len(all_sorted_files)} файлами")

        # ПРАВИЛЬНАЯ ЛОГИКА: используем фактические файлы в папках согласно DURATION_ANALYSIS.md
        logger.info("🔧 ПРАВИЛЬНАЯ ЛОГИКА: используем фактические файлы в папках вместо Excel диапазонов")

        # ПРАВИЛЬНАЯ ЛОГИКА: Excel длительности + фактические файлы из папок
        if folder_files and isinstance(folder_files, dict):
            # Используем Excel длительности для папок (правильные значения)
            correct_folder_durations = folder_durations.copy()

            logger.info(f"📊 Используем Excel длительности для папок:")
            for folder_name, duration in correct_folder_durations.items():
                folder_data = folder_files.get(folder_name, [])

                # Извлекаем файлы из новой структуры данных
                actual_files_in_folder = []
                if isinstance(folder_data, list) and len(folder_data) > 0:
                    if isinstance(folder_data[0], dict) and "file_path" in folder_data[0]:
                        # Новая структура - список словарей с excel_row и file_path
                        actual_files_in_folder = [item["file_path"] for item in folder_data if "file_path" in item]
                    else:
                        # Старая структура - список файлов или номера строк Excel
                        actual_files_in_folder = folder_data

                files_count = len(actual_files_in_folder)
                logger.info(f"   📁 Папка '{folder_name}': {files_count} файлов → {duration:.2f}с (из Excel)")

            logger.info(f"📊 Итоговые длительности папок (Excel): {correct_folder_durations}")

            # КОРРЕКТИРОВКА ДЛИТЕЛЬНОСТЕЙ ПОД XFADE ПЕРЕХОДЫ (согласно pro81)
            # Создаем изменяемую копию для корректировки
            adjusted_folder_durations_for_excel = correct_folder_durations.copy()

            total_adjusted_expected_duration = 0.0

            if effects_config and hasattr(effects_config, 'transitions_enabled') and hasattr(effects_config,
                                                                                             'transition_method') and hasattr(
                    effects_config, 'transition_duration'):
                xfade_duration = effects_config.transition_duration  # Длительность перехода из конфигурации

                if effects_config.transitions_enabled and effects_config.transition_method == "xfade":
                    logger.info(
                        f"🔧 Корректировка Excel длительностей под XFADE переходы (длительность перехода: {xfade_duration}с)...")
                    for folder_name, folder_files_data in folder_files.items():
                        # Извлекаем количество файлов в папке
                        if isinstance(folder_files_data, list) and len(folder_files_data) > 0:
                            if isinstance(folder_files_data[0], dict) and "file_path" in folder_files_data[0]:
                                # Новая структура - список словарей с excel_row и file_path
                                num_clips_in_folder = len([item for item in folder_files_data if "file_path" in item])
                            else:
                                # Старая структура - список файлов
                                num_clips_in_folder = len(folder_files_data)
                        else:
                            num_clips_in_folder = 0

                        # Рассчитываем общее количество переходов внутри текущей папки
                        # Если в папке N клипов, то внутри нее N-1 переходов.
                        # Если 0 или 1 клип, то переходов нет.
                        num_transitions_in_folder = max(0, num_clips_in_folder - 1)

                        # Общее время, которое переходы "съедят" в этой папке
                        total_xfade_overlap_in_folder = num_transitions_in_folder * xfade_duration

                        original_duration = adjusted_folder_durations_for_excel.get(folder_name, 0.0)

                        # Вычитаем "съеденное" время из ожидаемой длительности папки
                        # Защита от слишком короткой длительности (минимум 1 кадр)
                        adjusted_duration = max(0.033, original_duration - total_xfade_overlap_in_folder)

                        adjusted_folder_durations_for_excel[folder_name] = adjusted_duration
                        total_adjusted_expected_duration += adjusted_duration

                        logger.info(
                            f"    📁 {folder_name}: Ориг.={original_duration:.2f}с, Клипов={num_clips_in_folder}, Переходов={num_transitions_in_folder}, Оверлей={total_xfade_overlap_in_folder:.2f}с, Скорр.={adjusted_duration:.2f}с")
                else:
                    # Если XFADE переходы не включены, используем оригинальные длительности как есть
                    for duration in adjusted_folder_durations_for_excel.values():
                        total_adjusted_expected_duration += duration
                    logger.info("🔧 XFADE переходы отключены, корректировка длительностей не требуется.")
            else:
                # Если нет данных о переходах, используем оригинальные длительности
                for duration in adjusted_folder_durations_for_excel.values():
                    total_adjusted_expected_duration += duration
                logger.info("🔧 Нет данных о переходах, используем оригинальные длительности.")

            # Заменяем оригинальный словарь длительностей на скорректированный для последующих расчетов
            correct_folder_durations = adjusted_folder_durations_for_excel

            # Логируем обновленную общую ожидаемую длительность
            logger.info(f"📊 Итоговые скорректированные длительности папок (Excel): {correct_folder_durations}")
            logger.info(
                f"📊 Общая скорректированная ожидаемая длительность: {total_adjusted_expected_duration:.2f}с = {total_adjusted_expected_duration / 60:.2f} минут")

        else:
            # Fallback: если фактические файлы недоступны, используем Excel данные
            if folder_durations and isinstance(folder_durations, dict):
                correct_folder_durations = folder_durations.copy()
                logger.warning("⚠️ Используем Excel длительности как fallback")
            else:
                correct_folder_durations = {}
                logger.warning("⚠️ Нет данных о длительностях папок")

        if correct_folder_durations:
            total_expected_duration = sum(correct_folder_durations.values())
            logger.info(
                f"📊 Общая ожидаемая длительность: {total_expected_duration:.2f}с = {total_expected_duration / 60:.2f} минут")
        else:
            logger.warning("⚠️ Нет данных о длительностях папок")

        # ДИАГНОСТИКА: проверяем переданные данные с проверками типов
        logger.info(f"🔍 ДИАГНОСТИКА ПЕРЕДАННЫХ ДАННЫХ:")

        # Проверяем типы входных данных
        if not isinstance(excel_folder_to_files, dict):
            logger.error(
                f"❌ ОШИБКА ТИПОВ: excel_folder_to_files должен быть словарем, получен {type(excel_folder_to_files)}")
            excel_folder_to_files = {}

        if not isinstance(all_sorted_files, list):
            logger.error(f"❌ ОШИБКА ТИПОВ: all_sorted_files должен быть списком, получен {type(all_sorted_files)}")
            all_sorted_files = []

        if not isinstance(folder_durations, dict):
            logger.error(f"❌ ОШИБКА ТИПОВ: folder_durations должен быть словарем, получен {type(folder_durations)}")
            folder_durations = {}

        logger.info(f"   excel_folder_to_files: {excel_folder_to_files}")
        logger.info(f"   all_sorted_files: {len(all_sorted_files)} файлов")
        logger.info(f"   folder_durations: {folder_durations}")

        # ИСПРАВЛЕНИЕ: используем фактические файлы в папках согласно DURATION_ANALYSIS.md
        if folder_files:
            logger.info("📊 Используем фактические файлы в папках согласно DURATION_ANALYSIS.md")
            actual_folder_files = {}

            # ДИАГНОСТИКА: проверяем фактические файлы в папках
            total_actual_files = 0
            for folder_name, folder_data in folder_files.items():
                if isinstance(folder_data, list):
                    # Извлекаем файлы из новой структуры данных
                    if len(folder_data) > 0 and isinstance(folder_data[0], dict) and "file_path" in folder_data[0]:
                        # Новая структура - список словарей с excel_row и file_path
                        actual_files_count = len([item for item in folder_data if "file_path" in item])
                    else:
                        # Старая структура - список файлов или номера строк Excel
                        actual_files_count = len(folder_data)
                    total_actual_files += actual_files_count
                else:
                    logger.error(
                        f"❌ ОШИБКА ТИПОВ: файлы папки '{folder_name}' должны быть списком, получен {type(folder_data)}")
                    folder_files[folder_name] = []
            logger.info(f"📊 ДИАГНОСТИКА ФАКТИЧЕСКИХ ФАЙЛОВ:")
            logger.info(f"   Фактически в папках: {total_actual_files} файлов")
            logger.info(f"   Доступно all_sorted_files: {len(all_sorted_files)} файлов")

            # Используем фактические файлы из папок
            for folder_name, folder_data in folder_files.items():
                # Извлекаем файлы из новой структуры данных
                files_for_folder = []
                if isinstance(folder_data, list) and len(folder_data) > 0:
                    if isinstance(folder_data[0], dict) and "file_path" in folder_data[0]:
                        # Новая структура - список словарей с excel_row и file_path
                        files_for_folder = [item["file_path"] for item in folder_data if "file_path" in item]
                    else:
                        # Старая структура - список файлов или номера строк Excel
                        files_for_folder = folder_data.copy()

                logger.info(f"📁 Папка '{folder_name}': фактически содержит {len(files_for_folder)} файлов")

                # Убеждаемся, что файлы существуют
                existing_files = []
                for file_path in files_for_folder:
                    if os.path.exists(file_path):
                        existing_files.append(file_path)
                        logger.debug(f"   ✅ Файл существует: {Path(file_path).name}")
                    else:
                        logger.warning(f"   ❌ Файл не найден: {file_path}")

                actual_folder_files[folder_name] = existing_files
                logger.info(
                    f"📁 Папка '{folder_name}': {len(existing_files)} файлов найдено на диске (из {len(files_for_folder)} указанных)")

                # КРИТИЧЕСКАЯ ПРОВЕРКА: если файлов нет - это проблема
                if len(existing_files) == 0:
                    logger.error(f"❌ Папка '{folder_name}': не найдено ни одного файла!")
                    logger.error(f"❌ Возможные причины: файлы не существуют или неправильные пути")
                    logger.error(f"❌ Исходные файлы папки: {files_for_folder}")
                else:
                    logger.info(f"✅ Папка '{folder_name}': {len(existing_files)} файлов готовы к обработке")
        else:
            logger.info("🔍 ЕДИНЫЙ ПРАВИЛЬНЫЙ АЛГОРИТМ: Используем фактические файлы из папок на диске")
            # ИСПРАВЛЕНИЕ: Читаем фактические файлы из папок на диске
            actual_folder_files = {}

            # Определяем базовую папку для поиска
            base_folder = os.path.dirname(preprocessed_photo_folder)
            if not os.path.exists(base_folder):
                base_folder = preprocessed_photo_folder

            logger.info(f"🔍 Поиск фактических папок в: {base_folder}")

            for folder_name in correct_folder_durations.keys():
                # Попробуем найти папку на диске
                folder_path = os.path.join(base_folder, folder_name)
                if not os.path.exists(folder_path):
                    # Попробуем в preprocessed_photo_folder
                    folder_path = os.path.join(preprocessed_photo_folder, folder_name)

                if os.path.exists(folder_path):
                    # Читаем фактические файлы из папки
                    from utils import find_files
                    from image_processing_cv import SUPPORTED_FORMATS
                    folder_files = find_files(folder_path, SUPPORTED_FORMATS, recursive=True)
                    actual_folder_files[folder_name] = folder_files
                    logger.info(
                        f"✅ Папка '{folder_name}': {len(folder_files)} фактических файлов из папки {folder_path}")
                else:
                    logger.warning(f"⚠️ Папка '{folder_name}' не найдена на диске: {folder_path}")
                    actual_folder_files[folder_name] = []

            # Проверяем, что нашли файлы
            total_found_files = sum(len(files) for files in actual_folder_files.values())
            logger.info(f"🔍 Найдено файлов на диске: {total_found_files}")

            # Если не нашли файлы, используем все файлы из общего списка
            if total_found_files == 0:
                logger.warning("⚠️ Не найдено фактических папок на диске, используем все файлы из общего списка")
                # Распределяем все файлы по первой папке
                first_folder = list(correct_folder_durations.keys())[0]
                actual_folder_files[first_folder] = all_sorted_files
                for folder_name in list(correct_folder_durations.keys())[1:]:
                    actual_folder_files[folder_name] = []

        # СТАРАЯ ЛОГИКА УДАЛЕНА: Равномерное распределение длительностей
        # Теперь длительности вычисляются правильно в функции calculate_media_sequence_for_folder
        # которая учитывает приоритет видео над фото

        total_expected_duration = sum(correct_folder_durations.values())
        logger.info(f"📊 Итоговая ожидаемая длительность: {total_expected_duration:.2f}с")

        # Создаем новый список файлов в правильном порядке
        reordered_files = []

        # ИСПРАВЛЕНИЕ: Используем динамически полученные папки вместо фиксированного списка
        if actual_folder_files:
            logger.info(f"📁 Обнаружены папки в actual_folder_files: {list(actual_folder_files.keys())}")

            # Сортируем папки в правильном порядке для обработки
            folder_names = list(actual_folder_files.keys())

            # Пытаемся отсортировать папки по логике диапазонов
            def folder_sort_key(folder_name):
                # Для папок вида "1-2", "3-5", "6", "7", "8-10" и т.д.
                if '-' in folder_name:
                    start_num = int(folder_name.split('-')[0])
                    return start_num
                else:
                    try:
                        return int(folder_name)
                    except:
                        return 999  # Неопознанные папки в конец

            folder_names.sort(key=folder_sort_key)
            logger.info(f"📊 Порядок обработки папок: {folder_names}")

            for folder_name in folder_names:
                folder_files_list = actual_folder_files.get(folder_name, [])
                logger.info(f"📁 Папка '{folder_name}': {len(folder_files_list)} файлов")

                # Сортируем файлы в папке
                if photo_order == "random":
                    random.shuffle(folder_files_list)
                else:
                    folder_files_list.sort(key=lambda x: natural_sort_key(Path(x).stem))

                reordered_files.extend(folder_files_list)
        else:
            logger.warning("⚠️ actual_folder_files пуст, используем исходный список файлов")
            reordered_files = photo_files

        # Классификация файлов
        video_clips_with_audio = []
        video_clips_without_audio = []
        photo_files_only = []

        logger.info(f"📊 ДИАГНОСТИКА КЛАССИФИКАЦИИ:")
        logger.info(f"   Всего файлов в reordered_files: {len(reordered_files)}")

        for file_path in reordered_files:
            ext = Path(file_path).suffix.lower()
            logger.debug(f"   Файл: {Path(file_path).name} -> расширение: {ext}")

            if ext in ('.mp4', '.mov'):
                if preserve_clip_audio and validator.has_audio_stream(file_path):
                    video_clips_with_audio.append(file_path)
                    logger.debug(f"   -> Видео с аудио")
                else:
                    video_clips_without_audio.append(file_path)
                    logger.debug(f"   -> Видео без аудио")
            else:
                photo_files_only.append(file_path)
                logger.debug(f"   -> Фото")

        logger.info(f"📊 РЕЗУЛЬТАТ КЛАССИФИКАЦИИ:")
        logger.info(f"   Видеоклипы с аудио: {len(video_clips_with_audio)}")
        logger.info(f"   Видеоклипы без аудио: {len(video_clips_without_audio)}")
        logger.info(f"   Фото: {len(photo_files_only)}")

        # Если нет фото - это критическая ошибка
        if len(photo_files_only) == 0 and len(video_clips_with_audio) == 0 and len(video_clips_without_audio) == 0:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Ни одного файла не классифицировано!")
            logger.error(f"   reordered_files: {reordered_files}")
            logger.error(f"   actual_folder_files: {actual_folder_files}")
            return [], [], [], 0.0, {}

        # ИСПРАВЛЕНО: Не перезаписываем file_durations_map старой логикой!
        # file_durations_map уже правильно заполнен в цикле обработки файлов
        # file_durations_map = file_durations  # <-- УБРАНО! Эта строка перезаписывала правильные длительности

        # СОЗДАНИЕ ДИАГНОСТИЧЕСКОГО JSON ФАЙЛА
        diagnostic_data = {
            "timestamp": datetime.now().isoformat(),
            "video_number": video_number,
            "excel_path": excel_path,
            "input_data": {
                "total_files": len(all_sorted_files),
                "temp_audio_duration": temp_audio_duration,
                "adjust_videos_to_audio": adjust_videos_to_audio,
                "photo_order": photo_order,
                "overall_range": f"{overall_range_start}-{overall_range_end}",
                "folders_found": list(folder_files.keys()),
                "sorted_folders": sorted_folders
            },
            "folder_analysis": {
                "correct_folder_durations": correct_folder_durations,
                "total_expected_duration": sum(correct_folder_durations.values()),
                "total_expected_minutes": sum(correct_folder_durations.values()) / 60,
                "folder_durations_from_excel": folder_durations if folder_durations else {},
                "excel_folder_to_files": excel_folder_to_files if excel_folder_to_files else {}
            },
            "file_distribution": {},
            "duration_calculations": {},
            "final_results": {}
        }

        # Детальная информация о распределении файлов
        if excel_folder_to_files:
            diagnostic_data["file_distribution"]["method"] = "excel_based"
            diagnostic_data["file_distribution"]["source"] = "Excel данные для распределения файлов по папкам"
            for folder_name, file_items in excel_folder_to_files.items():
                files_for_folder = []
                excel_rows = []

                # Проверяем новую структуру данных - список словарей с excel_row и file_path
                if isinstance(file_items, list) and len(file_items) > 0:
                    if isinstance(file_items[0], dict) and "excel_row" in file_items[0]:
                        # Новая структура - список словарей с excel_row и file_path
                        for item in file_items:
                            excel_row = item.get("excel_row")
                            file_path = item.get("file_path")
                            folder_name_from_item = item.get("folder_name", folder_name)

                            if file_path and os.path.exists(file_path):
                                files_for_folder.append({
                                    "excel_row": excel_row,
                                    "file_path": file_path,
                                    "file_name": Path(file_path).name,
                                    "folder_name": folder_name_from_item
                                })
                                if excel_row is not None:
                                    excel_rows.append(excel_row)
                    else:
                        # Старая структура - файлы или номера строк
                        for file_item in file_items:
                            # ИСПРАВЛЕНИЕ: file_item может быть путем к файлу или номером строки
                            if isinstance(file_item, str) and ('/' in file_item or '\\' in file_item):
                                # Это путь к файлу (новая логика с фактическими файлами)
                                if os.path.exists(file_item):
                                    # Попытаемся извлечь номер строки Excel из имени файла
                                    file_basename = Path(file_item).name
                                    excel_row = None
                                    try:
                                        # Попробуем найти номер в имени файла (например, "1.mov" -> 1)
                                        if file_basename.split('.')[0].isdigit():
                                            excel_row = int(file_basename.split('.')[0])
                                    except:
                                        pass

                                    files_for_folder.append({
                                        "excel_row": excel_row,
                                        "file_path": file_item,
                                        "file_name": file_basename
                                    })
                                    excel_rows.append(excel_row)
                                else:
                                    logger.warning(f"   ❌ Файл не найден: {file_item}")
                            else:
                                # Это может быть номер строки Excel
                                try:
                                    file_number_int = int(file_item)
                                    if 1 <= file_number_int <= len(all_sorted_files):
                                        file_path = all_sorted_files[file_number_int - 1]
                                        files_for_folder.append({
                                            "excel_row": file_number_int,
                                            "file_path": file_path,
                                            "file_name": Path(file_path).name
                                        })
                                        excel_rows.append(file_number_int)
                                    else:
                                        logger.warning(
                                            f"   ❌ Строка {file_number_int} -> файл не найден (доступно файлов: {len(all_sorted_files)})")
                                except (ValueError, TypeError):
                                    logger.error(f"   ❌ Некорректный элемент: {file_item} (тип: {type(file_item)})")
                                    continue

                diagnostic_data["file_distribution"][folder_name] = {
                    "files_count": len(files_for_folder),
                    "excel_rows": excel_rows,
                    "files": files_for_folder
                }
        else:
            diagnostic_data["file_distribution"]["method"] = "uniform_distribution"
            diagnostic_data["file_distribution"]["source"] = "Равномерное распределение (fallback)"
            files_per_folder = len(all_sorted_files) // len(correct_folder_durations)
            remainder = len(all_sorted_files) % len(correct_folder_durations)
            start_idx = 0
            for i, folder_name in enumerate(correct_folder_durations.keys()):
                count = files_per_folder + (1 if i < remainder else 0)
                folder_files_list = all_sorted_files[start_idx:start_idx + count]
                diagnostic_data["file_distribution"][folder_name] = {
                    "files_count": count,
                    "start_index": start_idx,
                    "end_index": start_idx + count - 1,
                    "files": [{"file_path": f, "file_name": Path(f).name} for f in folder_files_list]
                }
                start_idx += count

        # Расчеты длительностей
        for folder_name, folder_duration in correct_folder_durations.items():
            files_in_folder = diagnostic_data["file_distribution"].get(folder_name, {}).get("files", [])
            if files_in_folder:
                file_duration = folder_duration / len(files_in_folder)
                diagnostic_data["duration_calculations"][folder_name] = {
                    "folder_duration": folder_duration,
                    "files_count": len(files_in_folder),
                    "duration_per_file": file_duration,
                    "total_folder_duration": folder_duration,
                    "files_with_durations": []
                }
                for file_info in files_in_folder:
                    file_path = file_info["file_path"]
                    calculated_duration = file_durations_map.get(file_path, file_duration)
                    diagnostic_data["duration_calculations"][folder_name]["files_with_durations"].append({
                        "file_name": file_info["file_name"],
                        "file_path": file_path,
                        "calculated_duration": calculated_duration
                    })

        # Финальные результаты
        diagnostic_data["final_results"] = {
            "total_files_processed": len(file_durations_map),
            "total_calculated_duration": sum(file_durations_map.values()) if file_durations_map else 0,
            "file_durations_map_sample": dict(list(file_durations_map.items())[:10]) if file_durations_map else {},
            "expected_vs_calculated": {
                "expected_total": sum(correct_folder_durations.values()),
                "calculated_total": sum(file_durations_map.values()) if file_durations_map else 0,
                "difference": sum(correct_folder_durations.values()) - (
                    sum(file_durations_map.values()) if file_durations_map else 0)
            }
        }

        # Сохранение диагностического файла
        diagnostic_file_path = Path(temp_folder) / f"video_duration_diagnostic_{video_number}.json"
        try:
            with open(diagnostic_file_path, 'w', encoding='utf-8') as f:
                json.dump(diagnostic_data, f, indent=2, ensure_ascii=False)
            logger.info(f"📊 Диагностический файл сохранен: {diagnostic_file_path}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения диагностического файла: {e}")

        # Логирование ключевых метрик
        logger.info(f"📊 ДИАГНОСТИЧЕСКИЕ МЕТРИКИ:")
        logger.info(f"   📁 Метод распределения: {diagnostic_data['file_distribution']['method']}")
        logger.info(f"   📊 Всего файлов: {diagnostic_data['input_data']['total_files']}")
        logger.info(
            f"   ⏱️ Ожидаемая длительность: {diagnostic_data['folder_analysis']['total_expected_duration']:.2f}с ({diagnostic_data['folder_analysis']['total_expected_minutes']:.2f} мин)")
        logger.info(
            f"   🔢 Вычисленная длительность: {diagnostic_data['final_results']['total_calculated_duration']:.2f}с")
        logger.info(f"   📂 Распределение по папкам:")
        for folder_name in correct_folder_durations.keys():
            folder_info = diagnostic_data["file_distribution"].get(folder_name, {})
            logger.info(f"      {folder_name}: {folder_info.get('files_count', 0)} файлов")

        # ДИАГНОСТИКА: Детальная информация о вычисленных длительностях
        logger.info(f"🔍 ДИАГНОСТИКА ДЛИТЕЛЬНОСТЕЙ ФАЙЛОВ:")
        logger.info(f"   temp_audio_duration (входной): {temp_audio_duration:.3f}с")
        logger.info(f"   adjust_videos_to_audio: {adjust_videos_to_audio}")
        logger.info(f"   Всего файлов: {len(all_sorted_files)}")
        logger.info(f"   Файлов с вычисленной длительностью: {len(file_durations_map)}")

        # Показываем первые несколько файлов для диагностики
        for i, file_path in enumerate(all_sorted_files[:10]):
            file_name = Path(file_path).name
            duration = file_durations_map.get(file_path, "оригинальная")
            logger.info(f"   Файл {i + 1}: {file_name} -> {duration}с")

        if len(all_sorted_files) > 10:
            logger.info(f"   ... и еще {len(all_sorted_files) - 10} файлов")

        # Вычисляем ожидаемую общую длительность
        expected_total = sum(file_durations_map.values()) if file_durations_map else 0
        logger.info(f"   Ожидаемая общая длительность медиафайлов: {expected_total:.3f}с")

        # ИСПРАВЛЕНИЕ: Определяем функцию calculate_target_duration ДО её первого использования
        def calculate_target_duration(file_path: str, folder_durations: Dict[str, float],
                                      all_sorted_files: List[str]) -> Optional[float]:
            """Возвращает предвычисленную длительность для файла"""
            target_duration = file_durations_map.get(file_path)

            if target_duration is None:
                logger.debug(f"🔧 Файл {Path(file_path).name}: используем оригинальную длительность (нет в расчетах)")
                return None

            # ЗАЩИТА: минимальная длительность
            if target_duration < 0.5:
                logger.warning(
                    f"⚠️ Целевая длительность слишком мала ({target_duration:.3f}с) для {Path(file_path).name}, используем оригинальную")
                return None

            logger.info(f"✂️ Файл {Path(file_path).name}: целевая длительность {target_duration:.2f}с")
            return target_duration

        # Инициализируем переменную для отслеживания длительности видео с аудио
        total_video_with_audio_duration = 0.0

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Объединяем логику, чтобы всегда использовать попапочное распределение
        # если adjust_videos_to_audio включен
        if adjust_videos_to_audio:
            if not folder_to_files:  # Если по какой-то причине folder_to_files все еще пуст
                logger.error(
                    "❌ КРИТИЧЕСКАЯ ОШИБКА: folder_to_files пуст, невозможно распределить файлы по папкам. Проверьте Excel и пути к файлам.")
                raise VideoProcessingError("Не удалось сопоставить файлы с папками из Excel.")

            # Обрабатываем файлы по папкам с новой логикой заполнения
            logger.info("🎬 Обработка файлов с заполнением времени")

            clip_index = 0

            # Итерируем по отсортированным папкам
            # sorted_folders уже содержит папки в правильном порядке ('1-5', '6-10' и т.д.)
            def folder_sort_key(folder_name):
                """Сортировка папок по диапазонам"""
                if '-' in folder_name:
                    start_num = int(folder_name.split('-')[0])
                    return start_num
                else:
                    try:
                        return int(folder_name)
                    except:
                        return 999  # Неопознанные папки в конец

            sorted_folder_names = sorted(folder_to_files.keys(), key=folder_sort_key)
            logger.info(f"📊 Порядок обработки папок: {sorted_folder_names}")

            for folder_name in sorted_folder_names:
                # Проверяем, что папка есть в рассчитанных длительностях
                if folder_name not in folder_durations:
                    logger.warning(f"⚠️ Папка '{folder_name}' отсутствует в рассчитанных длительностях. Пропускаем.")
                    continue

                folder_target_duration = folder_durations[folder_name]
                files_in_this_folder = folder_to_files.get(folder_name, [])  # Используем files из folder_to_files

                if not files_in_this_folder:
                    logger.warning(f"⚠️ Папка '{folder_name}' пуста (нет файлов для обработки).")
                    continue

                # ОТЛАДКА: Сортируем файлы ВНУТРИ папки для консистентности
                if photo_order == "random":
                    random.shuffle(files_in_this_folder)
                else:
                    files_in_this_folder.sort(key=lambda x: natural_sort_key(Path(x).stem))

                # Получаем последовательность воспроизведения для этой папки.
                # Analyzer.calculate_media_sequence_for_folder распределит время.
                media_sequence = analyzer.calculate_media_sequence_for_folder(
                    files_in_this_folder,
                    folder_target_duration,
                    folder_name,
                    transitions_enabled=effects_config.transitions_enabled if effects_config else False,
                    transition_duration=effects_config.transition_duration if effects_config else 0.5
                )

                # Обрабатываем каждый элемент последовательности
                for seq_item in media_sequence:
                    file_path = seq_item['file']
                    target_duration = seq_item['duration']
                    seq_type = seq_item['type']

                    ext = Path(file_path).suffix.lower()
                    output_path = Path(temp_folder) / f"processed_{clip_index}_{Path(file_path).stem}.mp4"

                    logger.info(f"   📄 {Path(file_path).name}: {target_duration:.2f}с ({seq_type})")

                    has_audio = False
                    if ext in ('.mp4', '.mov'):
                        # Проверяем наличие аудио в видеофайле
                        has_audio = preserve_clip_audio and validator.has_audio_stream(file_path)

                        # Обработка видео
                        success = video_processor.reencode_video(
                            file_path, str(output_path),
                            preserve_audio=has_audio,
                            target_duration=target_duration,
                            clip_index=clip_index
                        )

                        # Накапливаем длительность видео с аудио
                        if has_audio:
                            total_video_with_audio_duration += target_duration
                    else:
                        # Обработка фото
                        success = video_processor.create_video_from_image(
                            file_path, str(output_path),
                            target_duration, clip_index
                        )

                    if success:
                        processed_files.append(str(output_path))
                        # Дополнительная защита от tuple
                        safe_output_path = str(output_path) if not isinstance(output_path, tuple) else str(
                            output_path[0]) if output_path else ""
                        actual_duration_after_processing = validator.get_media_duration(str(output_path))
                        clips_info.append({
                            "path": safe_output_path,
                            "duration": actual_duration_after_processing,
                            "has_audio": has_audio,
                            "original_file": str(file_path),
                            "folder": str(folder_name),  # Добавляем имя папки
                            "type": str(seq_type)
                        })

                        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем file_durations_map для ConcatenationHelper
                        # Используем output_path как ключ, потому что ConcatenationHelper ищет по обработанному пути
                        file_durations_map[str(output_path)] = target_duration

                        logger.info(
                            f"   ✅ Обработан {Path(file_path).name} -> {Path(output_path).name}, фактическая длительность: {actual_duration_after_processing:.2f}с (целевая: {target_duration:.2f}с)")

                        # Копирование в folder_video_dir (для организации)
                        folder_video_dir = Path(temp_folder) / f"folder_{folder_name}"
                        folder_video_dir.mkdir(exist_ok=True)
                        try:
                            import shutil
                            shutil.copy2(str(output_path), str(folder_video_dir / Path(output_path).name))
                            logger.info(f"📁 Скопирован в папку '{folder_name}': {Path(output_path).name}")
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось скопировать в папку {folder_name}: {e}")

                    else:
                        logger.warning(f"Не удалось обработать файл: {Path(file_path).name}. Пропускаем.")
                        skipped_files.append(file_path)
                    clip_index += 1

        else:
            # Если adjust_videos_to_audio = False, то мы просто обрабатываем файлы
            # без привязки к folder_durations.
            logger.info(
                "📺 Обработка всех медиафайлов без подстройки под длительность аудио (adjust_videos_to_audio = False).")
            clip_index = 0
            total_video_with_audio_duration = 0.0

            # Здесь мы просто обрабатываем все файлы, которые были найдены
            for original_file_path in tqdm(all_sorted_files, desc="🎬 Обработка всех медиафайлов"):
                # target_duration здесь должна быть либо оригинальной длительностью, либо фиксированной,
                # так как нет Excel-логики для распределения.
                target_duration = validator.get_media_duration(original_file_path) or 3.0  # Fallback

                ext = Path(original_file_path).suffix.lower()
                output_file_name = f"processed_{clip_index}_{Path(original_file_path).stem}.mp4"
                output_path = Path(temp_folder) / output_file_name

                has_audio = False
                success = False

                if ext in ('.mp4', '.mov'):
                    has_audio = preserve_clip_audio and validator.has_audio_stream(original_file_path)
                    success = video_processor.reencode_video(
                        str(original_file_path), str(output_path),
                        preserve_audio=has_audio,
                        target_duration=target_duration,
                        clip_index=clip_index
                    )
                    if has_audio:
                        total_video_with_audio_duration += target_duration
                elif ext in SUPPORTED_FORMATS:  # Включая изображения
                    success = video_processor.create_video_from_image(
                        str(original_file_path), str(output_path),
                        target_duration, clip_index
                    )
                else:
                    logger.warning(f"Неподдерживаемый формат файла: {Path(original_file_path).name}. Пропускаем.")
                    skipped_files.append(original_file_path)
                    continue

                if success:
                    actual_duration_after_processing = validator.get_media_duration(str(output_path))
                    processed_files.append(str(output_path))
                    clips_info.append({
                        "path": str(output_path),
                        "duration": actual_duration_after_processing,
                        "has_audio": has_audio,
                        "original_file": str(original_file_path),
                        "type": "full"
                    })
                    # Заполняем file_durations_map здесь для этого режима
                    file_durations_map[str(original_file_path)] = target_duration
                else:
                    logger.warning(f"Не удалось обработать файл: {Path(original_file_path).name}. Пропускаем.")
                    skipped_files.append(original_file_path)

                clip_index += 1

        # Финальная статистика (вне if/else)
        total_processed_duration = sum(clip["duration"] for clip in clips_info)
        logger.info(f"Обработано файлов: {len(processed_files)}")
        logger.info(f"Пропущено файлов: {len(skipped_files)}")
        logger.info(f"Общая длительность обработанных файлов: {total_processed_duration:.2f} сек")

        if not processed_files:
            raise VideoProcessingError("Не удалось обработать ни одного фото/видео")

        # Возвращаем все необходимые результаты
        audio_offset = sum(clip["duration"] for clip in clips_info if clip.get("has_audio", False))
        logger.info(f"🎵 Audio offset для синхронизации: {audio_offset:.3f}с")
        return processed_files, skipped_files, clips_info, audio_offset, file_durations_map

    except Exception as e:
        logger.error(f"Критическая ошибка в process_photos_and_videos: {e}")
        # Возвращаем пустые значения вместо исключения для graceful degradation
        return [], [], [], 0.0, {}