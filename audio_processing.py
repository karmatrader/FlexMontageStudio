import os
import subprocess
import json
import random
import logging
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Union, Dict
from dataclasses import dataclass

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

import pandas as pd
from tqdm import tqdm
from ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_media_duration, _test_ffmpeg_working, run_ffmpeg_command
from core.file_api import file_api
from debug_min_simple import debug_min_call, log_min_stats

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
        if not file_api.exists(self.xlsx_file_path):
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
        """Чтение листа Excel через File API"""
        try:
            # Используем File API для кэшированного чтения
            df = file_api.read_excel(
                self.xlsx_file_path,
                sheet_name=language.upper(),
                header=None,
                usecols=[0, column_index]
            )
            logger.debug(f"Прочитан Excel лист '{language.upper()}' через File API, строк: {len(df)}")
            return df

        except FileNotFoundError:
            raise ExcelReaderError(f"Excel файл не найден: {self.xlsx_file_path}")
        except ValueError as e:
            if "Worksheet" in str(e):
                raise ExcelReaderError(f"Лист '{language.upper()}' не найден в Excel файле")
            else:
                raise ExcelReaderError(f"Ошибка чтения Excel: {e}")
        except Exception as e:
            raise ExcelReaderError(f"Неожиданная ошибка при чтении Excel через File API: {e}")

    def _find_video_range(self, df: pd.DataFrame, video_number: str) -> Tuple[int, int]:
        """Поиск диапазона строк для видео по новой структуре (столбец A = номер видео)"""
        target_video = f"ВИДЕО {video_number}"
        video_rows = []
        
        # Ищем все строки для заданного видео
        for idx, row in df.iterrows():
            video_col = str(row[0]).strip() if pd.notna(row[0]) else ""
            if video_col == target_video:
                # Нашли строку с меткой видео, теперь собираем все строки до следующего видео
                start_idx = idx
                
                # Ищем конец диапазона (до следующего видео или до конца файла)
                end_idx = len(df)
                for next_idx in range(idx + 1, len(df)):
                    next_video_col = str(df.iloc[next_idx][0]).strip() if pd.notna(df.iloc[next_idx][0]) else ""
                    if next_video_col.startswith("ВИДЕО "):
                        end_idx = next_idx
                        break
                
                # Собираем все строки данных (включая саму строку с меткой)
                for data_idx in range(start_idx, end_idx):
                    video_rows.append(data_idx + 1)  # +1 для Excel нумерации
                break
        
        if not video_rows:
            # Подробная диагностика для лучшего понимания проблемы
            available_videos = []
            for idx, row in df.iterrows():
                video_col = str(row[0]).strip() if pd.notna(row[0]) else ""
                if video_col.startswith("ВИДЕО "):
                    available_videos.append(video_col)
            
            logger.error(f"Видео {video_number} не найдено в столбце A")
            if available_videos:
                logger.error(f"Доступные видео: {', '.join(available_videos)}")
            else:
                logger.error("В Excel файле не найдено видео с метками 'ВИДЕО N'")
            
            raise ExcelReaderError(f"Видео {video_number} не найдено в столбце A. Доступные видео: {', '.join(available_videos) if available_videos else 'отсутствуют'}")
        
        # DEBUG: About to call min() on video_rows
        logger.debug(f"DEBUG: About to call min() on video_rows")
        logger.debug(f"DEBUG: Type: {type(video_rows)}, Length: {len(video_rows) if hasattr(video_rows, '__len__') else 'N/A'}")
        logger.debug(f"DEBUG: Contents: {video_rows}")
        if not video_rows:
            logger.error(f"ERROR: Empty sequence passed to min() at audio_processing.py:166")
            raise ValueError(f"Empty sequence passed to min() at audio_processing.py:166")
        
        # DEBUG: About to call max() on video_rows
        logger.debug(f"DEBUG: About to call max() on video_rows")
        logger.debug(f"DEBUG: Type: {type(video_rows)}, Length: {len(video_rows) if hasattr(video_rows, '__len__') else 'N/A'}")
        logger.debug(f"DEBUG: Contents: {video_rows}")
        if not video_rows:
            logger.error(f"ERROR: Empty sequence passed to max() at audio_processing.py:166")
            raise ValueError(f"Empty sequence passed to max() at audio_processing.py:166")
        
        start_row = debug_min_call(video_rows, context="audio_processing._find_video_range")
        end_row = max(video_rows) + 1  # +1 для range
        
        logger.debug(f"Найден диапазон для ВИДЕО {video_number}: строки {start_row}–{end_row - 1}")
        return start_row, end_row

    def _find_audio_files(self, output_directory: str, start_row: int, end_row: int) -> List[str]:
        """Поиск аудиофайлов по новой логике: строка Excel = номер аудиофайла"""
        output_dir = Path(output_directory)
        if not output_dir.exists():
            raise ExcelReaderError(f"Папка с аудио не найдена: {output_directory}")

        available_files = list(output_dir.iterdir())
        logger.debug(f"В папке {output_directory} найдено файлов: {len(available_files)}")

        audio_files = []
        missing_files = []

        # По новой логике: строка N = файл N.mp3 (001.mp3, 002.mp3, ...)
        for row_idx in range(start_row, end_row):
            file_number = str(row_idx).zfill(3) if row_idx < 1000 else str(row_idx)
            audio_filename = f"{file_number}.mp3"
            audio_path = output_dir / audio_filename

            if audio_path.exists():
                audio_files.append(audio_filename)
                logger.debug(f"Найден аудиофайл для строки {row_idx}: {audio_filename}")
            else:
                missing_files.append(audio_filename)
                logger.debug(f"Аудиофайл не найден для строки {row_idx}: {audio_filename}")

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

                # Добавляем тишину ПОСЛЕ КАЖДОГО файла (включая последний)
                if max_silence > 0:
                    silence_duration = random.uniform(min_silence, max_silence)
                    silence_path = temp_path / f"silence_{idx}.wav"

                    self._generate_silence(str(silence_path), silence_duration)
                    processed_files.append(str(silence_path))
                    total_duration += silence_duration

                    logger.debug(f"Добавлена тишина после {audio_file}: {silence_duration:.2f} сек")

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
            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=60)
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
            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=30)
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
            run_subprocess_hidden(cmd_concat, check=True, capture_output=True, text=True, timeout=300)

            # Конвертируем в MP3
            duration = self._get_audio_duration(str(temp_audio_path))
            cmd_mp3 = [
                get_ffmpeg_path(), "-i", str(temp_audio_path),
                "-c:a", "mp3", "-b:a", self.config.bitrate,
                "-map", "0:a", "-t", str(duration),
                "-y", str(final_audio_path)
            ]
            run_subprocess_hidden(cmd_mp3, check=True, capture_output=True, text=True, timeout=300)

            logger.info(f"Аудио склеено и сконвертировано: {final_audio_path}")
            return str(final_audio_path)

        except subprocess.CalledProcessError as e:
            raise FFmpegError(f"Ошибка склеивания аудио: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise FFmpegError("Таймаут при склеивании аудио")

    def _scale_audio_to_duration(self, audio_path: str, target_duration: float, temp_folder: str) -> Optional[str]:
        """Масштабирование аудио под целевую длительность"""
        try:
            temp_path = Path(temp_folder)
            scaled_audio_path = temp_path / f"scaled_{Path(audio_path).name}"
            
            # Используем atempo фильтр для изменения темпа
            current_duration = self._get_audio_duration(audio_path)
            speed_factor = current_duration / target_duration
            
            logger.info(f"🔧 Масштабирование аудио: {current_duration:.2f}с → {target_duration:.2f}с (фактор: {speed_factor:.3f})")
            
            # Ограничиваем фактор скорости (atempo поддерживает 0.5-2.0)
            if speed_factor < 0.5:
                logger.warning(f"⚠️ Слишком медленно ({speed_factor:.3f}), используем 0.5")
                speed_factor = 0.5
            elif speed_factor > 2.0:
                logger.warning(f"⚠️ Слишком быстро ({speed_factor:.3f}), используем 2.0")
                speed_factor = 2.0
                
            cmd = [
                get_ffmpeg_path(), "-i", audio_path,
                "-filter:a", f"atempo={speed_factor}",
                "-c:a", "mp3", "-b:a", self.config.bitrate,
                "-y", str(scaled_audio_path)
            ]
            
            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=180)
            
            # Проверяем результат
            result_duration = self._get_audio_duration(str(scaled_audio_path))
            logger.info(f"✅ Результат масштабирования: {result_duration:.2f}с")
            
            return str(scaled_audio_path)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка масштабирования аудио: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка масштабирования аудио: {e}")
            return None

    def _concatenate_audio_segments(self, audio_segments: List[str], temp_folder: str, output_filename: str = "final_audio.mp3") -> Optional[str]:
        """Склеивание аудио сегментов в финальный файл"""
        try:
            temp_path = Path(temp_folder)
            concat_list_path = temp_path / "segments_concat_list.txt"
            final_audio_path = temp_path / output_filename
            
            logger.info(f"🔗 Склеиваем {len(audio_segments)} аудио сегментов")
            
            # Создаем список файлов для конкатенации
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for i, segment_path in enumerate(audio_segments):
                    abs_path = Path(segment_path).resolve()
                    f.write(f"file '{abs_path}'\n")
                    logger.info(f"   Сегмент {i+1}: {Path(segment_path).name}")
            
            # Склеиваем напрямую в MP3
            cmd = [
                get_ffmpeg_path(), "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
                "-c:a", "mp3", "-b:a", self.config.bitrate,
                "-y", str(final_audio_path)
            ]
            
            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=300)
            
            # Проверяем результат
            final_duration = self._get_audio_duration(str(final_audio_path))
            logger.info(f"✅ Финальное аудио создано: {final_audio_path.name} ({final_duration:.2f}с)")
            
            return str(final_audio_path)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка склеивания сегментов: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка склеивания сегментов: {e}")
            return None

    def create_combined_audio(self, main_audio_path: str, video_clips_audio: List[str],
                             output_path: str, target_duration: float,
                             debug_info: Dict = None, background_music_path: str = None,
                             background_music_volume: float = 0.2) -> Tuple[str, float]:
        """
        ИСПРАВЛЕННАЯ функция создания комбинированного аудио с точной длительностью
        """
        logger.info(f"🎵 Создание комбинированного аудио")
        logger.info(f"   Главная дорожка: {main_audio_path}")
        logger.info(f"   Клипов с аудио: {len(video_clips_audio)}")
        logger.info(f"   Целевая длительность: {target_duration:.3f}с")
        logger.info(f"   Фоновая музыка: {background_music_path if background_music_path else 'НЕТ'}")
        logger.info(f"   Громкость музыки: {background_music_volume:.3f}")

        # КРИТИЧЕСКАЯ ПРОВЕРКА: проверяем фактическую длительность главной дорожки
        if not Path(main_audio_path).exists():
            raise AudioProcessingError(f"Главная аудиодорожка не найдена: {main_audio_path}")

        actual_main_duration = get_media_duration(main_audio_path)
        logger.info(f"   Фактическая длительность главной дорожки: {actual_main_duration:.3f}с")

        # ИСПРАВЛЕНИЕ: более гибкая проверка длительности
        duration_difference = abs(actual_main_duration - target_duration)
        max_allowed_difference = max(30.0, target_duration * 0.25)  # Увеличено до 25%

        logger.info(f"🔍 ДИАГНОСТИКА ДЛИТЕЛЬНОСТИ АУДИО:")
        logger.info(f"   Ожидаемая: {target_duration:.3f}с")
        logger.info(f"   Фактическая: {actual_main_duration:.3f}с")
        logger.info(f"   Разница: {duration_difference:.3f}с")
        logger.info(f"   Допустимая разница: {max_allowed_difference:.3f}с")

        # Используем фактическую длительность как базовую
        working_duration = actual_main_duration

        if duration_difference > max_allowed_difference:
            logger.warning(f"⚠️ Большая разница в длительности аудио: {duration_difference:.3f}с")
            logger.warning(f"   Используем фактическую длительность как базовую")

            if debug_info:
                logger.info(f"🔍 ОТЛАДОЧНАЯ ИНФОРМАЦИЯ:")
                for key, value in debug_info.items():
                    logger.info(f"     {key}: {value}")

        # НОВОЕ: Обработка фоновой музыки
        if background_music_path and Path(background_music_path).exists():
            logger.info(f"🎼 Добавляем фоновую музыку: {Path(background_music_path).name}")

            # Создаем аудио с фоновой музыкой
            return self._create_audio_with_background_music(
                main_audio_path, background_music_path, output_path,
                working_duration, background_music_volume, video_clips_audio
            )
        else:
            if background_music_path:
                logger.warning(f"⚠️ Фоновая музыка не найдена: {background_music_path}")
            else:
                logger.info(f"📻 Фоновая музыка не указана")

        # Без фоновой музыки - обрабатываем как раньше
        if not video_clips_audio:
            logger.info(f"📻 Используем только основную дорожку")

            # Корректируем длительность если нужно
            if abs(actual_main_duration - working_duration) > 1.0:
                logger.info(f"🔧 Корректируем длительность: {actual_main_duration:.3f}с → {working_duration:.3f}с")
                return self._adjust_audio_duration(main_audio_path, output_path, working_duration)
            else:
                # Просто копируем
                import shutil
                shutil.copy2(main_audio_path, output_path)
                logger.info(f"✅ Главная дорожка скопирована без изменений")
                return output_path, actual_main_duration

        # Если есть клипы с аудио, выполняем микширование
        logger.info(f"🎛️ Микширование {len(video_clips_audio)} аудиоклипов с главной дорожкой")

        # Создаем filter_complex для микширования
        inputs = [main_audio_path] + video_clips_audio
        filter_parts = []

        # Все входы нормализуем к моно и применяем соответствующие громкости
        for i, audio_path in enumerate(inputs):
            if i == 0:
                # Главная дорожка - полная громкость
                filter_parts.append(f"[{i}:a]volume=1.0[a{i}]")
            else:
                # Клипы - пониженная громкость
                filter_parts.append(f"[{i}:a]volume=0.3[a{i}]")

        # Микшируем все дорожки
        audio_inputs = "+".join([f"[a{i}]" for i in range(len(inputs))])
        filter_parts.append(f"{audio_inputs}amix=inputs={len(inputs)}:duration=first:dropout_transition=0[mixed]")

        # Обрезаем до точной длительности
        filter_parts.append(f"[mixed]atrim=0:{working_duration:.6f}[final]")

        filter_complex = ";".join(filter_parts)

        cmd = [get_ffmpeg_path()]

        # Добавляем все входные файлы
        for audio_path in inputs:
            cmd.extend(["-i", audio_path])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[final]",
            "-acodec", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-ac", "2",
            "-t", str(working_duration),  # Дополнительная защита
            "-y", output_path
        ])

        logger.debug(f"Команда микширования: {' '.join(cmd)}")

        try:
            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=300)

            if Path(output_path).exists():
                final_duration = get_media_duration(output_path)
                logger.info(f"✅ Микширование завершено: {final_duration:.3f}с")

                # ФИНАЛЬНАЯ ПРОВЕРКА длительности
                final_difference = abs(final_duration - working_duration)
                if final_difference > 1.0:
                    logger.warning(f"⚠️ Финальная длительность отличается: {final_difference:.3f}с")
                else:
                    logger.info(f"✅ Финальная длительность точная: разница {final_difference:.3f}с")

                return output_path, final_duration
            else:
                raise AudioProcessingError(f"Файл микширования не создан: {output_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка микширования аудио: {e.stderr}")
            raise AudioProcessingError(f"Ошибка микширования: {e.stderr}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка микширования: {e}")
            raise AudioProcessingError(f"Неожиданная ошибка: {e}")

    def synchronize_main_audio(self, audio_files: List[str], output_path: str,
                              target_duration: float, silence_config: Dict = None) -> Tuple[str, float]:
        """
        ИСПРАВЛЕННАЯ синхронизация главного аудио с точным контролем длительности
        """
        logger.info(f"🔄 Синхронизация главного аудио")
        logger.info(f"   Файлов: {len(audio_files)}")
        logger.info(f"   Целевая длительность: {target_duration:.3f}с")

        if not audio_files:
            raise AudioProcessingError("Нет аудиофайлов для синхронизации")

        # Парсим настройки пауз
        min_silence = silence_config.get('min', 1.0) if silence_config else 1.0
        max_silence = silence_config.get('max', 2.5) if silence_config else 2.5
        avg_silence = (min_silence + max_silence) / 2.0

        logger.info(f"   Средняя пауза между файлами: {avg_silence:.2f}с")

        # ДИАГНОСТИКА: рассчитываем ожидаемую длительность
        total_audio_duration = 0.0
        for audio_file in audio_files:
            if Path(audio_file).exists():
                duration = get_media_duration(audio_file)
                total_audio_duration += duration + avg_silence  # Аудио + пауза
                logger.debug(f"   {Path(audio_file).name}: {duration:.2f}с + {avg_silence:.2f}с пауза")
            else:
                logger.warning(f"   ❌ Аудиофайл не найден: {audio_file}")

        # Убираем последнюю паузу (после последнего файла паузы нет)
        if audio_files:
            total_audio_duration -= avg_silence

        logger.info(f"📊 ДИАГНОСТИКА СИНХРОНИЗАЦИИ:")
        logger.info(f"   Расчетная длительность аудио: {total_audio_duration:.3f}с")
        logger.info(f"   Целевая длительность: {target_duration:.3f}с")
        logger.info(f"   Разница: {abs(total_audio_duration - target_duration):.3f}с")

        # Создаем filter_complex для конкатенации с паузами
        filter_parts = []
        inputs = []

        # Добавляем все аудиофайлы как входы
        for i, audio_file in enumerate(audio_files):
            inputs.extend(["-i", audio_file])
            # Нормализуем громкость и формат
            filter_parts.append(f"[{i}:a]volume=1.0,aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")

        # Создаем паузы
        silence_duration_str = f"{avg_silence:.3f}"
        filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={silence_duration_str}[silence]")

        # Конкатенируем с паузами
        concat_inputs = []
        for i in range(len(audio_files)):
            concat_inputs.append(f"[a{i}]")
            if i < len(audio_files) - 1:  # Не добавляем паузу после последнего файла
                concat_inputs.append("[silence]")

        concat_filter = "".join(concat_inputs) + f"concat=n={len(concat_inputs)}:v=0:a=1[concatenated]"
        filter_parts.append(concat_filter)

        # ТОЧНАЯ ОБРЕЗКА или расширение до целевой длительности
        if abs(total_audio_duration - target_duration) > 0.1:
            if total_audio_duration < target_duration:
                # Нужно расширить - добавляем тишину в конце
                extra_silence = target_duration - total_audio_duration
                logger.info(f"🔧 Добавляем {extra_silence:.2f}с тишины в конец")
                filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={extra_silence:.3f}[extra_silence]")
                filter_parts.append("[concatenated][extra_silence]concat=n=2:v=0:a=1[padded]")
                final_stream = "[padded]"
            else:
                # Нужно обрезать
                logger.info(f"🔧 Обрезаем до {target_duration:.3f}с")
                filter_parts.append(f"[concatenated]atrim=0:{target_duration:.6f}[trimmed]")
                final_stream = "[trimmed]"
        else:
            final_stream = "[concatenated]"

        filter_complex = ";".join(filter_parts)

        cmd = [get_ffmpeg_path()] + inputs + [
            "-filter_complex", filter_complex,
            "-map", final_stream,
            "-acodec", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-ac", "2",
            "-t", str(target_duration),  # Дополнительная защита
            "-y", output_path
        ]

        logger.debug(f"Команда синхронизации: {' '.join(cmd)}")

        try:
            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=300)

            if Path(output_path).exists():
                actual_duration = get_media_duration(output_path)
                logger.info(f"✅ Синхронизация завершена: {actual_duration:.3f}с")

                # ПРОВЕРКА ТОЧНОСТИ
                accuracy = abs(actual_duration - target_duration)
                if accuracy < 1.0:
                    logger.info(f"✅ Высокая точность синхронизации: разница {accuracy:.3f}с")
                else:
                    logger.warning(f"⚠️ Низкая точность синхронизации: разница {accuracy:.3f}с")

                return output_path, actual_duration
            else:
                raise AudioProcessingError(f"Файл синхронизации не создан: {output_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка синхронизации аудио: {e.stderr}")
            raise AudioProcessingError(f"Ошибка синхронизации: {e.stderr}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка синхронизации: {e}")
            raise AudioProcessingError(f"Неожиданная ошибка: {e}")

    def _create_audio_with_background_music(self, main_audio_path: str, background_music_path: str,
                                           output_path: str, target_duration: float,
                                           music_volume: float, video_clips_audio: List[str]) -> Tuple[str, float]:
        """
        Создание аудио с фоновой музыкой
        """
        logger.info(f"🎼 Создание аудио с фоновой музыкой")

        try:
            # Получаем длительность музыки
            music_duration = get_media_duration(background_music_path)
            logger.info(f"   Длительность музыки: {music_duration:.2f}с")
            logger.info(f"   Целевая длительность: {target_duration:.2f}с")

            # Подготавливаем музыку (зацикливание или обрезка)
            temp_music_path = str(Path(output_path).parent / "temp_prepared_music.mp3")
            prepared_music_path = self._prepare_background_music(
                background_music_path, temp_music_path, target_duration, music_duration
            )

            # Микшируем основное аудио с музыкой
            if video_clips_audio:
                # Сначала микшируем основное аудио с клипами, потом добавляем музыку
                temp_mixed_path = str(Path(output_path).parent / "temp_mixed_audio.mp3")
                mixed_path, _ = self._mix_multiple_audio_sources(
                    main_audio_path, video_clips_audio, temp_mixed_path, target_duration
                )
                main_for_music = mixed_path
            else:
                main_for_music = main_audio_path

            # Финальное микширование с музыкой
            final_path = self._mix_audio_with_background_music(
                main_for_music, prepared_music_path, output_path, target_duration, music_volume
            )

            final_duration = get_media_duration(final_path)
            logger.info(f"✅ Аудио с фоновой музыкой создано: {final_duration:.2f}с")

            return final_path, final_duration

        except Exception as e:
            logger.error(f"❌ Ошибка создания аудио с фоновой музыкой: {e}")
            # Fallback - без музыки
            logger.warning("🔄 Создаем аудио без фоновой музыки")
            if video_clips_audio:
                return self._mix_multiple_audio_sources(
                    main_audio_path, video_clips_audio, output_path, target_duration
                )
            else:
                import shutil
                shutil.copy2(main_audio_path, output_path)
                return output_path, get_media_duration(output_path)

    def _prepare_background_music(self, music_path: str, output_path: str,
                                 target_duration: float, music_duration: float) -> str:
        """
        Подготовка фоновой музыки (зацикливание или обрезка)
        """
        logger.info(f"🎵 Подготовка фоновой музыки")

        try:
            if music_duration >= target_duration:
                # Музыка длиннее - обрезаем
                logger.info(f"   Обрезаем музыку: {music_duration:.2f}с → {target_duration:.2f}с")
                cmd = [
                    get_ffmpeg_path(),
                    "-i", music_path,
                    "-t", str(target_duration),
                    "-acodec", "mp3",
                    "-b:a", "128k",
                    "-y", output_path
                ]
            else:
                # Музыка короче - зацикливаем
                loops_needed = int(target_duration / music_duration) + 1
                logger.info(f"   Зацикливаем музыку: {loops_needed} раз")
                cmd = [
                    get_ffmpeg_path(),
                    "-stream_loop", str(loops_needed),
                    "-i", music_path,
                    "-t", str(target_duration),
                    "-acodec", "mp3",
                    "-b:a", "128k",
                    "-y", output_path
                ]

            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=120)

            if Path(output_path).exists():
                actual_duration = get_media_duration(output_path)
                logger.info(f"   ✅ Музыка подготовлена: {actual_duration:.2f}с")
                return output_path
            else:
                raise AudioProcessingError("Подготовленная музыка не создана")

        except Exception as e:
            logger.error(f"❌ Ошибка подготовки музыки: {e}")
            raise AudioProcessingError(f"Ошибка подготовки музыки: {e}")

    def _mix_audio_with_background_music(self, main_audio_path: str, music_path: str,
                                        output_path: str, target_duration: float,
                                        music_volume: float) -> str:
        """
        Микширование основного аудио с фоновой музыкой
        """
        logger.info(f"🎛️ Микширование с фоновой музыкой")
        logger.info(f"   Громкость основного аудио: 100%")
        logger.info(f"   Громкость фоновой музыки: {music_volume * 100:.1f}%")

        try:
            # Создаем filter_complex для микширования
            filter_complex = (
                f"[0:a]volume=1.0[main];"
                f"[1:a]volume={music_volume:.6f}[music];"
                f"[main][music]amix=inputs=2:duration=first:dropout_transition=0[mixed]"
            )

            cmd = [
                get_ffmpeg_path(),
                "-i", main_audio_path,
                "-i", music_path,
                "-filter_complex", filter_complex,
                "-map", "[mixed]",
                "-acodec", "mp3",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                "-t", str(target_duration),
                "-y", output_path
            ]

            logger.debug(f"Команда микширования: {' '.join(cmd)}")

            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=180)

            if Path(output_path).exists():
                final_duration = get_media_duration(output_path)
                logger.info(f"✅ Микширование завершено: {final_duration:.2f}с")
                return output_path
            else:
                raise AudioProcessingError("Файл микширования не создан")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка FFmpeg при микшировании:")
            logger.error(f"   stderr: {e.stderr}")
            raise AudioProcessingError(f"Ошибка микширования: {e.stderr}")
        except Exception as e:
            logger.error(f"❌ Ошибка микширования: {e}")
            raise AudioProcessingError(f"Ошибка микширования: {e}")

    def _adjust_audio_duration(self, input_path: str, output_path: str, target_duration: float) -> Tuple[str, float]:
        """
        Корректировка длительности аудио
        """
        logger.info(f"🔧 Корректировка длительности аудио до {target_duration:.2f}с")

        try:
            cmd = [
                get_ffmpeg_path(),
                "-i", input_path,
                "-t", str(target_duration),
                "-acodec", "copy",  # Копируем без перекодировки если возможно
                "-avoid_negative_ts", "make_zero",
                "-y", output_path
            ]

            run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=60)

            if Path(output_path).exists():
                actual_duration = get_media_duration(output_path)
                logger.info(f"✅ Длительность скорректирована: {actual_duration:.2f}с")
                return output_path, actual_duration
            else:
                raise AudioProcessingError("Скорректированный файл не создан")

        except Exception as e:
            logger.error(f"❌ Ошибка коррекции длительности: {e}")
            # Fallback - просто копируем
            import shutil
            shutil.copy2(input_path, output_path)
            return output_path, get_media_duration(output_path)

    def _mix_multiple_audio_sources(self, main_audio_path: str, video_clips_audio: List[str], 
                                   output_path: str, target_duration: float) -> Tuple[str, float]:
        """
        Микширование нескольких аудиоисточников
        """
        logger.info(f"🎛️ Микширование {len(video_clips_audio)} аудиоклипов с главной дорожкой")

        # Создаем filter_complex для микширования
        inputs = [main_audio_path] + video_clips_audio
        filter_parts = []

        # Все входы нормализуем к моно и применяем соответствующие громкости
        for i, audio_path in enumerate(inputs):
            if i == 0:
                # Главная дорожка - полная громкость
                filter_parts.append(f"[{i}:a]volume=1.0[a{i}]")
            else:
                # Клипы - пониженная громкость
                filter_parts.append(f"[{i}:a]volume=0.3[a{i}]")

        # Микшируем все дорожки
        audio_inputs = "+".join([f"[a{i}]" for i in range(len(inputs))])
        filter_parts.append(f"{audio_inputs}amix=inputs={len(inputs)}:duration=first:dropout_transition=0[mixed]")

        # Обрезаем до точной длительности
        filter_parts.append(f"[mixed]atrim=0:{target_duration:.6f}[final]")

        filter_complex = ";".join(filter_parts)

        cmd = [get_ffmpeg_path()]
        for input_file in inputs:
            cmd.extend(["-i", input_file])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[final]",
            "-acodec", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-ac", "2",
            "-t", str(target_duration),  # Дополнительная защита
            "-y", output_path
        ])

        logger.debug(f"Команда микширования: {' '.join(cmd)}")

        try:
            result = run_subprocess_hidden(cmd, check=True, capture_output=True, text=True, timeout=300)

            if Path(output_path).exists():
                final_duration = get_media_duration(output_path)
                logger.info(f"✅ Микширование завершено: {final_duration:.3f}с")

                # ФИНАЛЬНАЯ ПРОВЕРКА длительности
                final_difference = abs(final_duration - target_duration)
                if final_difference > 1.0:
                    logger.warning(f"⚠️ Финальная длительность отличается: {final_difference:.3f}с")
                else:
                    logger.info(f"✅ Финальная длительность точная: разница {final_difference:.3f}с")

                return output_path, final_duration
            else:
                raise AudioProcessingError(f"Файл микширования не создан: {output_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Ошибка микширования аудио: {e.stderr}")
            raise AudioProcessingError(f"Ошибка микширования: {e.stderr}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка микширования: {e}")
            raise AudioProcessingError(f"Неожиданная ошибка: {e}")


class BackgroundMusicProcessor:
    """Класс для добавления фоновой музыки"""

    def __init__(self, config: AudioConfig):
        self.config = config

    def add_background_music(self, final_audio_path: str, background_music_path: Optional[str],
                             temp_folder: str, target_duration: float) -> str:
        """
        УСТАРЕВШАЯ ФУНКЦИЯ: Добавляет фоновую музыку к основному аудио.
        Теперь это делается в create_combined_audio.
        """
        logger.info("=== 🎵 Добавление фоновой музыки (УСТАРЕВШАЯ ФУНКЦИЯ - ОТКЛЮЧЕНО) ===")
        logger.warning("Эта функция add_background_music устарела и не должна вызываться. Возвращаем основное аудио.")
        
        # Возвращаем основное аудио, так как смешивание происходит в create_combined_audio
        if Path(final_audio_path).exists():
            # Если music_path не указан или пуст, просто возвращаем основное аудио
            if not background_music_path or not Path(background_music_path).exists():
                return final_audio_path
            
            # Добавим заглушку, чтобы код не падал, если вдруг будет вызван
            logger.error("ОШИБКА: add_background_music была вызвана. Она устарела. Возвращаем final_audio_path.")
            return final_audio_path
        else:
            raise ValueError("Main audio path does not exist in obsolete function.")

    def _get_music_duration(self, music_path: str) -> float:
        """Получение длительности музыки"""
        duration = get_media_duration(music_path)
        if duration <= 0:
            raise AudioProcessingError(f"Не удалось получить длительность музыки: {music_path}")
        return duration

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


def process_audio_files_by_excel_folders(excel_folder_durations: Dict[str, float], audio_files: List[str],
                                         temp_audio_folder: str, temp_folder: str, audio_channels: int, 
                                         audio_sample_rate: int, audio_bitrate: str,
                                         silence_duration: Union[str, float] = "1.0-2.5",
                                         folder_audio_mapping: Dict[str, List[int]] = None,
                                         output_filename: str = "temp_combined_audio.mp3") -> Tuple[Optional[str], Optional[float]]:
    """
    Обрабатывает аудио по Excel папкам
    
    Args:
        excel_folder_durations: Словарь {папка: длительность} из Excel
        audio_files: Список всех аудиофайлов
        Остальные параметры: стандартные конфигурации
        
    Returns:
        Путь к финальному аудио и его длительность
    """
    try:
        logger.info("🎵 Обработка аудио по Excel папкам")
        logger.info(f"📋 Excel папки: {list(excel_folder_durations.keys())}")
        
        config = AudioConfig(
            channels=audio_channels,
            sample_rate=audio_sample_rate,
            bitrate=audio_bitrate,
            silence_duration=silence_duration
        )
        processor = AudioProcessor(config)
        
        audio_segments = []
        total_duration = 0.0
        
        # Обрабатываем каждую папку
        for folder, _ in excel_folder_durations.items():
            logger.info(f"📁 Обработка папки '{folder}'")
            
            # Используем соответствие из Excel, если доступно
            if folder_audio_mapping and folder in folder_audio_mapping:
                audio_numbers = folder_audio_mapping[folder]
                logger.info(f"   📊 Используем соответствие из Excel: {audio_numbers[0]:03d}-{audio_numbers[-1]:03d} ({len(audio_numbers)} файлов)")
            else:
                # Fallback: интерпретируем название папки как диапазон (старая логика)
                logger.warning(f"   ⚠️ Нет соответствия в Excel, используем название папки как диапазон")
                if '-' in folder:
                    start_num, end_num = map(int, folder.split('-'))
                    audio_numbers = list(range(start_num, end_num + 1))
                else:
                    audio_numbers = [int(folder)]
            
            # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ищем аудиофайлы озвучки в temp_audio_folder ---
            # temp_audio_folder теперь должен быть /temp/audio/
            # Мы ищем файлы 001.mp3, 002.mp3 и т.д.
            folder_audio_files = []
            for num in audio_numbers:
                # Формируем имя файла из номера строки, например, 001.mp3
                audio_filename = f"{num:03d}.mp3"  # Формат 001, 002, ...
                full_audio_file_path = Path(temp_audio_folder) / audio_filename  # ИСПРАВЛЕНО: Полный путь

                if full_audio_file_path.exists():
                    folder_audio_files.append(str(full_audio_file_path))
                    logger.debug(f"   ✅ Найден аудиофайл: {audio_filename}")
                else:
                    logger.warning(f"⚠️ Папка '{folder}': аудиофайл {audio_filename} не найден по пути {full_audio_file_path}")

            if not folder_audio_files:
                logger.warning(f"⚠️ Папка '{folder}': аудиофайлы не найдены")  # Это предупреждение, которое вы видели
                continue  # Пропускаем, если нет файлов
            
            # Обрабатываем аудио папки
            folder_temp = Path(temp_folder) / f"folder_{folder}"
            folder_temp.mkdir(exist_ok=True)
            
            folder_audio_path, folder_duration = processor.process_audio_files(
                folder_audio_files, temp_audio_folder, str(folder_temp)
            )
            
            if folder_audio_path:
                audio_segments.append(folder_audio_path)
                total_duration += folder_duration
                logger.info(f"   ✅ Длительность сегмента: {folder_duration:.2f}с")
        
        if not audio_segments:
            logger.error("❌ Нет обработанных аудио сегментов")
            return None, None
        
        # Склеиваем все сегменты с правильным именем файла
        logger.info(f"🔗 Склеиваем {len(audio_segments)} аудио сегментов")
        final_audio_path = processor._concatenate_audio_segments(audio_segments, temp_folder, output_filename)
        
        if final_audio_path:
            final_duration = processor._get_audio_duration(final_audio_path)
            logger.info(f"✅ Финальное аудио: {final_duration:.2f}с")
            return final_audio_path, final_duration
        
        return None, None
        
    except Exception as e:
        logger.error(f"Ошибка в process_audio_files_by_excel_folders: {e}")
        return None, None


def process_audio_files(audio_files: List[str], temp_audio_folder: str, temp_folder: str,
                        audio_channels: int, audio_sample_rate: int, audio_bitrate: str,
                        silence_duration: Union[str, float] = "1.0-2.5") -> Tuple[Optional[str], Optional[float]]:
    """
    Обратная совместимость: обрабатывает и склеивает аудиофайлы (СТАРАЯ ЛОГИКА)
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
    УСТАРЕВШАЯ ФУНКЦИЯ: Добавляет фоновую музыку к основному аудио.
    Теперь это делается в create_combined_audio.
    """
    logger.info("=== 🎵 Добавление фоновой музыки (УСТАРЕВШАЯ ФУНКЦИЯ - ОТКЛЮЧЕНО) ===")
    logger.warning("Эта функция add_background_music устарела и не должна вызываться. Возвращаем основное аудио.")
    
    # Возвращаем основное аудио, так как смешивание происходит в create_combined_audio
    if Path(final_audio_path).exists():
        # Если music_path не указан или пуст, просто возвращаем основное аудио
        if not background_music_path or not Path(background_music_path).exists():
            return final_audio_path
        
        # Добавим заглушку, чтобы код не падал, если вдруг будет вызван
        logger.error("ОШИБКА: add_background_music была вызвана. Она устарела. Возвращаем final_audio_path.")
        return final_audio_path
    else:
        raise ValueError("Main audio path does not exist in obsolete function.")