"""
Менеджер асинхронных задач
"""
import asyncio
import threading
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AsyncTaskManager:
    """Менеджер асинхронных задач"""

    def __init__(self):
        self.tasks: Dict[str, asyncio.Task] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def create_loop(self) -> asyncio.AbstractEventLoop:
        """Создание нового цикла событий"""
        if self.loop is None or self.loop.is_closed():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.info("Создан новый цикл событий")
        return self.loop

    def add_task(self, name: str, coro) -> Optional[asyncio.Task]:
        """
        Добавление задачи

        Args:
            name: Имя задачи
            coro: Корутина для выполнения

        Returns:
            Optional[asyncio.Task]: Задача или None если цикл не создан
        """
        if not self.loop:
            logger.error("Цикл событий не создан")
            return None

        with self._lock:
            if name in self.tasks and not self.tasks[name].done():
                logger.warning(f"Задача {name} уже выполняется")
                return self.tasks[name]

            task = self.loop.create_task(coro)
            self.tasks[name] = task
            logger.info(f"Добавлена задача: {name}")
            return task

    def cancel_task(self, name: str) -> bool:
        """
        Отмена задачи

        Args:
            name: Имя задачи

        Returns:
            bool: True если задача была отменена
        """
        with self._lock:
            if name in self.tasks:
                task = self.tasks[name]
                if not task.done():
                    task.cancel()
                    logger.info(f"Задача отменена: {name}")
                    return True
                else:
                    logger.info(f"Задача уже завершена: {name}")
        return False

    def cancel_all_tasks(self) -> None:
        """Отмена всех задач"""
        with self._lock:
            cancelled_count = 0
            for name, task in self.tasks.items():
                if not task.done():
                    task.cancel()
                    cancelled_count += 1

            if cancelled_count > 0:
                logger.info(f"Отменено задач: {cancelled_count}")

    def stop_loop(self) -> None:
        """Остановка цикла событий"""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            logger.info("Запрос на остановку цикла событий")

    def get_task_status(self, name: str) -> Optional[str]:
        """
        Получение статуса задачи

        Args:
            name: Имя задачи

        Returns:
            Optional[str]: Статус задачи или None если не найдена
        """
        with self._lock:
            if name in self.tasks:
                task = self.tasks[name]
                if task.done():
                    if task.cancelled():
                        return "cancelled"
                    elif task.exception():
                        return "error"
                    else:
                        return "completed"
                else:
                    return "running"
        return None

    def cleanup_completed_tasks(self) -> None:
        """Очистка завершенных задач"""
        with self._lock:
            completed_tasks = [name for name, task in self.tasks.items() if task.done()]

            for name in completed_tasks:
                del self.tasks[name]

            if completed_tasks:
                logger.info(f"Очищено завершенных задач: {len(completed_tasks)}")

    def get_active_tasks(self) -> list:
        """Получение списка активных задач"""
        with self._lock:
            return [name for name, task in self.tasks.items() if not task.done()]

    def close(self) -> None:
        """Закрытие менеджера задач"""
        self.cancel_all_tasks()
        if self.loop and not self.loop.is_closed():
            self.loop.close()
            logger.info("Цикл событий закрыт")