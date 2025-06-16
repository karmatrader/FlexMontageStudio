#!/usr/bin/env python3
"""
FlexMontage Studio - Основная точка входа в приложение
"""
import sys
import logging
import traceback
import os
from pathlib import Path

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

# Настройки для macOS
if sys.platform == "darwin":
    # Устанавливаем переменные окружения для правильной работы на macOS
    os.environ['QT_MAC_WANTS_LAYER'] = '1'
    os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
    # Принудительно используем системную тему
    os.environ['QT_QPA_PLATFORMTHEME'] = 'qt6ct'
    # Дополнительные настройки для GUI
    os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.qpa.*=false'


# Глобальный обработчик исключений
def handle_exception(exc_type, exc_value, exc_traceback):
    """Глобальный обработчик исключений"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Логируем полную информацию об ошибке
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.critical(f"Необработанное исключение:\n{error_msg}")
    print(f"CRITICAL ERROR:\n{error_msg}")


# Устанавливаем glобальный обработчик
sys.excepthook = handle_exception

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QSettings

from ui.main_window import MainWindow
from core.license_manager import LicenseManager


def setup_logging():
    """Настройка системы логирования"""
    # Определяем директорию для лога в зависимости от того, запущено ли из .app
    if getattr(sys, 'frozen', False):
        # Запущено из .app bundle
        if sys.platform == "darwin" and '.app' in sys.executable:
            # Для macOS .app - размещаем лог рядом с .app
            app_bundle_path = Path(sys.executable)
            # Поднимаемся до .app директории
            while app_bundle_path.suffix != '.app' and app_bundle_path.parent != app_bundle_path:
                app_bundle_path = app_bundle_path.parent
            
            if app_bundle_path.suffix == '.app':
                # Лог рядом с .app файлом
                log_dir = app_bundle_path.parent
            else:
                # Fallback - рядом с исполняемым файлом
                log_dir = Path(sys.executable).parent
        else:
            # Для Windows .exe - рядом с исполняемым файлом
            log_dir = Path(sys.executable).parent
        
        log_file = log_dir / 'FlexMontageStudio_session.log'
        print(f"🍎 .app режим - лог файл: {log_file}")
    else:
        # Запущено из Python скрипта
        app_dir = Path(__file__).parent.absolute()
        log_file = app_dir / 'FlexMontageStudio_session.log'
        print(f"🐍 Python режим - лог файл: {log_file}")
    
    # Принудительно создаем директорию если ее нет
    log_file.parent.mkdir(exist_ok=True)
    
    # Очищаем предыдущий лог при новом запуске
    try:
        if log_file.exists():
            log_file.unlink()
    except Exception as e:
        print(f"Не удалось удалить старый лог: {e}")
    
    # Создаем пустой файл лога
    try:
        log_file.touch()
        print(f"✅ Создан файл лога: {log_file}")
    except Exception as e:
        print(f"❌ Не удалось создать файл лога: {e}")
        # Используем временную директорию как fallback
        import tempfile
        log_file = Path(tempfile.gettempdir()) / 'FlexMontageStudio_session.log'
        print(f"🔄 Использую временный лог: {log_file}")
    
    # Настройка логирования с информационным уровнем
    logging.basicConfig(
        level=logging.INFO,  
        format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(log_file), encoding='utf-8', mode='w')
        ],
        force=True  # Принудительно перезаписываем конфигурацию
    )

    logger = logging.getLogger(__name__)
    logger.info("=== Система логирования инициализирована ===")
    logger.info(f"Лог файл: {log_file}")
    logger.info(f"Директория лога: {log_file.parent}")
    logger.info(f"Python версия: {sys.version}")
    logger.info(f"Платформа: {sys.platform}")
    logger.info(f"Запущено из .app: {getattr(sys, 'frozen', False)}")
    
    # Настройка логирования для всех модулей приложения
    for module_name in ['voice_proxy', 'audio_processing', 'video_processing', 
                       'final_assembly', 'parallel_montage_manager', 'ui.worker_threads']:
        module_logger = logging.getLogger(module_name)
        module_logger.setLevel(logging.INFO)
    
    return logger


def load_styles(app: QApplication) -> None:
    """Загрузка стилей приложения"""
    try:
        # Определяем путь к стилям в зависимости от режима запуска
        if getattr(sys, 'frozen', False):
            # Запущено из .app bundle
            if sys.platform == "darwin" and '.app' in sys.executable:
                # Для macOS .app - ищем стили рядом с .app
                app_bundle_path = Path(sys.executable)
                while app_bundle_path.suffix != '.app' and app_bundle_path.parent != app_bundle_path:
                    app_bundle_path = app_bundle_path.parent
                
                if app_bundle_path.suffix == '.app':
                    styles_path = app_bundle_path.parent / 'styles.qss'
                else:
                    styles_path = Path(sys.executable).parent / 'styles.qss'
            else:
                # Для Windows .exe
                styles_path = Path(sys.executable).parent / 'styles.qss'
        else:
            # Запущено из Python скрипта
            styles_path = Path(__file__).parent / 'styles.qss'
        
        logging.info(f"🎨 Поиск стилей в: {styles_path}")
        
        if styles_path.exists():
            with open(styles_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            logging.info("✅ Стили успешно загружены")
        else:
            logging.warning(f"⚠️ Файл styles.qss не найден по пути: {styles_path}")
            logging.warning("Используется стандартный стиль")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки стилей: {e}")


def check_application_license() -> bool:
    """Проверка лицензии приложения"""
    settings = QSettings("MyCompany", "AutoMontageApp")
    
    # Определяем правильный путь к файлам лицензий
    if getattr(sys, 'frozen', False):
        # Запущено из .app bundle
        if sys.platform == "darwin" and '.app' in sys.executable:
            # Для macOS .app - ищем лицензии рядом с .app
            app_bundle_path = Path(sys.executable)
            while app_bundle_path.suffix != '.app' and app_bundle_path.parent != app_bundle_path:
                app_bundle_path = app_bundle_path.parent
            
            if app_bundle_path.suffix == '.app':
                licenses_path = app_bundle_path.parent / 'licenses.json'
            else:
                licenses_path = Path(sys.executable).parent / 'licenses.json'
        else:
            # Для Windows .exe
            licenses_path = Path(sys.executable).parent / 'licenses.json'
    else:
        # Запущено из Python скрипта
        licenses_path = Path(__file__).parent / 'licenses.json'
    
    logging.info(f"🔑 Поиск лицензий в: {licenses_path}")
    license_manager = LicenseManager(str(licenses_path))

    # Попытка загрузить сохраненный ключ
    license_key = settings.value("license_key", "")

    if not license_key or not license_manager.check_license(license_key):
        # Удаляем неверный ключ
        settings.remove("license_key")

        # Запрашиваем новый ключ
        from PySide6.QtWidgets import QInputDialog
        license_key, ok = QInputDialog.getText(
            None,
            "Ввод лицензии",
            "Введите лицензионный ключ (XXXX-XXXX-XXXX-XXXX):"
        )

        if not ok or not license_key:
            QMessageBox.critical(None, "Ошибка", "Лицензионный ключ не введён!")
            return False

        if not license_manager.check_license(license_key):
            return False

        # Сохраняем корректный ключ
        settings.setValue("license_key", license_key)

    logging.info("Лицензия проверена успешно")
    return True


def main():
    """Главная функция приложения"""
    # Настройка логирования
    logger = setup_logging()
    
    # Добавляем обработчик для перехвата всех исключений
    def log_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Критическое исключение!", 
                        exc_info=(exc_type, exc_value, exc_traceback))
    
    sys.excepthook = log_exception

    try:
        logger.info("=== Запуск FlexMontage Studio ===")

        # Создание приложения
        app = QApplication(sys.argv)
        app.setApplicationName("FlexMontage Studio")
        app.setApplicationVersion("1.0")
        app.setOrganizationName("MyCompany")
        
        # Специальная настройка для macOS
        if sys.platform == "darwin":
            # Принудительно активируем приложение через NSApplication
            try:
                import objc
                from Foundation import NSBundle
                from AppKit import NSApplication, NSApplicationActivationPolicyRegular
                
                # Получаем NSApplication
                ns_app = NSApplication.sharedApplication()
                ns_app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                # Принудительно активируем приложение
                ns_app.activateIgnoringOtherApps_(True)
                
                logger.info("NSApplication активирован для macOS")
            except ImportError:
                logger.warning("PyObjC недоступен, используем стандартную активацию Qt")

        # Загрузка стилей
        load_styles(app)

        # Проверка лицензии
        if not check_application_license():
            logger.error("Проверка лицензии не пройдена")
            sys.exit(1)

        # Создание и отображение главного окна
        window = MainWindow()
        window.show()
        
        # Для macOS - принудительно выводим окно на передний план
        if sys.platform == "darwin":
            window.raise_()
            window.activateWindow()
            
            # Дополнительная принудительная активация через Qt
            from PySide6.QtCore import QTimer
            
            def force_activation():
                window.showNormal()
                window.raise_()
                window.activateWindow()
                app.processEvents()
                
                # Пытаемся еще раз через NSApplication
                try:
                    from AppKit import NSApplication
                    ns_app = NSApplication.sharedApplication()
                    ns_app.activateIgnoringOtherApps_(True)
                except:
                    pass
            
            # Запускаем принудительную активацию через 100мс
            QTimer.singleShot(100, force_activation)
            # И еще раз через 500мс для надежности
            QTimer.singleShot(500, force_activation)

        logger.info("Главное окно отображено, запуск цикла событий")

        # Запуск цикла событий
        exit_code = app.exec()

        logger.info(f"Приложение завершено с кодом: {exit_code}")
        
        # Принудительное завершение и очистка
        try:
            logger.info("Начало процедуры завершения приложения")
            
            # Закрываем все окна принудительно
            for widget in app.allWidgets():
                if widget and widget.isVisible():
                    widget.close()
            
            # Убеждаемся что все окна закрыты
            app.closeAllWindows()
            
            # Обрабатываем оставшиеся события
            app.processEvents()
            
            # Принудительное завершение QApplication
            app.quit()
            
            # Дополнительная очистка для macOS
            import gc
            gc.collect()
            
            # Явное завершение Python процесса для предотвращения перезапуска
            import os
            os._exit(exit_code)
            
        except Exception as cleanup_error:
            logger.warning(f"Ошибка при завершении приложения: {cleanup_error}")
            # Принудительное завершение в случае ошибки
            import os
            os._exit(1)
        
        return exit_code

    except ImportError as e:
        error_msg = f"Ошибка импорта модулей: {e}"
        logger.critical(error_msg)
        QMessageBox.critical(None, "Критическая ошибка", error_msg)
        return 1

    except Exception as e:
        error_msg = f"Критическая ошибка приложения: {e}"
        logger.critical(error_msg, exc_info=True)
        QMessageBox.critical(None, "Критическая ошибка",
                             f"Не удалось запустить приложение:\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())