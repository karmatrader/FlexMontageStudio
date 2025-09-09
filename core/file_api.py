#!/usr/bin/env python3
"""
File API - Унифицированный интерфейс для работы с файлами в FlexMontageStudio
"""
import os
import json
import csv
import shutil
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable
from dataclasses import dataclass, field
from threading import Lock
from functools import wraps
import time
import hashlib

import pandas as pd
import cv2
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class FileMetadata:
    """Метаданные файла"""
    path: Path
    size: int
    modified_time: float
    hash: Optional[str] = None
    content_type: Optional[str] = None
    cached_at: Optional[float] = None


@dataclass
class CacheEntry:
    """Запись в кэше"""
    content: Any
    metadata: FileMetadata
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    def touch(self):
        """Обновить время последнего доступа"""
        self.last_accessed = time.time()
        self.access_count += 1


class FileCache:
    """Кэш для файлов с автоматической очисткой"""
    
    def __init__(self, max_size: int = 100, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl  # Time to live в секундах
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        
    def get(self, key: str) -> Optional[CacheEntry]:
        """Получить запись из кэша"""
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                # Проверяем не устарела ли запись
                if time.time() - entry.last_accessed > self.ttl:
                    self._cache.pop(key, None)
                    return None
                entry.touch()
                return entry
            return None
    
    def set(self, key: str, entry: CacheEntry):
        """Добавить запись в кэш"""
        with self._lock:
            # Очищаем кэш если превышен размер
            if len(self._cache) >= self.max_size:
                self._cleanup()
            
            self._cache[key] = entry
            
    def _cleanup(self):
        """Очистка кэша по LRU принципу"""
        if not self._cache:
            return
            
        # Сортируем по времени последнего доступа
        sorted_items = sorted(
            self._cache.items(),
            key=lambda x: x[1].last_accessed
        )
        
        # Удаляем четверть самых старых записей
        remove_count = len(self._cache) // 4
        for key, _ in sorted_items[:remove_count]:
            self._cache.pop(key, None)
    
    def clear(self):
        """Очистить весь кэш"""
        with self._lock:
            self._cache.clear()
    
    def invalidate(self, key: str):
        """Удалить конкретную запись из кэша"""
        with self._lock:
            self._cache.pop(key, None)


def cache_file(cache_key: Optional[str] = None, ttl: int = 300):
    """Декоратор для кэширования результатов чтения файлов"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, file_path: Union[str, Path], *args, **kwargs):
            if not self.enable_cache:
                return func(self, file_path, *args, **kwargs)
                
            path = Path(file_path)
            key = cache_key or f"{func.__name__}:{str(path)}"
            
            # Проверяем кэш
            cached = self._file_cache.get(key)
            if cached:
                # Проверяем не изменился ли файл
                if path.exists():
                    current_mtime = path.stat().st_mtime
                    if current_mtime == cached.metadata.modified_time:
                        logger.debug(f"📦 Кэш попадание: {key}")
                        return cached.content
                
                # Файл изменился, удаляем из кэша
                self._file_cache.invalidate(key)
                logger.debug(f"🔄 Кэш невалиден: {key}")
            
            # Читаем файл
            logger.debug(f"📖 Чтение файла: {path}")
            content = func(self, file_path, *args, **kwargs)
            
            # Кэшируем если файл существует
            if path.exists():
                metadata = FileMetadata(
                    path=path,
                    size=path.stat().st_size,
                    modified_time=path.stat().st_mtime,
                    cached_at=time.time()
                )
                
                entry = CacheEntry(content=content, metadata=metadata)
                self._file_cache.set(key, entry)
                logger.debug(f"💾 Добавлено в кэш: {key}")
            
            return content
        return wrapper
    return decorator


class FileAPI:
    """Унифицированный API для работы с файлами"""
    
    def __init__(self, enable_cache: bool = True, cache_size: int = 100):
        self.enable_cache = enable_cache
        self._file_cache = FileCache(max_size=cache_size)
        self._lock = Lock()
        
        logger.info(f"🚀 FileAPI инициализирован (кэш: {'включен' if enable_cache else 'выключен'})")
    
    def exists(self, file_path: Union[str, Path]) -> bool:
        """Проверить существование файла"""
        return Path(file_path).exists()
    
    def get_metadata(self, file_path: Union[str, Path]) -> Optional[FileMetadata]:
        """Получить метаданные файла"""
        path = Path(file_path)
        if not path.exists():
            return None
            
        stat = path.stat()
        return FileMetadata(
            path=path,
            size=stat.st_size,
            modified_time=stat.st_mtime,
            content_type=self._detect_content_type(path)
        )
    
    def _detect_content_type(self, path: Path) -> str:
        """Определить тип содержимого файла"""
        suffix = path.suffix.lower()
        
        # Изображения
        if suffix in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']:
            return 'image'
        
        # Видео
        if suffix in ['.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v']:
            return 'video'
        
        # Аудио
        if suffix in ['.mp3', '.wav', '.aac', '.m4a', '.ogg']:
            return 'audio'
        
        # Документы
        if suffix in ['.json', '.csv', '.xlsx', '.xls', '.txt', '.md']:
            return 'document'
        
        # Конфигурация
        if suffix in ['.qss', '.css', '.ini', '.conf', '.cfg']:
            return 'config'
        
        return 'unknown'
    
    @cache_file(ttl=300)
    def read_json(self, file_path: Union[str, Path], default: Optional[Dict] = None) -> Dict:
        """Чтение JSON файла с кэшированием"""
        path = Path(file_path)
        
        if not path.exists():
            if default is not None:
                logger.warning(f"📄 JSON файл не найден: {path}, используется default")
                return default
            raise FileNotFoundError(f"JSON файл не найден: {path}")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.debug(f"📄 JSON прочитан: {path} ({len(str(data))} символов)")
                return data
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON {path}: {e}")
            if default is not None:
                return default
            raise
    
    def write_json(self, file_path: Union[str, Path], data: Dict, backup: bool = True) -> bool:
        """Запись JSON файла с резервным копированием"""
        path = Path(file_path)
        
        try:
            # Создаем директорию если не существует
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Создаем резервную копию
            if backup and path.exists():
                backup_path = path.with_suffix('.json.backup')
                shutil.copy2(path, backup_path)
                logger.debug(f"💾 Создан backup: {backup_path}")
            
            # Записываем файл
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # Инвалидируем кэш
            self._file_cache.invalidate(f"read_json:{str(path)}")
            
            logger.debug(f"✅ JSON записан: {path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка записи JSON {path}: {e}")
            return False
    
    @cache_file(ttl=600)
    def read_csv(self, file_path: Union[str, Path], **kwargs) -> List[Dict]:
        """Чтение файла CSV с кэшированием"""
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, **kwargs)
                data = list(reader)
                logger.debug(f"📊 CSV прочитан: {path} ({len(data)} строк)")
                return data
        except Exception as e:
            logger.error(f"❌ Ошибка чтения CSV {path}: {e}")
            raise
    
    def write_csv(self, file_path: Union[str, Path], data: List[Dict], **kwargs) -> bool:
        """Запись файла CSV"""
        path = Path(file_path)
        
        if not data:
            logger.warning(f"⚠️ Нет данных для записи в CSV: {path}")
            return False
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w', newline='', encoding='utf-8') as f:
                fieldnames = data[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames, **kwargs)
                writer.writeheader()
                writer.writerows(data)
            
            # Инвалидируем кэш
            self._file_cache.invalidate(f"read_csv:{str(path)}")
            
            logger.info(f"✅ CSV записан: {path} ({len(data)} строк)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка записи CSV {path}: {e}")
            return False
    
    @cache_file(ttl=600)
    def read_excel(self, file_path: Union[str, Path], sheet_name: str = None, **kwargs) -> pd.DataFrame:
        """Чтение Excel файла с кэшированием"""
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Excel файл не найден: {path}")
        
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, **kwargs)
            logger.debug(f"📊 Excel прочитан: {path}, лист: {sheet_name} ({len(df)} строк)")
            return df
        except Exception as e:
            logger.error(f"❌ Ошибка чтения Excel {path}: {e}")
            raise
    
    @cache_file(ttl=60)
    def read_text(self, file_path: Union[str, Path], encoding: str = 'utf-8') -> str:
        """Чтение текстового файла с кэшированием"""
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Текстовый файл не найден: {path}")
        
        try:
            with open(path, 'r', encoding=encoding) as f:
                content = f.read()
                logger.debug(f"📝 Текст прочитан: {path} ({len(content)} символов)")
                return content
        except Exception as e:
            logger.error(f"❌ Ошибка чтения текста {path}: {e}")
            raise
    
    def write_text(self, file_path: Union[str, Path], content: str, encoding: str = 'utf-8') -> bool:
        """Запись текстового файла"""
        path = Path(file_path)
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
            
            # Инвалидируем кэш
            self._file_cache.invalidate(f"read_text:{str(path)}")
            
            logger.info(f"✅ Текст записан: {path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка записи текста {path}: {e}")
            return False
    
    @cache_file(ttl=120)
    def read_image(self, file_path: Union[str, Path], use_opencv: bool = True):
        """Чтение изображения с кэшированием"""
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Изображение не найдено: {path}")
        
        try:
            if use_opencv:
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError(f"Не удалось загрузить изображение: {path}")
                logger.debug(f"🖼️ Изображение прочитано (OpenCV): {path}")
                return image
            else:
                image = Image.open(path)
                logger.debug(f"🖼️ Изображение прочитано (PIL): {path}")
                return image
                
        except Exception as e:
            logger.error(f"❌ Ошибка чтения изображения {path}: {e}")
            raise
    
    def ensure_directory(self, dir_path: Union[str, Path]) -> bool:
        """Убедиться что директория существует"""
        path = Path(dir_path)
        
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"📁 Директория создана/проверена: {path}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка создания директории {path}: {e}")
            return False
    
    def copy_file(self, src: Union[str, Path], dst: Union[str, Path], 
                  preserve_metadata: bool = True) -> bool:
        """Копирование файла"""
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            logger.error(f"❌ Исходный файл не найден: {src_path}")
            return False
        
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            if preserve_metadata:
                shutil.copy2(src_path, dst_path)
            else:
                shutil.copy(src_path, dst_path)
            
            logger.info(f"✅ Файл скопирован: {src_path} -> {dst_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка копирования {src_path} -> {dst_path}: {e}")
            return False
    
    def move_file(self, src: Union[str, Path], dst: Union[str, Path]) -> bool:
        """Перемещение файла"""
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            logger.error(f"❌ Исходный файл не найден: {src_path}")
            return False
        
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dst_path))
            
            logger.info(f"✅ Файл перемещен: {src_path} -> {dst_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка перемещения {src_path} -> {dst_path}: {e}")
            return False
    
    def delete_file(self, file_path: Union[str, Path]) -> bool:
        """Удаление файла"""
        path = Path(file_path)
        
        if not path.exists():
            logger.warning(f"⚠️ Файл для удаления не найден: {path}")
            return True
        
        try:
            path.unlink()
            
            # Инвалидируем все кэши для этого файла
            self._file_cache.invalidate(f"read_json:{str(path)}")
            self._file_cache.invalidate(f"read_csv:{str(path)}")
            self._file_cache.invalidate(f"read_excel:{str(path)}")
            self._file_cache.invalidate(f"read_text:{str(path)}")
            self._file_cache.invalidate(f"read_image:{str(path)}")
            
            logger.info(f"✅ Файл удален: {path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка удаления {path}: {e}")
            return False
    
    def get_cache_stats(self) -> Dict:
        """Получить статистику кэша"""
        with self._file_cache._lock:
            total_entries = len(self._file_cache._cache)
            total_access_count = sum(entry.access_count for entry in self._file_cache._cache.values())
            
            return {
                'total_entries': total_entries,
                'total_access_count': total_access_count,
                'max_size': self._file_cache.max_size,
                'ttl': self._file_cache.ttl
            }
    
    def clear_cache(self):
        """Очистить весь кэш"""
        self._file_cache.clear()
        logger.info("🧹 Кэш очищен")


# Глобальный экземпляр File API
file_api = FileAPI()