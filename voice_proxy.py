import os
import sys
import csv
import json
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
import random
import re
from asyncio import Semaphore

from core.config_manager import ConfigManager
from ffmpeg_utils import get_ffprobe_path, get_media_duration

# Настройка логгера для модуля
logger = logging.getLogger(__name__)

# Список реальных User-Agent'ов для ротации
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/117.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/117.0.2045.47 Safari/537.36",
    "Python/3.10 aiohttp/3.8.5 (Windows NT 10.0; Win64; x64)",
    "Python/3.10 aiohttp/3.8.5 (Macintosh; Intel Mac OS X 10_15_7)",
    "python-requests/2.28.1"
]

@dataclass
class VoiceConfig:
    """Конфигурация голоса"""
    language: str = "RU"
    stability: float = 1.0
    similarity: float = 1.0
    voice_speed: float = 1.0
    voice_style: Optional[str] = None
    max_retries: int = 10
    ban_retry_delay: int = 300  # Базовая задержка при бане IP
    standard_voice_id: str = ""
    use_library_voice: bool = True
    original_voice_id: str = ""
    public_owner_id: str = ""
    skip_voice_management: bool = False  # Флаг для отключения операций с голосами
    max_concurrent_requests: int = 5  # Максимальное количество параллельных запросов
    parallel_threads: int = 2  # Количество параллельных потоков обработки

@dataclass
class ProxyConfig:
    """Конфигурация прокси"""
    enabled: bool = False
    proxies: List[Dict[str, str]] = field(default_factory=list)  # Список прокси
    current_proxy_index: int = 0
    proxy_type: str = "standard"  # "standard" или "residential"
    rotate_endpoint: str = ""  # URL для ротации IP
    rotate_min_interval: int = 30  # Минимальный интервал между ротациями (секунды)
    rotate_auth_login: str = ""  # Логин для авторизации ротации
    rotate_auth_password: str = ""  # Пароль для авторизации ротации
    _last_rotate_time: float = field(default=0, init=False)  # Время последней ротации

    def __post_init__(self):
        """Валидация прокси"""
        if self.enabled and not self.proxies:
            logger.error("Прокси включены, но список прокси пуст")
            raise ConfigurationError("Список прокси пуст")
        for proxy in self.proxies:
            if not proxy.get("url") or not re.match(r'https?://', proxy["url"]):
                logger.error(f"Некорректный URL прокси: {proxy.get('url', 'пустой')}")
                raise ConfigurationError(f"Некорректный URL прокси: {proxy.get('url', 'пустой')}")

    @property
    def current_proxy(self) -> Optional[Dict[str, str]]:
        """Получение текущего прокси"""
        if not self.enabled or not self.proxies:
            return None
        return self.proxies[self.current_proxy_index]

    @property
    def auth(self) -> Optional[aiohttp.BasicAuth]:
        """Создание объекта авторизации для текущего прокси"""
        proxy = self.current_proxy
        if proxy and proxy.get("login") and proxy.get("password"):
            return aiohttp.BasicAuth(proxy["login"], proxy["password"])
        return None

    @property
    def proxy_url(self) -> Optional[str]:
        """URL текущего прокси или None если отключен"""
        proxy = self.current_proxy
        return proxy["url"] if self.enabled and proxy else None

    def rotate_proxy(self) -> bool:
        """Переключение на следующий прокси"""
        if not self.proxies:
            return False
        
        if self.proxy_type == "standard":
            # Для обычных прокси - просто переключаемся на следующий
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
            logger.info(f"Переключение на прокси: {self.current_proxy['url']}")
            return True
        else:
            # Для резидентских прокси - вызываем ротацию IP
            return self.rotate_residential_ip()
    
    def rotate_residential_ip(self) -> bool:
        """Ротация IP для резидентских прокси"""
        import time
        
        current_time = time.time()
        if current_time - self._last_rotate_time < self.rotate_min_interval:
            wait_time = self.rotate_min_interval - (current_time - self._last_rotate_time)
            logger.info(f"Ожидание {wait_time:.1f}с перед следующей ротацией IP")
            return False
        
        if not self.rotate_endpoint:
            logger.error("Не указан endpoint для ротации IP")
            return False
        
        try:
            # Получаем порт из текущего прокси URL
            proxy_url = self.current_proxy.get("url", "")
            import re
            port_match = re.search(r':([0-9]+)/?$', proxy_url)
            if not port_match:
                logger.error(f"Не удалось извлечь порт из URL прокси: {proxy_url}")
                return False
            
            sticky_port = port_match.group(1)
            
            # Выполняем запрос на ротацию
            import aiohttp
            import asyncio
            
            async def _rotate():
                # Используем основные логин и пароль прокси для ротации
                auth_login = self.current_proxy.get("login", "")
                auth_password = self.current_proxy.get("password", "")
                
                if auth_login and auth_password:
                    auth = aiohttp.BasicAuth(auth_login, auth_password)
                else:
                    auth = None
                
                async with aiohttp.ClientSession() as session:
                    params = {"port": sticky_port}
                    async with session.get(
                        self.rotate_endpoint,
                        params=params,
                        auth=auth,
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == "ok":
                                logger.info(f"IP успешно изменён для порта {sticky_port}")
                                self._last_rotate_time = time.time()
                                # Даём время на стабилизацию
                                await asyncio.sleep(5)
                                return True
                            else:
                                logger.error(f"Ошибка ротации IP: {data}")
                                return False
                        else:
                            logger.error(f"HTTP ошибка при ротации IP: {response.status}")
                            return False
            
            # Если мы в асинхронном контексте
            try:
                loop = asyncio.get_running_loop()
                return loop.run_until_complete(_rotate())
            except RuntimeError:
                # Если нет активного loop, создаём новый
                return asyncio.run(_rotate())
                
        except Exception as e:
            logger.error(f"Ошибка при ротации резидентского IP: {e}")
            return False

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
    """Менеджер API ключей из файла (CSV/TXT)"""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"Файл с ключами не найден: {file_path}")
        self._used_keys = set()
        
        # Определяем тип файла
        self.file_type = "txt" if self.file_path.suffix.lower() == ".txt" else "csv"
        logger.info(f"📄 Тип файла с ключами: {self.file_type.upper()}")

    def get_api_key(self) -> Optional[str]:
        """
        Получение API ключа из файла (CSV или TXT)
        """
        if self.file_type == "txt":
            return self._get_api_key_from_txt()
        else:
            return self._get_api_key_from_csv()
    
    def _get_api_key_from_txt(self) -> Optional[str]:
        """
        Получение API ключа из TXT файла (формат: api_key,date или просто api_key)
        """
        try:
            logger.info(f"🔑 Получение API ключа из TXT файла: {self.file_path}")
            
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
            
            # Парсим строки в формате api_key,date или просто api_key
            keys_with_dates = []
            current_date = datetime.now()
            
            for line in lines:
                if ',' in line:
                    # Формат: api_key,date
                    parts = line.split(',', 1)
                    api_key = parts[0].strip()
                    date_str = parts[1].strip()
                    
                    try:
                        last_used_date = datetime.strptime(date_str, '%d.%m.%Y')
                        keys_with_dates.append((api_key, last_used_date))
                    except ValueError:
                        logger.warning(f"⚠️ Некорректная дата в строке: {line}")
                        # Если дата некорректна, считаем ключ старым (доступным)
                        keys_with_dates.append((api_key, datetime.min))
                else:
                    # Старый формат: только api_key
                    api_key = line
                    # Для ключей без даты считаем их старыми (доступными)
                    keys_with_dates.append((api_key, datetime.min))
            
            # Фильтруем уже использованные ключи
            available_keys = [(key, date) for key, date in keys_with_dates if key not in self._used_keys]
            
            if not available_keys:
                logger.warning("⚠️ Все ключи из TXT файла уже использованы")
                return None
            
            # ВРЕМЕННОЕ ИСПРАВЛЕНИЕ: Используем все доступные ключи, независимо от даты
            # Дата в TXT файле - это дата добавления ключа, а не последнего использования
            filtered_keys = [api_key for api_key, _ in available_keys]
            
            logger.info(f"📊 Статистика TXT ключей: всего {len(available_keys)}, доступных {len(filtered_keys)}")
            
            if not filtered_keys:
                logger.warning("⚠️ Нет доступных ключей")
                return None
            
            # Берем первый доступный ключ
            api_key = filtered_keys[0]
            # НЕ добавляем в _used_keys здесь! Ключ должен помечаться как использованный только при исчерпании квоты
            
            logger.info(f"✅ API ключ успешно получен из TXT: {api_key[:10]}...{api_key[-10:]}")
            logger.info(f"📊 Доступно ключей: {len(filtered_keys)}/{len(keys_with_dates)}")
            
            return api_key
            
        except Exception as e:
            logger.error(f"Ошибка чтения TXT файла: {e}")
            return None
    
    def _get_api_key_from_csv(self) -> Optional[str]:
        """
        Получение API ключа из файла CSV с датами
        """
        try:
            logger.info(f"🔑 Получение API ключа из {self.file_path}")

            current_date = datetime.now().strftime('%d.%m.%Y')
            one_month_ago = datetime.now().date() - timedelta(days=31)
            logger.info(f"📅 Текущая дата: {current_date}, ищем ключи старше: {one_month_ago}")
            logger.info(f"🚫 Исключенные ключи: {len(self._used_keys)}")

            rows = []
            api_key = None

            with open(self.file_path, mode='r', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                fieldnames = reader.fieldnames

                if not fieldnames or 'API' not in fieldnames or 'Date' not in fieldnames:
                    logger.error(f"❌ Неверная структура файла API ключей. Найденные столбцы: {fieldnames}")
                    raise ConfigurationError("Файл API ключей должен содержать столбцы 'API' и 'Date'")

                logger.info(f"📋 Структура файла API ключей корректна. Столбцы: {fieldnames}")

                for row in reader:
                    rows.append(row)

                    if row.get('API') and not api_key and row.get('API') not in self._used_keys:
                        try:
                            row_date = datetime.strptime(row.get('Date', ''), '%d.%m.%Y').date()
                            if row_date <= one_month_ago:
                                api_key = row.get('API')
                                row['Date'] = current_date
                                logger.debug(f"Найден подходящий API ключ (старше месяца), дата: {row_date}")
                        except ValueError as e:
                            logger.warning(f"Некорректная дата в строке: {row.get('Date', '')}")
                            continue

                if not api_key:
                    logger.info("🔍 Ключи старше месяца не найдены, ищу любой доступный...")
                    for row in rows:
                        if row.get('API') and row.get('API') not in self._used_keys:
                            try:
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

            logger.info(f"📊 Обработано {len(rows)} строк из файла API ключей")

            if api_key:
                self._update_csv_file(fieldnames, rows)
                # НЕ добавляем в _used_keys здесь! Ключ должен помечаться как использованный только при исчерпании квоты
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
        Отметить ключ как исчерпанный и обновить дату использования
        """
        self._used_keys.add(api_key)
        logger.info(f"🚫 API ключ добавлен в черный список: {api_key[:10]}...{api_key[-10:]}")
        
        # Обновляем дату использования в зависимости от типа файла
        if self.file_type == "csv":
            self._update_csv_date(api_key)
        elif self.file_type == "txt":
            self._update_txt_date(api_key)
    
    def _update_txt_date(self, api_key: str):
        """
        Обновление даты использования ключа в TXT файле
        """
        try:
            current_date = datetime.now().strftime('%d.%m.%Y')
            lines = []
            key_found = False
            
            # Читаем существующие строки
            with open(self.file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                        
                    if ',' in line:
                        # Формат: api_key,date
                        parts = line.split(',', 1)
                        existing_key = parts[0].strip()
                        
                        if existing_key == api_key:
                            # Обновляем дату для найденного ключа
                            lines.append(f"{api_key},{current_date}")
                            key_found = True
                        else:
                            lines.append(line)
                    else:
                        # Старый формат: только api_key
                        if line == api_key:
                            # Обновляем формат и добавляем дату
                            lines.append(f"{api_key},{current_date}")
                            key_found = True
                        else:
                            lines.append(line)
            
            # Если ключ не найден в файле, добавляем его
            if not key_found:
                lines.append(f"{api_key},{current_date}")
            
            # Записываем обновленные строки обратно в файл
            with open(self.file_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')
                    
            logger.debug(f"Дата для ключа {api_key[:10]}... обновлена в TXT файле")
            
        except Exception as e:
            logger.error(f"Ошибка обновления даты в TXT файле: {e}")

    def _update_csv_date(self, api_key: str):
        """
        Обновление даты использования ключа в файле
        """
        try:
            rows = []
            with open(self.file_path, mode='r', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                fieldnames = reader.fieldnames
                current_date = datetime.now().strftime('%d.%m.%Y')
                
                for row in reader:
                    if row.get('API') == api_key:
                        row['Date'] = current_date
                    rows.append(row)
            
            self._update_csv_file(fieldnames, rows)
        except Exception as e:
            logger.error(f"Ошибка обновления даты в CSV: {e}")

    def _update_csv_file(self, fieldnames: List[str], rows: List[Dict[str, str]]):
        """Обновление файла API ключей"""
        temp_file_path = self.file_path.with_suffix('.tmp')

        try:
            with open(temp_file_path, mode='w', newline='', encoding='utf-8') as temp_file:
                writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            shutil.move(str(temp_file_path), str(self.file_path))
            logger.debug("Файл API ключей обновлен")

        except Exception as e:
            if temp_file_path.exists():
                temp_file_path.unlink()
            raise e

class ElevenLabsAPI:
    """Класс для работы с API ElevenLabs"""

    BASE_URL = "https://api.us.elevenlabs.io/v1"

    def __init__(self, api_key: str, proxy_config: ProxyConfig,
                 max_concurrent_requests: int = 1):
        self.api_key = api_key
        self.proxy_config = proxy_config
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._session: Optional[aiohttp.ClientSession] = None
        self._temp_voices: List[str] = []
        self._last_request_time = datetime.now()
        self._user_agent = random.choice(USER_AGENTS)  # Фиксированный на сессию

    async def __aenter__(self):
        """Асинхронный контекст менеджер"""
        connector = aiohttp.TCPConnector(ssl=False, limit=10, limit_per_host=5)
        timeout = aiohttp.ClientTimeout(total=300)

        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": self._user_agent}
        )
        if self.proxy_config.enabled:
            if not await self.check_proxy():
                logger.warning("Прокси недоступен, отключаем прокси")
                self.proxy_config.enabled = False
        if not await self.check_api_key():
            raise ConfigurationError("API ключ невалиден")
        await self.log_current_ip()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессии"""
        await self.cleanup_temp_voices(self.api_key)
        if self._session:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        """Получение сессии"""
        if not self._session:
            raise RuntimeError("API должен использоваться в контексте async with")
        return self._session

    async def log_current_ip(self) -> None:
        """Логирование текущего IP-адреса"""
        try:
            async with self.session.get(
                "https://api.ipify.org",
                proxy=self.proxy_config.proxy_url,
                proxy_auth=self.proxy_config.auth,
                timeout=10
            ) as response:
                if response.status == 200:
                    ip = await response.text()
                    logger.info(f"🌐 Текущий IP-адрес: {ip} (Прокси: {self.proxy_config.proxy_url or 'нет'})")
                else:
                    logger.warning(f"Не удалось получить IP-адрес: Статус {response.status}")
        except Exception as e:
            logger.error(f"Ошибка при получении IP-адреса: {e}")

    async def check_proxy(self) -> bool:
        """Проверка доступности текущего прокси"""
        try:
            async with self.session.get(
                "https://api.ipify.org",
                proxy=self.proxy_config.proxy_url,
                proxy_auth=self.proxy_config.auth,
                timeout=10
            ) as response:
                if response.status == 200:
                    logger.info(f"Прокси работает: {self.proxy_config.proxy_url}, IP: {await response.text()}")
                    return True
                else:
                    logger.warning(f"Прокси недоступен: {self.proxy_config.proxy_url}, Статус {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Ошибка проверки прокси {self.proxy_config.proxy_url}: {e}")
            return False

    async def check_api_key(self) -> bool:
        """Проверка валидности API ключа"""
        url = f"{self.BASE_URL}/user"
        headers = {"xi-api-key": self.api_key}
        try:
            async with self.session.get(url, headers=headers, timeout=10) as response:
                response_text = await response.text()
                logger.debug(f"Проверка API ключа: Статус={response.status}, Ответ={response_text}")
                if response.status == 200:
                    logger.info("API ключ валиден")
                    return True
                else:
                    logger.error(f"API ключ невалиден: Статус {response.status}, Ответ: {response_text}")
                    return False
        except Exception as e:
            logger.error(f"Ошибка проверки API ключа: {e}")
            return False

    async def add_voice(self, voice_id: str, public_owner_id: str, new_name: str,
                        is_temp: bool = False) -> bool:
        """
        Добавление голоса в библиотеку
        """
        if is_temp:
            await self.cleanup_temp_voices(self.api_key)

        # Валидация входных параметров
        if not voice_id or not public_owner_id:
            logger.error(f"Некорректные параметры: voice_id='{voice_id}', public_owner_id='{public_owner_id}'")
            raise APIError("voice_id или public_owner_id пусты")

        # Очистка имени
        cleaned_name = re.sub(r'[^a-zA-Z0-9_-]', '_', new_name.strip())
        if not cleaned_name or len(cleaned_name) < 3:
            cleaned_name = f"Voice_{datetime.now().strftime('%H%M%S%f')}"
        logger.info(f"Добавление голоса: original_name='{new_name}', cleaned_name='{cleaned_name}', voice_id='{voice_id}', public_owner_id='{public_owner_id}'")

        url = f"{self.BASE_URL}/voices/add/{public_owner_id}/{voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "User-Agent": self._user_agent
        }
        data = {"name": cleaned_name}

        for attempt in range(3):
            try:
                # Адаптивная задержка перед запросом
                await asyncio.sleep(0.1)  # Минимальная задержка

                logger.debug(f"Отправка POST запроса (попытка {attempt + 1}/3): URL={url}, headers={headers}, data={data}")

                async with self.session.post(
                        url,
                        json=data,
                        headers=headers,
                        proxy=self.proxy_config.proxy_url,
                        proxy_auth=self.proxy_config.auth,
                        timeout=120
                ) as response:
                    response_text = await response.text()
                    logger.debug(f"Ответ API: Статус={response.status}, Заголовки={dict(response.headers)}, Тело={response_text}")

                    if response.status == 200:
                        logger.info(f"Голос успешно добавлен: {cleaned_name}")
                        return True
                    else:
                        logger.error(f"Ошибка добавления голоса: Статус {response.status}, Ответ: {response_text}")

                        if "voice_limit_reached" in response_text:
                            logger.warning("Достигнут лимит голосов, выполняем очистку...")
                            await self.cleanup_temp_voices(self.api_key)
                            continue
                        elif "missing" in response_text and "name" in response_text:
                            logger.warning(f"Некорректное имя голоса: {cleaned_name}. Пробуем новое имя...")
                            cleaned_name = f"Voice_{datetime.now().strftime('%H%M%S%f')}_{attempt}"
                            data = {"name": cleaned_name}
                            continue
                        else:
                            raise APIError(f"Ошибка добавления голоса: Статус {response.status}, Ответ: {response_text}")

            except asyncio.TimeoutError:
                logger.error(f"Таймаут при добавлении голоса, попытка {attempt + 1}")
                if attempt == 2:
                    raise APIError("Таймаут при добавлении голоса")
                await asyncio.sleep(5 * (2 ** attempt))

            except aiohttp.ClientError as e:
                logger.error(f"Ошибка соединения при добавлении голоса: {e}")
                if attempt == 2:
                    raise APIError(f"Ошибка соединения: {e}")
                if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                    await self.log_current_ip()
                await asyncio.sleep(5 * (2 ** attempt))

        raise APIError("Не удалось добавить голос после нескольких попыток")

    async def get_voice_id(self, original_voice_id: str, public_owner_id: str) -> Optional[str]:
        """
        Получение ID голоса из библиотеки
        """
        url = f"{self.BASE_URL}/voices"
        headers = {
            "xi-api-key": self.api_key,
            "User-Agent": self._user_agent
        }

        try:
            # Адаптивная задержка
            await asyncio.sleep(0.1)  # Минимальная задержка

            logger.info(f"Получение ID голоса: original_voice_id='{original_voice_id}', public_owner_id='{public_owner_id}'")

            async with self.session.get(
                    url,
                    headers=headers,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:
                response_text = await response.text()
                logger.debug(f"Ответ API: Статус={response.status}, Заголовки={dict(response.headers)}, Тело={response_text}")

                if response.status == 200:
                    data = await response.json()

                    for voice in data.get("voices", []):
                        sharing = voice.get("sharing")
                        if sharing:
                            if (sharing.get("original_voice_id") == original_voice_id and
                                    sharing.get("public_owner_id") == public_owner_id):
                                voice_id = voice["voice_id"]
                                logger.info(f"Найден ID голоса: {voice_id}")
                                if voice_id not in self._temp_voices:
                                    self._temp_voices.append(voice_id)
                                return voice_id

                    logger.warning("ID голоса не найден в библиотеке")
                    return None
                else:
                    logger.error(f"Ошибка получения голосов: Статус {response.status}, Ответ: {response_text}")
                    raise APIError(f"Ошибка получения голосов: Статус {response.status}, Ответ: {response_text}")

        except asyncio.TimeoutError:
            logger.error("Таймаут при получении ID голоса")
            if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                await self.log_current_ip()
            raise APIError("Таймаут при получении ID голоса")
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения при получении ID голоса: {e}")
            if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                await self.log_current_ip()
            raise APIError(f"Ошибка соединения: {e}")

    async def delete_voice(self, voice_id: str, max_attempts: int = 3, api_key: str = None) -> bool:
        """
        Удаление голоса
        """
        # Используем актуальный API ключ, переданный как параметр, или fallback на self.api_key
        current_api_key = api_key or self.api_key
        
        url = f"{self.BASE_URL}/voices/{voice_id}"
        headers = {
            "xi-api-key": current_api_key,
            "User-Agent": self._user_agent
        }

        for attempt in range(max_attempts):
            try:
                # Адаптивная задержка
                await asyncio.sleep(0.1)  # Минимальная задержка

                logger.info(f"Удаление голоса {voice_id}, попытка {attempt + 1}/{max_attempts}")

                async with self.session.delete(
                        url,
                        headers=headers,
                        proxy=self.proxy_config.proxy_url,
                        proxy_auth=self.proxy_config.auth,
                        timeout=120
                ) as response:
                    response_text = await response.text()
                    logger.debug(f"Ответ API: Статус={response.status}, Заголовки={dict(response.headers)}, Тело={response_text}")

                    if response.status == 200:
                        logger.info(f"Голос {voice_id} успешно удален")
                        if voice_id in self._temp_voices:
                            self._temp_voices.remove(voice_id)
                        return True
                    else:
                        logger.error(f"Ошибка удаления голоса: Статус {response.status}, Ответ: {response_text}")
                        if attempt == max_attempts - 1:
                            raise APIError(f"Ошибка удаления голоса: Статус {response.status}, Ответ: {response_text}")

            except asyncio.TimeoutError:
                logger.error(f"Таймаут при удалении голоса, попытка {attempt + 1}")
                if attempt == max_attempts - 1:
                    raise APIError("Таймаут при удалении голоса")
                if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                    await self.log_current_ip()
                await asyncio.sleep(5 * (2 ** attempt))

            except aiohttp.ClientError as e:
                logger.error(f"Ошибка соединения при удалении голоса: {e}")
                if attempt == max_attempts - 1:
                    raise APIError(f"Ошибка соединения: {e}")
                if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                    await self.log_current_ip()
                await asyncio.sleep(5 * (2 ** attempt))

        return False

    async def cleanup_temp_voices(self, api_key: str = None) -> bool:
        """
        Очистка всех временных голосов
        """
        if not self._temp_voices:
            return True

        logger.info(f"Очистка {len(self._temp_voices)} временных голосов...")

        voices_to_delete = self._temp_voices.copy()

        # Используем актуальный API ключ
        current_api_key = api_key or self.api_key
        
        for voice_id in voices_to_delete:
            try:
                await self.delete_voice(voice_id, api_key=current_api_key)
            except APIError as e:
                logger.warning(f"Не удалось удалить временный голос {voice_id}: {e}")
                continue

        self._temp_voices.clear()
        logger.info("Очистка временных голосов завершена")
        return True

    async def cleanup_voices(self, api_key: str = None) -> bool:
        """
        Очистка пользовательских голосов (НЕ premade) - как в VoicePro.py
        """
        try:
            # Используем актуальный API ключ, переданный как параметр, или fallback на self.api_key
            current_api_key = api_key or self.api_key
            
            url = f"{self.BASE_URL}/voices"
            headers = {
                "xi-api-key": current_api_key,
                "User-Agent": self._user_agent
            }
            async with self.session.get(
                    url,
                    headers=headers,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(f"Ошибка получения списка голосов: {response.status}")
                    return False

                data = await response.json()
                all_voices = data.get("voices", [])
                
                # Подсчитываем и удаляем все голоса категории НЕ premade
                custom_voices = []
                premade_voices = []
                
                for voice in all_voices:
                    voice_id = voice["voice_id"]
                    voice_name = voice.get("name", "Unknown")
                    voice_category = voice.get("category", "custom")
                    
                    if voice_category == "premade":
                        premade_voices.append(f"{voice_id} ({voice_name})")
                    else:
                        custom_voices.append(voice_id)
                        logger.info(f"🗑️ Удаляем: {voice_id} ({voice_name})")
                
                if len(custom_voices) > 0:
                    logger.info(f"🧹 Найдено {len(custom_voices)} пользовательских голосов к удалению")
                else:
                    logger.info("✅ Пользовательских голосов не найдено")
                
                # Удаляем все пользовательские голоса
                deleted_count = 0
                for voice_id in custom_voices:
                    try:
                        await self.delete_voice(voice_id, api_key=current_api_key)
                        deleted_count += 1
                        logger.debug(f"✅ Удален: {voice_id}")
                    except APIError as e:
                        logger.warning(f"❌ Ошибка удаления {voice_id}: {e}")

                logger.info(f"🎯 Очистка голосов завершена: удалено {deleted_count} из {len(custom_voices)}")
                return True

        except Exception as e:
            logger.error(f"❌ Ошибка очистки голосов: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    async def cleanup_all_custom_voices(self, api_key: str = None) -> bool:
        """
        Агрессивная очистка - удаляет ВСЕ пользовательские голоса без исключений
        """
        try:
            # Используем актуальный API ключ, переданный как параметр, или fallback на self.api_key
            current_api_key = api_key or self.api_key
            logger.warning("🔥 АГРЕССИВНАЯ ОЧИСТКА: Удаляем ВСЕ пользовательские голоса")
            logger.info(f"🔑 Используем API ключ: {current_api_key[:8]}...{current_api_key[-4:] if current_api_key else 'None'}")

            url = f"{self.BASE_URL}/voices"
            headers = {
                "xi-api-key": current_api_key,
                "User-Agent": self._user_agent
            }

            # Адаптивная задержка
            await asyncio.sleep(0.1)

            async with self.session.get(
                    url,
                    headers=headers,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=120
            ) as response:
                if response.status != 200:
                    logger.error(f"Ошибка получения списка голосов: {response.status}")
                    return False

                data = await response.json()
                voices_to_delete = []

                for voice in data.get("voices", []):
                    voice_id = voice["voice_id"]
                    voice_category = voice.get("category", "custom")
                    voice_name = voice.get("name", "Unknown")
                    
                    # Удаляем ТОЛЬКО не-premade голоса
                    if voice_category != "premade":
                        logger.info(f"🗑️  Удаляем пользовательский голос: {voice_id} ({voice_name})")
                        voices_to_delete.append(voice_id)
                    else:
                        logger.info(f"⏭️  Сохраняем premade голос: {voice_id} ({voice_name})")

                logger.warning(f"🔥 К удалению: {len(voices_to_delete)} пользовательских голосов")

                for voice_id in voices_to_delete:
                    try:
                        await self.delete_voice(voice_id, api_key=current_api_key)  # Передаем актуальный API ключ
                    except APIError as e:
                        logger.warning(f"Не удалось удалить голос {voice_id}: {e}")
                        continue

        except Exception as e:
            logger.error(f"Ошибка агрессивной очистки голосов: {e}")
            return False

        logger.warning("🔥 Агрессивная очистка голосов завершена")
        return True

    async def text_to_speech(self, text: str, voice_id: str, output_path: str,
                             voice_config: VoiceConfig, row_index: int) -> bool:
        """
        Преобразование текста в речь с улучшенной обработкой ошибок и ротацией User-Agent
        """
        url = f"{self.BASE_URL}/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": self._user_agent
        }

        json_data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "similarity_boost": voice_config.similarity,
                "stability": voice_config.stability,
                "style_exaggeration": 0.0  # Добавить этот параметр
            },
            "generation_config": {
                "speed": voice_config.voice_speed
            }
        }

        if voice_config.voice_style:
            json_data["style"] = voice_config.voice_style

        ban_retries = 0
        backoff_base = 5
        adaptive_delay = voice_config.ban_retry_delay

        async with self.semaphore:
            for attempt in range(voice_config.max_retries):
                try:
                    # Простая задержка как в VoicePro
                    await asyncio.sleep(0.1)  # Минимальная задержка

                    logger.debug(f"Генерация аудио для строки {row_index + 1}, попытка {attempt + 1}/{voice_config.max_retries}, User-Agent: {headers['User-Agent']}, URL: {url}, Data: {json_data}, Прокси: {self.proxy_config.proxy_url or 'нет'}")

                    async with self.session.post(
                            url,
                            headers=headers,
                            json=json_data,
                            proxy=self.proxy_config.proxy_url,
                            proxy_auth=self.proxy_config.auth,
                            timeout=180  # Увеличен таймаут
                    ) as response:
                        logger.debug(f"Ответ API: Статус={response.status}, Заголовки={dict(response.headers)}")

                        if response.status == 200:
                            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                            with open(output_path, "wb") as audio_file:
                                async for chunk in response.content.iter_chunked(8192):
                                    audio_file.write(chunk)

                            logger.debug(f"✅ Сохранено: {Path(output_path).name}")
                            return True

                        else:
                            # Пытаемся прочитать ответ как текст только для ошибочных статусов
                            try:
                                response_text = await response.text()
                            except UnicodeDecodeError:
                                # Если не удается декодировать как текст, читаем как бинарные данные
                                response_bytes = await response.read()
                                response_text = f"<Бинарные данные: {len(response_bytes)} байт>"
                            logger.error(f"Ошибка API для строки {row_index + 1}: Статус {response.status}, Ответ: {response_text}")

                            try:
                                detail = await response.json() if response.content_type == 'application/json' else {}
                                detail = detail.get("detail", {})
                            except ValueError:
                                detail = {}

                            # Простая обработка квоты
                            if detail.get("status") == "quota_exceeded":
                                logger.error("Превышена квота")
                                raise QuotaExceededError("Превышена квота API")

                            # Простая обработка unusual activity
                            if detail.get("status") == "detected_unusual_activity":
                                logger.warning("Detected unusual activity")
                                if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                                    await self.log_current_ip()
                                await asyncio.sleep(5)
                                continue

                            logger.error(f"Ошибка API: {response.status}")
                            return False

                except asyncio.TimeoutError:
                    logger.warning("Таймаут запроса")
                    await asyncio.sleep(5)
                    continue

                except Exception as e:
                    logger.error(f"Ошибка соединения: {e}")
                    await asyncio.sleep(5)
                    continue

        return False

    def _needs_backoff(self, detail: dict, http_status: int) -> bool:
        """
        Проверка необходимости backoff по образцу VoicePro.py
        """
        status = str(detail.get("status", "")).lower()
        msg = str(detail.get("message", "")).lower()
        
        # Исключаем ошибку лимита голосов из backoff логики
        if "maximum amount of custom voices" in msg:
            return False
        
        triggers = ("subscription", "buy", "payment", "vpn", "proxy",
                    "detected_unusual_activity")
        return http_status in (402, 429) or any(t in status + " " + msg for t in triggers)

    async def simple_text_to_speech(self, api_key: str, text: str, output_path: str, voice_id: str,
                                    similarity: float = 0.75, stability: float = 0.50,
                                    style_exaggeration: float = 0.0, speed: float = 1.0) -> bool:
        """Упрощенный метод генерации речи по образцу VoicePro.py"""
        
        # ОТКЛЮЧЕНО: Принудительная очистка перед каждым запросом вызывает зависание процесса
        # Используем только один раз cleanup_voices в начале _process_rows
        # try:
        #     logger.warning("🔥 ПРИНУДИТЕЛЬНАЯ ОЧИСТКА ВСЕХ ГОЛОСОВ перед запросом")
        #     logger.info(f"🔑 Передаем актуальный API ключ: {api_key[:8]}...{api_key[-4:]}")
        #     await self.cleanup_all_custom_voices(api_key)  # Передаем актуальный API ключ
        #     await asyncio.sleep(1)  # Пауза для применения изменений
        # except Exception as e:
        #     logger.error(f"❌ Не удалось очистить голоса: {e}")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "similarity_boost": similarity,
                "stability": stability,
                "style_exaggeration": style_exaggeration
            },
            "generation_config": {
                "speed": speed
            }
        }

        while True:
            try:
                async with self.session.post(
                    url,
                    json=payload,
                    headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=30
                ) as response:

                    if response.status == 200:
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as audio_file:
                            async for chunk in response.content.iter_chunked(8192):
                                audio_file.write(chunk)
                        logger.debug(f"✅ Сохранено: {Path(output_path).name}")
                        return True

                    try:
                        response_text = await response.text()
                        if response.content_type == 'application/json':
                            detail = json.loads(response_text).get("detail", {})
                        else:
                            detail = {}
                    except (ValueError, json.JSONDecodeError):
                        detail = {}

                    if detail.get("status") == "quota_exceeded":
                        logger.error("Превышена квота")
                        return "quota_exceeded"

                    if detail.get("status") == "detected_unusual_activity":
                        logger.warning("Detected unusual activity")
                        if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                            await self.log_current_ip()
                        await asyncio.sleep(5)
                        continue

                    # Специальная обработка лимита голосов
                    if response.status == 400 and "maximum amount of custom voices" in response_text:
                        logger.error("🔴 ЛИМИТ ГОЛОСОВ: Превышен лимит пользовательских голосов в ElevenLabs")
                        logger.error(f"📊 Voice ID: {voice_id}")
                        logger.error("💡 Решение: Либо очистите старые голоса, либо обновите план ElevenLabs")
                        return "voice_limit_exceeded"  # Возвращаем специальный код

                    # Добавляем логику _needs_backoff из VoicePro.py
                    if self._needs_backoff(detail, response.status):
                        msg = detail.get("message", response_text)[:120]
                        logger.warning(f"API backoff: {response.status}: {msg} → proxy rotate")
                        if self.proxy_config.enabled and self.proxy_config.rotate_proxy():
                            await self.log_current_ip()
                        await asyncio.sleep(5)
                        continue

                    # Подробное логирование ошибок API для отладки
                    logger.error(f"Ошибка API: {response.status}")
                    logger.error(f"Voice ID: {voice_id}")
                    logger.error(f"Текст (первые 100 символов): {text[:100]}...")
                    logger.error(f"Ответ API: {response_text}")
                    
                    # Специальная обработка для voice_id проблем
                    if response.status == 400 and "voice" in response_text.lower():
                        logger.error(f"🎤 Возможно проблема с голосом {voice_id} - проверьте что голос существует")
                    
                    return False

            except asyncio.TimeoutError:
                logger.warning("Таймаут запроса")
                await asyncio.sleep(5)
                continue
            except Exception as e:
                logger.error(f"Ошибка соединения: {e}")
                await asyncio.sleep(5)
                continue

    async def generate_preview(self, text: str, voice_id: str, public_owner_id: str,
                              voice_config: VoiceConfig) -> Optional[bytes]:
        """
        Генерация предпросмотра голоса
        """
        if voice_config.skip_voice_management:
            logger.info("Управление голосами отключено, пропускаем добавление голоса")
            library_voice_id = voice_id
        else:
            temp_voice_name = f"Preview_{voice_id}_{datetime.now().strftime('%H%M%S%f')}"
            cleaned_name = re.sub(r'[^a-zA-Z0-9_-]', '_', temp_voice_name.strip())
            if not cleaned_name or len(cleaned_name) < 3:
                cleaned_name = f"PreviewVoice_{datetime.now().strftime('%H%M%S%f')}"
            logger.info(f"Генерация предпросмотра: original_name='{temp_voice_name}', cleaned_name='{cleaned_name}'")

            success = await self.add_voice(voice_id, public_owner_id, cleaned_name, is_temp=True)
            if not success:
                logger.error("Не удалось добавить голос для предпросмотра")
                return None

            library_voice_id = await self.get_voice_id(voice_id, public_owner_id)
            if not library_voice_id:
                logger.error("Не удалось получить ID голоса для предпросмотра")
                return None

        try:
            url = f"{self.BASE_URL}/text-to-speech/{library_voice_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": self._user_agent
            }

            json_data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "similarity_boost": voice_config.similarity,
                    "stability": voice_config.stability,
                    "style_exaggeration": 0.0  # Добавить этот параметр
                },
                "generation_config": {
                    "speed": voice_config.voice_speed
                }
            }

            if voice_config.voice_style:
                json_data["style"] = voice_config.voice_style

            # Адаптивная задержка
            await asyncio.sleep(0.1)  # Минимальная задержка

            logger.debug(f"Отправка POST запроса для предпросмотра: URL={url}, headers={headers}, data={json_data}")

            async with self.session.post(
                    url,
                    headers=headers,
                    json=json_data,
                    proxy=self.proxy_config.proxy_url,
                    proxy_auth=self.proxy_config.auth,
                    timeout=180
            ) as response:
                response_text = await response.text()
                logger.debug(f"Ответ API: Статус={response.status}, Заголовки={dict(response.headers)}, Тело={response_text}")

                if response.status == 200:
                    audio_data = await response.read()
                    logger.info("Предпросмотр голоса успешно сгенерирован")
                    return audio_data
                else:
                    logger.error(f"Ошибка генерации предпросмотра: Статус {response.status}, Ответ: {response_text}")
                    if "voice_limit_reached" in response_text:
                        raise VoiceLimitError(f"Достигнут лимит голосов: {response_text}")
                    else:
                        raise APIError(f"Ошибка генерации предпросмотра: Статус {response.status}, Ответ: {response_text}")

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
        """
        try:
            logger.info(f"Загрузка Excel файла: {self.excel_path}")

            excel_file = pd.ExcelFile(self.excel_path)
            sheet_names = excel_file.sheet_names

            logger.info(f"Доступные листы: {sheet_names}")

            if language not in sheet_names:
                raise ConfigurationError(f"Лист '{language}' не найден в Excel файле")

            df_full = pd.read_excel(excel_file, sheet_name=language, header=None)

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
        Получение списка уже существующих файлов (исправленная версия)
        """
        try:
            output_dir = Path(output_directory)
            if not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Выходная директория не существовала, создана")
                return []

            logger.error(f"[ДИАГНОСТИКА] Сканирование директории: {output_dir}")
            existing_files = []
            
            # Более безопасный способ - используем os.listdir вместо glob
            import os
            try:
                for filename in os.listdir(output_dir):
                    if filename.endswith('.mp3'):
                        try:
                            file_number = int(filename[:-4])  # убираем .mp3
                            existing_files.append(file_number)
                        except ValueError:
                            continue
            except OSError as e:
                logger.warning(f"Ошибка чтения директории: {e}")
                return []

            existing_files.sort()
            logger.error(f"[ДИАГНОСТИКА] Найдено существующих файлов: {len(existing_files)}")
            
            return existing_files
            
        except Exception as e:
            logger.error(f"Критическая ошибка в get_existing_files: {e}")
            return []  # Безопасный возврат пустого списка

class VoiceProcessor:
    """Основной класс для обработки озвучки"""

    def __init__(self, channel_name: str, thread=None):
        self.channel_name = channel_name
        self.thread = thread
        self.stats = ProcessingStats()

        logger.info(f"🔧 Инициализация VoiceProcessor для канала: {channel_name}")

        self._load_configuration()

    def _load_configuration(self):
        """Загрузка конфигурации канала"""
        try:
            logger.info(f"📋 Загрузка конфигурации для канала: {self.channel_name}")
            # Закомментировано: очистка имени канала ломает поддержку кириллицы
            # cleaned_channel_name = re.sub(r'[^a-zA-Z0-9_-]', '_', self.channel_name.strip())
            # if cleaned_channel_name != self.channel_name:
            #     logger.warning(f"Имя канала очищено: '{self.channel_name}' -> '{cleaned_channel_name}'")
            #     self.channel_name = cleaned_channel_name

            config_manager = ConfigManager()
            channel_config = config_manager.get_channel_config(self.channel_name)
            if not channel_config:
                logger.error(f"❌ Конфигурация канала '{self.channel_name}' не найдена")
                raise ConfigurationError(f"Конфигурация канала '{self.channel_name}' не найдена")

            logger.info(f"✅ Базовая конфигурация канала загружена: {len(channel_config)} параметров")

            proxy_config_raw = config_manager.get_proxy_config()
            proxies = []
            if proxy_config_raw.get("use_proxy", True):
                # Поддержка как proxy_list, так и одиночного proxy
                proxy_list = proxy_config_raw.get("proxy_list", [])
                
                # Если proxy_list пуст, проверяем одиночный proxy
                if not proxy_list and proxy_config_raw.get("proxy"):
                    proxy_list = [proxy_config_raw.get("proxy")]
                
                if isinstance(proxy_list, str):
                    proxy_list = proxy_list.split(",")
                
                for proxy in proxy_list:
                    if isinstance(proxy, str):
                        proxies.append({"url": proxy.strip(), "login": proxy_config_raw.get("proxy_login", ""),
                                       "password": proxy_config_raw.get("proxy_password", "")})
                    else:
                        proxies.append(proxy)

            # Получение настроек многопоточности из конфигурации
            max_concurrent_requests = int(channel_config.get("max_concurrent_requests", 1))
            parallel_threads = int(channel_config.get("parallel_threads", 2))
            
            logger.info(f"📊 Настройки многопоточности:")
            logger.info(f"   Максимальные параллельные запросы: {max_concurrent_requests}")
            logger.info(f"   Количество потоков обработки: {parallel_threads}")
            
            self.voice_config = VoiceConfig(
                language=channel_config.get("default_lang", "RU").upper(),
                stability=float(channel_config.get("default_stability", 1.0)),
                similarity=float(channel_config.get("default_similarity", 1.0)),
                voice_speed=float(channel_config.get("default_voice_speed", 1.0)),
                voice_style=channel_config.get("default_voice_style"),
                max_retries=int(channel_config.get("max_retries", 10)),
                ban_retry_delay=int(channel_config.get("ban_retry_delay", 300)),
                standard_voice_id=channel_config.get("standard_voice_id", ""),
                use_library_voice=bool(channel_config.get("use_library_voice", True)),
                original_voice_id=channel_config.get("original_voice_id", ""),
                public_owner_id=channel_config.get("public_owner_id", ""),
                skip_voice_management=bool(channel_config.get("skip_voice_management", False)),
                max_concurrent_requests=max_concurrent_requests,  # Используем настройку из GUI
                parallel_threads=parallel_threads  # Используем настройку из GUI
            )

            self.proxy_config = ProxyConfig(
                enabled=bool(proxy_config_raw.get("use_proxy", True)),
                proxies=proxies
            )

            self.csv_file_path = channel_config["csv_file_path"]
            self.output_directory = channel_config["output_directory"]
            self.excel_file_path = channel_config["global_xlsx_file_path"]
            self.channel_column = channel_config["channel_column"]

            logger.info(f"📁 Конфигурация путей:")
            logger.info(f"   Файл API ключей: {self.csv_file_path}")
            logger.info(f"   Выходная папка: {self.output_directory}")
            logger.info(f"   Excel файл: {self.excel_file_path}")
            logger.info(f"   Столбец канала: {self.channel_column}")
            logger.info(f"   Прокси: {len(self.proxy_config.proxies)}")

            self._validate_paths()

            logger.info(f"🎙️ Конфигурация голоса:")
            logger.info(f"   Голос ID: {self.voice_config.standard_voice_id}")
            logger.info(f"   Схожесть: {self.voice_config.similarity}")
            logger.info(f"   Стабильность: {self.voice_config.stability}")
            logger.info(f"   Скорость: {self.voice_config.voice_speed}")

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
            logger.error("❌ Путь к файлу API ключей не указан")
            raise ConfigurationError("Путь к файлу API ключей не указан")

        csv_path = Path(self.csv_file_path)
        if not csv_path.exists():
            logger.error(f"❌ Файл API ключей не найден: {self.csv_file_path}")
            raise FileNotFoundError(f"Файл API ключей не найден: {self.csv_file_path}")
        else:
            logger.info(f"✅ Файл API ключей найден: {self.csv_file_path}")

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
            logger.info(f"   🚫 Управление голосами: {'отключено' if self.voice_config.skip_voice_management else 'включено'}")

            logger.info("🔧 Инициализация компонентов...")
            api_key_manager = APIKeyManager(self.csv_file_path)
            logger.info("✅ APIKeyManager инициализирован")

            excel_processor = ExcelProcessor(self.excel_file_path, self.channel_column)
            logger.info("✅ ExcelProcessor инициализирован")

            logger.info("📄 Загрузка данных из Excel...")
            df_full, df_column = excel_processor.load_data(self.voice_config.language)
            self.stats.total_rows = len(df_column)
            logger.info(f"✅ Данные загружены: {self.stats.total_rows} строк")

            # ПРОСТАЯ реализация без проблемного get_existing_files
            logger.info("📁 Проверка существующих файлов...")
            existing_files = []
            try:
                import os
                output_dir = self.output_directory
                if os.path.exists(output_dir):
                    files = [f for f in os.listdir(output_dir) if f.endswith('.mp3')]
                    for f in files:
                        try:
                            num = int(f[:-4])
                            existing_files.append(num)
                        except ValueError:
                            pass
                    existing_files.sort()
                logger.info(f"📊 Найдено существующих файлов: {len(existing_files)}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка проверки файлов: {e}")
                existing_files = []

            logger.info("🔄 Запуск основного цикла обработки...")
            current_api_key = None

            while True:
                self._check_interruption()

                if current_api_key is None:
                    logger.info("🔑 Получение API ключа...")
                    current_api_key = api_key_manager.get_api_key()
                    if not current_api_key:
                        logger.error("❌ Не удалось получить API ключ - все ключи исчерпаны")
                        raise ConfigurationError("Не удалось получить API ключ - все ключи исчерпаны")
                    else:
                        logger.info(f"✅ API ключ получен: {current_api_key[:10]}...{current_api_key[-10:]}")

                try:
                    logger.info("🌐 Создание ElevenLabsAPI клиента...")
                    async with ElevenLabsAPI(current_api_key, self.proxy_config, self.voice_config.max_concurrent_requests) as api:
                        logger.info("✅ ElevenLabsAPI клиент создан")

                        # ПРИНУДИТЕЛЬНАЯ ОЧИСТКА голосов перед началом обработки
                        logger.info("🧹 Принудительная очистка всех пользовательских голосов перед началом обработки...")
                        try:
                            await api.cleanup_all_custom_voices(current_api_key)
                            logger.info("✅ Принудительная очистка голосов завершена")
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось выполнить принудительную очистку голосов: {e}")

                        logger.info("🔄 Запуск обработки строк...")
                        result = await self._process_rows(api, df_full, df_column, existing_files)

                        if result == "completed":
                            logger.info("🎉 Все строки успешно обработаны")
                            logger.info("🔍 Запуск валидации файлов...")
                            await self._validate_and_regenerate_files(api, df_full, df_column)
                            break
                        elif result == "quota_exceeded":
                            logger.warning("⚠️ Превышена квота или лимит, помечаем ключ как исчерпанный")
                            logger.info(f"🔒 Помечаем ключ как исчерпанный: {current_api_key[:8]}...{current_api_key[-4:]}")
                            api_key_manager.mark_key_as_exhausted(current_api_key)
                            current_api_key = None
                            self.stats.quota_exceeded_count += 1
                            logger.info("🔄 Переключаемся на следующий API ключ...")
                            # ВАЖНО: Принудительно выходим из контекста текущего API клиента
                            break
                        elif result == "voice_cleanup_retry":
                            logger.info("🔄 Голоса очищены, повторяем обработку строк...")
                            # Продолжаем с тем же API ключом
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

    async def _process_single_row(self, api: ElevenLabsAPI, df_full: pd.DataFrame, 
                                  df_column: pd.DataFrame, index: int, row: pd.Series, 
                                  existing_files: List[int], voice_id: str, 
                                  processing_semaphore: Semaphore, api_key: str) -> Tuple[str, int]:
        """
        Обработка одной строки (асинхронно)
        Возвращает: (результат, file_number)
        """
        async with processing_semaphore:  # Ограничиваем количество параллельных задач
            try:
                self._check_interruption()
                
                # Получение маркера видео
                video_marker = ""
                if index < len(df_full):
                    try:
                        cell_a = str(df_full.iloc[index, 0]).strip() if df_full.shape[1] > 0 else ""
                        cell_a = cell_a.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    except Exception:
                        cell_a = ""
                    if cell_a.startswith("ВИДЕО "):
                        video_marker = cell_a

                # Получение текста
                try:
                    text = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                    if not text or text.lower() == 'nan':
                        return "skipped_empty", index + 1
                except Exception:
                    return "skipped_error", index + 1

                file_number = index + 1
                if file_number in existing_files:
                    return "skipped_exists", file_number

                file_name = f"{str(file_number).zfill(3)}.mp3"
                output_path = Path(self.output_directory) / file_name

                # Логирование
                if video_marker:
                    logger.info(f"🎙️ Обработка строки {file_number} с маркером '{video_marker}' -> {file_name}")
                else:
                    logger.debug(f"🎙️ Обработка строки {file_number} -> {file_name}")

                # API вызов
                success = await api.simple_text_to_speech(
                    api.api_key, text, str(output_path), voice_id,
                    self.voice_config.similarity, self.voice_config.stability,
                    0.0, self.voice_config.voice_speed
                )

                # Обработка результата
                if success == "quota_exceeded":
                    return "quota_exceeded", file_number
                elif success == "voice_limit_exceeded":
                    return "voice_limit_exceeded", file_number
                elif success:
                    # Не изменяем existing_files здесь - это будет сделано в основном потоке
                    return "success", file_number
                else:
                    return "failed", file_number
                    
            except Exception as e:
                logger.error(f"Неожиданная ошибка для строки {index + 1}: {e}")
                return "error", index + 1

    async def _get_first_premade_voice(self, api: ElevenLabsAPI) -> str:
        """
        Получить первый реальный premade голос из ElevenLabs API
        """
        try:
            logger.info("🔍 Поиск premade голоса...")
            
            url = f"{api.BASE_URL}/voices"
            headers = {
                "xi-api-key": api.api_key,
                "User-Agent": api._user_agent
            }

            async with api.session.get(
                    url,
                    headers=headers,
                    proxy=api.proxy_config.proxy_url,
                    proxy_auth=api.proxy_config.auth,
                    timeout=120
            ) as response:
                if response.status != 200:
                    logger.error(f"Ошибка получения списка голосов: {response.status}")
                    logger.error("⚠️ Fallback на голос Rachel")
                    return "21m00Tcm4TlvDq8ikWAM"  # Rachel - стабильный голос

                data = await response.json()
                all_voices = data.get("voices", [])
                
                # Ищем первый premade голос
                for voice in all_voices:
                    voice_id = voice["voice_id"]
                    voice_name = voice.get("name", "Unknown")
                    voice_category = voice.get("category", "custom")
                    
                    if voice_category == "premade":
                        logger.info(f"🎯 Выбран premade голос: {voice_name} ({voice_id})")
                        return voice_id
                
                logger.error("❌ НЕ НАЙДЕНО премиум голосов! Используем голос Rachel")
                return "21m00Tcm4TlvDq8ikWAM"  # Rachel
                
        except Exception as e:
            logger.error(f"Ошибка получения premade голоса: {e}")
            logger.error("⚠️ Fallback на голос Rachel")
            return "21m00Tcm4TlvDq8ikWAM"  # Rachel

    async def _process_rows(self, api: ElevenLabsAPI, df_full: pd.DataFrame,
                            df_column: pd.DataFrame, existing_files: List[int]) -> str:
        """
        Обработка строк Excel файла
        """
        try:
            # В начале метода
            processing_start_time = datetime.now()
            max_processing_time = timedelta(minutes=30)  # Максимум 30 минут
            
            # Используем настроенный голос из конфигурации
            voice_id = self.voice_config.standard_voice_id or self.voice_config.original_voice_id
            
            if voice_id:
                logger.info(f"✅ Используем настроенный голос из конфигурации: {voice_id}")
            else:
                # Если голос не настроен, получаем первый доступный premade голос
                logger.warning("⚠️ Голос не настроен в конфигурации, используем premade голос")
                voice_id = await self._get_first_premade_voice(api)
            
            # Очищаем голоса один раз перед запуском
            if not self.voice_config.skip_voice_management:
                logger.info("🧹 Очистка пользовательских голосов...")
                await api.cleanup_voices(api.api_key)

            # Получаем настройки многопоточности
            max_concurrent_tasks = self.voice_config.parallel_threads  # Используем parallel_threads из GUI
            logger.info(f"🔧 Максимум параллельных задач: {max_concurrent_tasks}")
            
            # Создаем semaphore для ограничения количества параллельных задач
            processing_semaphore = Semaphore(max_concurrent_tasks)

            try:
                # Подготавливаем все задачи для параллельной обработки
                tasks = []
                for index, row in df_column.iterrows():
                    # Создаем корутину для каждой строки
                    task = self._process_single_row(
                        api, df_full, df_column, index, row, 
                        existing_files, voice_id, processing_semaphore, api.api_key
                    )
                    tasks.append(task)

                logger.info(f"🚀 Параллельная обработка: {len(tasks)} строк, {max_concurrent_tasks} потоков")
                
                # Выполняем все задачи параллельно
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Обрабатываем результаты
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Исключение при обработке строки {i + 1}: {result}")
                        self.stats.failed_rows += 1
                        continue
                        
                    status, file_number = result
                    
                    if status == "success":
                        self.stats.processed_rows += 1
                        existing_files.append(file_number)  # Добавляем в список обработанных
                        logger.debug(f"✅ Строка {file_number} успешно обработана")
                    elif status == "quota_exceeded":
                        logger.warning(f"⚠️ Превышена квота на строке {file_number}")
                        return "quota_exceeded"
                    elif status == "voice_limit_exceeded":
                        logger.error(f"🔴 Лимит голосов достигнут на строке {file_number}")
                        logger.error("💡 Требуется агрессивная очистка ВСЕХ пользовательских голосов...")
                        # Здесь корректный контекст для вызова cleanup_voices
                        try:
                            # Агрессивная очистка - удаляем все пользовательские голоса
                            await api.cleanup_all_custom_voices(api_key)  # Передаем актуальный API ключ
                            logger.info("✅ Агрессивная очистка голосов выполнена")
                            logger.info(f"🔄 Повторная обработка строки {file_number} после очистки голосов...")
                            # ВАЖНО: Не увеличиваем failed_rows, а возвращаемся к обработке той же партии строк
                            return "voice_cleanup_retry"
                        except Exception as e:
                            logger.error(f"❌ Не удалось очистить голоса: {e}")
                            self.stats.failed_rows += 1
                    elif status == "failed":
                        self.stats.failed_rows += 1
                        logger.error(f"❌ Не удалось сгенерировать аудио для строки {file_number}")
                    elif status.startswith("skipped"):
                        self.stats.skipped_rows += 1
                        if status == "skipped_exists":
                            logger.debug(f"⏭️ Файл для строки {file_number} уже существует")
                    elif status == "error":
                        self.stats.failed_rows += 1
                        logger.error(f"❌ Ошибка обработки строки {file_number}")

                logger.info(f"📊 Параллельная обработка завершена:")
                logger.info(f"   ✅ Успешно: {self.stats.processed_rows}")
                logger.info(f"   ⏭️ Пропущено: {self.stats.skipped_rows}")  
                logger.info(f"   ❌ Ошибок: {self.stats.failed_rows}")

                return "completed"

            except Exception as e:
                logger.error(f"Ошибка в основном цикле обработки: {e}")
                return "error"

        except Exception as e:
            logger.error(f"Ошибка в процессе обработки строк: {e}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            logger.error(f"Полная трассировка:", exc_info=True)
            return "error"

    async def _setup_library_voice(self, api: ElevenLabsAPI) -> Optional[str]:
        """
        Настройка голоса из библиотеки
        """
        try:
            new_voice_name = f"Library_{self.channel_name}_{datetime.now().strftime('%H%M%S')}"

            await api.add_voice(
                self.voice_config.original_voice_id,
                self.voice_config.public_owner_id,
                new_voice_name
            )

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

        validation_start_time = asyncio.get_event_loop().time()
        max_validation_time = 600

        config_manager = ConfigManager()
        channel_config = config_manager.get_channel_config(self.channel_name)
        audio_folder = Path(channel_config['audio_folder'])
        corrupted_files = []

        for index, row in df_column.iterrows():
            current_time = asyncio.get_event_loop().time()
            if current_time - validation_start_time > max_validation_time:
                logger.warning("Таймаут валидации файлов - завершаем досрочно")
                break

            file_path = audio_folder / f"{index + 1}.mp3"

            if not file_path.exists():
                continue

            file_size = file_path.stat().st_size
            if file_size < 200:
                logger.warning(f"Подозрительно маленький файл: {file_path} ({file_size} байт)")
                corrupted_files.append((index + 1, file_path, "маленький размер"))
                continue

            try:
                duration = get_media_duration(str(file_path))

                if duration is None or duration <= 0:
                    logger.warning(f"Не удалось получить длительность файла: {file_path}")
                    corrupted_files.append((index + 1, file_path, "неопределенная длительность"))
                elif duration < 0.5:
                    logger.warning(f"Слишком короткое аудио: {file_path} ({duration:.2f}с)")
                    corrupted_files.append((index + 1, file_path, f"слишком короткая длительность: {duration:.2f}с"))
                else:
                    logger.debug(f"Файл {file_path} прошел валидацию: {duration:.2f}с")

            except subprocess.TimeoutExpired:
                logger.warning(f"Таймаут при проверке {file_path} - пропускаем")
            except FileNotFoundError:
                logger.warning(f"ffprobe не найден - пропускаем валидацию {file_path}")
            except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
                logger.debug(f"Не удалось проверить {file_path} через ffprobe: {e}")

        if not corrupted_files:
            logger.info("Все аудиофайлы прошли валидацию ✅")
            return

        logger.warning(f"Обнаружено {len(corrupted_files)} поврежденных файлов. Начинаем перегенерацию...")

        regenerated_count = 0
        for row_num, file_path, reason in corrupted_files:
            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Удален поврежденный файл: {file_path} (причина: {reason})")

                text_row = df_column.iloc[row_num - 1]
                text = str(text_row.iloc[0]).strip() if not pd.isna(text_row.iloc[0]) else ""

                if text and text.lower() != 'nan':
                    logger.info(f"Перегенерируем файл {row_num}.mp3: '{text[:50]}...'")

                    success = await api.text_to_speech(
                        text=text,
                        voice_id=self.voice_config.original_voice_id or self.voice_config.standard_voice_id,
                        output_path=str(file_path),
                        voice_config=self.voice_config,
                        row_index=row_num
                    )

                    if success:
                        logger.info(f"✅ Файл {row_num}.mp3 успешно перегенерирован")
                        regenerated_count += 1
                    else:
                        logger.error(f"❌ Не удалось перегенерировать файл {row_num}.mp3")

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

async def create_preview_api(channel_name: str) -> ElevenLabsAPI:
    """
    Создание API экземпляра для предпросмотра голосов
    """
    try:
        config_manager = ConfigManager()
        channel_config = config_manager.get_channel_config(channel_name)
        if not channel_config:
            raise ConfigurationError(f"Конфигурация канала '{channel_name}' не найдена")

        proxy_config_raw = config_manager.get_proxy_config()
        proxies = []
        if proxy_config_raw.get("use_proxy", True):
            proxy_list = proxy_config_raw.get("proxy_list", [])
            if isinstance(proxy_list, str):
                proxy_list = proxy_list.split(",")
            for proxy in proxy_list:
                if isinstance(proxy, str):
                    proxies.append({"url": proxy.strip(), "login": proxy_config_raw.get("proxy_login", ""),
                                   "password": proxy_config_raw.get("proxy_password", "")})
                else:
                    proxies.append(proxy)

        proxy_config = ProxyConfig(
            enabled=bool(proxy_config_raw.get("use_proxy", True)),
            proxies=proxies,
            proxy_type=proxy_config_raw.get("proxy_type", "standard"),
            rotate_endpoint=proxy_config_raw.get("rotate_endpoint", ""),
            rotate_min_interval=int(proxy_config_raw.get("rotate_min_interval", 30)),
            rotate_auth_login=proxy_config_raw.get("rotate_auth_login", ""),
            rotate_auth_password=proxy_config_raw.get("rotate_auth_password", "")
        )

        api_key_manager = APIKeyManager(channel_config["csv_file_path"])
        api_key = api_key_manager.get_api_key()
        if not api_key:
            raise ConfigurationError("Не удалось получить API ключ")

        return ElevenLabsAPI(api_key, proxy_config)

    except Exception as e:
        logger.error(f"Ошибка создания API для предпросмотра: {e}")
        raise ConfigurationError(f"Ошибка создания API: {e}")

async def process_voice_and_proxy(channel_name: str, thread=None) -> ProcessingStats:
    """
    Обратная совместимость: основная функция обработки озвучки
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

def create_voice_config(**kwargs) -> VoiceConfig:
    """Создание конфигурации голоса с проверкой параметров"""
    return VoiceConfig(**kwargs)

def create_proxy_config(**kwargs) -> ProxyConfig:
    """Создание конфигурации прокси с проверкой параметров"""
    return ProxyConfig(**kwargs)

async def quick_voice_processing(channel_name: str, **config_overrides) -> ProcessingStats:
    """
    Быстрая обработка озвучки с переопределением конфигурации
    """
    processor = VoiceProcessor(channel_name)

    for key, value in config_overrides.items():
        if hasattr(processor.voice_config, key):
            setattr(processor.voice_config, key, value)
        elif hasattr(processor.proxy_config, key):
            setattr(processor.proxy_config, key, value)

    return await processor.process()

async def main():
    """Функция для тестирования модуля"""
    import argparse

    parser = argparse.ArgumentParser(description='Тестирование обработки озвучки')
    parser.add_argument('--channel', type=str, required=True, help='Название канала')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='DEBUG', help='Уровень логирования')

    args = parser.parse_args()

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