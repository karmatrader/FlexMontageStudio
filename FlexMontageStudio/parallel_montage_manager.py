"""
Менеджер параллельного монтажа видео
"""
import asyncio
import logging
import traceback
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QObject
import concurrent.futures

from core.config_manager import ConfigManager

logger = logging.getLogger(__name__)


@dataclass
class MontageTask:
    """Задача монтажа"""
    channel_name: str
    video_number: int
    task_id: str
    preserve_clip_audio_videos: Optional[List[int]] = None
    
    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"{self.channel_name}_video_{self.video_number}_{datetime.now().strftime('%H%M%S')}"


@dataclass
class MontageResult:
    """Результат монтажа"""
    task: MontageTask
    success: bool
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    duration: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class ParallelMontageManager(QObject):
    """Менеджер параллельного монтажа видео"""
    
    # Сигналы для GUI
    task_started = Signal(str, str, int)  # task_id, channel_name, video_number
    task_completed = Signal(str, bool, str)  # task_id, success, message
    progress_updated = Signal(str, str)  # task_id, progress_message
    all_tasks_completed = Signal(int, int)  # total_tasks, successful_tasks
    
    def __init__(self, max_concurrent_montages: int = 3):
        super().__init__()
        self.max_concurrent_montages = max_concurrent_montages
        self.semaphore = asyncio.Semaphore(max_concurrent_montages)
        self.active_tasks: Dict[str, MontageTask] = {}
        self.completed_tasks: List[MontageResult] = []
        self.config_manager = ConfigManager()
        
    def set_max_concurrent_montages(self, max_concurrent: int):
        """Установка максимального количества параллельных монтажей"""
        self.max_concurrent_montages = max_concurrent
        # Создаем новый семафор с новым лимитом
        self.semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"Установлен лимит параллельных монтажей: {max_concurrent}")
    
    def validate_video_numbers(self, channel_name: str, video_numbers: List[int]) -> Tuple[List[int], List[str]]:
        """
        Валидация номеров видео по Excel файлу
        
        Returns:
            Tuple[List[int], List[str]]: Валидные номера и ошибки валидации
        """
        try:
            channel_config = self.config_manager.get_channel_config(channel_name)
            if not channel_config:
                return [], [f"Конфигурация канала '{channel_name}' не найдена"]
            
            excel_path = channel_config.get("global_xlsx_file_path")
            if not excel_path or not Path(excel_path).exists():
                return [], [f"Excel файл не найден: {excel_path}"]
            
            # Здесь можно добавить более детальную валидацию через pandas
            # Пока возвращаем все номера как валидные
            valid_numbers = []
            errors = []
            
            for video_num in video_numbers:
                if video_num <= 0:
                    errors.append(f"Номер видео должен быть больше 0: {video_num}")
                elif video_num > 1000:  # Разумный лимит
                    errors.append(f"Номер видео слишком большой: {video_num}")
                else:
                    valid_numbers.append(video_num)
            
            return valid_numbers, errors
            
        except Exception as e:
            logger.error(f"Ошибка валидации номеров видео: {e}")
            return [], [f"Ошибка валидации: {e}"]
    
    def check_system_load_warning(self, total_tasks: int) -> Optional[str]:
        """
        Проверка нагрузки на систему и генерация предупреждения
        
        Returns:
            Optional[str]: Текст предупреждения или None
        """
        if total_tasks > 5:
            return (f"⚠️ ПРЕДУПРЕЖДЕНИЕ О НАГРУЗКЕ ⚠️\n\n"
                   f"Вы собираетесь запустить {total_tasks} задач монтажа одновременно.\n"
                   f"Это может сильно нагрузить систему и привести к:\n\n"
                   f"• Высокому использованию CPU и RAM\n"
                   f"• Замедлению работы компьютера\n"
                   f"• Возможным ошибкам из-за нехватки ресурсов\n\n"
                   f"Рекомендуется запускать не более 3-5 задач одновременно.\n\n"
                   f"Продолжить выполнение?")
        return None
    
    async def process_tasks_parallel(self, tasks: List[MontageTask]) -> List[MontageResult]:
        """
        Параллельная обработка задач монтажа
        
        Args:
            tasks: Список задач для обработки
            
        Returns:
            List[MontageResult]: Результаты выполнения
        """
        logger.info(f"🎬 Начало параллельного монтажа: {len(tasks)} задач")
        self.completed_tasks.clear()
        
        # Создаем корутины для всех задач
        coroutines = [self._process_single_task(task) for task in tasks]
        
        try:
            # Запускаем все задачи параллельно
            results = await asyncio.gather(*coroutines, return_exceptions=True)
            
            # Обрабатываем результаты
            final_results = []
            successful_count = 0
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    # Обработка исключения
                    error_result = MontageResult(
                        task=tasks[i],
                        success=False,
                        error_message=str(result),
                        end_time=datetime.now()
                    )
                    final_results.append(error_result)
                    logger.error(f"❌ Задача {tasks[i].task_id} завершилась с ошибкой: {result}")
                else:
                    final_results.append(result)
                    if result.success:
                        successful_count += 1
            
            # Уведомляем о завершении всех задач
            self.all_tasks_completed.emit(len(tasks), successful_count)
            
            logger.info(f"🏁 Параллельный монтаж завершен: {successful_count}/{len(tasks)} успешно")
            return final_results
            
        except Exception as e:
            logger.error(f"Критическая ошибка параллельного монтажа: {e}")
            logger.error(traceback.format_exc())
            raise
    
    async def _process_single_task(self, task: MontageTask) -> MontageResult:
        """
        Обработка одной задачи монтажа
        
        Args:
            task: Задача для обработки
            
        Returns:
            MontageResult: Результат выполнения
        """
        async with self.semaphore:  # Ограничиваем количество параллельных задач
            start_time = datetime.now()
            
            try:
                logger.info(f"🎬 [МОНТАЖ-{task.task_id}] Начало обработки видео {task.video_number} для канала {task.channel_name}")
                
                # Уведомляем GUI о начале задачи
                self.task_started.emit(task.task_id, task.channel_name, task.video_number)
                self.active_tasks[task.task_id] = task
                
                # ИСПРАВЛЕНИЕ: Используем subprocess вместо импорта для избежания побочных эффектов
                # Импорт main.py может вызвать повторную инициализацию GUI
                logger.debug("Запуск монтажа через subprocess для избежания конфликтов GUI")
                
                # Эмулируем прогресс
                self.progress_updated.emit(task.task_id, "Загрузка конфигурации...")
                
                # Запускаем монтаж в executor для избежания блокировки
                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    success = await loop.run_in_executor(
                        executor,
                        self._run_montage_sync,
                        task.channel_name,
                        task.video_number,
                        task.preserve_clip_audio_videos,
                        task.task_id
                    )
                    
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # Генерируем примерный путь к выходному файлу
                output_path = f"video_{task.video_number}.mp4" if success else None
                
                # Создаем результат
                result = MontageResult(
                    task=task,
                    success=success,
                    output_path=output_path,
                    duration=duration,
                    start_time=start_time,
                    end_time=end_time
                )
                
                # Уведомляем GUI
                if success:
                    success_message = f"✅ Видео {task.video_number} канала {task.channel_name} успешно создано за {duration:.1f}с"
                    self.task_completed.emit(task.task_id, True, success_message)
                    logger.info(f"✅ [МОНТАЖ-{task.task_id}] Завершено успешно: {output_path}")
                else:
                    error_message = f"❌ Видео {task.video_number} канала {task.channel_name} - ошибка монтажа"
                    self.task_completed.emit(task.task_id, False, error_message)
                    logger.error(f"❌ [МОНТАЖ-{task.task_id}] Завершено с ошибкой")
                
                return result
                
            except Exception as e:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                error_message = f"Ошибка монтажа видео {task.video_number} канала {task.channel_name}: {str(e)}"
                
                result = MontageResult(
                    task=task,
                    success=False,
                    error_message=error_message,
                    duration=duration,
                    start_time=start_time,
                    end_time=end_time
                )
                
                # Уведомляем GUI
                self.task_completed.emit(task.task_id, False, error_message)
                
                logger.error(f"❌ [МОНТАЖ-{task.task_id}] Ошибка: {e}")
                logger.error(traceback.format_exc())
                
                return result
                
            finally:
                # Убираем задачу из активных
                if task.task_id in self.active_tasks:
                    del self.active_tasks[task.task_id]
    
    def _run_montage_sync(self, channel_name: str, video_number: int, preserve_clip_audio_videos: Optional[List[int]], task_id: str) -> bool:
        """
        Синхронный запуск монтажа через прямой вызов (БЕЗ subprocess для избежания GUI дублирования)
        
        Returns:
            bool: True если монтаж успешен, False если ошибка
        """
        try:
            logger.info(f"[МОНТАЖ-{task_id}] Начало РЕАЛЬНОГО монтажа видео {video_number} (прямой вызов)")
            
            # ОКОНЧАТЕЛЬНОЕ ИСПРАВЛЕНИЕ v2.0: Прямой вызов функции монтажа
            # НЕ используем subprocess - это вызывает GUI дублирование
            logger.info(f"[МОНТАЖ-{task_id}] FIXED v2.0: Прямой вызов main.process_auto_montage()")
            
            try:
                # Блокируем инициализацию GUI при импорте
                import os
                os.environ['FLEXMONTAGE_NO_GUI'] = '1'
                os.environ['FLEXMONTAGE_CLI_MODE'] = '1'
                
                # Импортируем функцию процесса монтажа напрямую
                from main import process_auto_montage
                
                logger.info(f"[МОНТАЖ-{task_id}] 🎬 Запуск РЕАЛЬНОГО монтажа: канал='{channel_name}', видео={video_number}")
                
                # Вызываем функцию монтажа в том же процессе
                success = process_auto_montage(
                    channel_name=channel_name,
                    video_number=str(video_number),
                    preserve_clip_audio_videos=preserve_clip_audio_videos or []
                )
                
                if success:
                    logger.info(f"[МОНТАЖ-{task_id}] ✅ РЕАЛЬНЫЙ монтаж завершен УСПЕШНО")
                else:
                    logger.error(f"[МОНТАЖ-{task_id}] ❌ РЕАЛЬНЫЙ монтаж завершен с ОШИБКОЙ")
                
                return success
                
            except ImportError as import_error:
                logger.error(f"[МОНТАЖ-{task_id}] Ошибка импорта main.process_auto_montage: {import_error}")
                return False
            except Exception as processing_error:
                logger.error(f"[МОНТАЖ-{task_id}] Ошибка при выполнении монтажа: {processing_error}")
                logger.error(f"[МОНТАЖ-{task_id}] Трейсбек:", exc_info=True)
                return False
            
        except Exception as e:
            logger.error(f"[МОНТАЖ-{task_id}] Критическая ошибка выполнения монтажа: {e}")
            logger.error(f"[МОНТАЖ-{task_id}] Критический трейсбек:", exc_info=True)
            return False
    
    def get_active_tasks_count(self) -> int:
        """Получение количества активных задач"""
        return len(self.active_tasks)
    
    def get_active_tasks_info(self) -> List[Dict[str, Any]]:
        """Получение информации об активных задачах"""
        return [
            {
                "task_id": task.task_id,
                "channel_name": task.channel_name,
                "video_number": task.video_number
            }
            for task in self.active_tasks.values()
        ]
    
    def stop_all_tasks(self):
        """Остановка всех активных задач"""
        logger.warning("⏹️ Получен запрос на остановку всех задач монтажа")
        # Здесь можно добавить логику принудительной остановки
        # Пока просто логируем - реализация зависит от архитектуры main.py
    
    @staticmethod
    def parse_video_numbers(video_numbers_str: str) -> List[int]:
        """
        Парсинг строки с номерами видео
        
        Args:
            video_numbers_str: Строка вида "1,3,5-8,10"
            
        Returns:
            List[int]: Список номеров видео
        """
        if not video_numbers_str.strip():
            return []
        
        numbers = []
        parts = video_numbers_str.split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
                
            if '-' in part:
                # Обработка диапазона "5-8"
                try:
                    start, end = map(int, part.split('-', 1))
                    if start <= end:
                        numbers.extend(range(start, end + 1))
                    else:
                        logger.warning(f"Некорректный диапазон: {part}")
                except ValueError:
                    logger.warning(f"Некорректный диапазон: {part}")
            else:
                # Обработка одиночного номера
                try:
                    numbers.append(int(part))
                except ValueError:
                    logger.warning(f"Некорректный номер видео: {part}")
        
        # Удаляем дубликаты и сортируем
        return sorted(list(set(numbers)))


class ParallelMontageThread(QThread):
    """Поток для выполнения параллельного монтажа в GUI"""
    
    # Передаем сигналы от менеджера
    task_started = Signal(str, str, int)
    task_completed = Signal(str, bool, str)
    progress_updated = Signal(str, str)
    all_tasks_completed = Signal(int, int)
    error_occurred = Signal(str)
    
    def __init__(self, tasks: List[MontageTask], max_concurrent: int = 3):
        super().__init__()
        self.tasks = tasks
        self.max_concurrent = max_concurrent
        self.manager: Optional[ParallelMontageManager] = None
        self.results: List[MontageResult] = []
    
    def run(self):
        """Запуск параллельного монтажа в отдельном потоке"""
        try:
            # Создаем менеджер
            self.manager = ParallelMontageManager(self.max_concurrent)
            
            # Подключаем сигналы
            self.manager.task_started.connect(self.task_started.emit)
            self.manager.task_completed.connect(self.task_completed.emit)
            self.manager.progress_updated.connect(self.progress_updated.emit)
            self.manager.all_tasks_completed.connect(self.all_tasks_completed.emit)
            
            # Создаем новый event loop для потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Запускаем параллельную обработку
                self.results = loop.run_until_complete(
                    self.manager.process_tasks_parallel(self.tasks)
                )
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"Критическая ошибка в потоке параллельного монтажа: {e}")
            self.error_occurred.emit(str(e))


# Вспомогательные функции


def create_montage_tasks(channel_names: List[str], video_numbers: List[int], 
                        preserve_clip_audio_videos: Optional[List[int]] = None) -> List[MontageTask]:
    """
    Создание задач монтажа для множественных каналов и номеров видео
    
    Args:
        channel_names: Список названий каналов
        video_numbers: Список номеров видео
        preserve_clip_audio_videos: Список номеров видео для сохранения аудио клипов
        
    Returns:
        List[MontageTask]: Список задач монтажа
    """
    tasks = []
    
    for channel_name in channel_names:
        for video_number in video_numbers:
            task = MontageTask(
                channel_name=channel_name,
                video_number=video_number,
                task_id="",  # Автогенерация в __post_init__
                preserve_clip_audio_videos=preserve_clip_audio_videos
            )
            tasks.append(task)
    
    return tasks


# Функция для тестирования
async def test_parallel_montage():
    """Тестовая функция для проверки параллельного монтажа"""
    
    # Создаем тестовые задачи
    tasks = [
        MontageTask("1 ЗВЁЗДНЫЕ ТАЙНЫ TV", 1, ""),
        MontageTask("1 ЗВЁЗДНЫЕ ТАЙНЫ TV", 2, ""),
        MontageTask("2 ЗВЁЗДЫ TV", 1, ""),
    ]
    
    # Создаем менеджер
    manager = ParallelMontageManager(max_concurrent_montages=2)
    
    # Запускаем обработку
    results = await manager.process_tasks_parallel(tasks)
    
    # Выводим результаты
    for result in results:
        status = "✅ Успешно" if result.success else "❌ Ошибка"
        print(f"{status}: {result.task.channel_name} - Видео {result.task.video_number}")
        if result.error_message:
            print(f"   Ошибка: {result.error_message}")
        if result.duration:
            print(f"   Время: {result.duration:.1f}с")


if __name__ == "__main__":
    # Запуск тестирования
    asyncio.run(test_parallel_montage())