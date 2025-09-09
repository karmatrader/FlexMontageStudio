import warnings

warnings.filterwarnings("ignore", category=UserWarning)

import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field

import whisper
from tqdm import tqdm

from utils import rgb_to_bgr, add_alpha_to_color, format_time

# Настройка логгера для модуля
logger = logging.getLogger(__name__)


@dataclass
class SubtitleSegment:
    """Класс для представления сегмента субтитров"""
    start: float
    end: float
    text: str

    def __post_init__(self):
        # Валидация данных
        if self.start < 0:
            self.start = 0.0
        if self.end <= self.start:
            self.end = self.start + 0.1  # Минимальная длительность
        self.text = self.text.strip()


@dataclass
class SubtitleConfig:
    """Конфигурация для генерации субтитров"""
    # Whisper настройки
    model_name: str = "medium"
    language: str = "ru"

    # Ограничения текста
    max_words: int = 3
    time_offset: float = -0.3

    # Стиль текста
    fontsize: int = 110
    font_color: str = "&HFFFFFF"

    # Обводка
    outline_thickness: int = 4
    outline_color: str = "&H000000"

    # Тень
    shadow_thickness: int = 1
    shadow_color: str = "&H333333"
    shadow_alpha: int = 50
    shadow_offset_x: int = 2
    shadow_offset_y: int = 2

    # Подложка
    use_backdrop: bool = False
    back_color: str = "&HFFFFFF"

    # Отступы
    margin_left: int = 10
    margin_right: int = 10
    margin_vertical: int = 20

    # Дополнительные параметры
    video_width: int = 1920
    video_height: int = 1080
    encoding: int = 1


class SubtitleError(Exception):
    """Базовое исключение для ошибок субтитров"""
    pass


class WhisperError(SubtitleError):
    """Ошибки Whisper"""
    pass


class SubtitleGenerationError(SubtitleError):
    """Ошибки генерации субтитров"""
    pass


class WhisperTranscriber:
    """Класс для транскрипции аудио с помощью Whisper"""

    def __init__(self, model_name: str = "medium"):
        self.model_name = model_name
        self._model = None
        self._load_model()

    def _load_model(self):
        """Загрузка модели Whisper"""
        try:
            logger.info(f"Загрузка модели Whisper: {self.model_name}")
            self._model = whisper.load_model(self.model_name)
            logger.info(f"Модель Whisper ({self.model_name}) успешно загружена")
        except Exception as e:
            raise WhisperError(f"Ошибка загрузки модели Whisper {self.model_name}: {e}")

    def transcribe_audio(self, audio_path: str, language: str = "ru") -> Dict[str, Any]:
        """
        Транскрипция аудиофайла

        Args:
            audio_path: Путь к аудиофайлу
            language: Язык для распознавания

        Returns:
            Dict с результатами транскрипции
        """
        if not self._model:
            raise WhisperError("Модель Whisper не загружена")

        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise WhisperError(f"Аудиофайл не найден: {audio_path}")

        try:
            logger.info(f"Начинается транскрипция аудио: {audio_file.name}")
            logger.debug(f"Язык распознавания: {language}")

            # Загружаем аудио
            audio_data = whisper.load_audio(str(audio_file))

            # Выполняем транскрипцию
            result = self._model.transcribe(
                audio_data,
                language=language,
                verbose=False,  # Отключаем verbose вывод Whisper
                word_timestamps=True  # Включаем временные метки для слов
            )

            logger.info(f"Транскрипция завершена. Сегментов: {len(result.get('segments', []))}")
            return result

        except Exception as e:
            raise WhisperError(f"Ошибка транскрипции аудио: {e}")

    def get_model_info(self) -> Dict[str, str]:
        """Получение информации о модели"""
        return {
            "name": self.model_name,
            "status": "loaded" if self._model else "not_loaded"
        }


class SubtitleSegmentProcessor:
    """Класс для обработки сегментов субтитров"""

    @staticmethod
    def split_segment(segment: Dict[str, Any], max_words: int, time_offset: float,
                      max_duration: float) -> List[SubtitleSegment]:
        """
        Разбивает сегмент на подсегменты с ограничением по словам

        Args:
            segment: Исходный сегмент от Whisper
            max_words: Максимальное количество слов в подсегменте
            time_offset: Смещение времени
            max_duration: Максимальная длительность аудио

        Returns:
            List[SubtitleSegment]: Список обработанных сегментов
        """
        try:
            text = segment.get("text", "").strip()
            if not text:
                return []

            words = text.split()
            if not words:
                return []

            start_time = float(segment.get("start", 0))
            end_time = float(segment.get("end", start_time + 1))
            duration = end_time - start_time

            # Применяем смещение времени
            start_shifted = max(0, start_time + time_offset)
            # DEBUG: About to call min() on end_shifted calculation
            logger.debug(f"DEBUG: About to call min() on end_shifted calculation")
            logger.debug(f"DEBUG: start_shifted: {start_shifted}, duration: {duration}, max_duration: {max_duration}")
            end_shifted = min(start_shifted + duration, max_duration)

            if end_shifted <= start_shifted:
                logger.warning(f"Сегмент игнорирован из-за некорректного времени: {start_shifted}-{end_shifted}")
                return []

            # Если слов меньше лимита, возвращаем как есть
            if len(words) <= max_words:
                return [SubtitleSegment(
                    start=start_shifted,
                    end=end_shifted,
                    text=text
                )]

            # Разбиваем на подсегменты
            segments = []
            total_words = len(words)

            for i in range(0, total_words, max_words):
                chunk_words = words[i:i + max_words]
                chunk_text = " ".join(chunk_words)
                chunk_word_count = len(chunk_words)

                # Пропорциональное распределение времени
                chunk_duration = duration * chunk_word_count / total_words
                chunk_start = start_shifted + (i / total_words) * duration
                # DEBUG: About to call min() on chunk_end calculation
                logger.debug(f"DEBUG: About to call min() on chunk_end calculation")
                logger.debug(f"DEBUG: chunk_start: {chunk_start}, chunk_duration: {chunk_duration}, max_duration: {max_duration}")
                chunk_end = min(chunk_start + chunk_duration, max_duration)

                if chunk_end > chunk_start:
                    segments.append(SubtitleSegment(
                        start=chunk_start,
                        end=chunk_end,
                        text=chunk_text
                    ))

            logger.debug(f"Сегмент разбит на {len(segments)} подсегментов")
            return segments

        except Exception as e:
            logger.error(f"Ошибка обработки сегмента: {e}")
            return []

    @staticmethod
    def process_whisper_segments(whisper_result: Dict[str, Any], max_words: int,
                                 time_offset: float, max_duration: float) -> List[SubtitleSegment]:
        """
        Обработка всех сегментов от Whisper

        Args:
            whisper_result: Результат от Whisper
            max_words: Максимум слов в сегменте
            time_offset: Смещение времени
            max_duration: Максимальная длительность

        Returns:
            List[SubtitleSegment]: Обработанные сегменты
        """
        segments = whisper_result.get("segments", [])
        if not segments:
            logger.warning("Whisper не обнаружил сегментов в аудио")
            return []

        processed_segments = []

        logger.info(f"Обработка {len(segments)} сегментов от Whisper")

        for i, segment in enumerate(segments):
            try:
                split_segments = SubtitleSegmentProcessor.split_segment(
                    segment, max_words, time_offset, max_duration
                )
                processed_segments.extend(split_segments)

            except Exception as e:
                logger.error(f"Ошибка обработки сегмента {i}: {e}")
                continue

        logger.info(f"Получено {len(processed_segments)} финальных сегментов субтитров")
        return processed_segments


class ASSSubtitleWriter:
    """Класс для записи субтитров в формате ASS"""

    def __init__(self, config: SubtitleConfig):
        self.config = config

    def write_subtitles(self, segments: List[SubtitleSegment], output_path: str) -> bool:
        """
        Запись субтитров в файл ASS

        Args:
            segments: Список сегментов субтитров
            output_path: Путь для сохранения файла

        Returns:
            bool: Успешность операции
        """
        if not segments:
            logger.warning("Нет сегментов для записи субтитров")
            return False

        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Подготавливаем цвета для ASS формата
            font_color_bgr = rgb_to_bgr(self.config.font_color)
            outline_color_bgr = rgb_to_bgr(self.config.outline_color)
            shadow_color_with_alpha = add_alpha_to_color(
                rgb_to_bgr(self.config.shadow_color),
                self.config.shadow_alpha
            )

            logger.debug(
                f"Цвета субтитров - шрифт: {font_color_bgr}, обводка: {outline_color_bgr}, тень: {shadow_color_with_alpha}")

            # Записываем ASS файл
            with open(output_file, "w", encoding="utf-8") as f:
                # Заголовок
                f.write(self._generate_ass_header())

                # Стили
                f.write(self._generate_ass_styles(font_color_bgr, outline_color_bgr, shadow_color_with_alpha))

                # События (субтитры)
                f.write("[Events]\n")
                f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

                # Записываем каждый сегмент
                written_count = 0
                for segment in tqdm(segments, desc="📝 Запись субтитров"):
                    if self._write_segment(f, segment):
                        written_count += 1

                logger.info(f"Записано сегментов субтитров: {written_count}/{len(segments)}")

            if output_file.exists():
                logger.info(f"ASS файл создан: {output_path}")
                return True
            else:
                logger.error("ASS файл не был создан")
                return False

        except Exception as e:
            logger.error(f"Ошибка записи ASS файла: {e}")
            return False

    def _generate_ass_header(self) -> str:
        """Генерация заголовка ASS файла"""
        return f"""[Script Info]
Title: FlexMontage Studio Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: {self.config.video_width}
PlayResY: {self.config.video_height}

"""

    def _generate_ass_styles(self, font_color: str, outline_color: str, shadow_color: str) -> str:
        """Генерация стилей ASS"""
        border_style = 3 if self.config.use_backdrop else 1

        return f"""[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{self.config.fontsize},{font_color},&H000000,{outline_color},{self.config.back_color},0,0,0,0,100,100,0,0,{border_style},{self.config.outline_thickness},{self.config.shadow_thickness},2,{self.config.margin_left},{self.config.margin_right},{self.config.margin_vertical},{self.config.encoding}

"""

    def _write_segment(self, file_handle, segment: SubtitleSegment) -> bool:
        """Запись одного сегмента в файл"""
        try:
            # Форматируем время
            start_time = format_time(segment.start)
            end_time = format_time(segment.end)

            # Проверяем корректность времени
            if end_time <= start_time:
                logger.debug(f"Пропущен сегмент с некорректным временем: {start_time}-{end_time}")
                return False

            # Подготавливаем текст
            text = segment.text.replace("\n", "\\N").replace("{", "\\{").replace("}", "\\}")
            if not text.strip():
                return False

            # Добавляем тег тени
            shadow_tag = f"\\shad{self.config.shadow_offset_x},{self.config.shadow_offset_y}"

            # Записываем строку диалога
            file_handle.write(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{{{shadow_tag}}}{text}\n")
            return True

        except Exception as e:
            logger.error(f"Ошибка записи сегмента: {e}")
            return False


class SubtitleGenerator:
    """Основной класс для генерации субтитров"""

    def __init__(self, config: SubtitleConfig):
        self.config = config
        self.transcriber = WhisperTranscriber(config.model_name)
        self.writer = ASSSubtitleWriter(config)

    def generate_subtitles(self, audio_path: str, output_folder: str,
                           max_duration: float) -> Optional[str]:
        """
        Полная генерация субтитров из аудио

        Args:
            audio_path: Путь к аудиофайлу
            output_folder: Папка для сохранения
            max_duration: Максимальная длительность видео

        Returns:
            Optional[str]: Путь к файлу субтитров или None при ошибке
        """
        try:
            logger.info("=== 📝 Генерация субтитров ===")
            logger.info(f"Модель: {self.config.model_name}, Язык: {self.config.language}")

            # Транскрипция аудио
            whisper_result = self.transcriber.transcribe_audio(audio_path, self.config.language)

            # Обработка сегментов
            segments = SubtitleSegmentProcessor.process_whisper_segments(
                whisper_result,
                self.config.max_words,
                self.config.time_offset,
                max_duration
            )

            if not segments:
                logger.warning("Не удалось получить сегменты субтитров")
                return None

            # Запись субтитров
            output_path = os.path.join(output_folder, "subtitles.ass")
            success = self.writer.write_subtitles(segments, output_path)

            if success:
                logger.info(f"Субтитры успешно созданы: {output_path}")
                return output_path
            else:
                logger.error("Не удалось создать файл субтитров")
                return None

        except SubtitleError as e:
            logger.error(f"Ошибка генерации субтитров: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при генерации субтитров: {e}")
            return None

    def get_config_info(self) -> Dict[str, Any]:
        """Получение информации о текущей конфигурации"""
        return {
            "model": self.transcriber.get_model_info(),
            "language": self.config.language,
            "max_words": self.config.max_words,
            "time_offset": self.config.time_offset,
            "fontsize": self.config.fontsize
        }


# Функция для обратной совместимости
def generate_subtitles(audio_path: str, temp_folder: str, subtitle_model: str,
                       subtitle_language: str, subtitle_max_words: int, subtitle_time_offset: float,
                       temp_audio_duration: float, subtitle_fontsize: int, subtitle_font_color: str,
                       subtitle_use_backdrop: bool, subtitle_back_color: str, subtitle_outline_thickness: int,
                       subtitle_outline_color: str, subtitle_shadow_thickness: int, subtitle_shadow_color: str,
                       subtitle_shadow_alpha: int, subtitle_shadow_offset_x: int, subtitle_shadow_offset_y: int,
                       subtitle_margin_l: int, subtitle_margin_r: int, subtitle_margin_v: int) -> Optional[str]:
    """
    Обратная совместимость: генерация субтитров с оригинальными параметрами
    """
    try:
        # Создаем конфигурацию из переданных параметров
        config = SubtitleConfig(
            model_name=subtitle_model,
            language=subtitle_language,
            max_words=subtitle_max_words,
            time_offset=subtitle_time_offset,
            fontsize=subtitle_fontsize,
            font_color=subtitle_font_color,
            use_backdrop=subtitle_use_backdrop,
            back_color=subtitle_back_color,
            outline_thickness=subtitle_outline_thickness,
            outline_color=subtitle_outline_color,
            shadow_thickness=subtitle_shadow_thickness,
            shadow_color=subtitle_shadow_color,
            shadow_alpha=subtitle_shadow_alpha,
            shadow_offset_x=subtitle_shadow_offset_x,
            shadow_offset_y=subtitle_shadow_offset_y,
            margin_left=subtitle_margin_l,
            margin_right=subtitle_margin_r,
            margin_vertical=subtitle_margin_v
        )

        # Генерируем субтитры
        generator = SubtitleGenerator(config)
        return generator.generate_subtitles(audio_path, temp_folder, temp_audio_duration)

    except Exception as e:
        logger.error(f"Ошибка в generate_subtitles (compatibility): {e}")
        return None


# Вспомогательные функции для удобства использования
def create_subtitle_config(**kwargs) -> SubtitleConfig:
    """Создание конфигурации субтитров с проверкой параметров"""
    return SubtitleConfig(**kwargs)


def quick_generate_subtitles(audio_path: str, output_folder: str, duration: float,
                             model: str = "medium", language: str = "ru") -> Optional[str]:
    """Быстрая генерация субтитров с минимальными параметрами"""
    config = SubtitleConfig(model_name=model, language=language)
    generator = SubtitleGenerator(config)
    return generator.generate_subtitles(audio_path, output_folder, duration)