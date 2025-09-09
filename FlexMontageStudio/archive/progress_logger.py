"""
Модуль для оптимизированного логирования с прогресс-барами
"""
import logging
import sys
import time
from typing import Optional, Dict, Any
from pathlib import Path

class ProgressLogger:
    """Класс для красивого логирования с прогресс-барами"""
    
    def __init__(self, debug_config: Optional[Dict[str, bool]] = None):
        self.debug_config = debug_config or {}
        self.logger = logging.getLogger(__name__)
        
        # Определяем есть ли хоть один включенный debug режим
        self.is_debug_mode = any(self.debug_config.values()) if self.debug_config else False
        
        # Счетчики для статистики
        self.stats = {
            "videos_processed": 0,
            "photos_processed": 0,
            "files_skipped": 0,
            "folders_processed": 0
        }
    
    def log_stage(self, stage: str, details: str = ""):
        """Логирование этапов процесса - всегда видно"""
        if details:
            message = f"🔄 {stage}: {details}"
        else:
            message = f"🔄 {stage}"
        
        self.logger.info(message)
        print(f"\n{message}")  # Дублируем в консоль для наглядности
    
    def log_progress_bar(self, current: int, total: int, prefix: str, suffix: str = ""):
        """Красивый прогресс-бар"""
        try:
            bar_length = 40
            progress = current / total if total > 0 else 0
            filled_length = int(bar_length * progress)
            
            bar = "█" * filled_length + "░" * (bar_length - filled_length)
            percent = f"{progress * 100:.1f}%"
            
            if suffix:
                message = f"\r{prefix} |{bar}| {current}/{total} ({percent}) {suffix}"
            else:
                message = f"\r{prefix} |{bar}| {current}/{total} ({percent})"
            
            # Выводим в консоль без перевода строки
            sys.stdout.write(message)
            sys.stdout.flush()
            
            # Если завершено - переходим на новую строку
            if current >= total:
                print()
        except Exception as e:
            # В случае ошибки просто логируем без прогресс-бара
            self.logger.error(f"Ошибка в progress bar (current={current}, total={total}, prefix={prefix}): {e}")
            print(f"\r{prefix}: {current}/{total}")  # Простое отображение
    
    def log_folder_start(self, folder_name: str, folder_idx: int, total_folders: int, 
                        files_count: int, duration: float):
        """Логирование начала обработки папки"""
        message = f"📁 Папка {folder_idx+1}/{total_folders}: '{folder_name}' ({files_count} файлов, {duration:.1f}с)"
        
        if self.is_debug_mode:
            self.logger.info(message)
        else:
            # В обычном режиме показываем только основные этапы
            print(f"   {message}")
        
        self.stats["folders_processed"] += 1
    
    def log_file_processed(self, file_type: str, file_name: str, duration: float, 
                          debug_category: str = ""):
        """Логирование обработки файла"""
        if debug_category and self.debug_config.get(debug_category, False):
            # Детальное логирование только если включен соответствующий debug
            self.logger.debug(f"   {file_type} {file_name} -> {duration:.2f}с")
        
        # Обновляем статистику
        if "видео" in file_type.lower():
            self.stats["videos_processed"] += 1
        elif "фото" in file_type.lower():
            self.stats["photos_processed"] += 1
    
    def log_file_skipped(self, file_name: str, reason: str, debug_category: str = ""):
        """Логирование пропущенного файла"""
        if debug_category and self.debug_config.get(debug_category, False):
            self.logger.warning(f"   ⚠️ Пропущен {file_name}: {reason}")
        
        self.stats["files_skipped"] += 1
    
    def log_error(self, message: str, exception: Optional[Exception] = None):
        """Логирование ошибок - всегда видно"""
        error_msg = f"❌ {message}"
        if exception:
            error_msg += f": {exception}"
        
        self.logger.error(error_msg)
        print(f"\n{error_msg}")
    
    def log_warning(self, message: str, debug_category: str = ""):
        """Логирование предупреждений"""
        warning_msg = f"⚠️ {message}"
        
        if debug_category and self.debug_config.get(debug_category, False):
            # Показываем warning только в debug режиме
            self.logger.warning(warning_msg)
        elif not debug_category:
            # Общие warning показываем всегда
            self.logger.warning(warning_msg)
            print(f"   {warning_msg}")
    
    def log_success(self, message: str, show_stats: bool = False):
        """Логирование успешного завершения"""
        success_msg = f"✅ {message}"
        self.logger.info(success_msg)
        print(f"\n{success_msg}")
        
        if show_stats:
            self.log_final_stats()
    
    def log_final_stats(self):
        """Логирование финальной статистики"""
        print(f"\n📊 Статистика обработки:")
        print(f"   📁 Папок обработано: {self.stats['folders_processed']}")
        print(f"   🎬 Видео обработано: {self.stats['videos_processed']}")
        print(f"   📷 Фото обработано: {self.stats['photos_processed']}")
        print(f"   ⚠️ Файлов пропущено: {self.stats['files_skipped']}")
        
        total_processed = self.stats['videos_processed'] + self.stats['photos_processed']
        print(f"   📈 Всего обработано: {total_processed} файлов")
    
    def create_animated_progress(self, message: str, duration: float = 2.0):
        """Создает анимированный прогресс для длительных операций"""
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        frame_count = len(frames)
        
        start_time = time.time()
        frame_idx = 0
        
        while time.time() - start_time < duration:
            frame = frames[frame_idx % frame_count]
            sys.stdout.write(f"\r{frame} {message}")
            sys.stdout.flush()
            
            time.sleep(0.1)
            frame_idx += 1
        
        # Завершаем красиво
        sys.stdout.write(f"\r✅ {message}\n")
        sys.stdout.flush()


def get_progress_logger(debug_config: Optional[Dict[str, bool]] = None) -> ProgressLogger:
    """Фабричная функция для создания ProgressLogger"""
    return ProgressLogger(debug_config)


# Пример использования в video_processing.py
def setup_optimized_logging(debug_config: Dict[str, bool]) -> ProgressLogger:
    """Настройка оптимизированного логирования"""
    progress_logger = ProgressLogger(debug_config)
    
    # Определяем уровень логирования
    if any(debug_config.values()):
        # Если хоть один debug включен - показываем все
        logging.getLogger().setLevel(logging.DEBUG)
        progress_logger.log_stage("Режим отладки включен", "Детальное логирование активно")
    else:
        # Обычный режим - только важная информация
        logging.getLogger().setLevel(logging.INFO)
        progress_logger.log_stage("Обычный режим", "Показываются только основные этапы")
    
    return progress_logger