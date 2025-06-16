import os
import random
import subprocess
import json
import logging
import shutil
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from PIL import Image, ImageFile
import cv2
from tqdm import tqdm
import pandas as pd

from utils import filter_hidden_files, natural_sort_key, find_files

# Настройка PIL для обработки поврежденных изображений
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Настройка логгера для модуля
logger = logging.getLogger(__name__)


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
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            version_line = result.stdout.splitlines()[0]
            logger.info(f"FFmpeg доступен: {version_line}")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"FFmpeg недоступен: {e}")
            return False

    @staticmethod
    def get_media_duration(file_path: str) -> float:
        """Получение длительности медиафайла"""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", file_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(result.stdout)
            duration = float(data["format"]["duration"])

            if duration <= 0:
                raise VideoProcessingError(f"Некорректная длительность: {duration}")

            logger.debug(f"Длительность {Path(file_path).name}: {duration:.2f} сек")
            return duration

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
            raise VideoProcessingError(f"Ошибка получения длительности {file_path}: {e}")
        except subprocess.TimeoutExpired:
            raise VideoProcessingError(f"Таймаут при получении длительности {file_path}")

    @staticmethod
    def has_audio_stream(file_path: str) -> bool:
        """Проверка наличия аудиодорожки"""
        if not Path(file_path).exists():
            return False

        try:
            cmd = ["ffprobe", "-v", "error", "-show_streams", "-select_streams", "a", "-of", "json", file_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(result.stdout)
            has_audio = len(data.get("streams", [])) > 0

            logger.debug(f"Аудиодорожка в {Path(file_path).name}: {'есть' if has_audio else 'нет'}")
            return has_audio

        except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Ошибка проверки аудиодорожки {file_path}: {e}")
            return False

    @staticmethod
    def check_video_params(file_path: str, config: VideoConfig) -> Tuple[bool, List[str]]:
        """Проверка параметров видео"""
        if not Path(file_path).exists():
            return False, ["file not found"]

        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,pixel_format",
                "-of", "json", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(result.stdout)

            stream = data.get("streams", [{}])[0]
            codec = stream.get("codec_name", "")
            width = stream.get("width", 0)
            height = stream.get("height", 0)
            pix_fmt = stream.get("pixel_format", "")

            # Парсинг frame rate
            fps_fraction = stream.get("r_frame_rate", "0/1")
            try:
                num, den = map(int, fps_fraction.split("/"))
                fps = num / den if den != 0 else 0
            except (ValueError, ZeroDivisionError):
                fps = 0

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
        subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError, subprocess.TimeoutExpired) as e:
            logger.error(f"Ошибка проверки параметров {file_path}: {e}")
            return False, [f"error={str(e)}"]


class VideoProcessor:
    """Основной класс для обработки видео"""

    def __init__(self, config: VideoConfig):
        self.config = config
        self.validator = FFmpegValidator()

        if not self.validator.check_availability():
            raise FFmpegError("FFmpeg недоступен")

    def reencode_video(self, input_path: str, output_path: str, preserve_audio: bool = False,
                       target_duration: Optional[float] = None) -> bool:
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

        # Формируем команду FFmpeg
        cmd = [
            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
            "-vf", self._get_video_filter(),
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

    def _get_video_filter(self) -> str:
        """Получение фильтра для видео"""
        return (
            f"fps={self.config.frame_rate},"
            f"format={self.config.pixel_format},"
            f"scale={self.config.resolution}:force_original_aspect_ratio=decrease,"
            f"pad={self.config.resolution}:(ow-iw)/2:(oh-ih)/2"
        )

    def extract_first_frame(self, video_path: str, output_path: str) -> bool:
        """Извлечение первого кадра из видео"""
        if not Path(video_path).exists():
            logger.error(f"Видеофайл не найден: {video_path}")
            return False

        cmd = [
            "ffmpeg", "-i", video_path, "-vf", "select=eq(n\\,0)", "-vframes", "1",
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

    def create_video_from_image(self, image_path: str, output_path: str, duration: float) -> bool:
        """Создание видео из изображения"""
        if not Path(image_path).exists():
            logger.error(f"Изображение не найдено: {image_path}")
            return False

        if duration <= 0:
            logger.error(f"Некорректная длительность: {duration}")
            return False

        # Создаем директорию для выходного файла
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-loop", "1", "-i", image_path,
            "-vf", self._get_video_filter(),
            "-c:v", self.config.codec, "-preset", self.config.preset, "-crf", str(self.config.crf),
            "-an", "-t", str(duration), "-r", str(self.config.frame_rate),
            "-map", "0:v:0", "-map", "-0:s", "-map", "-0:d",
            "-fflags", "+genpts+discardcorrupt", "-y", output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=120
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

    def __init__(self, bokeh_config: BokehConfig):
        self.bokeh_config = bokeh_config

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

            if self.bokeh_config.enabled:
                processed_image = self._apply_bokeh_effect(image_path)
                if processed_image is None:
                    return False
            else:
                # Простое копирование без обработки
                shutil.copy2(image_path, output_path)
                logger.debug(f"Изображение скопировано: {Path(image_path).name}")
                return True

            # Сохраняем обработанное изображение
            success = self._save_image(processed_image, output_path)
            if success:
                logger.debug(f"Изображение обработано: {Path(image_path).name}")

            return success

        except Exception as e:
            logger.error(f"Ошибка обработки изображения {image_path}: {e}")
            return False

    def _apply_bokeh_effect(self, image_path: str) -> Optional[Image.Image]:
        """Применение эффекта боке"""
        try:
            img = Image.open(image_path)

            # Вычисляем размеры для сохранения пропорций
            img_aspect = img.width / img.height
            target_width, target_height = self.bokeh_config.image_size

            new_width = int(target_height * img_aspect)
            new_height = target_height

            # Изменяем размер изображения
            img_resized = img.resize((new_width, new_height), Image.LANCZOS)

            # Если изображение уже нужного размера, возвращаем его
            if new_width >= target_width:
                return img_resized

            # Создаем размытый фон
            blurred_background = self._create_blurred_background(img, target_width, target_height)

            # Накладываем исходное изображение на размытый фон
            x_offset = (target_width - new_width) // 2
            blurred_background.paste(img_resized, (x_offset, 0))

            return blurred_background

        except Exception as e:
            logger.error(f"Ошибка применения эффекта боке: {e}")
            return None

    def _create_blurred_background(self, img: Image.Image, target_width: int, target_height: int) -> Image.Image:
        """Создание размытого фона"""
        # Изменяем размер изображения для фона
        img_resized = img.resize((target_width, target_height), Image.LANCZOS)

        # Конвертируем в numpy array для обработки OpenCV
        img_np = np.array(img_resized)

        # Применяем размытие Гаусса
        blurred = cv2.GaussianBlur(
            img_np,
            self.bokeh_config.blur_kernel,
            self.bokeh_config.blur_sigma
        )

        # Конвертируем обратно в PIL Image
        return Image.fromarray(blurred)

    def _save_image(self, image: Image.Image, output_path: str) -> bool:
        """Сохранение изображения"""
        try:
            output_path = Path(output_path)
            ext = output_path.suffix.lower()

            # Конвертируем RGBA в RGB для JPEG
            if image.mode == "RGBA" and ext in ['.jpg', '.jpeg']:
                image = image.convert("RGB")
                logger.debug("Конвертировано из RGBA в RGB для JPEG")

            # Сохраняем в соответствующем формате
            if ext == '.png':
                image.save(output_path, format="PNG", optimize=True)
            else:
                image.save(output_path, format="JPEG", quality=95, optimize=True)

            return True

        except Exception as e:
            logger.error(f"Ошибка сохранения изображения: {e}")
            return False


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
                folder_durations[folder] = 0.0
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


def resize_and_blur(img: Image.Image, image_size: Tuple[int, int],
                    bokeh_blur_kernel: Tuple[int, int], bokeh_blur_sigma: float) -> Image.Image:
    """Обратная совместимость: изменение размера и размытие"""
    try:
        # Изменяем размер
        img_resized = img.resize(image_size, Image.LANCZOS)

        # Применяем размытие
        img_np = np.array(img_resized)
        blurred = cv2.GaussianBlur(img_np, bokeh_blur_kernel, bokeh_blur_sigma)
        return Image.fromarray(blurred)
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        return img


def process_image_fixed_height(img_path: str, desired_size: Tuple[int, int],
                               bokeh_blur_kernel: Tuple[int, int], bokeh_blur_sigma: float) -> Optional[Image.Image]:
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
                      frame_rate: Optional[int] = None):
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
        image_files = find_files(photo_folder_vid, ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov'), recursive=True)

        # Инициализируем процессоры
        image_processor = ImageProcessor(bokeh_config)
        video_processor = VideoProcessor(video_config)
        validator = FFmpegValidator()

        # Счетчик для progress bar
        image_files_only = [f for f in image_files if Path(f).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')]

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
                        success = image_processor.process_image(str(image_path), str(output_path))
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
                              preserve_video_duration: bool = True) -> Tuple[
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

        video_processor = VideoProcessor(video_config)
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
                    success = video_processor.reencode_video(clip, str(output_path), preserve_audio=True)
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
                    success = video_processor.reencode_video(clip, str(output_path), preserve_audio=False)
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
                except Exception as e:
                    logger.warning(f"Не удалось получить длительность {output_path}: {e}")
                    skipped_files.append(clip)

            except Exception as e:
                logger.error(f"Ошибка обработки видео без аудио {clip}: {e}")
                skipped_files.append(clip)

        # Обработка фото
        total_video_duration = total_video_with_audio_duration + total_video_without_audio_duration
        remaining_duration = max(0, temp_audio_duration - total_video_duration)

        if photo_files_only and remaining_duration > 0:
            duration_per_photo = remaining_duration / len(photo_files_only)
            duration_per_photo = max(duration_per_photo, 1.0)  # Минимум 1 секунда

            for idx, photo_path in enumerate(tqdm(photo_files_only, desc="📷 Обработка фото")):
                try:
                    output_path = Path(temp_folder) / f"processed_photo_{idx}_{Path(photo_path).stem}.mp4"

                    success = video_processor.create_video_from_image(photo_path, str(output_path), duration_per_photo)
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