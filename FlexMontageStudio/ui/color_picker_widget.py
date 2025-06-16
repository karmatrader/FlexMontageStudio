"""
Виджет для выбора цвета с палитрой
"""
import logging
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QColorDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

logger = logging.getLogger(__name__)

class ColorPickerWidget(QWidget):
    """Виджет для выбора цвета с палитрой"""
    
    # Сигнал при изменении цвета
    color_changed = Signal(str)  # Отправляет цвет в формате &HBBGGRR
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_color = QColor(255, 255, 255)  # Белый по умолчанию
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Текстовое поле для ввода цвета
        self.color_entry = QLineEdit()
        self.color_entry.setMinimumWidth(100)
        self.color_entry.setPlaceholderText("&HFFFFFF")
        self.color_entry.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.color_entry)
        
        # Кнопка выбора цвета
        self.color_button = QPushButton()
        self.color_button.setFixedSize(30, 24)
        self.color_button.clicked.connect(self.open_color_dialog)
        self.update_button_color()
        layout.addWidget(self.color_button)
        
    def rgb_to_ass_format(self, color: QColor) -> str:
        """Преобразование QColor в формат &HBBGGRR"""
        r = color.red()
        g = color.green()
        b = color.blue()
        return f"&H{b:02X}{g:02X}{r:02X}"
    
    def ass_format_to_rgb(self, ass_color: str) -> QColor:
        """Преобразование из формата &HBBGGRR в QColor"""
        try:
            # Убираем префикс &H
            if ass_color.startswith('&H'):
                hex_color = ass_color[2:]
            else:
                hex_color = ass_color
            
            # Если цвет в формате BBGGRR (6 символов)
            if len(hex_color) == 6:
                # Конвертируем из BBGGRR в RGB
                bb = int(hex_color[0:2], 16)
                gg = int(hex_color[2:4], 16)
                rr = int(hex_color[4:6], 16)
                
                return QColor(rr, gg, bb)
            else:
                # Если формат не распознан, возвращаем белый
                return QColor(255, 255, 255)
                
        except Exception as e:
            logger.warning(f"Ошибка преобразования цвета {ass_color}: {e}")
            return QColor(255, 255, 255)
    
    def update_button_color(self):
        """Обновление цвета кнопки"""
        color_hex = self.current_color.name()
        self.color_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color_hex};
                border: 1px solid #666;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border: 2px solid #999;
            }}
        """)
    
    def on_text_changed(self, text: str):
        """Обработка изменения текста"""
        if text:
            # Преобразуем введенный текст в цвет
            new_color = self.ass_format_to_rgb(text)
            if new_color != self.current_color:
                self.current_color = new_color
                self.update_button_color()
                self.color_changed.emit(text)
    
    def open_color_dialog(self):
        """Открытие диалога выбора цвета"""
        color = QColorDialog.getColor(self.current_color, self, "Выберите цвет")
        
        if color.isValid():
            self.current_color = color
            # Преобразуем в ASS формат и обновляем поле
            ass_color = self.rgb_to_ass_format(color)
            self.color_entry.setText(ass_color)
            self.update_button_color()
            self.color_changed.emit(ass_color)
    
    def set_color(self, ass_color: str):
        """Установка цвета из внешнего источника"""
        self.color_entry.setText(ass_color)
        self.current_color = self.ass_format_to_rgb(ass_color)
        self.update_button_color()
    
    def get_color(self) -> str:
        """Получение текущего цвета в формате ASS"""
        return self.color_entry.text() or "&HFFFFFF"
    
    def setText(self, color: str):
        """Совместимость с QLineEdit - установка цвета через текст"""
        self.set_color(color)
    
    def text(self) -> str:
        """Совместимость с QLineEdit - получение текста"""
        return self.get_color()