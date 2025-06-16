"""
Менеджер библиотеки голосов ElevenLabs
Отвечает за загрузку, кэширование и управление публичными голосами
ДОБАВЛЕНА АВТООЧИСТКА ВРЕМЕННЫХ ГОЛОСОВ ДЛЯ ПРЕДОТВРАЩЕНИЯ ПЕРЕПОЛНЕНИЯ ЛИМИТА
"""
import json
import asyncio
import aiohttp
import logging
import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class APIKeyManager:
    """Менеджер API ключей из CSV файла"""

    def __init__(self, csv_file_path: str):
        self.csv_file_path = Path(csv_file_path)
        if not self.csv_file_path.exists():
            raise FileNotFoundError(f"CSV файл не найден: {csv_file_path}")

    def get_api_key(self) -> Optional[str]:
        """
        Получение API ключа из CSV файла

        Returns:
            Optional[str]: API ключ или None если не найден
        """
        try:
            logger.info(f"Получение API ключа из {self.csv_file_path}")

            current_date = datetime.now().strftime('%d.%m.%Y')
            one_month_ago = datetime.now().date() - timedelta(days=31)

            # Читаем CSV файл
            rows = []
            api_key = None

            with open(self.csv_file_path, mode='r', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                fieldnames = reader.fieldnames

                if not fieldnames or 'API' not in fieldnames or 'Date' not in fieldnames:
                    logger.error("CSV файл должен содержать столбцы 'API' и 'Date'")
                    return None

                for row in reader:
                    rows.append(row)

                    # Ищем подходящий API ключ (сначала старые)
                    if row.get('API') and not api_key:
                        try:
                            row_date = datetime.strptime(row.get('Date', ''), '%d.%m.%Y').date()
                            # Ищем ключи старше месяца
                            if row_date <= one_month_ago:
                                api_key = row.get('API')
                                row['Date'] = current_date
                                logger.debug(f"Найден подходящий API ключ (старше месяца), дата: {row_date}")
                        except ValueError as e:
                            logger.warning(f"Некорректная дата в строке: {row.get('Date', '')}")
                            continue

                # Если не найден старый ключ, используем любой доступный
                if not api_key:
                    logger.info("Ключи старше месяца не найдены, ищу любой доступный...")
                    for row in rows:
                        if row.get('API'):
                            try:
                                # ИСПРАВЛЕНО: попытаемся парсить дату, но даже если не получится - возьмем ключ
                                try:
                                    row_date = datetime.strptime(row.get('Date', ''), '%d.%m.%Y').date()
                                    logger.debug(f"Найден резервный API ключ, дата: {row_date}")
                                except ValueError:
                                    logger.debug(f"Найден резервный API ключ с некорректной датой: {row.get('Date', 'нет даты')}")
                                
                                api_key = row.get('API')
                                row['Date'] = current_date
                                break
                            except Exception:
                                continue

            # Обновляем CSV файл если нашли ключ
            if api_key:
                self._update_csv_file(fieldnames, rows)
                logger.info("API ключ успешно получен")
            else:
                logger.warning("Подходящий API ключ не найден")

            return api_key

        except Exception as e:
            logger.error(f"Ошибка получения API ключа: {e}")
            return None

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


@dataclass
class VoiceInfo:
    """Информация о голосе"""
    voice_id: str
    name: str
    original_voice_id: str
    public_owner_id: str
    description: str = ""
    language: str = ""
    gender: str = ""
    age: str = ""
    accent: str = ""
    category: str = ""
    use_case: str = ""
    preview_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для сериализации"""
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "original_voice_id": self.original_voice_id,
            "public_owner_id": self.public_owner_id,
            "description": self.description,
            "language": self.language,
            "gender": self.gender,
            "age": self.age,
            "accent": self.accent,
            "category": self.category,
            "use_case": self.use_case,
            "preview_url": self.preview_url
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VoiceInfo':
        """Создание из словаря"""
        return cls(**data)

    def __str__(self) -> str:
        """Строковое представление для отображения в UI"""
        parts = [self.name]
        if self.language:
            parts.append(f"[{self.language}]")
        if self.gender:
            parts.append(f"({self.gender})")
        if self.description:
            parts.append(f"- {self.description[:50]}...")
        return " ".join(parts)


@dataclass
class VoiceCache:
    """Кэш голосов"""
    voices: List[VoiceInfo] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    cache_duration_hours: int = 24

    def is_expired(self) -> bool:
        """Проверка истечения кэша"""
        if not self.last_updated:
            return True
        return datetime.now() - self.last_updated > timedelta(hours=self.cache_duration_hours)

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для сериализации"""
        return {
            "voices": [voice.to_dict() for voice in self.voices],
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "cache_duration_hours": self.cache_duration_hours
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VoiceCache':
        """Создание из словаря"""
        voices = [VoiceInfo.from_dict(voice_data) for voice_data in data.get("voices", [])]
        last_updated = None
        if data.get("last_updated"):
            try:
                last_updated = datetime.fromisoformat(data["last_updated"])
            except ValueError:
                logger.warning("Некорректная дата в кэше голосов")

        return cls(
            voices=voices,
            last_updated=last_updated,
            cache_duration_hours=data.get("cache_duration_hours", 24)
        )


class VoiceLibraryManager:
    """Менеджер библиотеки голосов ElevenLabs"""

    BASE_URL = "https://api.us.elevenlabs.io/v1"

    def __init__(self, cache_file: str = "voices_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache = VoiceCache()
        self._load_cache()

        # Отслеживание созданных временных голосов для очистки
        self.created_preview_voices: Set[str] = set()
        self.public_voice_ids: Set[str] = set()  # ID публичных голосов для фильтрации

    def _load_cache(self) -> None:
        """Загрузка кэша из файла"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                self.cache = VoiceCache.from_dict(cache_data)
                logger.info(f"Загружен кэш голосов: {len(self.cache.voices)} голосов")

                # Восстанавливаем список публичных голосов
                self.public_voice_ids = {voice.voice_id for voice in self.cache.voices}

            except Exception as e:
                logger.error(f"Ошибка загрузки кэша голосов: {e}")
                self.cache = VoiceCache()

    def _save_cache(self) -> None:
        """Сохранение кэша в файл"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"Кэш голосов сохранен: {len(self.cache.voices)} голосов")
        except Exception as e:
            logger.error(f"Ошибка сохранения кэша голосов: {e}")

    async def cleanup_temporary_voices(self, api_key: str, proxy_config: Optional[Dict] = None) -> None:
        """
        Очистка временных голосов, созданных для предпросмотра

        Args:
            api_key: API ключ ElevenLabs
            proxy_config: Конфигурация прокси
        """
        if not self.created_preview_voices:
            return

        logger.info(f"Очистка {len(self.created_preview_voices)} временных голосов...")

        try:
            # Настройка прокси
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=30)

            proxy_url = None
            proxy_auth = None

            if proxy_config and proxy_config.get("use_proxy", False):
                proxy_url = proxy_config.get("proxy")
                if proxy_config.get("proxy_login") and proxy_config.get("proxy_password"):
                    proxy_auth = aiohttp.BasicAuth(
                        proxy_config["proxy_login"],
                        proxy_config["proxy_password"]
                    )

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": "FlexMontage-Studio/1.0"}
            ) as session:

                headers = {"xi-api-key": api_key}

                # Получаем список всех голосов
                url = f"{self.BASE_URL}/voices"
                async with session.get(
                    url,
                    headers=headers,
                    proxy=proxy_url,
                    proxy_auth=proxy_auth
                ) as response:

                    if response.status == 200:
                        data = await response.json()
                        current_voices = data.get("voices", [])

                        # Ищем и удаляем временные голоса (не входящие в список публичных)
                        deleted_count = 0
                        for voice in current_voices:
                            voice_id = voice.get("voice_id", "")
                            voice_name = voice.get("name", "")

                            # Удаляем голос если он:
                            # 1. Не в списке известных публичных голосов
                            # 2. Создан недавно (меньше часа назад)
                            # 3. Имеет признаки временного голоса
                            if (voice_id not in self.public_voice_ids and
                                (voice_id in self.created_preview_voices or
                                 self._is_temporary_voice(voice))):

                                delete_url = f"{self.BASE_URL}/voices/{voice_id}"
                                async with session.delete(
                                    delete_url,
                                    headers=headers,
                                    proxy=proxy_url,
                                    proxy_auth=proxy_auth
                                ) as delete_response:

                                    if delete_response.status == 200:
                                        logger.debug(f"Удален временный голос: {voice_name} ({voice_id})")
                                        deleted_count += 1
                                        self.created_preview_voices.discard(voice_id)
                                    else:
                                        logger.warning(f"Не удалось удалить голос {voice_name}: {delete_response.status}")

                        if deleted_count > 0:
                            logger.info(f"Очищено {deleted_count} временных голосов")
                        else:
                            logger.debug("Временные голоса не найдены для очистки")
                    else:
                        logger.warning(f"Не удалось получить список голосов для очистки: {response.status}")

        except Exception as e:
            logger.error(f"Ошибка очистки временных голосов: {e}")

    def _is_temporary_voice(self, voice_data: Dict[str, Any]) -> bool:
        """
        Определяет, является ли голос временным

        Args:
            voice_data: Данные голоса из API

        Returns:
            bool: True если голос временный
        """
        # Проверяем признаки временного голоса
        voice_name = voice_data.get("name", "").lower()
        category = voice_data.get("category", "").lower()

        # Временные голоса часто имеют стандартные имена или категории
        temp_indicators = [
            "preview", "temp", "temporary", "test", "sample",
            "copy", "clone", "duplicate"
        ]

        for indicator in temp_indicators:
            if indicator in voice_name or indicator in category:
                return True

        # Проверяем дату создания (если доступна)
        # Голоса созданные в последний час могут быть временными
        try:
            # Если есть информация о времени создания
            if "date_unix" in voice_data:
                created_time = datetime.fromtimestamp(voice_data["date_unix"])
                if datetime.now() - created_time < timedelta(hours=1):
                    return True
        except:
            pass

        return False

    async def get_public_voices(self, api_key: str, proxy_config: Optional[Dict] = None,
                               force_refresh: bool = False) -> List[VoiceInfo]:
        """
        Получение списка публичных голосов

        Args:
            api_key: API ключ ElevenLabs
            proxy_config: Конфигурация прокси
            force_refresh: Принудительное обновление кэша

        Returns:
            List[VoiceInfo]: Список голосов
        """
        # Проверяем кэш
        if not force_refresh and not self.cache.is_expired() and self.cache.voices:
            logger.info(f"Используется кэшированный список голосов: {len(self.cache.voices)} голосов")
            return self.cache.voices

        logger.info("Загрузка публичных голосов из ElevenLabs API...")

        # Очищаем временные голоса перед загрузкой новых
        await self.cleanup_temporary_voices(api_key, proxy_config)

        try:
            # Настройка прокси
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=30)

            proxy_url = None
            proxy_auth = None

            if proxy_config and proxy_config.get("use_proxy", False):
                proxy_url = proxy_config.get("proxy")
                if proxy_config.get("proxy_login") and proxy_config.get("proxy_password"):
                    proxy_auth = aiohttp.BasicAuth(
                        proxy_config["proxy_login"],
                        proxy_config["proxy_password"]
                    )

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": "FlexMontage-Studio/1.0"}
            ) as session:

                # Получаем собственные голоса
                url = f"{self.BASE_URL}/voices"
                headers = {"xi-api-key": api_key}

                async with session.get(
                    url,
                    headers=headers,
                    proxy=proxy_url,
                    proxy_auth=proxy_auth
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Ошибка получения голосов: {response.status} - {error_text}")
                        # Если есть кэшированные голоса, возвращаем их
                        if self.cache.voices:
                            logger.info("Используется устаревший кэш голосов из-за ошибки API")
                            return self.cache.voices
                        raise Exception(f"Ошибка API: {response.status} - {error_text}")

                    data = await response.json()
                    own_voices = data.get("voices", [])
                    logger.info(f"Получено {len(own_voices)} собственных голосов")

                # Получаем публичную библиотеку голосов
                public_url = f"{self.BASE_URL}/shared-voices"

                try:
                    async with session.get(
                        public_url,
                        headers=headers,
                        proxy=proxy_url,
                        proxy_auth=proxy_auth
                    ) as response:

                        if response.status == 200:
                            public_data = await response.json()
                            public_voices_raw = public_data.get("voices", [])
                            logger.info(f"Получено {len(public_voices_raw)} публичных голосов")
                        else:
                            logger.warning(f"Не удалось получить публичные голоса: {response.status}")
                            public_voices_raw = []

                except Exception as e:
                    logger.warning(f"Ошибка получения публичных голосов: {e}")
                    public_voices_raw = []

                # Обрабатываем все голоса
                all_voices = []

                # Обрабатываем собственные голоса (могут быть публичными)
                for voice_data in own_voices:
                    voice_info = self._parse_voice_data(voice_data, is_own_voice=True)
                    if voice_info:
                        all_voices.append(voice_info)

                # Обрабатываем публичные голоса
                for voice_data in public_voices_raw:
                    voice_info = self._parse_voice_data(voice_data, is_own_voice=False)
                    if voice_info:
                        all_voices.append(voice_info)

                logger.info(f"Обработано всего голосов: {len(all_voices)}")

                # Сохраняем ID публичных голосов для фильтрации
                self.public_voice_ids = {voice.voice_id for voice in all_voices}

                # Обновляем кэш
                self.cache.voices = all_voices
                self.cache.last_updated = datetime.now()
                self._save_cache()

                return all_voices

        except asyncio.TimeoutError:
            logger.error("Таймаут при загрузке голосов")
            if self.cache.voices:
                logger.info("Используется устаревший кэш голосов из-за таймаута")
                return self.cache.voices
            raise Exception("Таймаут при загрузке голосов из ElevenLabs")
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения: {e}")
            if self.cache.voices:
                logger.info("Используется устаревший кэш голосов из-за ошибки соединения")
                return self.cache.voices
            raise Exception(f"Ошибка соединения с ElevenLabs: {e}")
        except Exception as e:
            logger.error(f"Общая ошибка загрузки голосов: {e}")
            # Если есть кэшированные голоса, возвращаем их
            if self.cache.voices:
                logger.info("Используется устаревший кэш голосов из-за ошибки")
                return self.cache.voices
            raise

    def _parse_voice_data(self, voice_data: Dict[str, Any], is_own_voice: bool = False) -> Optional[VoiceInfo]:
        """Парсинг данных голоса из API"""
        try:
            # Для публичных голосов структура может отличаться
            if is_own_voice:
                # Это собственный голос - проверяем, является ли он публичным
                sharing = voice_data.get("sharing")
                if not sharing or sharing.get("status") != "enabled":
                    # Голос не является публичным
                    return None

                voice_info = VoiceInfo(
                    voice_id=voice_data.get("voice_id", ""),
                    name=voice_data.get("name", "Unknown"),
                    original_voice_id=sharing.get("original_voice_id", voice_data.get("voice_id", "")),
                    public_owner_id=sharing.get("public_owner_id", ""),
                    description=sharing.get("description", ""),
                    language=voice_data.get("labels", {}).get("language", ""),
                    gender=voice_data.get("labels", {}).get("gender", ""),
                    age=voice_data.get("labels", {}).get("age", ""),
                    accent=voice_data.get("labels", {}).get("accent", ""),
                    category=voice_data.get("category", ""),
                    use_case=voice_data.get("labels", {}).get("use case", ""),
                    preview_url=voice_data.get("preview_url", "")
                )
            else:
                # Это публичный голос из библиотеки
                voice_info = VoiceInfo(
                    voice_id=voice_data.get("public_voice_id", voice_data.get("voice_id", "")),
                    name=voice_data.get("name", "Unknown"),
                    original_voice_id=voice_data.get("original_voice_id", voice_data.get("voice_id", "")),
                    public_owner_id=voice_data.get("public_owner_id", ""),
                    description=voice_data.get("description", ""),
                    language=voice_data.get("labels", {}).get("language", ""),
                    gender=voice_data.get("labels", {}).get("gender", ""),
                    age=voice_data.get("labels", {}).get("age", ""),
                    accent=voice_data.get("labels", {}).get("accent", ""),
                    category=voice_data.get("category", ""),
                    use_case=voice_data.get("labels", {}).get("use case", ""),
                    preview_url=voice_data.get("preview_url", "")
                )

            # Проверяем обязательные поля
            if not voice_info.voice_id:
                logger.warning(f"Пропущен голос {voice_info.name} - отсутствует voice_id")
                return None

            logger.debug(f"Обработан голос: {voice_info.name} (ID: {voice_info.voice_id})")
            return voice_info

        except Exception as e:
            logger.error(f"Ошибка парсинга данных голоса: {e}")
            logger.debug(f"Данные голоса: {voice_data}")
            return None

    async def preview_voice(self, voice_id: str, api_key: str,
                          sample_text: str = "Hello, this is a voice preview.",
                          proxy_config: Optional[Dict] = None) -> Optional[bytes]:
        """
        Предпросмотр голоса с автоматической очисткой временных файлов

        Args:
            voice_id: ID голоса
            api_key: API ключ
            sample_text: Текст для озвучки
            proxy_config: Конфигурация прокси

        Returns:
            Optional[bytes]: Аудиоданные или None при ошибке
        """
        try:
            logger.info(f"Генерация предпросмотра голоса {voice_id}")

            # Периодически очищаем временные голоса
            if len(self.created_preview_voices) > 2:  # Если накопилось много временных голосов
                await self.cleanup_temporary_voices(api_key, proxy_config)

            # Настройка прокси
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=30)

            proxy_url = None
            proxy_auth = None

            if proxy_config and proxy_config.get("use_proxy", False):
                proxy_url = proxy_config.get("proxy")
                if proxy_config.get("proxy_login") and proxy_config.get("proxy_password"):
                    proxy_auth = aiohttp.BasicAuth(
                        proxy_config["proxy_login"],
                        proxy_config["proxy_password"]
                    )

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": "FlexMontage-Studio/1.0"}
            ) as session:

                url = f"{self.BASE_URL}/text-to-speech/{voice_id}"
                headers = {
                    "xi-api-key": api_key,
                    "Content-Type": "application/json"
                }

                data = {
                    "text": sample_text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                }

                async with session.post(
                    url,
                    headers=headers,
                    json=data,
                    proxy=proxy_url,
                    proxy_auth=proxy_auth
                ) as response:

                    if response.status == 200:
                        audio_data = await response.read()
                        logger.info("Предпросмотр голоса успешно сгенерирован")

                        # Отмечаем что мог быть создан временный голос
                        self.created_preview_voices.add(voice_id)

                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка генерации предпросмотра: {error_text}")

                        # Если ошибка связана с лимитом голосов, пытаемся очистить
                        if "voice_limit_reached" in error_text:
                            logger.info("Попытка очистки временных голосов из-за превышения лимита...")
                            await self.cleanup_temporary_voices(api_key, proxy_config)

                        return None

        except Exception as e:
            logger.error(f"Ошибка предпросмотра голоса: {e}")
            return None

    def search_voices(self, query: str, language: Optional[str] = None,
                     gender: Optional[str] = None) -> List[VoiceInfo]:
        """
        Поиск голосов по критериям

        Args:
            query: Поисковый запрос (по имени или описанию)
            language: Фильтр по языку
            gender: Фильтр по полу

        Returns:
            List[VoiceInfo]: Отфильтрованный список голосов
        """
        if not self.cache.voices:
            return []

        filtered_voices = self.cache.voices

        # Фильтр по запросу
        if query:
            query_lower = query.lower()
            filtered_voices = [
                voice for voice in filtered_voices
                if query_lower in voice.name.lower() or query_lower in voice.description.lower()
            ]

        # Фильтр по языку
        if language:
            filtered_voices = [
                voice for voice in filtered_voices
                if voice.language.lower() == language.lower()
            ]

        # Фильтр по полу
        if gender:
            filtered_voices = [
                voice for voice in filtered_voices
                if voice.gender.lower() == gender.lower()
            ]

        return filtered_voices

    def get_voice_by_ids(self, original_voice_id: str, public_owner_id: str) -> Optional[VoiceInfo]:
        """
        Поиск голоса по original_voice_id и public_owner_id

        Args:
            original_voice_id: ID оригинального голоса
            public_owner_id: ID владельца голоса

        Returns:
            Optional[VoiceInfo]: Найденный голос или None
        """
        for voice in self.cache.voices:
            if (voice.original_voice_id == original_voice_id and
                voice.public_owner_id == public_owner_id):
                return voice
        return None

    def clear_cache(self) -> None:
        """Очистка кэша"""
        self.cache = VoiceCache()
        self.public_voice_ids.clear()
        self.created_preview_voices.clear()
        if self.cache_file.exists():
            self.cache_file.unlink()
        logger.info("Кэш голосов очищен")