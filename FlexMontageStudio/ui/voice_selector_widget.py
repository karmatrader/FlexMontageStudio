"""
Виджет для выбора голоса из библиотеки ElevenLabs
"""
import asyncio
import logging
import tempfile
import subprocess
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

# Функция для скрытия окон консоли на Windows
def run_subprocess_hidden(*args, **kwargs):
    """Запуск subprocess с скрытой консолью на Windows"""
    try:
        # Более универсальная проверка Windows (включая скомпилированные приложения)
        if (os.name == 'nt' or 'win' in sys.platform.lower()) and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass  # Если не удалось определить ОС, продолжаем без флагов
    return subprocess.run(*args, **kwargs)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QLineEdit, QProgressBar, QMessageBox, QDialog,
    QTextEdit, QGroupBox, QGridLayout
)
from PySide6.QtCore import QThread, Signal, Qt
from voice_library_manager import VoiceLibraryManager, VoiceInfo, APIKeyManager
from ffmpeg_utils import get_ffmpeg_path
from core.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class VoiceLoaderThread(QThread):
    """Поток для загрузки голосов"""
    voices_loaded = Signal(list)  # List[VoiceInfo]
    error_occurred = Signal(str)
    progress_updated = Signal(str)

    def __init__(self, api_key: str, proxy_config: Dict, manager: VoiceLibraryManager,
                 force_refresh: bool = False):
        super().__init__()
        self.api_key = api_key
        self.proxy_config = proxy_config
        self.voice_manager = manager
        self.force_refresh = force_refresh

    def run(self):
        """Запуск загрузки голосов"""
        try:
            self.progress_updated.emit("Загрузка голосов из ElevenLabs...")

            # Создаем новый цикл событий для потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                voices = loop.run_until_complete(
                    self.voice_manager.get_public_voices(
                        self.api_key,
                        self.proxy_config,
                        self.force_refresh
                    )
                )

                self.progress_updated.emit(f"Загружено {len(voices)} голосов")
                self.voices_loaded.emit(voices)

            finally:
                loop.close()

        except Exception as e:
            logger.error(f"Ошибка загрузки голосов: {e}")
            self.error_occurred.emit(str(e))


class VoicePreviewThread(QThread):
    """Поток для предпросмотра голоса"""
    preview_ready = Signal(bytes)
    error_occurred = Signal(str)
    progress_updated = Signal(str)

    def __init__(self, voice_id: str, api_key: str, proxy_config: Dict,
                 manager: VoiceLibraryManager, sample_text: str = ""):
        super().__init__()
        self.voice_id = voice_id
        self.api_key = api_key
        self.proxy_config = proxy_config
        self.voice_manager = manager
        self.sample_text = sample_text or "Привет! Это предпросмотр голоса для FlexMontage Studio."

    def run(self):
        """Запуск генерации предпросмотра"""
        try:
            self.progress_updated.emit("Генерация предпросмотра...")

            # Создаем новый цикл событий для потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                audio_data = loop.run_until_complete(
                    self.voice_manager.preview_voice(
                        self.voice_id,
                        self.api_key,
                        self.sample_text,
                        self.proxy_config
                    )
                )

                if audio_data == "LIMIT_REACHED":
                    self.error_occurred.emit("VOICE_LIMIT_REACHED")
                elif audio_data == "QUOTA_EXCEEDED":
                    self.error_occurred.emit("QUOTA_EXCEEDED")
                elif audio_data:
                    self.progress_updated.emit("Предпросмотр готов")
                    self.preview_ready.emit(audio_data)
                else:
                    self.error_occurred.emit("Не удалось сгенерировать предпросмотр")

            finally:
                loop.close()

        except Exception as e:
            logger.error(f"Ошибка генерации предпросмотра: {e}")
            self.error_occurred.emit(str(e))


class VoiceDetailsDialog(QDialog):
    """Диалог с подробной информацией о голосе"""

    def __init__(self, voice: VoiceInfo, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.setWindowTitle(f"Подробности голоса: {voice.name}")
        self.setMinimumSize(450, 350)
        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # Основная информация
        self._create_main_info_group(layout)

        # Характеристики голоса
        self._create_characteristics_group(layout)

        # Описание
        self._create_description_group(layout)

        # Технические данные
        self._create_technical_group(layout)

        # Кнопки
        self._create_buttons(layout)

    def _create_main_info_group(self, parent_layout):
        """Создание группы основной информации"""
        info_group = QGroupBox("Основная информация")
        info_layout = QGridLayout(info_group)

        # Имя
        info_layout.addWidget(QLabel("Имя:"), 0, 0)
        name_label = QLabel(self.voice.name)
        name_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_label, 0, 1)

        # Категория
        if self.voice.category:
            info_layout.addWidget(QLabel("Категория:"), 1, 0)
            info_layout.addWidget(QLabel(self.voice.category), 1, 1)

        # Область применения
        if self.voice.use_case:
            info_layout.addWidget(QLabel("Область применения:"), 2, 0)
            info_layout.addWidget(QLabel(self.voice.use_case), 2, 1)

        parent_layout.addWidget(info_group)

    def _create_characteristics_group(self, parent_layout):
        """Создание группы характеристик"""
        if not any([self.voice.language, self.voice.gender, self.voice.age, self.voice.accent]):
            return

        char_group = QGroupBox("Характеристики")
        char_layout = QGridLayout(char_group)

        row = 0
        if self.voice.language:
            char_layout.addWidget(QLabel("Язык:"), row, 0)
            char_layout.addWidget(QLabel(self.voice.language), row, 1)
            row += 1

        if self.voice.gender:
            char_layout.addWidget(QLabel("Пол:"), row, 0)
            char_layout.addWidget(QLabel(self.voice.gender), row, 1)
            row += 1

        if self.voice.age:
            char_layout.addWidget(QLabel("Возраст:"), row, 0)
            char_layout.addWidget(QLabel(self.voice.age), row, 1)
            row += 1

        if self.voice.accent:
            char_layout.addWidget(QLabel("Акцент:"), row, 0)
            char_layout.addWidget(QLabel(self.voice.accent), row, 1)
            row += 1

        parent_layout.addWidget(char_group)

    def _create_description_group(self, parent_layout):
        """Создание группы описания"""
        if not self.voice.description:
            return

        desc_group = QGroupBox("Описание")
        desc_layout = QVBoxLayout(desc_group)
        desc_text = QTextEdit()
        desc_text.setPlainText(self.voice.description)
        desc_text.setReadOnly(True)
        desc_text.setMaximumHeight(80)
        desc_layout.addWidget(desc_text)
        parent_layout.addWidget(desc_group)

    def _create_technical_group(self, parent_layout):
        """Создание группы технических данных"""
        tech_group = QGroupBox("Технические данные")
        tech_layout = QGridLayout(tech_group)

        # ID голоса
        tech_layout.addWidget(QLabel("ID голоса:"), 0, 0)
        voice_id_edit = QLineEdit(self.voice.voice_id)
        voice_id_edit.setReadOnly(True)
        tech_layout.addWidget(voice_id_edit, 0, 1)

        # Оригинальный ID
        tech_layout.addWidget(QLabel("Оригинальный ID:"), 1, 0)
        orig_id_edit = QLineEdit(self.voice.original_voice_id)
        orig_id_edit.setReadOnly(True)
        tech_layout.addWidget(orig_id_edit, 1, 1)

        # ID владельца
        tech_layout.addWidget(QLabel("ID владельца:"), 2, 0)
        owner_id_edit = QLineEdit(self.voice.public_owner_id)
        owner_id_edit.setReadOnly(True)
        tech_layout.addWidget(owner_id_edit, 2, 1)

        parent_layout.addWidget(tech_group)

    def _create_buttons(self, parent_layout):
        """Создание кнопок"""
        button_layout = QHBoxLayout()

        # Кнопка копирования ID
        copy_button = QPushButton("📋 Копировать ID")
        copy_button.clicked.connect(self.copy_voice_ids)
        button_layout.addWidget(copy_button)

        button_layout.addStretch()

        # Кнопка закрытия
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)

        parent_layout.addLayout(button_layout)

    def copy_voice_ids(self):
        """Копирование ID голоса в буфер обмена"""
        try:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()

            text = f"Voice ID: {self.voice.voice_id}\n" \
                   f"Original Voice ID: {self.voice.original_voice_id}\n" \
                   f"Public Owner ID: {self.voice.public_owner_id}"

            clipboard.setText(text)

            # Показываем уведомление
            QMessageBox.information(self, "Успех", "ID голоса скопированы в буфер обмена!")

        except Exception as e:
            logger.error(f"Ошибка копирования в буфер обмена: {e}")


class VoiceSelectorWidget(QWidget):
    """Виджет для выбора голоса из библиотеки ElevenLabs"""

    voice_selected = Signal(str, str)  # original_voice_id, public_owner_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.voice_manager = VoiceLibraryManager()
        self.current_voices: List[VoiceInfo] = []
        self.current_api_key = ""
        self.current_proxy_config = {}

        self.voice_loader_thread: Optional[VoiceLoaderThread] = None
        self.preview_thread: Optional[VoicePreviewThread] = None

        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Заголовок и кнопка обновления
        header_layout = QHBoxLayout()
        header_label = QLabel("Выбор голоса из библиотеки ElevenLabs:")
        header_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        self.refresh_button = QPushButton("🔄 Обновить")
        self.refresh_button.setToolTip("Обновить список голосов")
        self.refresh_button.clicked.connect(self.refresh_voices)
        header_layout.addWidget(self.refresh_button)

        layout.addLayout(header_layout)

        # Поиск
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск:"))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Введите имя голоса или описание...")
        self.search_edit.textChanged.connect(self.filter_voices)
        search_layout.addWidget(self.search_edit)

        layout.addLayout(search_layout)

        # Выпадающий список голосов
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumHeight(30)
        self.voice_combo.currentIndexChanged.connect(self.on_voice_selected)
        layout.addWidget(self.voice_combo)

        # Кнопки управления
        buttons_layout = QHBoxLayout()

        self.details_button = QPushButton("ℹ️ Подробности")
        self.details_button.setToolTip("Показать подробную информацию о голосе")
        self.details_button.clicked.connect(self.show_voice_details)
        self.details_button.setEnabled(False)
        buttons_layout.addWidget(self.details_button)

        self.preview_button = QPushButton("Предпросмотр")
        self.preview_button.setToolTip("Прослушать образец голоса")
        self.preview_button.clicked.connect(self.preview_voice)
        self.preview_button.setEnabled(False)
        buttons_layout.addWidget(self.preview_button)

        buttons_layout.addStretch()

        self.use_button = QPushButton("✓ Использовать этот голос")
        self.use_button.setToolTip("Выбрать этот голос для использования")
        self.use_button.clicked.connect(self.use_selected_voice)
        self.use_button.setEnabled(False)
        buttons_layout.addWidget(self.use_button)

        layout.addLayout(buttons_layout)

        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Статус
        self.status_label = QLabel("Для начала загрузите список голосов")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.status_label)

    def set_api_config(self, api_key: str, proxy_config: Dict):
        """Установка конфигурации API"""
        self.current_api_key = api_key
        self.current_proxy_config = proxy_config

        # Автоматически загружаем голоса если есть кэш
        if not self.voice_manager.cache.is_expired() and self.voice_manager.cache.voices:
            self.current_voices = self.voice_manager.cache.voices
            self.update_voice_combo()
            self.status_label.setText(f"Загружено {len(self.current_voices)} голосов из кэша")
        else:
            self.status_label.setText("Нажмите 'Обновить' для загрузки голосов")

    def refresh_voices(self, force: bool = False):
        """Обновление списка голосов"""
        # Пытаемся получить API ключ из настроек канала
        api_key = self._get_api_key_from_config()
        
        if not api_key:
            QMessageBox.warning(self, "Предупреждение",
                                "Сначала укажите API ключ в настройках канала (путь к файлу API ключей)")
            return
            
        # Обновляем текущий ключ
        self.current_api_key = api_key

        # Останавливаем предыдущую загрузку
        if self.voice_loader_thread and self.voice_loader_thread.isRunning():
            self.voice_loader_thread.quit()
            self.voice_loader_thread.wait()

        # Создаем новый поток загрузки
        self.voice_loader_thread = VoiceLoaderThread(
            self.current_api_key,
            self.current_proxy_config,
            self.voice_manager,
            force_refresh=force
        )

        self.voice_loader_thread.voices_loaded.connect(self.on_voices_loaded)
        self.voice_loader_thread.error_occurred.connect(self.on_load_error)
        self.voice_loader_thread.progress_updated.connect(self.on_progress_updated)

        # Настраиваем UI для загрузки
        self.refresh_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Неопределенный прогресс
        self.status_label.setText("Загрузка голосов...")

        # Запускаем загрузку
        self.voice_loader_thread.start()

    def _get_api_key_from_config(self) -> str:
        """Получение API ключа из конфигурации текущего канала"""
        try:
            # Находим главное окно и определяем выбранный канал
            main_window = self.window()
            logger.debug(f"Main window найдено: {type(main_window).__name__}")
            
            # Получаем список выбранных каналов из channel_combo
            selected_channels = []
            if hasattr(main_window, 'channel_combo'):
                selected_channels = main_window.channel_combo.checkedItems()
                logger.debug(f"✅ Найдены выбранные каналы через channel_combo: {selected_channels}")
            else:
                logger.warning("main_window.channel_combo не найден")
                return ""
            
            logger.info(f"Выбранные каналы: {selected_channels}")
            if not selected_channels:
                logger.warning("Канал не выбран")
                return ""
            
            current_channel_name = selected_channels[0]  # Берем первый выбранный
            logger.info(f"✅ Определен выбранный канал: {current_channel_name}")
            
            # Получаем конфигурацию канала
            config_manager = ConfigManager()
            channel_config = config_manager.get_channel_config(current_channel_name)
            
            if not channel_config:
                logger.warning(f"Конфигурация канала '{current_channel_name}' не найдена")
                return ""
            
            # Получаем путь к CSV файлу с API ключами
            csv_file_path = channel_config.get("csv_file_path", "")
            if not csv_file_path:
                logger.warning("Не указан путь к файлу с API ключами в настройках канала")
                return ""
            
            # Получаем API ключ из файла
            api_key_manager = APIKeyManager(csv_file_path)
            api_key = api_key_manager.get_api_key()
            
            if not api_key:
                logger.warning("Не удалось получить API ключ из файла")
                return ""
            
            logger.info(f"API ключ получен из конфигурации канала: {api_key[:8]}...{api_key[-4:]}")
            return api_key
            
        except Exception as e:
            logger.error(f"Ошибка получения API ключа из конфигурации: {e}")
            return ""

    def on_voices_loaded(self, voices: List[VoiceInfo]):
        """Обработка успешной загрузки голосов"""
        self.current_voices = voices
        self.update_voice_combo()

        # Восстанавливаем UI
        self.refresh_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        if voices:
            self.status_label.setText(f"Загружено {len(voices)} голосов")
        else:
            self.status_label.setText("Публичные голоса не найдены")

    def on_load_error(self, error: str):
        """Обработка ошибки загрузки"""
        self.refresh_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Ошибка загрузки: {error}")

        QMessageBox.critical(self, "Ошибка загрузки голосов",
                             f"Не удалось загрузить голоса:\n{error}")

    def on_progress_updated(self, message: str):
        """Обновление прогресса"""
        self.status_label.setText(message)

    def update_voice_combo(self):
        """Обновление комбобокса с голосами"""
        self.voice_combo.clear()

        if not self.current_voices:
            self.voice_combo.addItem("Нет доступных голосов")
            self.details_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            self.use_button.setEnabled(False)
            return

        # Группируем голоса по языкам
        voices_by_language = {}
        for voice in self.current_voices:
            lang = voice.language or "Неизвестный язык"
            if lang not in voices_by_language:
                voices_by_language[lang] = []
            voices_by_language[lang].append(voice)

        # Добавляем голоса в комбобокс
        for language in sorted(voices_by_language.keys()):
            # Добавляем разделитель языка
            if len(voices_by_language) > 1:
                self.voice_combo.addItem(f"=== {language} ===")
                # Делаем элемент неактивным
                self.voice_combo.model().item(self.voice_combo.count() - 1).setEnabled(False)

            # Добавляем голоса этого языка
            for voice in sorted(voices_by_language[language], key=lambda v: v.name):
                display_text = self._format_voice_display(voice)
                self.voice_combo.addItem(display_text, voice)

        # Включаем кнопки если есть голоса
        self.details_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.use_button.setEnabled(True)

    def _format_voice_display(self, voice: VoiceInfo) -> str:
        """Форматирование отображения голоса в списке"""
        parts = [voice.name]

        # Добавляем характеристики в скобках
        characteristics = []
        if voice.gender:
            characteristics.append(voice.gender)
        if voice.age:
            characteristics.append(voice.age)
        if voice.accent:
            characteristics.append(voice.accent)

        if characteristics:
            parts.append(f"({', '.join(characteristics)})")

        # Добавляем краткое описание
        if voice.description and len(voice.description) > 0:
            desc = voice.description[:40] + "..." if len(voice.description) > 40 else voice.description
            parts.append(f"- {desc}")

        return " ".join(parts)

    def filter_voices(self):
        """Фильтрация голосов по поисковому запросу"""
        if not self.current_voices:
            return

        search_text = self.search_edit.text().strip()

        if not search_text:
            # Показываем все голоса
            filtered_voices = self.current_voices
        else:
            # Фильтруем голоса
            filtered_voices = []
            search_lower = search_text.lower()

            for voice in self.current_voices:
                if (search_lower in voice.name.lower() or
                        search_lower in voice.description.lower() or
                        search_lower in voice.language.lower() or
                        search_lower in voice.gender.lower()):
                    filtered_voices.append(voice)

        # Временно сохраняем полный список и обновляем отображение
        original_voices = self.current_voices
        self.current_voices = filtered_voices
        self.update_voice_combo()
        self.current_voices = original_voices

        # Обновляем статус
        if search_text:
            self.status_label.setText(f"Найдено {len(filtered_voices)} голосов по запросу '{search_text}'")
        else:
            self.status_label.setText(f"Показано {len(filtered_voices)} голосов")

    def on_voice_selected(self, index: int):
        """Обработка выбора голоса"""
        if index < 0:
            return

        voice_data = self.voice_combo.itemData(index)
        if isinstance(voice_data, VoiceInfo):
            # Обновляем состояние кнопок
            self.details_button.setEnabled(True)
            self.preview_button.setEnabled(True)
            self.use_button.setEnabled(True)

    def get_selected_voice(self) -> Optional[VoiceInfo]:
        """Получение выбранного голоса"""
        current_index = self.voice_combo.currentIndex()
        if current_index < 0:
            return None

        voice_data = self.voice_combo.itemData(current_index)
        if isinstance(voice_data, VoiceInfo):
            return voice_data

        return None

    def show_voice_details(self):
        """Показ подробностей о голосе"""
        voice = self.get_selected_voice()
        if not voice:
            QMessageBox.information(self, "Информация", "Выберите голос из списка")
            return

        dialog = VoiceDetailsDialog(voice, self)
        dialog.exec()

    def preview_voice(self):
        """Предпросмотр голоса"""
        voice = self.get_selected_voice()
        if not voice:
            QMessageBox.information(self, "Информация", "Выберите голос из списка")
            return

        # Получаем актуальный API ключ из конфигурации
        api_key = self._get_api_key_from_config()
        if not api_key:
            QMessageBox.warning(self, "Предупреждение",
                                "Сначала укажите API ключ в настройках канала (путь к файлу API ключей)")
            return

        # Останавливаем предыдущий предпросмотр
        if self.preview_thread and self.preview_thread.isRunning():
            self.preview_thread.quit()
            self.preview_thread.wait()

        # Создаем поток для генерации предпросмотра
        self.preview_thread = VoicePreviewThread(
            voice.voice_id,
            api_key,  # Используем актуальный API ключ
            self.current_proxy_config,
            self.voice_manager
        )

        self.preview_thread.preview_ready.connect(self.on_preview_ready)
        self.preview_thread.error_occurred.connect(self.on_preview_error)
        self.preview_thread.progress_updated.connect(self.on_progress_updated)

        # Настраиваем UI
        self.preview_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Запускаем генерацию
        self.preview_thread.start()

    def on_preview_ready(self, audio_data: bytes):
        """Обработка готового предпросмотра"""
        self.preview_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        try:
            # Сохраняем аудио во временный файл
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

            # Воспроизводим аудио
            self.play_audio_file(temp_path)

            # Удаляем временный файл через некоторое время
            import threading
            def cleanup():
                import time
                time.sleep(10)  # Ждем 10 секунд
                try:
                    Path(temp_path).unlink()
                except:
                    pass

            threading.Thread(target=cleanup, daemon=True).start()

        except Exception as e:
            logger.error(f"Ошибка воспроизведения предпросмотра: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось воспроизвести предпросмотр:\n{e}")

    def on_preview_error(self, error: str):
        """Обработка ошибки предпросмотра"""
        self.preview_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        if error == "VOICE_LIMIT_REACHED":
            QMessageBox.information(self, "Лимит операций с голосами",
                                  "Достигнут месячный лимит операций с голосами ElevenLabs.\n"
                                  "Предпросмотр голосов временно недоступен.\n\n"
                                  "Вы можете продолжить использовать выбранные голоса для генерации озвучки.")
        elif error == "QUOTA_EXCEEDED":
            QMessageBox.warning(self, "Превышена квота API",
                               "Превышена квота API ключа для предпросмотра голосов.\n"
                               "Попробуйте обновить список голосов для получения нового API ключа.")
        else:
            QMessageBox.critical(self, "Ошибка предпросмотра",
                                f"Не удалось сгенерировать предпросмотр:\n{error}")

    def play_audio_file(self, file_path: str):
        """Воспроизведение аудиофайла"""
        try:
            import platform
            system = platform.system()

            if system == "Darwin":  # macOS
                run_subprocess_hidden(["afplay", file_path], check=True)
            elif system == "Windows":
                import winsound
                winsound.PlaySound(file_path, winsound.SND_FILENAME)
            else:  # Linux
                # Пробуем разные плееры
                players = ["paplay", "aplay", "mpg123", get_ffmpeg_path().replace("ffmpeg", "ffplay")]
                for player in players:
                    try:
                        run_subprocess_hidden([player, file_path], check=True,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    raise Exception("Не найден подходящий аудиоплеер")

        except Exception as e:
            logger.error(f"Ошибка воспроизведения аудио: {e}")
            QMessageBox.information(self, "Информация",
                                    f"Предпросмотр сгенерирован, но не удалось воспроизвести.\n"
                                    f"Аудиофайл сохранен: {file_path}")

    def use_selected_voice(self):
        """Использование выбранного голоса"""
        voice = self.get_selected_voice()
        if not voice:
            QMessageBox.information(self, "Информация", "Выберите голос из списка")
            return

        # Испускаем сигнал с данными голоса
        self.voice_selected.emit(voice.original_voice_id, voice.public_owner_id)

        # Показываем подтверждение
        QMessageBox.information(self, "Успех",
                                f"Голос '{voice.name}' выбран для использования!")

    def set_current_voice(self, original_voice_id: str, public_owner_id: str):
        """Установка текущего голоса по ID"""
        # Ищем голос в списке
        for i in range(self.voice_combo.count()):
            voice_data = self.voice_combo.itemData(i)
            if isinstance(voice_data, VoiceInfo):
                if (voice_data.original_voice_id == original_voice_id and
                        voice_data.public_owner_id == public_owner_id):
                    self.voice_combo.setCurrentIndex(i)
                    return

        # Если голос не найден, показываем предупреждение
        if original_voice_id and public_owner_id:
            self.status_label.setText(f"Текущий голос не найден в библиотеке. Обновите список голосов.")

    def clear_selection(self):
        """Очистка выбора"""
        self.voice_combo.setCurrentIndex(-1)
        self.details_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.use_button.setEnabled(False)