import os
import subprocess
import json
import random
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Union
from dataclasses import dataclass

import pandas as pd
from tqdm import tqdm
from ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_media_duration, _test_ffmpeg_working

# Настройка логгера для модуля
logger = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    """Конфигурация для обработки аудио"""
    channels: int = 1
    sample_rate: int = 44100
    bitrate: str = "192k"
    silence_duration: Union[str, float] = "1.0-2.5"
    background_music_volume: float = 0.2


class AudioProcessingError(Exception):
    """Исключение для ошибок обработки аудио"""
    pass


class ExcelReaderError(Exception):
    """Исключение для ошибок чтения Excel"""
    pass


class FFmpegError(Exception):
    """Исключение для ошибок FFmpeg"""
    pass


class ExcelAudioReader:
    """Класс для чтения аудиоданных из Excel файлов"""

    def __init__(self, xlsx_file_path: str):
        self.xlsx_file_path = Path(xlsx_file_path)
        if not self.xlsx_file_path.exists():
            raise ExcelReaderError(f"Excel файл не найден: {xlsx_file_path}")

    def get_audio_files_for_video(self, output_directory: str, video_number: str,
                                  language: str = "ru", channel_column: str = "B") -> Tuple[
        List[str], Optional[int], Optional[int]]:
        """
        Читает Excel-файл и возвращает список аудиофайлов для заданного номера видео и диапазон строк

        Args:
            output_directory: Папка с аудиофайлами
            video_number: Номер видео
            language: Язык листа Excel
            channel_column: Столбец канала (B, C, D и т.д.)

        Returns:
            Tuple[List[str], Optional[int], Optional[int]]: Список файлов, начальная строка, конечная строка
        """
        try:
            # Валидация столбца
            column_index = self._validate_column(channel_column)

            # Чтение Excel файла
            df = self._read_excel_sheet(language, column_index)

            # Поиск видео маркеров
            start_row, end_row = self._find_video_range(df, video_number)

            # Поиск аудиофайлов
            audio_files = self._find_audio_files(output_directory, start_row, end_row)

            logger.info(
                f"Найдено {len(audio_files)} аудиофайлов для видео {video_number} (строки {start_row}-{end_row})")
            return audio_files, start_row, end_row

        except Exception as e:
            logger.error(f"Ошибка получения аудиофайлов для видео {video_number}: {e}")
            return [], None, None

    def _validate_column(self, channel_column: str) -> int:
        """Валидация и конвертация столбца"""
        channel_column = channel_column.upper().strip()
        if not channel_column.isalpha() or len(channel_column) != 1:
            raise ExcelReaderError(
                f"Некорректное обозначение столбца: {channel_column}. Ожидается одна буква (B, C, D)")

        # Конвертируем букву в индекс (A=0, B=1, C=2)
        column_index = ord(channel_column) - ord('A')
        if column_index < 0:
            raise ExcelReaderError(f"Столбец {channel_column} недопустим")

        return column_index

    def _read_excel_sheet(self, language: str, column_index: int) -> pd.DataFrame:
        """Чтение листа Excel"""
        try:
            # Читаем столбец A (индекс 0) для меток и нужный столбец для текста
            df = pd.read_excel(
                self.xlsx_file_path,
                sheet_name=language.upper(),
                header=None,
                usecols=[0, column_index]
            )
            logger.debug(f"Прочитан Excel лист '{language.upper()}', строк: {len(df)}")
            return df

        except FileNotFoundError:
            raise ExcelReaderError(f"Excel файл не найден: {self.xlsx_file_path}")
        except ValueError as e:
            if "Worksheet" in str(e):
                raise ExcelReaderError(f"Лист '{language.upper()}' не найден в Excel файле")
            else:
                raise ExcelReaderError(f"Ошибка чтения Excel: {e}")
        except Exception as e:
            raise ExcelReaderError(f"Неожиданная ошибка при чтении Excel: {e}")

    def _find_video_range(self, df: pd.DataFrame, video_number: str) -> Tuple[int, int]:
        """Поиск диапазона строк для видео"""
        video_markers = []
        target_marker = f"ВИДЕО {video_number}"

        # Ищем все видео маркеры
        for idx, row in df.iterrows():
            marker = str(row[0]).strip() if pd.notna(row[0]) else ""
            if marker.startswith("ВИДЕО"):
                video_markers.append((idx + 1, marker))  # +1 для Excel нумерации

        if not video_markers:
            raise ExcelReaderError("Не найдено ни одного видео маркера в столбце A")

        # Ищем нужный маркер
        start_row = None
        end_row = None

        for i, (row_idx, marker) in enumerate(video_markers):
            if marker == target_marker:
                start_row = row_idx + 1  # Начинаем со следующей строки после метки
                # Конец - до следующего маркера или до конца файла
                end_row = video_markers[i + 1][0] if i + 1 < len(video_markers) else len(df) + 1
                break

        if start_row is None:
            available_videos = [marker for _, marker in video_markers]
            raise ExcelReaderError(f"Маркер '{target_marker}' не найден. Доступные видео: {available_videos}")

        logger.debug(f"Найден диапазон для {target_marker}: строки {start_row}–{end_row - 1}")
        return start_row, end_row

    def _find_audio_files(self, output_directory: str, start_row: int, end_row: int) -> List[str]:
        """Поиск аудиофайлов в заданном диапазоне"""
        output_dir = Path(output_directory)
        if not output_dir.exists():
            raise ExcelReaderError(f"Папка с аудио не найдена: {output_directory}")

        available_files = list(output_dir.iterdir())
        logger.debug(f"В папке {output_directory} найдено файлов: {len(available_files)}")

        audio_files = []
        missing_files = []

        for row_idx in range(start_row, end_row):
            # Форматируем номер файла (001, 002, или просто числа для больших)
            file_number = str(row_idx).zfill(3) if row_idx < 1000 else str(row_idx)
            audio_filename = f"{file_number}.mp3"
            audio_path = output_dir / audio_filename

            if audio_path.exists():
                audio_files.append(audio_filename)
                logger.debug(f"Найден аудиофайл: {audio_filename}")
            else:
                missing_files.append(audio_filename)
                logger.debug(f"Аудиофайл не найден: {audio_filename}")

        if missing_files:
            logger.warning(f"Не найдено аудиофайлов: {len(missing_files)} из {end_row - start_row}")
            logger.debug(f"Отсутствующие файлы: {missing_files[:5]}{'...' if len(missing_files) > 5 else ''}")

        if not audio_files:
            raise ExcelReaderError(f"Не найдено ни одного аудиофайла в диапазоне строк {start_row}-{end_row}")

        return audio_files


class AudioProcessor:
    """Класс для обработки аудиофайлов"""

    def __init__(self, config: AudioConfig):
        self.config = config
        self._validate_ffmpeg()

    def _validate_ffmpeg(self):
        """Проверка наличия FFmpeg"""
        ffmpeg_path = get_ffmpeg_path()
        logger.info(f"🔍 Проверка FFmpeg по пути: {ffmpeg_path}")
        
        # Используем улучшенную функцию проверки из ffmpeg_utils
        if not _test_ffmpeg_working(ffmpeg_path):
            logger.error(f"❌ FFmpeg недоступен по пути: {ffmpeg_path}")
            raise FFmpegError("FFmpeg недоступен")
        
        logger.info(f"✅ FFmpeg доступен по пути: {ffmpeg_path}")

    def process_audio_files(self, audio_files: List[str], temp_audio_folder: str,
                            temp_folder: str) -> Tuple[Optional[str], Optional[float]]:
        """
        Обрабатывает и склеивает аудиофайлы с добавлением тишины

        Args:
            audio_files: Список имен аудиофайлов
            temp_audio_folder: Папка с исходными аудиофайлами
            temp_folder: Временная папка для обработки

        Returns:
            Tuple[Optional[str], Optional[float]]: Путь к финальному аудио и его длительность
        """
        try:
            logger.info(f"Начинаем обработку {len(audio_files)} аудиофайлов")

            # Парсим настройки тишины
            min_silence, max_silence = self._parse_silence_duration()

            # Обрабатываем каждый аудиофайл
            processed_files, total_duration = self._process_individual_files(
                audio_files, temp_audio_folder, temp_folder, min_silence, max_silence
            )

            if not processed_files:
                raise AudioProcessingError("Не удалось обработать ни одного аудиофайла")

            # Склеиваем все файлы
            final_audio_path = self._concatenate_audio_files(processed_files, temp_folder)

            # Проверяем финальную длительность
            final_duration = self._get_audio_duration(final_audio_path)

            logger.info(
                f"Обработка аудио завершена: {len(processed_files)} файлов, длительность: {final_duration:.2f} сек")
            return final_audio_path, final_duration

        except Exception as e:
            logger.error(f"Ошибка обработки аудиофайлов: {e}")
            return None, None

    def _parse_silence_duration(self) -> Tuple[float, float]:
        """Парсинг настроек длительности тишины"""
        silence = self.config.silence_duration

        if isinstance(silence, str) and '-' in silence:
            try:
                min_dur, max_dur = map(float, silence.split('-'))
                if min_dur < 0 or max_dur < 0 or min_dur > max_dur:
                    logger.warning(f"Некорректный диапазон тишины: {silence}, используется 0")
                    return 0.0, 0.0
                return min_dur, max_dur
            except ValueError:
                logger.warning(f"Некорректный формат тишины: {silence}, используется 0")
                return 0.0, 0.0

        elif isinstance(silence, (int, float)):
            if silence < 0:
                logger.warning("Отрицательная длительность тишины, используется 0")
                return 0.0, 0.0
            return float(silence), float(silence)

        else:
            logger.warning(f"Некорректный тип silence_duration: {type(silence)}, используется 0")
            return 0.0, 0.0

    def _process_individual_files(self, audio_files: List[str], temp_audio_folder: str,
                                  temp_folder: str, min_silence: float, max_silence: float) -> Tuple[List[str], float]:
        """Обработка отдельных аудиофайлов"""
        processed_files = []
        total_duration = 0.0

        temp_audio_path = Path(temp_audio_folder)
        temp_path = Path(temp_folder)

        for idx, audio_file in enumerate(tqdm(audio_files, desc="🎵 Обработка аудио")):
            try:
                input_path = temp_audio_path / audio_file
                output_path = temp_path / f"processed_{Path(audio_file).stem}.wav"

                # Конвертируем в WAV с нужными параметрами
                self._convert_to_wav(str(input_path), str(output_path))

                # Получаем длительность
                duration = self._get_audio_duration(str(output_path))
                total_duration += duration
                processed_files.append(str(output_path))

                logger.debug(f"Обработан {audio_file}: {duration:.2f} сек")

                # Добавляем тишину между файлами (кроме последнего)
                if max_silence > 0 and idx < len(audio_files) - 1:
                    silence_duration = random.uniform(min_silence, max_silence)
                    silence_path = temp_path / f"silence_{idx}.wav"

                    self._generate_silence(str(silence_path), silence_duration)
                    processed_files.append(str(silence_path))
                    total_duration += silence_duration

                    logger.debug(f"Добавлена тишина: {silence_duration:.2f} сек")

            except Exception as e:
                logger.error(f"Ошибка обработки {audio_file}: {e}")
                continue

        logger.info(f"Обработано файлов: {len([f for f in processed_files if 'processed_' in f])}/{len(audio_files)}")
        return processed_files, total_duration

    def _convert_to_wav(self, input_path: str, output_path: str):
        """Конвертация аудио в WAV"""
        cmd = [
            get_ffmpeg_path(), "-i", input_path,
            "-c:a", "pcm_s16le",
            "-ac", str(self.config.channels),
            "-ar", str(self.config.sample_rate),
            "-y", output_path
        ]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
            logger.debug(f"Конвертирован в WAV: {Path(input_path).name}")
        except subprocess.CalledProcessError as e:
            raise FFmpegError(f"Ошибка конвертации в WAV: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise FFmpegError(f"Таймаут при конвертации: {input_path}")

    def _generate_silence(self, output_path: str, duration: float):
        """Генерация тишины"""
        # Определяем layout каналов
        channel_layout = "mono" if self.config.channels == 1 else "stereo"

        cmd = [
            get_ffmpeg_path(), "-f", "lavfi",
            "-i", f"anullsrc=channel_layout={channel_layout}:sample_rate={self.config.sample_rate}",
            "-t", str(duration),
            "-c:a", "pcm_s16le",
            "-y", output_path
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.CalledProcessError as e:
            raise FFmpegError(f"Ошибка генерации тишины: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise FFmpegError("Таймаут при генерации тишины")

    def _get_audio_duration(self, audio_path: str) -> float:
        """Получение длительности аудиофайла"""
        return get_media_duration(audio_path)

    def _concatenate_audio_files(self, processed_files: List[str], temp_folder: str) -> str:
        """Склеивание аудиофайлов"""
        temp_path = Path(temp_folder)
        concat_list_path = temp_path / "audio_concat_list.txt"
        temp_audio_path = temp_path / "temp_audio.wav"
        final_audio_path = temp_path / "final_audio.mp3"

        # Создаем список файлов для конкатенации
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for audio_file in processed_files:
                # Используем абсолютные пути для безопасности
                abs_path = Path(audio_file).resolve()
                f.write(f"file '{abs_path}'\n")

        try:
            # Склеиваем в WAV
            cmd_concat = [
                get_ffmpeg_path(), "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
                "-c:a", "pcm_s16le", "-y", str(temp_audio_path)
            ]
            subprocess.run(cmd_concat, check=True, capture_output=True, text=True, timeout=300)

            # Конвертируем в MP3
            duration = self._get_audio_duration(str(temp_audio_path))
            cmd_mp3 = [
                get_ffmpeg_path(), "-i", str(temp_audio_path),
                "-c:a", "mp3", "-b:a", self.config.bitrate,
                "-map", "0:a", "-t", str(duration),
                "-y", str(final_audio_path)
            ]
            subprocess.run(cmd_mp3, check=True, capture_output=True, text=True, timeout=300)

            logger.info(f"Аудио склеено и сконвертировано: {final_audio_path}")
            return str(final_audio_path)

        except subprocess.CalledProcessError as e:
            raise FFmpegError(f"Ошибка склеивания аудио: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise FFmpegError("Таймаут при склеивании аудио")


class BackgroundMusicProcessor:
    """Класс для добавления фоновой музыки"""

    def __init__(self, config: AudioConfig):
        self.config = config

    def add_background_music(self, final_audio_path: str, background_music_path: Optional[str],
                             temp_folder: str, target_duration: float) -> str:
        """
        Добавление фоновой музыки к аудио

        Args:
            final_audio_path: Путь к основному аудио
            background_music_path: Путь к фоновой музыке (может быть None)
            temp_folder: Временная папка
            target_duration: Целевая длительность

        Returns:
            str: Путь к финальному аудио с музыкой
        """
        if not background_music_path or not Path(background_music_path).exists():
            logger.warning(f"Фоновая музыка недоступна: {background_music_path}")
            return final_audio_path

        try:
            logger.info("=== 🎵 Добавление фоновой музыки ===")

            # Получаем длительность фоновой музыки
            music_duration = self._get_music_duration(background_music_path)
            logger.info(f"Длительность фоновой музыки: {int(music_duration // 60)}:{int(music_duration % 60):02d}")

            # Подготавливаем музыку
            temp_music_path = self._prepare_background_music(
                background_music_path, temp_folder, target_duration, music_duration
            )

            # Микшируем аудио
            final_path = self._mix_audio_with_music(
                final_audio_path, temp_music_path, temp_folder, target_duration
            )

            logger.info(f"Фоновая музыка добавлена с громкостью {self.config.background_music_volume}")
            return final_path

        except Exception as e:
            logger.error(f"Ошибка добавления фоновой музыки: {e}")
            return final_audio_path

    def _get_music_duration(self, music_path: str) -> float:
        """Получение длительности музыки"""
        duration = get_media_duration(music_path)
        if duration <= 0:
            raise AudioProcessingError(f"Не удалось получить длительность музыки: {music_path}")
        return duration

    def _prepare_background_music(self, music_path: str, temp_folder: str,
                                  target_duration: float, music_duration: float) -> str:
        """Подготовка фоновой музыки (обрезка или зацикливание)"""
        temp_music_path = Path(temp_folder) / "temp_music.mp3"

        try:
            if music_duration < target_duration:
                logger.info(f"Музыка короче видео ({music_duration:.2f} < {target_duration:.2f}), зацикливаем")
                # Зацикливаем музыку
                cmd = [
                    get_ffmpeg_path(), "-i", music_path,
                    "-filter_complex", f"aloop=loop=-1:size={int(target_duration * self.config.sample_rate)}",
                    "-c:a", "mp3", "-b:a", self.config.bitrate,
                    "-t", str(target_duration), "-y", str(temp_music_path)
                ]
            else:
                # Обрезаем музыку
                cmd = [
                    get_ffmpeg_path(), "-i", music_path,
                    "-c:a", "mp3", "-b:a", self.config.bitrate,
                    "-t", str(target_duration), "-y", str(temp_music_path)
                ]

            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
            return str(temp_music_path)

        except subprocess.CalledProcessError as e:
            raise AudioProcessingError(f"Ошибка подготовки музыки: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise AudioProcessingError("Таймаут при подготовке музыки")

    def _mix_audio_with_music(self, audio_path: str, music_path: str,
                              temp_folder: str, target_duration: float) -> str:
        """Микширование аудио с музыкой"""
        final_path = Path(temp_folder) / "final_audio_with_music.mp3"

        # Создаем фильтр для микширования
        volume_filter = (
            f"[0:a]volume=1.0[a];"
            f"[1:a]volume={self.config.background_music_volume}[b];"
            f"[a][b]amix=inputs=2:duration=longest"
        )

        cmd = [
            get_ffmpeg_path(), "-i", audio_path, "-i", music_path,
            "-filter_complex", volume_filter,
            "-c:a", "mp3", "-b:a", self.config.bitrate,
            "-t", str(target_duration), "-y", str(final_path)
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
            return str(final_path)
        except subprocess.CalledProcessError as e:
            raise AudioProcessingError(f"Ошибка микширования: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise AudioProcessingError("Таймаут при микшировании")


# Функции для обратной совместимости с существующим кодом
def get_audio_files_for_video(xlsx_file_path: str, output_directory: str, video_number: str,
                              language: str = "ru", channel_column: str = "B") -> Tuple[
    List[str], Optional[int], Optional[int]]:
    """
    Обратная совместимость: читает Excel и возвращает аудиофайлы для видео
    """
    try:
        reader = ExcelAudioReader(xlsx_file_path)
        return reader.get_audio_files_for_video(output_directory, video_number, language, channel_column)
    except Exception as e:
        logger.error(f"Ошибка в get_audio_files_for_video: {e}")
        return [], None, None


def process_audio_files(audio_files: List[str], temp_audio_folder: str, temp_folder: str,
                        audio_channels: int, audio_sample_rate: int, audio_bitrate: str,
                        silence_duration: Union[str, float] = "1.0-2.5") -> Tuple[Optional[str], Optional[float]]:
    """
    Обратная совместимость: обрабатывает и склеивает аудиофайлы
    """
    try:
        config = AudioConfig(
            channels=audio_channels,
            sample_rate=audio_sample_rate,
            bitrate=audio_bitrate,
            silence_duration=silence_duration
        )
        processor = AudioProcessor(config)
        return processor.process_audio_files(audio_files, temp_audio_folder, temp_folder)
    except Exception as e:
        logger.error(f"Ошибка в process_audio_files: {e}")
        return None, None


def add_background_music(final_audio_path: str, background_music_path: Optional[str],
                         temp_folder: str, temp_audio_duration: float, audio_bitrate: str,
                         audio_sample_rate: int, background_music_volume: float) -> str:
    """
    Обратная совместимость: добавляет фоновую музыку
    """
    try:
        config = AudioConfig(
            sample_rate=audio_sample_rate,
            bitrate=audio_bitrate,
            background_music_volume=background_music_volume
        )
        processor = BackgroundMusicProcessor(config)
        return processor.add_background_music(final_audio_path, background_music_path, temp_folder, temp_audio_duration)
    except Exception as e:
        logger.error(f"Ошибка в add_background_music: {e}")
        return final_audio_path