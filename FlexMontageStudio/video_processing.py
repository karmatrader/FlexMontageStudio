import os
import random
import subprocess
import json
import logging
import shutil
import math
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import cv2
from tqdm import tqdm
import pandas as pd

from utils import filter_hidden_files, natural_sort_key, find_files
from ffmpeg_utils import get_ffmpeg_path as ffmpeg_utils_get_ffmpeg_path, \
    get_ffprobe_path as ffmpeg_utils_get_ffprobe_path, _test_ffmpeg_working, get_media_duration
from image_processing_cv import ImageProcessorCV, SUPPORTED_FORMATS

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
    resolution: str = "1920:1080"
    frame_rate: int = 30
    crf: int = 23
    preset: str = "fast"
    codec: str = "libx264"
    pixel_format: str = "yuv420p"

    @property
    def width(self) -> int:
        return int(self.resolution.split(':')[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split(':')[1])

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
    def check_availability() -> bool:
        """Проверка доступности FFmpeg"""
        ffmpeg_path = get_ffmpeg_path()
        logger.info(f"🔍 Проверка FFmpeg по пути: {ffmpeg_path}")

        # Используем улучшенную функцию проверки из ffmpeg_utils
        if _test_ffmpeg_working(ffmpeg_path):
            logger.info(f"✅ FFmpeg доступен по пути: {ffmpeg_path}")
            return True
        else:
            logger.error(f"❌ FFmpeg недоступен по пути: {ffmpeg_path}")
            return False

    @staticmethod
    def get_media_duration(file_path: str) -> float:
        """Получение длительности медиафайла"""
        return get_media_duration(file_path)

    @staticmethod
    def has_audio_stream(file_path: str) -> bool:
        """Проверка наличия аудиодорожки"""
        if not Path(file_path).exists():
            return False

        try:
            # Используем FFmpeg вместо ffprobe для совместимости с imageio_ffmpeg
            cmd = [ffmpeg_utils_get_ffmpeg_path(), "-i", file_path, "-f", "null", "-"]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=120)  # Увеличиваем таймаут для больших файлов

            # Ищем информацию об аудиопотоках в stderr
            stderr = result.stderr
            has_audio = 'Stream #' in stderr and 'Audio:' in stderr

            logger.debug(f"Аудиодорожка в {Path(file_path).name}: {'есть' if has_audio else 'нет'}")
            return has_audio

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Ошибка проверки аудиодорожки {file_path}: {e}")
            return False

    @staticmethod
    def check_video_params(file_path: str, config: VideoConfig) -> Tuple[bool, List[str]]:
        """Проверка параметров видео"""
        if not Path(file_path).exists():
            return False, ["file not found"]

        try:
            # Используем FFmpeg вместо ffprobe для совместимости с imageio_ffmpeg
            cmd = [ffmpeg_utils_get_ffmpeg_path(), "-i", file_path, "-f", "null", "-"]
            result = subprocess.run(cmd, capture_output=True, text=True,
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
    transition_type: str = "fade"  # fade, dissolve, wipeleft, wiperight, etc.
    transition_duration: float = 0.5
    auto_zoom_alternation: bool = True


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
        """ПЛАВНЫЙ ZOOM без дрожания на основе zoom+step"""
        if self.config.zoom_effect == "none":
            return ""

        # Определяем тип зума
        zoom_type = self.config.zoom_effect
        if zoom_type == "auto" and self.config.auto_zoom_alternation:
            # Чередование zoom_in и zoom_out
            zoom_type = "zoom_in" if clip_index % 2 == 0 else "zoom_out"

        # Параметры для плавного зума
        zoom_intensity = max(1.01, min(self.config.zoom_intensity, 1.3))
        fps = 30  # Фиксированный FPS
        
        # Рассчитываем количество кадров для длительности
        total_frames = int(duration * fps)
        
        # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: используем маленький шаг для плавности
        zoom_range = zoom_intensity - 1.0
        # Маленький шаг для плавности, независимо от длительности
        zoom_step = min(0.001, zoom_range / 200)  # Ограничиваем максимальным шагом

        logger.info(
            f"🔍 SMOOTH ZOOM клип {clip_index}: длительность={duration:.2f}с, zoom_step={zoom_step:.6f}, max_zoom={zoom_intensity}")

        if zoom_type == "zoom_in":
            # Плавный Zoom In: используем zoom+step для плавности
            return f"scale=4000:-1,zoompan=z='min(zoom+{zoom_step:.6f},{zoom_intensity})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1920x1080:fps={fps}"
        elif zoom_type == "zoom_out":
            # Плавный Zoom Out: начинаем с большого зума и уменьшаем
            return f"scale=4000:-1,zoompan=z='if(lte(zoom,1.0),{zoom_intensity},max(1.001,zoom-{zoom_step:.6f}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1920x1080:fps={fps}"

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
        if not self.config.transitions_enabled:
            return ""

        transition_type = self.config.transition_type

        # Различные типы переходов xfade
        if transition_type in ["fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown",
                               "slideleft", "slideright", "slideup", "slidedown"]:
            return f"xfade=transition={transition_type}:duration={duration}"

        return ""


def create_video_effects_config(channel_config: Dict[str, Any]) -> VideoEffectsConfig:
    """
    Создание конфигурации эффектов из настроек канала

    Args:
        channel_config: Словарь с настройками канала

    Returns:
        VideoEffectsConfig: Конфигурация эффектов
    """
    return VideoEffectsConfig(
        effects_enabled=channel_config.get("video_effects_enabled", False),
        zoom_effect=channel_config.get("video_zoom_effect", "none"),
        zoom_intensity=float(channel_config.get("video_zoom_intensity", 1.1)),
        rotation_effect=channel_config.get("video_rotation_effect", "none"),
        rotation_angle=float(channel_config.get("video_rotation_angle", 5.0)),
        color_effect=channel_config.get("video_color_effect", "none"),
        filter_effect=channel_config.get("video_filter_effect", "none"),
        transitions_enabled=channel_config.get("video_transitions_enabled", False),
        transition_type=channel_config.get("transition_type", "fade"),
        transition_duration=float(channel_config.get("transition_duration", 0.5)),
        auto_zoom_alternation=channel_config.get("auto_zoom_alternation", True)
    )


class VideoProcessor:
    """Основной класс для обработки видео"""

    def __init__(self, config: VideoConfig, effects_config: VideoEffectsConfig = None):
        self.config = config
        self.effects_config = effects_config or VideoEffectsConfig()
        self.effects_processor = VideoEffectsProcessor(self.effects_config, self.config)
        self.validator = FFmpegValidator()

        if not self.validator.check_availability():
            raise FFmpegError("FFmpeg недоступен")

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
                input_duration = min(input_duration, target_duration)
        except Exception:
            input_duration = target_duration or 1.0

        # Формируем команду FFmpeg
        cmd = [
            get_ffmpeg_path(), "-reinit_filter", "0", "-i", input_path,
            "-vf", self._get_video_filter(clip_index, input_duration),
            "-c:v", self.config.codec, "-preset", self.config.preset, "-crf", str(self.config.crf),
            "-fps_mode", "vfr", "-fflags", "+genpts+discardcorrupt"
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
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 минут таймаут
            )

            logger.debug(f"FFmpeg output: {result.stderr}")

            # Проверяем, что файл создан и имеет правильную длительность
            if not Path(output_path).exists():
                logger.error(f"Выходной файл не создан: {output_path}")
                return False

            try:
                duration = self.validator.get_media_duration(output_path)
                if duration <= 0:
                    logger.error(f"Некорректная длительность выходного файла: {duration}")
                    return False
            except Exception as e:
                logger.error(f"Ошибка проверки длительности выходного файла: {e}")
                return False

            logger.info(f"Видео успешно перекодировано: {Path(output_path).name}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка перекодирования {input_path}: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"Таймаут при перекодировании {input_path}")
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
            base_filters.extend([
                f"fps={self.config.frame_rate}",
                f"format={self.config.pixel_format}",
                f"scale={self.config.resolution}:force_original_aspect_ratio=decrease",
                f"pad={self.config.resolution}:(ow-iw)/2:(oh-ih)/2"
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
            result = subprocess.run(
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

        if duration <= 0:
            logger.error(f"Некорректная длительность: {duration}")
            return False

        # Создаем директорию для выходного файла
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        video_filter = self._get_video_filter(clip_index, duration)
        logger.debug(f"Используемый видео фильтр: {video_filter}")

        # ОТЛАДКА: проверяем фильтр на наличие проблемных символов
        if "zoom2" in video_filter:
            logger.error(f"ОБНАРУЖЕНА ОШИБКА zoom2 в фильтре: {video_filter}")

        cmd = [
            get_ffmpeg_path(), "-loop", "1", "-i", image_path,
            "-vf", video_filter,
            "-c:v", self.config.codec, "-preset", self.config.preset, "-crf", str(self.config.crf),
            "-an", "-t", str(duration), "-r", str(self.config.frame_rate),
            "-map", "0:v:0", "-map", "-0:s", "-map", "-0:d",
            "-fflags", "+genpts+discardcorrupt", "-y", output_path
        ]

        # ОТЛАДКА: логируем полную команду
        logger.debug(f"FFmpeg команда: {' '.join(cmd)}")

        try:
            # ИСПРАВЛЕНИЕ: Увеличиваем timeout в зависимости от длительности
            timeout_seconds = max(120, int(duration * 10))  # Минимум 2 минуты, или 10 секунд на каждую секунду видео
            logger.debug(f"Создание видео из изображения с timeout={timeout_seconds}с для duration={duration:.1f}с")

            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )

            # Проверяем, что файл создан и имеет правильную длительность
            if not Path(output_path).exists():
                logger.error(f"Выходной файл не создан: {output_path}")
                return False

            try:
                actual_duration = self.validator.get_media_duration(output_path)
                if actual_duration <= 0:
                    logger.error(f"Некорректная длительность выходного файла: {actual_duration}")
                    return False
            except Exception as e:
                logger.error(f"Ошибка проверки длительности выходного файла: {e}")
                return False

            logger.debug(f"Видео создано из изображения: {Path(image_path).name} -> {Path(output_path).name}")
            return True

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Ошибка создания видео из изображения {image_path}: {e}")
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

    def get_folder_ranges_from_excel(self, video_number: str) -> Tuple[int, int, List[str]]:
        """
        Извлечение диапазонов строк и папок из Excel

        Args:
            video_number: Номер видео

        Returns:
            Tuple[int, int, List[str]]: Начальная строка, конечная строка, список папок
        """
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel файл не найден: {self.excel_path}")

        try:
            df = pd.read_excel(self.excel_path)
            folder_ranges = {}
            current_video = None
            start_row = None

            for idx, row in df.iterrows():
                cell_value = str(row.iloc[0]).strip()  # Столбец A
                row_num = idx + 1  # Номер строки (начинается с 1)

                # Проверяем метку видео
                if cell_value.startswith("ВИДЕО "):
                    video_label = cell_value.replace("ВИДЕО ", "")

                    # Сохраняем диапазон для предыдущего видео
                    if current_video is not None and start_row is not None:
                        folder_ranges[current_video] = {
                            "start": start_row,
                            "end": row_num - 1,
                            "folders": []
                        }

                    current_video = video_label
                    start_row = row_num

                elif current_video == video_number and cell_value:
                    # Добавляем папку для текущего видео
                    if current_video not in folder_ranges:
                        folder_ranges[current_video] = {
                            "start": start_row,
                            "end": row_num,
                            "folders": []
                        }
                    folder_ranges[current_video]["folders"].append(cell_value)

            # Добавляем последний диапазон
            if current_video is not None and start_row is not None:
                if current_video not in folder_ranges:
                    folder_ranges[current_video] = {"start": start_row, "end": len(df) + 1, "folders": []}
                else:
                    folder_ranges[current_video]["end"] = len(df) + 1

            if video_number not in folder_ranges:
                raise VideoProcessingError(f"Видео {video_number} не найдено в Excel файле")

            video_info = folder_ranges[video_number]
            start = video_info["start"]
            end = video_info["end"]
            folders = self._sort_folders(video_info["folders"])

            logger.info(f"Диапазон для видео {video_number}: строки {start}–{end}")
            logger.debug(f"Папки для видео {video_number}: {folders}")

            return start, end, folders

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

    def calculate_folder_durations(self, audio_folder: str, folders: List[str],
                                   start_row: int, end_row: int) -> Tuple[Dict[str, float], float]:
        """
        Расчет длительности для каждой папки на основе аудиофайлов

        Args:
            audio_folder: Папка с аудиофайлами
            folders: Список папок
            start_row: Начальная строка
            end_row: Конечная строка

        Returns:
            Tuple[Dict[str, float], float]: Длительности папок и общая длительность
        """
        audio_folder_path = Path(audio_folder)
        if not audio_folder_path.exists():
            raise FileNotFoundError(f"Папка с аудио не найдена: {audio_folder}")

        # Собираем длительности всех аудиофайлов
        audio_durations = {}
        total_duration = 0.0

        for line_num in range(start_row, end_row + 1):
            audio_filename = f"{str(line_num).zfill(3)}.mp3"
            audio_file = audio_folder_path / audio_filename

            if audio_file.exists():
                try:
                    duration = self.validator.get_media_duration(str(audio_file))
                    audio_durations[line_num] = duration
                    total_duration += duration
                except Exception as e:
                    logger.warning(f"Ошибка получения длительности {audio_file}: {e}")
                    audio_durations[line_num] = 0.0
            else:
                audio_durations[line_num] = 0.0
                logger.debug(f"Аудиофайл не найден: {audio_file}")

        # Рассчитываем длительность для каждой папки
        folder_durations = {}

        for folder in folders:
            if folder == "root":
                # В backup версии root папка имеет 0.0 длительность - это правильно!
                folder_durations[folder] = 0.0
                logger.debug(f"Длительность папки root: 0.0 сек")
                continue

            try:
                if '-' in folder:
                    folder_start, folder_end = map(int, folder.split('-'))
                else:
                    folder_start = folder_end = int(folder)

                # Абсолютные номера строк
                abs_start = start_row + folder_start - 1
                abs_end = start_row + folder_end - 1

                folder_duration = 0.0
                for line_num in range(abs_start, abs_end + 1):
                    folder_duration += audio_durations.get(line_num, 0.0)

                folder_durations[folder] = folder_duration
                logger.debug(f"Длительность папки {folder}: {folder_duration:.2f} сек")

            except (ValueError, IndexError) as e:
                logger.warning(f"Не удалось разобрать диапазон для папки {folder}: {e}")
                folder_durations[folder] = 0.0

        logger.info(f"Общая длительность аудио: {total_duration:.2f} сек")
        return folder_durations, total_duration


class ConcatenationHelper:
    """Вспомогательный класс для создания списков конкатенации"""

    @staticmethod
    def create_concat_list(files: List[str], output_path: str, shuffle: bool = False) -> str:
        """
        Создание файла списка для конкатенации

        Args:
            files: Список файлов
            output_path: Путь для сохранения списка
            shuffle: Перемешать файлы

        Returns:
            str: Путь к созданному файлу списка
        """
        if shuffle:
            files = files.copy()
            random.shuffle(files)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            for file_path in files:
                # Используем абсолютные пути для безопасности
                abs_path = Path(file_path).resolve()
                f.write(f"file '{abs_path}'\n")

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
    config = VideoConfig(
        resolution=target_resolution,
        frame_rate=target_fps,
        codec=f"lib{target_codec}" if not target_codec.startswith('lib') else target_codec,
        pixel_format=target_pix_fmt
    )
    return FFmpegValidator.check_video_params(input_path, config)


def reencode_video(input_path: str, output_path: str, video_resolution: str, frame_rate: int,
                   video_crf: int, video_preset: str, preserve_audio: bool = False,
                   target_duration: Optional[float] = None) -> bool:
    """Обратная совместимость: перекодирование видео"""
    try:
        config = VideoConfig(
            resolution=video_resolution,
            frame_rate=frame_rate,
            crf=video_crf,
            preset=video_preset
        )
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
                         temp_audio_duration: float) -> str:
    """Обратная совместимость: создание списка конкатенации (случайный порядок)"""
    concat_list_path = Path(temp_folder) / "concat_list.txt"
    return ConcatenationHelper.create_concat_list(processed_photo_files, str(concat_list_path), shuffle=True)


def concat_photos_in_order(processed_photo_files: List[str], temp_folder: str,
                           temp_audio_duration: float) -> str:
    """Обратная совместимость: создание списка конкатенации (по порядку)"""
    concat_list_path = Path(temp_folder) / "concat_list.txt"
    return ConcatenationHelper.create_concat_list(processed_photo_files, str(concat_list_path), shuffle=False)


def get_folder_ranges_from_excel(excel_path: str, video_number: str) -> Tuple[int, int, List[str]]:
    """Обратная совместимость: получение диапазонов из Excel"""
    try:
        analyzer = MediaAnalyzer(excel_path)
        return analyzer.get_folder_ranges_from_excel(video_number)
    except Exception as e:
        logger.error(f"Ошибка анализа Excel: {e}")
        return 0, 0, []


def get_folder_durations(audio_folder: str, sorted_folders: List[str],
                         overall_range_start: int, overall_range_end: int) -> Tuple[
    Dict[str, float], float, Dict[int, float]]:
    """Обратная совместимость: получение длительностей папок"""
    try:
        excel_path = "dummy.xlsx"  # Этот параметр не используется в новой реализации
        analyzer = MediaAnalyzer(excel_path)
        folder_durations, total_duration = analyzer.calculate_folder_durations(
            audio_folder, sorted_folders, overall_range_start, overall_range_end
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
                      frame_rate: Optional[int] = None, effects_config: dict = None):
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
            video_config.resolution = video_resolution
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
                              overall_range_end: int, excel_path: str, photo_order: str = "order",
                              adjust_videos_to_audio: bool = True, preserve_clip_audio: bool = False,
                              preserve_video_duration: bool = True, effects_config: VideoEffectsConfig = None) -> Tuple[
    List[str], List[str], List[Dict[str, Any]], float]:
    """
    Обратная совместимость: основная функция обработки фото и видео

    Эта функция сохраняет оригинальную сигнатуру, но использует новые классы внутри
    """
    try:
        logger.info("=== 🎬 Начало обработки фото и видео ===")

        if not photo_files:
            logger.warning("Нет файлов для обработки")
            return [], [], [], 0.0

        # Инициализация
        video_config = VideoConfig(
            resolution=video_resolution,
            frame_rate=frame_rate,
            crf=video_crf,
            preset=video_preset
        )

        # Используем переданную конфигурацию эффектов или создаем пустую
        if effects_config is None:
            effects_config = VideoEffectsConfig()

        video_processor = VideoProcessor(video_config, effects_config)
        validator = FFmpegValidator()
        analyzer = MediaAnalyzer(excel_path)

        # Результаты
        processed_files = []
        skipped_files = []
        clips_info = []

        # Группировка файлов по папкам
        folder_files = {}
        for file_path in photo_files:
            relative_path = Path(file_path).relative_to(Path(preprocessed_photo_folder))
            folder_name = str(relative_path.parent) if str(relative_path.parent) != "." else "root"

            if folder_name not in folder_files:
                folder_files[folder_name] = []
            folder_files[folder_name].append(file_path)

        # Сортировка папок
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

        sorted_folders = sorted(folder_files.keys(), key=folder_sort_key)
        logger.info(f"Найдено папок: {sorted_folders}")

        # Получение длительностей папок
        folder_durations, total_duration = analyzer.calculate_folder_durations(
            audio_folder, sorted_folders, overall_range_start, overall_range_end
        )

        # Увеличиваем timeout для final_assembly
        # Отладочная информация о folder_durations
        logger.info(f"📊 Рассчитанные folder_durations: {folder_durations}")
        logger.info(f"📊 Всего длительность из Excel: {total_duration}")
        logger.info(f"📊 Отсортированные папки: {sorted_folders}")
        logger.info(f"📊 Диапазон Excel: {overall_range_start}-{overall_range_end}")

        if not folder_durations:
            logger.warning("⚠️ folder_durations пустой! Будет использована равномерная распределение.")
        else:
            logger.info(f"✅ Найдено {len(folder_durations)} папок с длительностями")

        # Сортировка файлов внутри папок
        all_sorted_files = []
        for folder in sorted_folders:
            files_in_folder = folder_files[folder]
            if photo_order == "random":
                random.shuffle(files_in_folder)
            else:
                files_in_folder.sort(key=lambda x: natural_sort_key(Path(x).stem))
            all_sorted_files.extend(files_in_folder)

        # Классификация файлов
        video_clips_with_audio = []
        video_clips_without_audio = []
        photo_files_only = []

        for file_path in all_sorted_files:
            ext = Path(file_path).suffix.lower()
            if ext in ('.mp4', '.mov'):
                if preserve_clip_audio and validator.has_audio_stream(file_path):
                    video_clips_with_audio.append(file_path)
                else:
                    video_clips_without_audio.append(file_path)
            else:
                photo_files_only.append(file_path)

        logger.info(f"Видеоклипы с аудио: {len(video_clips_with_audio)}")
        logger.info(f"Видеоклипы без аудио: {len(video_clips_without_audio)}")
        logger.info(f"Фото: {len(photo_files_only)}")

        # Обработка видеоклипов с аудио
        total_video_with_audio_duration = 0.0
        for idx, clip in enumerate(tqdm(video_clips_with_audio, desc="🎬 Видео с аудио")):
            try:
                output_path = Path(temp_folder) / f"processed_video_audio_{idx}_{Path(clip).stem}.mp4"

                # Проверяем параметры видео - используем более мягкую проверку
                is_match, reasons = validator.check_video_params(clip, video_config)
                if is_match:
                    # Файл уже соответствует параметрам, просто копируем
                    shutil.copy2(clip, output_path)
                    logger.debug(f"Видео уже соответствует параметрам: {Path(clip).name}")
                else:
                    # Требуется перекодирование
                    logger.debug(f"Перекодирование: {Path(clip).name} -> {Path(output_path).name}")
                    success = video_processor.reencode_video(clip, str(output_path), preserve_audio=True,
                                                             clip_index=idx)
                    if not success:
                        logger.warning(f"Не удалось перекодировать видео: {Path(clip).name}")
                        skipped_files.append(clip)
                        continue

                # Получаем длительность обработанного файла
                try:
                    duration = validator.get_media_duration(str(output_path))
                    processed_files.append(str(output_path))
                    clips_info.append({"path": str(output_path), "duration": duration, "has_audio": True})
                    total_video_with_audio_duration += duration
                    logger.info(f"   📹 Видео с аудио {idx}: {Path(clip).name} -> длительность {duration:.2f}с")
                except Exception as e:
                    logger.warning(f"Не удалось получить длительность {output_path}: {e}")
                    skipped_files.append(clip)

            except Exception as e:
                logger.error(f"Ошибка обработки видео с аудио {clip}: {e}")
                skipped_files.append(clip)

        # Обработка видеоклипов без аудио
        total_video_without_audio_duration = 0.0
        for idx, clip in enumerate(tqdm(video_clips_without_audio, desc="🎬 Видео без аудио")):
            try:
                output_path = Path(temp_folder) / f"processed_video_{idx}_{Path(clip).stem}.mp4"

                # Проверяем параметры видео - используем более мягкую проверку
                is_match, reasons = validator.check_video_params(clip, video_config)
                if is_match:
                    # Файл уже соответствует параметрам, просто копируем
                    shutil.copy2(clip, output_path)
                    logger.debug(f"Видео уже соответствует параметрам: {Path(clip).name}")
                else:
                    # Требуется перекодирование
                    logger.debug(f"Перекодирование: {Path(clip).name} -> {Path(output_path).name}")
                    # Индекс для видео без аудио = количество видео с аудио + текущий индекс
                    video_clip_index = len(video_clips_with_audio) + idx
                    success = video_processor.reencode_video(clip, str(output_path), preserve_audio=False,
                                                             clip_index=video_clip_index)
                    if not success:
                        logger.warning(f"Не удалось перекодировать видео: {Path(clip).name}")
                        skipped_files.append(clip)
                        continue

                # Получаем длительность обработанного файла
                try:
                    duration = validator.get_media_duration(str(output_path))
                    processed_files.append(str(output_path))
                    clips_info.append({"path": str(output_path), "duration": duration, "has_audio": False})
                    total_video_without_audio_duration += duration
                    logger.info(f"   📹 Видео без аудио {idx}: {Path(clip).name} -> длительность {duration:.2f}с")
                except Exception as e:
                    logger.warning(f"Не удалось получить длительность {output_path}: {e}")
                    skipped_files.append(clip)

            except Exception as e:
                logger.error(f"Ошибка обработки видео без аудио {clip}: {e}")
                skipped_files.append(clip)

        # Обработка фото - восстанавливаем простую логику из backup
        total_video_duration = total_video_with_audio_duration + total_video_without_audio_duration
        remaining_duration = max(0, temp_audio_duration - total_video_duration)

        # ДИАГНОСТИКА: детальное логирование длительностей
        logger.info(f"🔍 ДИАГНОСТИКА ДЛИТЕЛЬНОСТЕЙ:")
        logger.info(f"   temp_audio_duration (общая длительность аудио): {temp_audio_duration:.2f}с")
        logger.info(f"   total_video_with_audio_duration: {total_video_with_audio_duration:.2f}с")
        logger.info(f"   total_video_without_audio_duration: {total_video_without_audio_duration:.2f}с")
        logger.info(f"   total_video_duration: {total_video_duration:.2f}с")
        logger.info(f"   remaining_duration для фото: {remaining_duration:.2f}с")
        logger.info(f"   количество фото для обработки: {len(photo_files_only)}")

        if photo_files_only and remaining_duration > 0:
            # ТОЧНО как в backup: простое деление на количество фото
            duration_per_photo = remaining_duration / len(photo_files_only)
            duration_per_photo = max(duration_per_photo, 1.0)  # Минимум 1 секунда

            for idx, photo_path in enumerate(tqdm(photo_files_only, desc="📷 Обработка фото")):
                try:
                    output_path = Path(temp_folder) / f"processed_photo_{idx}_{Path(photo_path).stem}.mp4"

                    # Индекс клипа для чередования эффектов
                    clip_index = len(video_clips_with_audio) + len(video_clips_without_audio) + idx

                    success = video_processor.create_video_from_image(photo_path, str(output_path), duration_per_photo,
                                                                      clip_index)
                    if success:
                        try:
                            duration = validator.get_media_duration(str(output_path))
                            processed_files.append(str(output_path))
                            clips_info.append({"path": str(output_path), "duration": duration, "has_audio": False})
                        except Exception as e:
                            logger.warning(f"Не удалось получить длительность {output_path}: {e}")
                            skipped_files.append(photo_path)
                    else:
                        skipped_files.append(photo_path)

                except Exception as e:
                    logger.error(f"Ошибка обработки фото {photo_path}: {e}")
                    skipped_files.append(photo_path)

        # Финальная статистика
        total_processed_duration = sum(clip["duration"] for clip in clips_info)
        logger.info(f"Обработано файлов: {len(processed_files)}")
        logger.info(f"Пропущено файлов: {len(skipped_files)}")
        logger.info(f"Общая длительность: {total_processed_duration:.2f} сек")

        # Проверяем, что хотя бы что-то обработано
        if not processed_files:
            raise VideoProcessingError("Не удалось обработать ни одного фото/видео")

        return processed_files, skipped_files, clips_info, total_video_with_audio_duration

    except Exception as e:
        logger.error(f"Критическая ошибка в process_photos_and_videos: {e}")
        raise VideoProcessingError(f"Ошибка обработки фото и видео: {e}")