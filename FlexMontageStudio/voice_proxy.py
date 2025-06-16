import os
import sys
import csv
import asyncio
import aiohttp
import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass, field
import shutil
import pandas as pd
from contextlib import asynccontextmanager

from core.config_manager import ConfigManager
from ffmpeg_utils import get_ffprobe_path, get_media_duration

# Настройка логгера для модуля
logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """Конфигурация голоса"""
    language: str = "RU"
    stability: float = 1.0
    similarity: float = 1.0
    voice_speed: float = 1.0
    voice_style: Optional[str] = None
    max_retries: int = 10
    ban_retry_delay: int = 120
    standard_voice_id: str = ""
    use_library_voice: bool = True
    original_voice_id: str = ""
    public_owner_id: str = ""


@dataclass
class ProxyConfig:
    """Конфигурация прокси"""
    enabled: bool = False
    url: str = ""
    login: str = ""
    password: str = ""

    @property
    def auth(self) -> Optional[aiohttp.BasicAuth]:
        """Создание объекта авторизации для прокси"""
        if self.enabled and self.login and self.password:
            return aiohttp.BasicAuth(self.login, self.password)
        return None

    @property
    def proxy_url(self) -> Optional[str]:
        """URL прокси или None если отключен"""
        return self.url if self.enabled and self.url else None


@dataclass
class ProcessingStats:
    """Статистика обработки"""
    total_rows: int = 0
    processed_rows: int = 0
    skipped_rows: int = 0
    failed_rows: int = 0
    quota_exceeded_count: int = 0
    ban_count: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def duration(self) -> Optional[timedelta]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


class VoiceProcessingError(Exception):
    """Базовое исключение для ошибок обработки голоса"""
    pass


class APIError(VoiceProcessingError):
    """Ошибка API ElevenLabs"""
    pass


class QuotaExceededError(APIError):
    """Превышение квоты API"""
    pass


class BannedIPError(APIError):
    """Бан IP адреса"""
    pass


class VoiceLimitError(APIError):
    """Превышение лимита голосов"""
    pass


class ConfigurationError(VoiceProcessingError):
    """Ошибка конфигурации"""
    pass


class APIKeyManager:
    """Менеджер API ключей из CSV файла"""

    def __init__(self, csv_file_path: str):
        self.csv_file_path = Path(csv_file_path)
        if not self.csv_file_path.exists():
            raise FileNotFoundError(f"CSV файл не найден: {csv_file_path}")

    def __init__(self, csv_file_path: str):
        self.csv_file_path = Path(csv_file_path)
        if not self.csv_file_path.exists():
            raise FileNotFoundError(f"CSV файл не найден: {csv_file_path}")
        self._used_keys = set()  # Список уже использованных ключей

    def get_api_key(self) -> Optional[str]:
        """
        Получение API ключа из CSV файла

        Returns:
            Optional[str]: API ключ или None если не найден
        """
        try:
            logger.info(f"🔑 Получение API ключа из {self.csv_file_path}")

            current_date = datetime.now().strftime('%d.%m.%Y')
            one_month_ago = datetime.now().date() - timedelta(days=31)
            logger.info(f"📅 Текущая дата: {current_date}, ищем ключи старше: {one_month_ago}")
            logger.info(f"🚫 Исключенные ключи: {len(self._used_keys)}")

            # Читаем CSV файл
            rows = []
            api_key = None

            with open(self.csv_file_path, mode='r', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                fieldnames = reader.fieldnames

                if not fieldnames or 'API' not in fieldnames or 'Date' not in fieldnames:
                    logger.error(f"❌ Неверная структура CSV файла. Найденные столбцы: {fieldnames}")
                    raise ConfigurationError("CSV файл должен содержать столбцы 'API' и 'Date'")

                logger.info(f"📋 Структура CSV файла корректна. Столбцы: {fieldnames}")

                for row in reader:
                    rows.append(row)

                    # Ищем подходящий API ключ (сначала старые, потом любые), исключая уже использованные
                    if row.get('API') and not api_key and row.get('API') not in self._used_keys:
                        try:
                            row_date = datetime.strptime(row.get('Date', ''), '%d.%m.%Y').date()
                            # ИСПРАВЛЕНО: ищем ключи старше месяца ИЛИ любые доступные (если нет старых)
                            if row_date <= one_month_ago:
                                api_key = row.get('API')
                                row['Date'] = current_date
                                logger.debug(f"Найден подходящий API ключ (старше месяца), дата: {row_date}")
                        except ValueError as e:
                            logger.warning(f"Некорректная дата в строке: {row.get('Date', '')}")
                            continue

                # Если не найден старый ключ, используем любой доступный (кроме уже использованных)
                if not api_key:
                    logger.info("🔍 Ключи старше месяца не найдены, ищу любой доступный...")
                    for row in rows:
                        if row.get('API') and row.get('API') not in self._used_keys:
                            try:
                                # ИСПРАВЛЕНО: попытаемся парсить дату, но даже если не получится - возьмем ключ
                                try:
                                    row_date = datetime.strptime(row.get('Date', ''), '%d.%m.%Y').date()
                                    logger.info(f"📋 Найден резервный API ключ, дата: {row_date}")
                                except ValueError:
                                    logger.info(
                                        f"📋 Найден резервный API ключ с некорректной датой: {row.get('Date', 'нет даты')}")

                                api_key = row.get('API')
                                row['Date'] = current_date
                                break
                            except Exception:
                                continue

            logger.info(f"📊 Обработано {len(rows)} строк из CSV файла")

            # Обновляем CSV файл если нашли ключ
            if api_key:
                self._update_csv_file(fieldnames, rows)
                # Добавляем ключ в список использованных
                self._used_keys.add(api_key)
                logger.info(f"✅ API ключ успешно получен: {api_key[:10]}...{api_key[-10:]}")
            else:
                logger.warning("⚠️ Подходящий API ключ не найден")
                logger.warning(f"   - Всего ключей в файле: {sum(1 for row in rows if row.get('API'))}")
                logger.warning(f"   - Уже использованных: {len(self._used_keys)}")
                logger.warning(f"   - Дата отсечения: {one_month_ago}")

            return api_key

        except Exception as e:
            logger.error(f"Ошибка получения API ключа: {e}")
            return None

    def mark_key_as_exhausted(self, api_key: str):
        """
        Отметить ключ как исчерпанный (для случаев превышения лимитов)

        Args:
            api_key: API ключ для добавления в черный список
        """
        self._used_keys.add(api_key)
        logger.info(f"🚫 API ключ добавлен в черный список: {api_key[:10]}...{api_key[-10:]}")

    def _update_csv_file(self, fieldnames: List[str], rows: List[Dict[str, str]]):
        """Обновление CSV файла"""
        temp_file_path = self.csv_file_path.with_suffix('.tmp')

        try:
            with open(temp_file_path, mode='w', newline='', encoding='utf-8') as temp_file:
                writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            # Атомарно заменяем файл
            shutil.move(str(temp_file_path), str(self.csv_file_path))
            logger.debug("CSV файл обновлен")

        except Exception as e:
            # Удаляем временный файл в случае ошибки
            if temp_file_path.exists():
                temp_file_path.unlink()
            raise e


class ElevenLabsAPI:
    """Класс для работы с API ElevenLabs"""

    BASE_URL = "https://api.us.elevenlabs.io/v1"

    def __init__(self, api_key: str, proxy_config: ProxyConfig,
                 max_concurrent_requests: int = 2):
        self.api_key = api_key
        self.proxy_config = proxy_config
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._session: Optional[aiohttp.ClientSession] = None
        # Трекинг временных голосов для предпросмотра
        self._temp_voices: List[str] = []

    async def __aenter__(self):
        """Асинхронный контекст менеджер"""
        connector = aiohttp.TCPConnector(ssl=False, limit=10, limit_per_host=5)
        timeout = aiohttp.ClientTimeout(total=300)  # 5 минут общий таймаут

        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "FlexMontage-Studio/1.0"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессии"""
        # Очищаем все временные голоса при выходе
        await self.cleanup_temp_voices()

        if self._session:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        """Получение сессии"""
        if not self._session:
            raise RuntimeError("API должен использоваться в контексте async with")
        return self._session

    async def add_voice(self, voice_id: str, public_owner_id: str, new_name: str,
                        is_temp: bool = False) -> bool:
        """
        Добавление голоса в библиотеку

        Args:
            voice_id: ID оригинального голоса
            public_owner_id: ID владельца голоса
            new_name: Новое имя голоса
            is_temp: Является ли голос временным (для предпросмотра)

        Returns:
            bool: Успешность операции
        """
        # Проактивная очистка перед добавлением нового голоса
        if is_temp:
            await self.cleanup_temp_voices()

        url = f"{self.BASE_URL}/voices/add/{public_owner_id}/{voice_id}"
        headers = {"xi-api-key": self.api_key}
        data = {"name": new_name}

        try:
            logger.info(f"Добавление голоса: {new_name}")

            async with self.session.post(
                    url,
                    json=data,
                    headers=headers,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:

                if response.status == 200:
                    logger.info("Голос успешно добавлен")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка добавления голоса: {error_text}")

                    # Проверяем на превышение лимита голосов
                    if "voice_limit_reached" in error_text:
                        logger.warning("Достигнут лимит голосов, выполняем очистку...")
                        await self.cleanup_temp_voices()
                        # Повторная попытка после очистки
                        async with self.session.post(
                                url,
                                json=data,
                                headers=headers,
                                proxy=self.proxy_config.proxy_url,
                                proxy_auth=self.proxy_config.auth,
                                timeout=120
                        ) as retry_response:
                            if retry_response.status == 200:
                                logger.info("Голос успешно добавлен после очистки")
                                return True
                            else:
                                retry_error_text = await retry_response.text()
                                logger.error(f"Повторная ошибка добавления голоса: {retry_error_text}")
                                raise VoiceLimitError(
                                    f"Не удалось добавить голос даже после очистки: {retry_error_text}")
                    else:
                        raise APIError(f"Ошибка добавления голоса: {error_text}")

        except asyncio.TimeoutError:
            logger.error("Таймаут при добавлении голоса")
            raise APIError("Таймаут при добавлении голоса")
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения при добавлении голоса: {e}")
            raise APIError(f"Ошибка соединения: {e}")

    async def get_voice_id(self, original_voice_id: str, public_owner_id: str) -> Optional[str]:
        """
        Получение ID голоса из библиотеки

        Args:
            original_voice_id: ID оригинального голоса
            public_owner_id: ID владельца

        Returns:
            Optional[str]: ID голоса или None если не найден
        """
        url = f"{self.BASE_URL}/voices"
        headers = {"xi-api-key": self.api_key}

        try:
            logger.info("Получение ID голоса из библиотеки")

            async with self.session.get(
                    url,
                    headers=headers,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:

                if response.status == 200:
                    data = await response.json()

                    for voice in data.get("voices", []):
                        sharing = voice.get("sharing")
                        if sharing:
                            if (sharing.get("original_voice_id") == original_voice_id and
                                    sharing.get("public_owner_id") == public_owner_id):
                                voice_id = voice["voice_id"]
                                logger.info(f"Найден ID голоса: {voice_id}")
                                # Добавляем в список временных голосов если это предпросмотр
                                if voice_id not in self._temp_voices:
                                    self._temp_voices.append(voice_id)
                                return voice_id

                    logger.warning("ID голоса не найден в библиотеке")
                    return None
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения голосов: {error_text}")
                    raise APIError(f"Ошибка получения голосов: {error_text}")

        except asyncio.TimeoutError:
            logger.error("Таймаут при получении ID голоса")
            raise APIError("Таймаут при получении ID голоса")
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения при получении ID голоса: {e}")
            raise APIError(f"Ошибка соединения: {e}")

    async def delete_voice(self, voice_id: str, max_attempts: int = 3) -> bool:
        """
        Удаление голоса

        Args:
            voice_id: ID голоса для удаления
            max_attempts: Максимальное количество попыток

        Returns:
            bool: Успешность операции
        """
        url = f"{self.BASE_URL}/voices/{voice_id}"
        headers = {"xi-api-key": self.api_key}

        for attempt in range(max_attempts):
            try:
                logger.info(f"Удаление голоса {voice_id}, попытка {attempt + 1}/{max_attempts}")

                async with self.session.delete(
                        url,
                        headers=headers,
                        proxy=self.proxy_config.proxy_url,
                        proxy_auth=self.proxy_config.auth,
                        timeout=120
                ) as response:

                    if response.status == 200:
                        logger.info(f"Голос {voice_id} успешно удален")
                        # Удаляем из списка временных голосов
                        if voice_id in self._temp_voices:
                            self._temp_voices.remove(voice_id)
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка удаления голоса: {error_text}")
                        if attempt == max_attempts - 1:
                            raise APIError(f"Ошибка удаления голоса: {error_text}")

            except asyncio.TimeoutError:
                logger.error(f"Таймаут при удалении голоса, попытка {attempt + 1}")
                if attempt == max_attempts - 1:
                    raise APIError("Таймаут при удалении голоса")
                await asyncio.sleep(5)

            except aiohttp.ClientError as e:
                logger.error(f"Ошибка соединения при удалении голоса: {e}")
                if attempt == max_attempts - 1:
                    raise APIError(f"Ошибка соединения: {e}")
                await asyncio.sleep(5)

        return False

    async def cleanup_temp_voices(self) -> bool:
        """
        Очистка всех временных голосов (используемых для предпросмотра)

        Returns:
            bool: Успешность операции
        """
        if not self._temp_voices:
            return True

        logger.info(f"Очистка {len(self._temp_voices)} временных голосов...")

        # Создаем копию списка для итерации
        voices_to_delete = self._temp_voices.copy()

        for voice_id in voices_to_delete:
            try:
                await self.delete_voice(voice_id)
            except APIError as e:
                logger.warning(f"Не удалось удалить временный голос {voice_id}: {e}")
                continue

        # Очищаем список
        self._temp_voices.clear()
        logger.info("Очистка временных голосов завершена")
        return True

    async def cleanup_voices(self) -> bool:
        """
        Очистка всех голосов кроме предустановленных

        Returns:
            bool: Успешность операции
        """
        try:
            logger.info("Начало очистки голосов")

            url = f"{self.BASE_URL}/voices"
            headers = {"xi-api-key": self.api_key}

            async with self.session.get(
                    url,
                    headers=headers,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения списка голосов: {error_text}")
                    return False

                data = await response.json()
                voices_to_delete = []

                for voice in data.get("voices", []):
                    if voice.get("category") != "premade":
                        voices_to_delete.append(voice["voice_id"])

                logger.info(f"Найдено голосов для удаления: {len(voices_to_delete)}")

                # Удаляем голоса
                for voice_id in voices_to_delete:
                    try:
                        await self.delete_voice(voice_id)
                    except APIError as e:
                        logger.warning(f"Не удалось удалить голос {voice_id}: {e}")
                        continue

                logger.info("Очистка голосов завершена")
                return True

        except Exception as e:
            logger.warning(f"Ошибка очистки голосов: {e}")
            return False

    async def text_to_speech(self, text: str, voice_id: str, output_path: str,
                             voice_config: VoiceConfig, row_index: int) -> bool:
        """
        Преобразование текста в речь

        Args:
            text: Текст для озвучки
            voice_id: ID голоса
            output_path: Путь для сохранения файла
            voice_config: Конфигурация голоса
            row_index: Индекс строки (для логирования)

        Returns:
            bool: Успешность операции
        """
        url = f"{self.BASE_URL}/text-to-speech/{voice_id}"
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json"}

        # Подготавливаем данные запроса
        json_data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "similarity_boost": voice_config.similarity,
                "stability": voice_config.stability
            }
        }

        if voice_config.voice_style:
            json_data["style"] = voice_config.voice_style

        ban_retries = 0

        async with self.semaphore:  # Ограничиваем количество параллельных запросов
            for attempt in range(voice_config.max_retries):
                try:
                    logger.debug(f"Генерация аудио для строки {row_index + 1}, попытка {attempt + 1}")

                    async with self.session.post(
                            url,
                            headers=headers,
                            json=json_data,
                            proxy=self.proxy_config.proxy_url,
                            proxy_auth=self.proxy_config.auth,
                            timeout=120
                    ) as response:

                        if response.status == 200:
                            # Сохраняем аудиофайл
                            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                            with open(output_path, "wb") as audio_file:
                                async for chunk in response.content.iter_chunked(8192):
                                    audio_file.write(chunk)

                            logger.info(f"Аудио сохранено: {Path(output_path).name}")
                            return True

                        else:
                            # Обрабатываем ошибки
                            try:
                                response_data = await response.json()
                                detail = response_data.get("detail", {})
                                status = detail.get("status", "")

                                if status == "detected_unusual_activity":
                                    ban_retries += 1
                                    if ban_retries >= voice_config.max_retries:
                                        logger.error("Превышено максимальное количество попыток после бана IP")
                                        raise BannedIPError("IP адрес заблокирован")

                                    logger.warning(f"Бан IP, попытка {ban_retries}/{voice_config.max_retries}")
                                    await asyncio.sleep(voice_config.ban_retry_delay)
                                    continue

                                elif status == "quota_exceeded":
                                    logger.error(f"Превышена квота: {detail.get('message', 'Неизвестная ошибка')}")
                                    raise QuotaExceededError("Превышена квота API")

                                elif status == "voice_limit_reached":
                                    logger.warning("Достигнут лимит голосов при генерации аудио")
                                    raise VoiceLimitError("Достигнут лимит голосов")

                                elif status == "voice_add_edit_limit_reached":
                                    logger.error(
                                        f"Превышен лимит операций с голосами: {detail.get('message', 'Неизвестная ошибка')}")
                                    raise VoiceLimitError("Превышен месячный лимит операций с голосами")

                                else:
                                    error_text = await response.text()
                                    logger.error(f"Ошибка API: {error_text}")
                                    if attempt == voice_config.max_retries - 1:
                                        raise APIError(f"Ошибка API: {error_text}")

                            except ValueError:
                                error_text = await response.text()
                                logger.error(f"Некорректный ответ от API: {error_text}")
                                if attempt == voice_config.max_retries - 1:
                                    raise APIError(f"Некорректный ответ: {error_text}")

                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут для строки {row_index + 1}, попытка {attempt + 1}")
                    if attempt == voice_config.max_retries - 1:
                        raise APIError("Таймаут при генерации аудио")
                    await asyncio.sleep(5)

                except aiohttp.ServerDisconnectedError:
                    logger.warning(f"Сервер отключился для строки {row_index + 1}")
                    if attempt == voice_config.max_retries - 1:
                        raise APIError("Сервер отключился")
                    await asyncio.sleep(5)

                except aiohttp.ClientError as e:
                    logger.warning(f"Ошибка соединения для строки {row_index + 1}: {e}")
                    if attempt == voice_config.max_retries - 1:
                        raise APIError(f"Ошибка соединения: {e}")
                    await asyncio.sleep(5)

        return False

    async def generate_preview(self, text: str, voice_id: str, public_owner_id: str,
                               voice_config: VoiceConfig) -> Optional[bytes]:
        """
        Генерация предпросмотра голоса

        Args:
            text: Текст для озвучки
            voice_id: ID оригинального голоса
            public_owner_id: ID владельца голоса
            voice_config: Конфигурация голоса

        Returns:
            Optional[bytes]: Аудио данные или None при ошибке
        """
        try:
            # Создаем уникальное имя для временного голоса
            temp_voice_name = f"Preview_{voice_id}_{datetime.now().strftime('%H%M%S%f')}"

            # Добавляем голос в библиотеку как временный
            success = await self.add_voice(voice_id, public_owner_id, temp_voice_name, is_temp=True)
            if not success:
                logger.error("Не удалось добавить голос для предпросмотра")
                return None

            # Получаем ID добавленного голоса
            library_voice_id = await self.get_voice_id(voice_id, public_owner_id)
            if not library_voice_id:
                logger.error("Не удалось получить ID голоса для предпросмотра")
                return None

            # Генерируем аудио
            url = f"{self.BASE_URL}/text-to-speech/{library_voice_id}"
            headers = {"xi-api-key": self.api_key, "Content-Type": "application/json"}

            json_data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "similarity_boost": voice_config.similarity,
                    "stability": voice_config.stability
                }
            }

            if voice_config.voice_style:
                json_data["style"] = voice_config.voice_style

            async with self.session.post(
                    url,
                    headers=headers,
                    json=json_data,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:

                if response.status == 200:
                    audio_data = await response.read()
                    logger.info("Предпросмотр голоса успешно сгенерирован")
                    return audio_data
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка генерации предпросмотра: {error_text}")

                    if "voice_limit_reached" in error_text:
                        raise VoiceLimitError(f"Достигнут лимит голосов: {error_text}")
                    else:
                        raise APIError(f"Ошибка генерации предпросмотра: {error_text}")

        except Exception as e:
            logger.error(f"Критическая ошибка генерации предпросмотра: {e}")
            return None


class ExcelProcessor:
    """Класс для обработки Excel файлов"""

    def __init__(self, excel_path: str, channel_column: str):
        self.excel_path = Path(excel_path)
        self.channel_column = channel_column.upper()

        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel файл не найден: {excel_path}")

    def load_data(self, language: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Загрузка данных из Excel

        Args:
            language: Язык листа для загрузки

        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: Полные данные и данные нужного столбца
        """
        try:
            logger.info(f"Загрузка Excel файла: {self.excel_path}")

            # Загружаем Excel файл
            excel_file = pd.ExcelFile(self.excel_path)
            sheet_names = excel_file.sheet_names

            logger.info(f"Доступные листы: {sheet_names}")

            if language not in sheet_names:
                raise ConfigurationError(f"Лист '{language}' не найден в Excel файле")

            # Читаем данные
            df_full = pd.read_excel(excel_file, sheet_name=language, header=None)

            # Вычисляем индекс столбца
            column_index = ord(self.channel_column) - ord('A')
            if column_index >= df_full.shape[1]:
                raise ConfigurationError(f"Столбец {self.channel_column} не существует в файле")

            df_column = pd.read_excel(excel_file, sheet_name=language, header=None, usecols=[column_index])

            logger.info(f"Данные загружены: {df_full.shape[0]} строк, используется столбец {self.channel_column}")

            return df_full, df_column

        except Exception as e:
            logger.error(f"Ошибка загрузки Excel файла: {e}")
            raise ConfigurationError(f"Ошибка загрузки Excel: {e}")

    def get_existing_files(self, output_directory: str) -> List[int]:
        """
        Получение списка уже существующих файлов

        Args:
            output_directory: Директория с файлами

        Returns:
            List[int]: Список номеров строк с существующими файлами
        """
        output_dir = Path(output_directory)
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            return []

        existing_files = []
        for file_path in output_dir.glob("*.mp3"):
            try:
                # Извлекаем номер строки из имени файла
                file_number = int(file_path.stem)
                existing_files.append(file_number)
            except ValueError:
                continue

        existing_files.sort()
        logger.info(f"Найдено существующих файлов: {len(existing_files)}")

        return existing_files


class VoiceProcessor:
    """Основной класс для обработки озвучки"""

    def __init__(self, channel_name: str, thread=None):
        self.channel_name = channel_name
        self.thread = thread
        self.stats = ProcessingStats()

        logger.info(f"🔧 Инициализация VoiceProcessor для канала: {channel_name}")

        # Загружаем конфигурацию
        self._load_configuration()

    def _load_configuration(self):
        """Загрузка конфигурации канала"""
        try:
            logger.info(f"📋 Загрузка конфигурации для канала: {self.channel_name}")
            config_manager = ConfigManager()
            channel_config = config_manager.get_channel_config(self.channel_name)
            if not channel_config:
                logger.error(f"❌ Конфигурация канала '{self.channel_name}' не найдена")
                raise ConfigurationError(f"Конфигурация канала '{self.channel_name}' не найдена")

            logger.info(f"✅ Базовая конфигурация канала загружена: {len(channel_config)} параметров")

            proxy_config_raw = config_manager.get_proxy_config()
            logger.info(f"🌐 Прокси конфигурация загружена: {proxy_config_raw.get('use_proxy', False)}")

            # Создаем конфигурации
            self.voice_config = VoiceConfig(
                language=channel_config.get("default_lang", "RU").upper(),
                stability=float(channel_config.get("default_stability", 1.0)),
                similarity=float(channel_config.get("default_similarity", 1.0)),
                voice_speed=float(channel_config.get("default_voice_speed", 1.0)),
                voice_style=channel_config.get("default_voice_style"),
                max_retries=int(channel_config.get("max_retries", 10)),
                ban_retry_delay=int(channel_config.get("ban_retry_delay", 120)),
                standard_voice_id=channel_config.get("standard_voice_id", ""),
                use_library_voice=bool(channel_config.get("use_library_voice", True)),
                original_voice_id=channel_config.get("original_voice_id", ""),
                public_owner_id=channel_config.get("public_owner_id", "")
            )

            self.proxy_config = ProxyConfig(
                enabled=bool(proxy_config_raw.get("use_proxy", True)),
                url=proxy_config_raw.get("proxy", ""),
                login=proxy_config_raw.get("proxy_login", ""),
                password=proxy_config_raw.get("proxy_password", "")
            )

            # Пути к файлам
            self.csv_file_path = channel_config["csv_file_path"]
            self.output_directory = channel_config["output_directory"]
            self.excel_file_path = channel_config["global_xlsx_file_path"]
            self.channel_column = channel_config["channel_column"]

            logger.info(f"📁 Конфигурация путей:")
            logger.info(f"   CSV файл: {self.csv_file_path}")
            logger.info(f"   Выходная папка: {self.output_directory}")
            logger.info(f"   Excel файл: {self.excel_file_path}")
            logger.info(f"   Столбец канала: {self.channel_column}")

            # Валидация путей
            self._validate_paths()

            logger.info(f"✅ Конфигурация канала '{self.channel_name}' загружена")

        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            raise ConfigurationError(f"Ошибка конфигурации: {e}")

    def _validate_paths(self):
        """Валидация путей к файлам"""
        logger.info("🔍 Валидация путей к файлам...")

        if not self.excel_file_path:
            logger.error("❌ Путь к Excel файлу не указан")
            raise ConfigurationError("Путь к Excel файлу не указан")

        excel_path = Path(self.excel_file_path)
        if not excel_path.exists():
            logger.error(f"❌ Excel файл не найден: {self.excel_file_path}")
            raise FileNotFoundError(f"Excel файл не найден: {self.excel_file_path}")
        else:
            logger.info(f"✅ Excel файл найден: {self.excel_file_path}")

        if not self.csv_file_path:
            logger.error("❌ Путь к CSV файлу не указан")
            raise ConfigurationError("Путь к CSV файлу не указан")

        csv_path = Path(self.csv_file_path)
        if not csv_path.exists():
            logger.error(f"❌ CSV файл не найден: {self.csv_file_path}")
            raise FileNotFoundError(f"CSV файл не найден: {self.csv_file_path}")
        else:
            logger.info(f"✅ CSV файл найден: {self.csv_file_path}")

        # Проверяем выходную директорию
        output_path = Path(self.output_directory)
        if not output_path.exists():
            logger.warning(f"⚠️ Выходная директория не существует, будет создана: {self.output_directory}")
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"✅ Выходная директория создана: {self.output_directory}")
            except Exception as e:
                logger.error(f"❌ Не удалось создать выходную директорию: {e}")
                raise
        else:
            logger.info(f"✅ Выходная директория найдена: {self.output_directory}")

    def _check_interruption(self):
        """Проверка прерывания процесса"""
        if self.thread is not None and self.thread.is_stopped():
            logger.info(f"Процесс прерван для канала {self.channel_name}")
            raise InterruptedError("Процесс остановлен")

    async def process(self) -> ProcessingStats:
        """
        Основной метод обработки озвучки

        Returns:
            ProcessingStats: Статистика обработки
        """
        self.stats.start_time = datetime.now()

        try:
            logger.info("=" * 60)
            logger.info(f"🎙️ НАЧАЛО ОБРАБОТКИ ОЗВУЧКИ канала: {self.channel_name}")
            logger.info("=" * 60)

            logger.info(f"📊 Статистика запуска:")
            logger.info(f"   📋 Канал: {self.channel_name}")
            logger.info(f"   🔗 Поток: {self.thread is not None}")
            logger.info(f"   📅 Время запуска: {self.stats.start_time}")

            # Инициализация компонентов
            logger.info("🔧 Инициализация компонентов...")
            api_key_manager = APIKeyManager(self.csv_file_path)
            logger.info("✅ APIKeyManager инициализирован")

            excel_processor = ExcelProcessor(self.excel_file_path, self.channel_column)
            logger.info("✅ ExcelProcessor инициализирован")

            # Загрузка данных из Excel
            logger.info("📄 Загрузка данных из Excel...")
            df_full, df_column = excel_processor.load_data(self.voice_config.language)
            self.stats.total_rows = len(df_column)
            logger.info(f"✅ Данные загружены: {self.stats.total_rows} строк")

            # Получение списка существующих файлов
            logger.info("📁 Проверка существующих файлов...")
            existing_files = excel_processor.get_existing_files(self.output_directory)
            logger.info(f"📊 Найдено существующих файлов: {len(existing_files)}")

            # Основной цикл обработки
            logger.info("🔄 Запуск основного цикла обработки...")
            current_api_key = None

            while True:
                self._check_interruption()

                # Получаем API ключ (новый или следующий если текущий исчерпан)
                if current_api_key is None:
                    logger.info("🔑 Получение API ключа...")
                    current_api_key = api_key_manager.get_api_key()
                    if not current_api_key:
                        logger.error("❌ Не удалось получить API ключ - все ключи исчерпаны")
                        raise ConfigurationError("Не удалось получить API ключ - все ключи исчерпаны")
                    else:
                        logger.info(f"✅ API ключ получен: {current_api_key[:10]}...{current_api_key[-10:]}")

                # Обрабатываем строки
                try:
                    logger.info("🌐 Создание ElevenLabsAPI клиента...")
                    async with ElevenLabsAPI(current_api_key, self.proxy_config) as api:
                        logger.info("✅ ElevenLabsAPI клиент создан")

                        logger.info("🔄 Запуск обработки строк...")
                        result = await self._process_rows(api, df_full, df_column, existing_files)

                        if result == "completed":
                            logger.info("🎉 Все строки успешно обработаны")
                            # Валидация и перегенерация поврежденных файлов
                            logger.info("🔍 Запуск валидации файлов...")
                            await self._validate_and_regenerate_files(api, df_full, df_column)
                            break
                        elif result == "quota_exceeded":
                            logger.warning("⚠️ Превышена квота или лимит, помечаем ключ как исчерпанный")
                            api_key_manager.mark_key_as_exhausted(current_api_key)
                            current_api_key = None  # Сбрасываем текущий ключ для получения нового
                            self.stats.quota_exceeded_count += 1
                            continue
                        else:
                            logger.error(f"❌ Неожиданный результат обработки: {result}")
                            break

                except InterruptedError:
                    logger.info("🛑 Получен сигнал прерывания")
                    raise
                except Exception as e:
                    logger.error(f"❌ Критическая ошибка обработки: {e}")
                    logger.error(f"   Тип ошибки: {type(e).__name__}")
                    logger.error(f"   Трассировка: {traceback.format_exc()}")
                    # Помечаем текущий ключ как проблемный и пробуем следующий
                    if current_api_key:
                        api_key_manager.mark_key_as_exhausted(current_api_key)
                        current_api_key = None
                        logger.warning("🔄 Пробуем следующий API ключ...")
                        continue
                    else:
                        raise VoiceProcessingError(f"Ошибка обработки: {e}")

        except InterruptedError:
            logger.info(f"🛑 Обработка канала {self.channel_name} прервана пользователем")
            raise
        except Exception as e:
            logger.error(f"❌ Финальная ошибка обработки канала {self.channel_name}: {e}")
            logger.error(f"   Тип ошибки: {type(e).__name__}")
            logger.error(f"   Трассировка: {traceback.format_exc()}")
            raise
        finally:
            self.stats.end_time = datetime.now()
            logger.info("📊 Завершение обработки, вывод статистики...")
            self._log_final_statistics()

        return self.stats

    async def _process_rows(self, api: ElevenLabsAPI, df_full: pd.DataFrame,
                            df_column: pd.DataFrame, existing_files: List[int]) -> str:
        """
        Обработка строк Excel файла

        Args:
            api: API клиент ElevenLabs
            df_full: Полный DataFrame
            df_column: DataFrame нужного столбца
            existing_files: Список существующих файлов

        Returns:
            str: Результат обработки ('completed', 'quota_exceeded', 'error')
        """
        try:
            # Очистка голосов
            await api.cleanup_voices()

            # Настройка голоса из библиотеки
            library_voice_id = None
            if self.voice_config.use_library_voice:
                library_voice_id = await self._setup_library_voice(api)

            # Обработка строк
            try:
                column_index = ord(self.channel_column) - ord('A')

                for index, row in df_column.iterrows():
                    self._check_interruption()

                    # Проверяем, является ли строка меткой видео
                    if index < len(df_full):
                        cell_a = str(df_full.iloc[index, 0]).strip() if df_full.shape[1] > 0 else ""
                        if cell_a.startswith("ВИДЕО "):
                            logger.debug(f"Пропуск метки видео: {cell_a} (строка {index + 1})")
                            continue

                    # Получаем текст для озвучки
                    text = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                    if not text or text.lower() == 'nan':
                        logger.debug(f"Пропуск пустой строки {index + 1}")
                        continue

                    # Проверяем, существует ли уже файл
                    file_number = index + 1
                    if file_number in existing_files:
                        logger.debug(f"Файл для строки {file_number} уже существует")
                        self.stats.skipped_rows += 1
                        continue

                    # Формируем путь к выходному файлу
                    file_name = f"{str(file_number).zfill(3)}.mp3"
                    output_path = Path(self.output_directory) / file_name

                    # Выбираем голос
                    voice_id = library_voice_id if library_voice_id else self.voice_config.standard_voice_id

                    # Генерируем аудио
                    try:
                        success = await api.text_to_speech(
                            text, voice_id, str(output_path),
                            self.voice_config, index
                        )

                        if success:
                            self.stats.processed_rows += 1
                            existing_files.append(file_number)  # Добавляем в список
                        else:
                            self.stats.failed_rows += 1
                            logger.error(f"Не удалось сгенерировать аудио для строки {file_number}")

                    except QuotaExceededError:
                        logger.warning(f"Превышена квота на строке {file_number}")
                        return "quota_exceeded"
                    except BannedIPError:
                        logger.warning(f"IP заблокирован на строке {file_number}")
                        self.stats.ban_count += 1
                        return "quota_exceeded"  # Пробуем следующий ключ
                    except VoiceLimitError:
                        logger.warning(f"Достигнут лимит голосов на строке {file_number}")
                        # Пытаемся очистить голоса и продолжить
                        await api.cleanup_voices()
                        return "quota_exceeded"  # Пробуем следующий ключ
                    except APIError as e:
                        logger.error(f"Ошибка API для строки {file_number}: {e}")
                        self.stats.failed_rows += 1
                        continue

                return "completed"

            finally:
                # Очищаем голос из библиотеки
                if library_voice_id:
                    try:
                        await api.delete_voice(library_voice_id)
                        logger.info(f"Голос {library_voice_id} удален из библиотеки")
                    except Exception as e:
                        logger.warning(f"Не удалось удалить голос {library_voice_id}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в процессе обработки строк: {e}")
            return "error"

    async def _setup_library_voice(self, api: ElevenLabsAPI) -> Optional[str]:
        """
        Настройка голоса из библиотеки

        Args:
            api: API клиент

        Returns:
            Optional[str]: ID голоса или None при ошибке
        """
        try:
            new_voice_name = f"Library_{self.channel_name}_{datetime.now().strftime('%H%M%S')}"

            # Добавляем голос в библиотеку
            await api.add_voice(
                self.voice_config.original_voice_id,
                self.voice_config.public_owner_id,
                new_voice_name
            )

            # Получаем ID добавленного голоса
            library_voice_id = await api.get_voice_id(
                self.voice_config.original_voice_id,
                self.voice_config.public_owner_id
            )

            if not library_voice_id:
                logger.error("Не удалось получить ID голоса из библиотеки")
                return None

            logger.info(f"Голос из библиотеки настроен: {library_voice_id}")
            return library_voice_id

        except Exception as e:
            logger.error(f"Ошибка настройки голоса из библиотеки: {e}")
            return None

    async def _validate_and_regenerate_files(self, api: ElevenLabsAPI, df_full: pd.DataFrame, df_column: pd.DataFrame):
        """
        Валидация созданных аудиофайлов и перегенерация поврежденных
        """
        import subprocess
        import json

        logger.info("Начало валидации аудиофайлов...")

        # Добавляем таймаут для всей функции валидации (максимум 10 минут)
        validation_start_time = asyncio.get_event_loop().time()
        max_validation_time = 600  # 10 минут

        config_manager = ConfigManager()
        channel_config = config_manager.get_channel_config(self.channel_name)
        audio_folder = Path(channel_config['audio_folder'])
        corrupted_files = []

        # Проверяем все созданные файлы
        for index, row in df_column.iterrows():
            # Проверяем таймаут валидации
            current_time = asyncio.get_event_loop().time()
            if current_time - validation_start_time > max_validation_time:
                logger.warning("Таймаут валидации файлов - завершаем досрочно")
                break

            file_path = audio_folder / f"{index + 1}.mp3"

            if not file_path.exists():
                continue

            # Проверка размера файла
            file_size = file_path.stat().st_size
            if file_size < 200:  # Меньше 200 байт - подозрительно
                logger.warning(f"Подозрительно маленький файл: {file_path} ({file_size} байт)")
                corrupted_files.append((index + 1, file_path, "маленький размер"))
                continue

            # Проверка целостности MP3 через ffprobe (более мягкая проверка)
            try:
                # Используем нашу исправленную функцию с таймаутом
                duration = get_media_duration(str(file_path))

                if duration is None or duration <= 0:
                    logger.warning(f"Не удалось получить длительность файла: {file_path}")
                    corrupted_files.append((index + 1, file_path, "неопределенная длительность"))
                elif duration < 0.5:  # Только если меньше 0.5 секунды - явно поврежден
                    logger.warning(f"Слишком короткое аудио: {file_path} ({duration:.2f}с)")
                    corrupted_files.append((index + 1, file_path, f"слишком короткая длительность: {duration:.2f}с"))
                else:
                    logger.debug(f"Файл {file_path} прошел валидацию: {duration:.2f}с")

            except subprocess.TimeoutExpired:
                logger.warning(f"Таймаут при проверке {file_path} - пропускаем")
            except FileNotFoundError:
                logger.warning(f"ffprobe не найден - пропускаем валидацию {file_path}")
            except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
                # Только логируем, но НЕ помечаем как поврежденный - файл может быть рабочим
                logger.debug(f"Не удалось проверить {file_path} через ffprobe: {e}")

        if not corrupted_files:
            logger.info("Все аудиофайлы прошли валидацию ✅")
            return

        logger.warning(f"Обнаружено {len(corrupted_files)} поврежденных файлов. Начинаем перегенерацию...")

        # Перегенерируем поврежденные файлы
        regenerated_count = 0
        for row_num, file_path, reason in corrupted_files:
            try:
                # Удаляем поврежденный файл
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Удален поврежденный файл: {file_path} (причина: {reason})")

                # Получаем текст для перегенерации
                text_row = df_column.iloc[row_num - 1]
                text = str(text_row.iloc[0]).strip() if not pd.isna(text_row.iloc[0]) else ""

                if text and text.lower() != 'nan':
                    logger.info(f"Перегенерируем файл {row_num}.mp3: '{text[:50]}...'")

                    # Генерируем новый аудиофайл
                    success = await api.text_to_speech(
                        text=text,
                        voice_id=self.voice_config.original_voice_id or self.voice_config.standard_voice_id,
                        output_path=str(file_path),
                        row_index=row_num,
                        voice_config=self.voice_config
                    )

                    if success:
                        logger.info(f"Файл {row_num}.mp3 успешно перегенерирован")
                        regenerated_count += 1
                    else:
                        logger.error(f"Не удалось перегенерировать файл {row_num}.mp3")

            except Exception as e:
                logger.error(f"Ошибка перегенерации файла {row_num}.mp3: {e}")

        logger.info(f"Валидация завершена. Перегенерировано: {regenerated_count}/{len(corrupted_files)} файлов")

    def _log_final_statistics(self):
        """Логирование финальной статистики"""
        logger.info(f"=== Статистика обработки канала {self.channel_name} ===")
        logger.info(f"Всего строк: {self.stats.total_rows}")
        logger.info(f"Обработано: {self.stats.processed_rows}")
        logger.info(f"Пропущено: {self.stats.skipped_rows}")
        logger.info(f"Ошибок: {self.stats.failed_rows}")
        logger.info(f"Превышений квоты: {self.stats.quota_exceeded_count}")
        logger.info(f"Банов IP: {self.stats.ban_count}")

        if self.stats.duration:
            logger.info(f"Время выполнения: {self.stats.duration}")

        success_rate = (self.stats.processed_rows / max(1, self.stats.total_rows - self.stats.skipped_rows)) * 100
        logger.info(f"Успешность: {success_rate:.1f}%")


# Функция для создания API экземпляра с управлением временными голосами
async def create_preview_api(channel_name: str) -> ElevenLabsAPI:
    """
    Создание API экземпляра для предпросмотра голосов

    Args:
        channel_name: Название канала

    Returns:
        ElevenLabsAPI: Настроенный API клиент
    """
    try:
        config_manager = ConfigManager()
        channel_config = config_manager.get_channel_config(channel_name)
        if not channel_config:
            raise ConfigurationError(f"Конфигурация канала '{channel_name}' не найдена")

        proxy_config_raw = config_manager.get_proxy_config()

        # Создаем конфигурацию прокси
        proxy_config = ProxyConfig(
            enabled=bool(proxy_config_raw.get("use_proxy", True)),
            url=proxy_config_raw.get("proxy", ""),
            login=proxy_config_raw.get("proxy_login", ""),
            password=proxy_config_raw.get("proxy_password", "")
        )

        # Получаем API ключ
        api_key_manager = APIKeyManager(channel_config["csv_file_path"])
        api_key = api_key_manager.get_api_key()
        if not api_key:
            raise ConfigurationError("Не удалось получить API ключ")

        return ElevenLabsAPI(api_key, proxy_config)

    except Exception as e:
        logger.error(f"Ошибка создания API для предпросмотра: {e}")
        raise ConfigurationError(f"Ошибка создания API: {e}")


# Функция для обратной совместимости
async def process_voice_and_proxy(channel_name: str, thread=None) -> ProcessingStats:
    """
    Обратная совместимость: основная функция обработки озвучки

    Args:
        channel_name: Название канала
        thread: Объект потока для проверки прерывания

    Returns:
        ProcessingStats: Статистика обработки
    """
    try:
        processor = VoiceProcessor(channel_name, thread)
        return await processor.process()
    except InterruptedError:
        logger.info(f"Обработка канала {channel_name} прервана пользователем")
        raise
    except Exception as e:
        logger.error(f"Критическая ошибка обработки канала {channel_name}: {e}")
        raise VoiceProcessingError(f"Ошибка обработки: {e}")


# Вспомогательные функции для удобства
def create_voice_config(**kwargs) -> VoiceConfig:
    """Создание конфигурации голоса с проверкой параметров"""
    return VoiceConfig(**kwargs)


def create_proxy_config(**kwargs) -> ProxyConfig:
    """Создание конфигурации прокси с проверкой параметров"""
    return ProxyConfig(**kwargs)


async def quick_voice_processing(channel_name: str, **config_overrides) -> ProcessingStats:
    """
    Быстрая обработка озвучки с переопределением конфигурации

    Args:
        channel_name: Название канала
        **config_overrides: Переопределение параметров конфигурации

    Returns:
        ProcessingStats: Статистика обработки
    """
    processor = VoiceProcessor(channel_name)

    # Переопределяем конфигурацию если нужно
    for key, value in config_overrides.items():
        if hasattr(processor.voice_config, key):
            setattr(processor.voice_config, key, value)
        elif hasattr(processor.proxy_config, key):
            setattr(processor.proxy_config, key, value)

    return await processor.process()


# Основная функция для тестирования
async def main():
    """Функция для тестирования модуля"""
    import argparse

    parser = argparse.ArgumentParser(description='Тестирование обработки озвучки')
    parser.add_argument('--channel', type=str, required=True, help='Название канала')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='INFO', help='Уровень логирования')

    args = parser.parse_args()

    # Настройка логирования
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'voice_{args.channel}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        ]
    )

    try:
        stats = await process_voice_and_proxy(args.channel)
        print(f"\n=== Обработка завершена ===")
        print(f"Обработано строк: {stats.processed_rows}")
        print(f"Время выполнения: {stats.duration}")

    except KeyboardInterrupt:
        logger.info("Обработка прервана пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())