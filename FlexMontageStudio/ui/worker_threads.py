"""
Рабочие потоки для UI - исправленная версия
"""
import asyncio
import logging
import traceback
import sys
import gc
import os
from typing import Dict, List, Any
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QObject

from core.config_manager import ConfigManager
from core.logging_config import LoggingConfig
from core.task_manager import AsyncTaskManager

# Статический импорт main для совместимости с Nuitka
try:
    # Если запущено из startup.py, импортируем через main модуль
    import main
    process_auto_montage = main.process_auto_montage
    MAIN_IMPORT_SUCCESS = True
except (ImportError, AttributeError) as e:
    # Если статический импорт не удался, будем пытаться динамический
    MAIN_IMPORT_SUCCESS = False
    process_auto_montage = None

logger = logging.getLogger(__name__)


class ConfigLoader(QThread):
    """Поток для загрузки конфигурации"""
    config_loaded = Signal(dict, dict, object)  # channel_config, proxy_config, LoggingConfig
    error_occurred = Signal(str)

    def __init__(self, channel_name: str, config_manager: ConfigManager):
        super().__init__()
        self.channel_name = channel_name
        self.config_manager = config_manager

    def run(self):
        """Загрузка конфигурации в отдельном потоке"""
        try:
            logger.info(f"Загрузка конфигурации для канала: {self.channel_name}")

            channel_config = self.config_manager.get_channel_config(self.channel_name)
            proxy_config = self.config_manager.get_proxy_config()

            # Создание конфигурации логирования
            debug_config = proxy_config.get("debug_config", {})
            logging_config = LoggingConfig.from_dict(debug_config)

            # Настройка глобального уровня логирования
            logging_config.setup_global_logging()

            self.config_loaded.emit(channel_config, proxy_config, logging_config)
            logger.info(f"Конфигурация канала {self.channel_name} успешно загружена")

        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации для канала {self.channel_name}: {e}")
            logger.error(f"Полный стектрейс: {traceback.format_exc()}")
            self.error_occurred.emit(str(e))


class MontageThread(QThread):
    """Поток для выполнения монтажа с детальным логированием"""
    finished = Signal()
    error_occurred = Signal(str)
    progress_updated = Signal(str)

    def __init__(self, channel_name: str, config: Dict[str, Any],
                 preserve_clip_audio_videos: List[int] = None):
        super().__init__()
        self.channel_name = channel_name
        self.config = config
        self.preserve_clip_audio_videos = preserve_clip_audio_videos or []
        self._stop_flag = False  # Флаг для мягкой остановки

    def stop(self):
        """Мягкая остановка монтажа"""
        self._stop_flag = True
        logger.info(f"🛑 Запрос на остановку монтажа для канала: {self.channel_name}")

    def is_stopped(self):
        """Проверка остановки"""
        return self._stop_flag

    def run(self):
        """Выполнение монтажа в отдельном потоке с детальным логированием"""
        try:
            logger.info("="*50)
            logger.info(f"🎬 НАЧАЛО МОНТАЖА для канала: {self.channel_name}")
            logger.info("="*50)

            # Проверяем системную информацию
            logger.info(f"🖥️  Система: {sys.platform}")
            logger.info(f"🐍 Python версия: {sys.version}")
            logger.info(f"📊 Использование памяти перед стартом: {self._get_memory_usage()}")
            logger.info(f"📁 Текущая директория: {os.getcwd()}")

            # Проверяем конфигурацию
            logger.info(f"📋 Конфигурация содержит {len(self.config)} параметров:")
            for key in sorted(self.config.keys()):
                value = self.config[key]
                if len(str(value)) > 100:  # Обрезаем длинные значения
                    logger.info(f"   {key}: {str(value)[:100]}...")
                else:
                    logger.info(f"   {key}: {value}")

            logger.info(f"🎵 Preserve audio videos: {self.preserve_clip_audio_videos}")

            self.progress_updated.emit(f"Начинается монтаж канала {self.channel_name}...")

            # Проверяем наличие важных путей
            self._validate_paths()

            # Проверяем импорт модуля main
            logger.info("📦 Проверяем импорт функции process_auto_montage...")
            
            # Инициализируем переменную для избежания UnboundLocalError
            current_process_auto_montage = process_auto_montage
            
            if MAIN_IMPORT_SUCCESS and process_auto_montage is not None:
                logger.info("✅ Статический импорт process_auto_montage успешен")
                current_process_auto_montage = process_auto_montage
            else:
                # Пытаемся динамический импорт как fallback
                logger.info("🔄 Пытаемся динамический импорт process_auto_montage...")
                try:
                    import main
                    current_process_auto_montage = main.process_auto_montage
                    logger.info("✅ Динамический импорт process_auto_montage успешен")
                except (ImportError, AttributeError) as e:
                    logger.error(f"❌ Ошибка импорта process_auto_montage: {e}")
                    raise
                except Exception as e:
                    logger.error(f"❌ Неожиданная ошибка при импорте: {e}")
                    logger.error(f"Стектрейс: {traceback.format_exc()}")
                    raise

            # Проверяем функцию
            if not callable(current_process_auto_montage):
                raise ValueError("process_auto_montage не является функцией")

            logger.info("🎬 Запуск process_auto_montage...")
            self.progress_updated.emit("Выполняется обработка видео...")

            # Проверка остановки перед основным процессом
            if self._stop_flag:
                logger.info("🛑 Монтаж остановлен перед запуском process_auto_montage")
                return

            # Принудительная сборка мусора перед началом
            gc.collect()
            logger.info(f"🗑️  Сборка мусора выполнена, память: {self._get_memory_usage()}")

            # Запускаем процесс монтажа
            current_process_auto_montage(
                self.channel_name,
                preserve_clip_audio_videos=self.preserve_clip_audio_videos
            )

            logger.info("✅ process_auto_montage завершен успешно")
            logger.info(f"📊 Использование памяти после завершения: {self._get_memory_usage()}")

            # Проверка остановки после завершения
            if self._stop_flag:
                logger.info("🛑 Монтаж был остановлен во время выполнения")
                self.progress_updated.emit(f"Монтаж канала {self.channel_name} остановлен")
                return

            self.progress_updated.emit(f"Монтаж канала {self.channel_name} завершен")
            logger.info(f"🎉 Монтаж канала {self.channel_name} завершен успешно!")

            self.finished.emit()

        except ImportError as e:
            error_msg = f"Ошибка импорта модуля main: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Стектрейс: {traceback.format_exc()}")
            self.error_occurred.emit(error_msg)

        except FileNotFoundError as e:
            error_msg = f"Файл не найден: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Стектрейс: {traceback.format_exc()}")
            self.error_occurred.emit(error_msg)

        except MemoryError as e:
            error_msg = f"Недостаточно памяти: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Использование памяти: {self._get_memory_usage()}")
            self.error_occurred.emit(error_msg)

        except Exception as e:
            error_msg = f"Ошибка при монтаже канала {self.channel_name}: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            logger.error(f"Полный стектрейс:")
            logger.error(traceback.format_exc())
            logger.error(f"Использование памяти при ошибке: {self._get_memory_usage()}")
            self.error_occurred.emit(error_msg)

        finally:
            # Финальная очистка
            gc.collect()
            logger.info("🏁 Поток монтажа завершен")

    def _validate_paths(self):
        """Проверка существования важных путей"""
        logger.info("📁 Проверка путей...")

        important_paths = [
            'global_xlsx_file_path',
            'channel_folder',
            'base_path',
            'csv_file_path',
            'output_directory',
            'photo_folder',
            'audio_folder',
            'output_folder'
        ]

        for path_key in important_paths:
            if path_key in self.config:
                path_value = self.config[path_key]
                if path_value:
                    from pathlib import Path

                    # Для channel_folder нужно строить полный путь
                    if path_key == 'channel_folder':
                        base_path = self.config.get('base_path', '')
                        if base_path:
                            full_path = Path(base_path) / path_value
                            exists = full_path.exists()
                            logger.info(f"   {path_key}: {path_value} {'✅' if exists else '❌'}")
                            if not exists:
                                logger.warning(f"⚠️  Путь канала не существует: {full_path}")
                        else:
                            logger.warning(f"⚠️  Отсутствует base_path для проверки channel_folder")
                    else:
                        path_obj = Path(path_value)
                        exists = path_obj.exists()
                        logger.info(f"   {path_key}: {path_value} {'✅' if exists else '❌'}")
                        if not exists:
                            logger.warning(f"⚠️  Путь не существует: {path_value}")
                else:
                    logger.warning(f"⚠️  Пустой путь для {path_key}")

    def _get_memory_usage(self) -> str:
        """Получение информации об использовании памяти"""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return f"RSS: {memory_info.rss / 1024 / 1024:.1f}MB, VMS: {memory_info.vms / 1024 / 1024:.1f}MB"
        except ImportError:
            # Если psutil не установлен
            return "N/A (psutil не найден)"
        except Exception as e:
            return f"Ошибка получения памяти: {e}"


class VoiceoverWorker(QObject):
    """Воркер для выполнения озвучки"""
    finished = Signal(str)
    error_occurred = Signal(str, str)
    stopped = Signal(str)
    progress = Signal(str)

    def __init__(self, channel_name: str, task_manager: AsyncTaskManager):
        super().__init__()
        self.channel_name = channel_name
        self.task_manager = task_manager
        self._stop_flag = False
        self.task = None

    def start(self):
        """Запуск задачи озвучки"""
        logger.info(f"Запуск задачи озвучки для канала: {self.channel_name}")
        self.progress.emit(f"Запуск озвучки для канала: {self.channel_name}")
        self.task = self.task_manager.add_task(f"voiceover_{self.channel_name}", self.run())

    def stop(self):
        """Остановка задачи озвучки"""
        self._stop_flag = True
        self.task_manager.cancel_task(f"voiceover_{self.channel_name}")
        logger.info(f"Запрос на остановку задачи озвучки для канала: {self.channel_name}")

    def is_stopped(self):
        """Проверка остановки"""
        return self._stop_flag

    async def run(self):
        """Асинхронное выполнение озвучки с детальным логированием"""
        try:
            logger.info(f"🎬 НАЧАЛО ОЗВУЧКИ для канала: {self.channel_name}")
            logger.info(f"   📋 Канал: {self.channel_name}")
            logger.info(f"   🔧 Платформа: {sys.platform}")
            logger.info(f"   📁 Текущая директория: {os.getcwd()}")

            # Импорт здесь для избежания циклических зависимостей
            logger.info("📦 Импорт voice_proxy модуля...")
            try:
                from voice_proxy import process_voice_and_proxy
                logger.info("✅ voice_proxy импортирован успешно")
            except ImportError as e:
                logger.error(f"❌ Ошибка импорта voice_proxy: {e}")
                raise

            # Проверяем доступность функции
            if not callable(process_voice_and_proxy):
                error_msg = "process_voice_and_proxy не является функцией"
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)

            logger.info(f"🚀 Запуск процесса озвучки для канала {self.channel_name}...")
            self.progress.emit(f"Начинается озвучка канала {self.channel_name}")

            await process_voice_and_proxy(self.channel_name, thread=self)

            if not self._stop_flag:
                logger.info(f"✅ Задача озвучки ЗАВЕРШЕНА для канала: {self.channel_name}")
                self.progress.emit(f"Озвучка канала {self.channel_name} завершена успешно")
                self.finished.emit(self.channel_name)
            else:
                logger.info(f"🛑 Задача озвучки ОСТАНОВЛЕНА для канала: {self.channel_name}")
                self.progress.emit(f"Озвучка канала {self.channel_name} остановлена")
                self.stopped.emit(self.channel_name)

        except asyncio.CancelledError:
            logger.info(f"❌ Задача озвучки для канала {self.channel_name} ПРЕРВАНА")
            self.progress.emit(f"Озвучка канала {self.channel_name} прервана")
            self.stopped.emit(self.channel_name)

        except ImportError as e:
            error_msg = f"Ошибка импорта модулей для озвучки канала {self.channel_name}: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Стектрейс: {traceback.format_exc()}")
            self.progress.emit(f"Ошибка импорта в канале {self.channel_name}")
            if not self._stop_flag:
                self.error_occurred.emit(self.channel_name, error_msg)
            else:
                self.stopped.emit(self.channel_name)

        except Exception as e:
            error_msg = f"Критическая ошибка при озвучке канала {self.channel_name}: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            logger.error(f"Полная трассировка ошибки:")
            logger.error(traceback.format_exc())

            # Диагностика типа ошибки
            if "license" in str(e).lower():
                logger.error(f"🔑 Проблема с лицензией в канале {self.channel_name}")
            elif "config" in str(e).lower():
                logger.error(f"⚙️  Проблема с конфигурацией в канале {self.channel_name}")
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                logger.error(f"🌐 Проблема с сетевым подключением в канале {self.channel_name}")
            elif "api" in str(e).lower():
                logger.error(f"🔌 Проблема с API в канале {self.channel_name}")

            self.progress.emit(f"Ошибка в озвучке канала {self.channel_name}: {str(e)[:100]}")
            if not self._stop_flag:
                self.error_occurred.emit(self.channel_name, error_msg)
            else:
                self.stopped.emit(self.channel_name)


class MassVoiceoverManager(QThread):
    """Менеджер массовой озвучки"""
    finished = Signal()
    error_occurred = Signal(str, str)
    progress = Signal(str)
    stopped = Signal()

    def __init__(self, channel_names: List[str]):
        super().__init__()
        self.channel_names = channel_names
        self.workers = []
        self._stop_flag = False
        self._completed_tasks = 0
        self.task_manager = AsyncTaskManager()

    def run(self):
        """Выполнение массовой озвучки с детальным логированием"""
        loop = None  # Инициализируем переменную loop
        try:
            logger.info("="*60)
            logger.info("🎙️  НАЧАЛО МАССОВОЙ ОЗВУЧКИ")
            logger.info("="*60)

            logger.info(f"🎯 Каналы для озвучки: {self.channel_names}")
            logger.info(f"📊 Количество каналов: {len(self.channel_names)}")
            logger.info(f"🔧 Система: {sys.platform}")
            logger.info(f"📊 Использование памяти перед стартом: {self._get_memory_usage()}")

            # Проверяем зависимости
            self._validate_dependencies()

            # Создаём цикл событий в отдельном потоке
            logger.info("🔄 Создание цикла событий для массовой озвучки...")
            loop = self.task_manager.create_loop()
            logger.info("✅ Цикл событий создан успешно")

            logger.info(f"🚀 Создание задач для озвучки каналов: {self.channel_names}")

            for i, channel_name in enumerate(self.channel_names, 1):
                if self._stop_flag:
                    logger.warning("⚠️  Прерывание запуска новых задач массовой озвучки")
                    break

                logger.info(f"📋 Создание задачи {i}/{len(self.channel_names)} для канала: {channel_name}")

                worker = VoiceoverWorker(channel_name, self.task_manager)
                worker.finished.connect(self.on_task_finished)
                worker.stopped.connect(self.on_task_stopped)
                worker.error_occurred.connect(self.on_task_error)
                worker.progress.connect(self.progress.emit)
                self.workers.append(worker)

                logger.info(f"🎬 Запуск воркера для канала: {channel_name}")
                worker.start()
                logger.info(f"✅ Воркер для канала {channel_name} запущен")

            logger.info(f"🎉 Создано {len(self.workers)} задач для озвучки")
            logger.info(f"📊 Использование памяти после создания задач: {self._get_memory_usage()}")

            # Запускаем цикл событий
            logger.info("🔄 Запуск цикла событий...")
            loop.run_forever()
            logger.info("🏁 Цикл событий завершен")

        except ImportError as e:
            error_msg = f"Ошибка импорта модулей для озвучки: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Стектрейс: {traceback.format_exc()}")
            self.error_occurred.emit("ImportError", error_msg)

        except Exception as e:
            error_msg = f"Критическая ошибка в менеджере массовой озвучки: {e}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            logger.error(f"Полный стектрейс: {traceback.format_exc()}")
            logger.error(f"Использование памяти при ошибке: {self._get_memory_usage()}")
            self.error_occurred.emit("CriticalError", error_msg)
        finally:
            # Закрываем цикл событий безопасно
            try:
                if loop is not None and not loop.is_closed():
                    logger.info("🔒 Закрытие цикла событий...")
                    loop.stop()
                    loop.close()
                    logger.info("✅ Цикл событий закрыт")
            except Exception as e:
                logger.error(f"❌ Ошибка при закрытии цикла событий: {e}")

            # Останавливаем все воркеры принудительно
            try:
                for worker in self.workers:
                    if hasattr(worker, '_stop_flag'):
                        worker._stop_flag = True
            except Exception as e:
                logger.error(f"❌ Ошибка при остановке воркеров: {e}")

            # Принудительная сборка мусора
            gc.collect()
            logger.info("🗑️  Сборка мусора выполнена")
            logger.info("🏁 Менеджер массовой озвучки завершен")

    def stop(self):
        """Остановка всех задач"""
        self._stop_flag = True
        for worker in self.workers:
            worker.stop()
        # Останавливаем цикл событий
        self.task_manager.stop_loop()
        logger.info("Запрос на остановку всех задач массовой озвучки")

    def on_task_finished(self, channel_name: str):
        """Обработка завершения задачи"""
        self._completed_tasks += 1
        self.progress.emit(f"Озвучка завершена для канала: {channel_name}")
        logger.info(
            f"Задача для канала {channel_name} завершена. "
            f"Завершено задач: {self._completed_tasks}/{len(self.workers)}"
        )

        if self._completed_tasks == len(self.workers) and not self._stop_flag:
            self.finished.emit()
            self.task_manager.stop_loop()

    def on_task_stopped(self, channel_name: str):
        """Обработка остановки задачи"""
        self._completed_tasks += 1
        self.progress.emit(f"Озвучка остановлена для канала: {channel_name}")
        logger.info(
            f"Задача для канала {channel_name} остановлена. "
            f"Завершено задач: {self._completed_tasks}/{len(self.workers)}"
        )

        if self._completed_tasks == len(self.workers):
            self.stopped.emit()
            self.task_manager.stop_loop()

    def on_task_error(self, channel_name: str, error: str):
        """Обработка ошибки задачи с детальным логированием"""
        self._completed_tasks += 1

        logger.error(f"❌ ОШИБКА в задаче для канала {channel_name}")
        logger.error(f"   📋 Канал: {channel_name}")
        logger.error(f"   ⚠️  Ошибка: {error}")
        logger.error(f"   📊 Завершено задач: {self._completed_tasks}/{len(self.workers)}")
        logger.error(f"   📊 Использование памяти при ошибке: {self._get_memory_usage()}")

        # Проверяем, связана ли ошибка с конкретными проблемами
        if "license" in error.lower():
            logger.error(f"   🔑 Проблема с лицензией в канале {channel_name}")
        elif "import" in error.lower() or "module" in error.lower():
            logger.error(f"   📦 Проблема с модулями в канале {channel_name}")
        elif "config" in error.lower():
            logger.error(f"   ⚙️  Проблема с конфигурацией в канале {channel_name}")
        elif "network" in error.lower() or "api" in error.lower():
            logger.error(f"   🌐 Проблема с сетью/API в канале {channel_name}")

        self.error_occurred.emit(channel_name, error)

        if self._completed_tasks == len(self.workers):
            if self._stop_flag:
                logger.info("🛑 Все задачи завершены после остановки")
                self.stopped.emit()
            else:
                logger.info("🏁 Все задачи завершены (с ошибками)")
                self.finished.emit()
            self.task_manager.stop_loop()

    def _validate_dependencies(self):
        """Проверка зависимостей для озвучки"""
        logger.info("🔍 Проверка зависимостей для озвучки...")

        # Проверяем импорт voice_proxy
        try:
            from voice_proxy import process_voice_and_proxy
            if callable(process_voice_and_proxy):
                logger.info("✅ voice_proxy импортирован и process_voice_and_proxy доступна")
            else:
                logger.error("❌ process_voice_and_proxy не является функцией")
                raise ValueError("process_voice_and_proxy не является функцией")
        except ImportError as e:
            logger.error(f"❌ Ошибка импорта voice_proxy: {e}")
            raise
        
        # Проверяем AsyncTaskManager
        if hasattr(self, 'task_manager') and self.task_manager:
            logger.info("✅ AsyncTaskManager инициализирован")
        else:
            logger.error("❌ AsyncTaskManager не инициализирован")
            raise ValueError("AsyncTaskManager не инициализирован")
        
        logger.info("✅ Все зависимости проверены успешно")

    def _get_memory_usage(self) -> str:
        """Получение информации об использовании памяти"""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return f"RSS: {memory_info.rss / 1024 / 1024:.1f}MB, VMS: {memory_info.vms / 1024 / 1024:.1f}MB"
        except ImportError:
            return "N/A (psutil не найден)"
        except Exception as e:
            return f"Ошибка получения памяти: {e}"