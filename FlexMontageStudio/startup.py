#!/usr/bin/env python3
"""
FlexMontage Studio - Основная точка входа в приложение
"""
import sys
import os
import logging
import traceback
from pathlib import Path

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

# Импорт отладчика min() вызовов
# Настройки для macOS
if sys.platform == "darwin":
    # Устанавливаем переменные окружения для правильной работы на macOS
    os.environ['QT_MAC_WANTS_LAYER'] = '1'
    os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
    # Принудительно используем /системную тему
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

from ui.main_window import MainWindow
from core.license_manager import LicenseManager
from core.file_api import file_api
from utils.app_paths import get_config_file_path, ensure_config_files_external, create_sample_config_files


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
    """Загрузка стилей приложения через File API"""
    try:
        # Ищем styles.qss внутри приложения (рядом с startup.py)
        styles_path = Path(__file__).parent / 'styles.qss'

        if file_api.exists(styles_path):
            # Используем File API для чтения с кэшированием
            styles_content = file_api.read_text(styles_path)
            app.setStyleSheet(styles_content)
            logging.info(f"✅ Стили успешно загружены через File API: {styles_path}")
        else:
            logging.warning(f"⚠️ Файл styles.qss не найден по пути: {styles_path}")
            logging.warning("Используется стандартный стиль")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки стилей через File API: {e}")


def check_application_license() -> bool:
    """Улучшенная проверка лицензии приложения с множественными стратегиями"""
    # Импорты в начале функции
    from PySide6.QtWidgets import QInputDialog, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
    from PySide6.QtCore import Qt, QSettings
    from utils.app_paths import get_config_file_path
    from core.license_manager import LicenseManager
    
    logger = logging.getLogger(__name__)
    logger.info("🔐 Начинаем проверку лицензии...")

    settings = QSettings("MyCompany", "AutoMontageApp")

    try:
        licenses_path = get_config_file_path('license.json')
        logger.info(f"📄 Путь к лицензиям: {licenses_path}")

        if not licenses_path.exists():
            logger.warning(f"⚠️ Файл лицензий не найден: {licenses_path}")
            
            # Используем новый license_manager для получения HWID
            license_mgr = LicenseManager()
            hwid = license_mgr.get_hwid()
            
            # Создаем простой диалог с кнопкой копирования
            dialog = QDialog()
            dialog.setWindowTitle("Лицензия не найдена")
            dialog.setFixedSize(450, 420)
            
            layout = QVBoxLayout(dialog)
            
            # Основной текст
            main_label = QLabel(
                f"<b>🔑 Файл лицензии не найден!</b><br><br>"
                f"<b>Ваш Hardware ID (HWID):</b><br>"
                f"<code>{hwid}</code><br><br>"
                f"<b>📱 Для получения лицензии:</b><br>"
                f"1. Скопируйте HWID выше<br>"
                f"2. Отправьте его боту:<br>"
                f"   <a href='https://t.me/fms_license_bot' style='color: #12BAC4; text-decoration: underline;'>https://t.me/fms_license_bot</a><br>"
                f"3. Бот пришлет файл лицензии<br>"
                f"4. Поместите файл рядом с приложением<br>"
                f"5. Перезапустите программу<br><br>"
                f"<b>🛒 Купить лицензию на сайте:</b><br>"
                f"   <a href='https://flexmontage.pro' style='color: #12BAC4; text-decoration: underline;'>https://flexmontage.pro</a><br><br>"
                f"⚠️ Лицензия будет работать только на этом компьютере!"
            )
            main_label.setTextFormat(Qt.TextFormat.RichText)
            main_label.setWordWrap(True)
            main_label.linkActivated.connect(lambda url: __import__('webbrowser').open(url))
            layout.addWidget(main_label)
            
            # Кнопки
            buttons_layout = QHBoxLayout()
            
            copy_button = QPushButton("Скопировать HWID")
            copy_button.clicked.connect(lambda: QApplication.clipboard().setText(hwid))
            buttons_layout.addWidget(copy_button)
            
            ok_button = QPushButton("OK")
            ok_button.clicked.connect(dialog.accept)
            ok_button.setDefault(True)
            buttons_layout.addWidget(ok_button)
            
            layout.addLayout(buttons_layout)
            
            dialog.exec()
            return False

        license_manager = LicenseManager(str(licenses_path))
        logger.info("✅ LicenseManager инициализирован")

        # Попытка загрузить сохраненный ключ
        license_key = settings.value("license_key", "")
        logger.info(f"🗝️ Сохраненный ключ: {'найден' if license_key else 'отсутствует'}")

        # Если нет сохраненного ключа, пробуем использовать демо-ключ из файла
        if not license_key:
            logger.info("🔍 Ищем демо-лицензию в файле...")
            demo_key = "ybjL-nS2S-dTim-Xwf4"

            if license_manager.check_license(demo_key):
                logger.info("🎉 Найдена и активирована демо-лицензия")
                settings.setValue("license_key", demo_key)
                return True
            else:
                logger.warning("⚠️ Демо-лицензия не найдена или недействительна")

        # Проверяем сохраненный ключ
        if license_key and license_manager.check_license(license_key):
            logger.info("✅ Сохраненная лицензия действительна")
            return True

        # Если дошли сюда - лицензия не найдена или недействительна
        if license_key:
            logger.warning("⚠️ Сохраненная лицензия недействительна, удаляем")
            settings.remove("license_key")

        # Генерируем и показываем HWID пользователю
        hwid = license_manager.get_hwid()
        
        # Показываем HWID и информацию о получении лицензии
        dialog2 = QDialog()
        dialog2.setWindowTitle("Требуется лицензия - HWID")
        dialog2.setFixedSize(450, 350)
        
        layout2 = QVBoxLayout(dialog2)
        
        # Основной текст
        main_label2 = QLabel(
            f"<b>🔑 FlexMontage Studio - Получение лицензии</b><br><br>"
            f"<b>Ваш Hardware ID (HWID):</b><br>"
            f"<code>{hwid}</code><br><br>"
            f"<b>📱 Для получения лицензии:</b><br>"
            f"1. Скопируйте HWID выше<br>"
            f"2. Отправьте его боту:<br>"
            f"   <a href='https://t.me/fms_license_bot' style='color: #12BAC4; text-decoration: underline;'>https://t.me/fms_license_bot</a><br>"
            f"3. Бот пришлет файл лицензии<br>"
            f"4. Поместите файл рядом с программой<br><br>"
            f"<b>🛒 Купить лицензию на сайте:</b><br>"
            f"   <a href='https://flexmontage.pro' style='color: #12BAC4; text-decoration: underline;'>https://flexmontage.pro</a><br><br>"
            f"⚠️ Лицензия будет работать только на этом компьютере!"
        )
        main_label2.setTextFormat(Qt.TextFormat.RichText)
        main_label2.setWordWrap(True)
        main_label2.linkActivated.connect(lambda url: __import__('webbrowser').open(url))
        layout2.addWidget(main_label2)
        
        # Кнопки
        buttons_layout2 = QHBoxLayout()
        
        copy_button2 = QPushButton("Скопировать HWID")
        copy_button2.clicked.connect(lambda: QApplication.clipboard().setText(hwid))
        buttons_layout2.addWidget(copy_button2)
        
        continue_button = QPushButton("Продолжить")
        continue_button.clicked.connect(dialog2.accept)
        continue_button.setDefault(True)
        buttons_layout2.addWidget(continue_button)
        
        layout2.addLayout(buttons_layout2)
        
        dialog2.exec()

        # Предоставляем пользователю выбор: ввести ключ или закрыть приложение
        
        license_key, ok = QInputDialog.getText(
            None,
            "Ввод лицензионного ключа",
            f"Ваш HWID: {hwid}\n\n"
            "Введите полученный лицензионный ключ\n"
            "или нажмите Cancel для выхода:"
        )

        if not ok or not license_key:
            QMessageBox.information(None, "Закрытие приложения",
                                    "Для работы FlexMontage Studio требуется действительная лицензия.")
            return False

        if not license_manager.check_license(license_key):
            logger.error("❌ Введенная лицензия недействительна")
            QMessageBox.warning(
                None,
                "Недействительная лицензия",
                "Введенный лицензионный ключ недействителен.\n\n"
                "Проверьте правильность ввода или обратитесь в поддержку."
            )
            return False

        # Сохраняем корректный ключ
        settings.setValue("license_key", license_key)
        logger.info("✅ Новая лицензия сохранена и активирована")
        return True

    except Exception as e:
        logger.error(f"❌ Критическая ошибка проверки лицензии: {e}")
        QMessageBox.critical(
            None,
            "Ошибка лицензии",
            f"Произошла ошибка при проверке лицензии:\n{e}\n\n"
            "Обратитесь в техническую поддержку."
        )
        return False


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

        # Инициализация отладчика min() вызовов
        logger.info("🔧 Используем простой отладчик min() вызовов")

        # Создание приложения
        app = QApplication(sys.argv)
        app.setApplicationName("FlexMontage Studio")
        app.setApplicationVersion("1.0")
        app.setOrganizationName("MyCompany")
        
        # Платформенная диагностика
        logger.info(f"🖥️ Платформа: {sys.platform}")
        logger.info(f"🏗️ Frozen: {getattr(sys, 'frozen', False)}")
        if sys.platform == "win32":
            logger.info("🪟 Windows-специфичные настройки...")
            # Настройки для Windows  
            from PySide6.QtCore import Qt
            app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
            logger.info("✅ Windows настройки применены")

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
            except Exception as e:
                logger.warning(f"Ошибка активации NSApplication: {e}")
        else:
            logger.info("Не macOS - пропускаем NSApplication активацию")

        # Улучшенная диагностика системы
        logger.info("🔍 Запуск диагностики системы...")
        try:
            from diagnostic_info import log_diagnostic_info
            log_diagnostic_info()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось записать полную диагностическую информацию: {e}")
            # Fallback - базовая диагностика
            from utils.app_paths import get_app_directory
            app_dir = get_app_directory()
            logger.info(f"🔍 Базовая диагностика:")
            logger.info(f"   sys.executable = {sys.executable}")
            logger.info(f"   get_app_directory() = {app_dir}")
            logger.info(f"   cwd = {os.getcwd()}")
            logger.info(f"   frozen = {getattr(sys, 'frozen', False)}")
            logger.info(f"   platform = {sys.platform}")

        # Проверка и создание конфигурационных файлов (ВСЕГДА, не только для frozen)
        if not ensure_config_files_external():
            logger.info("🔧 Первый запуск - создаём конфигурационные файлы...")

            # Показываем приветственное сообщение только для скомпилированного приложения
            if getattr(sys, 'frozen', False):
                QMessageBox.information(
                    None,
                    "Добро пожаловать в FlexMontage Studio!",
                    "🎉 Это ваш первый запуск!\n\n"
                    "Сейчас создадим конфигурационные файлы с тестовыми данными.\n"
                    "Вы сможете сразу попробовать приложение в работе.\n\n"
                    "Нажмите OK для продолжения..."
                )

            try:
                # Создаем конфигурационные файлы с тестовыми данными
                create_sample_config_files()
                logger.info("✅ Конфигурационные файлы созданы успешно")

                # Показываем результат только для скомпилированного приложения
                if getattr(sys, 'frozen', False):
                    QMessageBox.information(
                        None,
                        "Готово к использованию!",
                        "✅ Конфигурационные файлы созданы!\n\n"
                        "📋 Что создано:\n"
                        "• channels.json - настройки с тестовым каналом\n"
                        "• styles.qss - стили интерфейса\n"
                        "• TestChannel/ - папка с тестовыми данными\n\n"
                        "🔑 Для работы приложения требуется лицензия!\n"
                        "📧 Обратитесь к администратору для получения файла лицензии\n\n"
                        "📝 Также добавьте свои API ключи ElevenLabs в файл api_keys.csv"
                    )

            except Exception as e:
                logger.error(f"❌ Ошибка создания файлов: {e}")
                QMessageBox.critical(
                    None,
                    "Ошибка создания файлов",
                    f"Не удалось создать конфигурационные файлы:\n{e}\n\n"
                    "Проверьте права доступа к папке приложения."
                )
                sys.exit(1)

        # Загрузка стилей
        load_styles(app)

        # Проверка лицензии (ПОСЛЕ создания конфигурационных файлов)
        logger.info("🔐 Проверяем лицензию...")
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

                # Пытаемся еще раз через NSApplication (только для macOS)
                if sys.platform == "darwin":
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

            # Логирование статистики min() вызовов
            logger.info("📊 Статистика min() вызовов при завершении:")
            try:
                from debug_min_simple import log_min_stats
                log_min_stats()
            except ImportError:
                logger.info("Отладочный модуль min() недоступен")

            # Финальная статистика min() вызовов
            pass

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
            # Логирование статистики min() вызовов при ошибке
            logger.info("📊 Статистика min() вызовов при ошибке завершения:")
            try:
                from debug_min_simple import log_min_stats
                log_min_stats()
            except ImportError:
                logger.info("Отладочный модуль min() недоступен")
            # Принудительное завершение в случае ошибки
            import os
            os._exit(1)

        return exit_code

    except ImportError as e:
        error_msg = f"Ошибка импорта модулей: {e}"
        logger.critical(error_msg)
        try:
            from debug_min_simple import log_min_stats
            log_min_stats()
        except ImportError:
            logger.info("Отладочный модуль min() недоступен")
        QMessageBox.critical(None, "Критическая ошибка", error_msg)
        return 1

    except Exception as e:
        error_msg = f"Критическая ошибка приложения: {e}"
        logger.critical("📊 Статистика min() вызовов при критической ошибке:")
        try:
            from debug_min_simple import log_min_stats
            log_min_stats()
        except ImportError:
            logger.info("Отладочный модуль min() недоступен")
        logger.critical(error_msg, exc_info=True)
        QMessageBox.critical(None, "Критическая ошибка",
                             f"Не удалось запустить приложение:\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())