"""
Диалоговые окна для UI
"""
import logging
from typing import Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QWidget, QFileDialog, QLabel, QTextEdit,
    QGroupBox, QGridLayout
)
from PySide6.QtCore import Qt

from voice_library_manager import VoiceInfo

logger = logging.getLogger(__name__)


class AddChannelDialog(QDialog):
    """Диалог добавления нового канала"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать новый канал")
        self.setMinimumWidth(500)
        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса"""
        self.layout = QVBoxLayout(self)

        # Форма для основных параметров
        self.form_layout = QFormLayout()
        self.layout.addLayout(self.form_layout)

        # Поле имени канала
        self.channel_name_input = QLineEdit()
        self.channel_name_input.setPlaceholderText("Введите название канала")
        self.form_layout.addRow("Название канала:", self.channel_name_input)

        # Поле столбца канала
        self.channel_column_input = QLineEdit()
        self.channel_column_input.setPlaceholderText("Введите букву столбца (B, C, D и т.д.)")
        self.form_layout.addRow("Столбец канала:", self.channel_column_input)

        # Поля путей
        self.path_inputs = {}
        self._create_path_inputs()

        # Кнопки
        self._create_buttons()

    def _create_path_inputs(self):
        """Создание полей для путей"""
        paths = [
            ("global_xlsx_file_path", "Путь к общему Excel-файлу:", True),
            ("base_path", "Базовый путь:", False),
            ("channel_folder", "Папка канала:", False),
            ("csv_file_path", "Путь к CSV-файлу:", True),
            ("output_directory", "Папка для вывода:", False),
            ("photo_folder", "Папка с фото:", False),
            ("audio_folder", "Папка с аудио:", False),
            ("output_folder", "Папка для готового видео:", False),
            ("logo_path", "Путь к логотипу:", True),
            ("logo2_path", "Путь к дополнительному логотипу:", True),
            ("subscribe_frames_folder", "Папка с кадрами подписки:", False),
            ("background_music_path", "Путь к фоновой музыке:", True)
        ]

        for path_key, label, is_file in paths:
            entry_widget = QWidget()
            entry_layout = QHBoxLayout(entry_widget)
            entry_layout.setContentsMargins(0, 0, 0, 0)

            # Поле ввода
            entry = QLineEdit()
            entry.setMinimumWidth(300)
            entry_layout.addWidget(entry)

            # Кнопка обзора
            browse_button = QPushButton("...")
            browse_button.setObjectName("browse")
            browse_button.setFixedWidth(30)
            browse_button.clicked.connect(
                lambda checked, e=entry, file=is_file: self.browse_path(e, file)
            )
            entry_layout.addWidget(browse_button)

            self.form_layout.addRow(label, entry_widget)
            self.path_inputs[path_key] = entry

    def _create_buttons(self):
        """Создание кнопок управления"""
        self.button_layout = QHBoxLayout()

        self.create_button = QPushButton("Создать канал")
        self.create_button.setObjectName("dialog")
        self.create_button.clicked.connect(self.accept)

        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("dialog")
        self.cancel_button.clicked.connect(self.reject)

        self.button_layout.addWidget(self.create_button)
        self.button_layout.addWidget(self.cancel_button)
        self.layout.addLayout(self.button_layout)

    def browse_path(self, entry: QLineEdit, is_file: bool):
        """Обзор пути к файлу или папке"""
        if is_file:
            path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        else:
            path = QFileDialog.getExistingDirectory(self, "Выберите папку")

        if path:
            entry.setText(path)

    def get_channel_data(self) -> Dict[str, Any]:
        """Получение данных канала из формы"""
        return {
            "name": self.channel_name_input.text().strip(),
            "channel_column": self.channel_column_input.text().upper().strip(),
            "paths": {key: input_field.text().strip()
                      for key, input_field in self.path_inputs.items()}
        }

    def validate_input(self) -> tuple[bool, str]:
        """
        Валидация введенных данных

        Returns:
            tuple: (is_valid, error_message)
        """
        channel_name = self.channel_name_input.text().strip()
        if not channel_name:
            return False, "Название канала не может быть пустым!"

        channel_column = self.channel_column_input.text().upper().strip()
        if not channel_column or not channel_column.isalpha() or ord(channel_column) < ord('B'):
            return False, "Столбец канала должен быть буквой B или выше!"

        # Проверка обязательных путей
        required_paths = [
            "global_xlsx_file_path", "base_path", "channel_folder",
            "csv_file_path", "output_directory"
        ]

        for path_key in required_paths:
            if not self.path_inputs[path_key].text().strip():
                return False, f"Поле '{path_key}' не может быть пустым!"

        return True, ""

    def accept(self):
        """Переопределение accept для валидации"""
        is_valid, error_message = self.validate_input()
        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Ошибка валидации", error_message)
            return

        super().accept()


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
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Успех", "ID голоса скопированы в буфер обмена!")

        except Exception as e:
            logger.error(f"Ошибка копирования в буфер обмена: {e}")