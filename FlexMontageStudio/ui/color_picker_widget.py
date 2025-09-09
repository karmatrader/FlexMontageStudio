"""
Виджет для выбора цвета - кнопка-палитра с диалогом выбора
"""
import logging
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QColorDialog
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
        self.current_color_str = "&HFFFFFF"  # Белый по умолчанию
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Кнопка-палитра цвета
        self.color_button = QPushButton()
        self.color_button.setFixedSize(100, 24)
        self.color_button.clicked.connect(self._open_color_dialog)
        layout.addWidget(self.color_button)
        
        # Устанавливаем белый цвет по умолчанию
        self.current_color_str = "&HFFFFFF"
        self._update_button_color()
        
    def _update_button_color(self):
        """Обновление цвета кнопки"""
        try:
            # Конвертируем &HBBGGRR в RGB
            rgb_color = self._convert_hex_to_rgb(self.current_color_str)
            self.color_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {rgb_color};
                    border: 1px solid #666666;
                    border-radius: 3px;
                    min-width: 100px;
                }}
                QPushButton:hover {{
                    border: 2px solid #12BAC4;
                }}
                QPushButton:pressed {{
                    border: 2px solid #FFFFFF;
                }}
            """)
        except Exception as e:
            logger.warning(f"Ошибка обновления цвета кнопки: {e}")
            # Fallback на белый цвет
            self.color_button.setStyleSheet("""
                QPushButton {
                    background-color: #FFFFFF;
                    border: 1px solid #666666;
                    border-radius: 3px;
                    min-width: 100px;
                }
            """)
    
    def _convert_hex_to_rgb(self, hex_color: str) -> str:
        """Конвертация формата &HBBGGRR в #RRGGBB"""
        try:
            # Убираем &H и берем последние 6 символов
            if hex_color.startswith("&H"):
                hex_str = hex_color[2:]
            else:
                hex_str = hex_color.lstrip("#")
            
            # Если меньше 6 символов, дополняем нулями
            hex_str = hex_str.zfill(6)
            
            # В FFmpeg формате: BBGGRR, нужно преобразовать в RRGGBB
            if len(hex_str) == 6:
                # Меняем местами BB GG RR -> RR GG BB
                bb = hex_str[0:2]
                gg = hex_str[2:4] 
                rr = hex_str[4:6]
                rgb_hex = f"#{rr}{gg}{bb}"
            else:
                rgb_hex = f"#{hex_str}"
            
            return rgb_hex
            
        except Exception as e:
            logger.warning(f"Ошибка конвертации цвета {hex_color}: {e}")
            return "#FFFFFF"  # Fallback на белый
    
    def get_color(self) -> str:
        """Получение текущего выбранного цвета"""
        return self.current_color_str
    
    def set_color(self, hex_color: str):
        """Установка цвета программно"""
        try:
            self.current_color_str = hex_color
            self._update_button_color()
            logger.debug(f"🎨 Установлен цвет: {hex_color}")
        except Exception as e:
            logger.error(f"Ошибка установки цвета: {e}")
    
    def text(self) -> str:
        """Совместимость с QLineEdit - возвращает текущий цвет"""
        return self.current_color_str
    
    def setText(self, color: str):
        """Совместимость с QLineEdit - устанавливает цвет"""
        self.set_color(color)
    
    def _open_color_dialog(self):
        """Открытие диалога выбора цвета"""
        try:
            # Конвертируем текущий цвет в QColor для диалога
            current_qcolor = self._convert_ass_to_qcolor(self.current_color_str)
            
            # Открываем диалог выбора цвета
            color = QColorDialog.getColor(current_qcolor, self, "Выберите цвет")
            
            if color.isValid():
                # Конвертируем выбранный цвет в ASS формат
                ass_color = self._convert_qcolor_to_ass(color)
                
                # Устанавливаем новый цвет
                self.current_color_str = ass_color
                self._update_button_color()
                
                # Отправляем сигнал об изменении
                self.color_changed.emit(ass_color)
                
                logger.debug(f"🎨 Выбран цвет: {ass_color}")
                
        except Exception as e:
            logger.error(f"Ошибка при открытии диалога выбора цвета: {e}")
    
    def _convert_ass_to_qcolor(self, ass_color: str) -> QColor:
        """Конвертация из ASS формата &HBBGGRR в QColor"""
        try:
            if ass_color.startswith("&H"):
                hex_str = ass_color[2:]
            else:
                hex_str = ass_color.lstrip("#")
            
            hex_str = hex_str.zfill(6)
            
            # В ASS формате: BBGGRR
            bb = int(hex_str[0:2], 16)
            gg = int(hex_str[2:4], 16) 
            rr = int(hex_str[4:6], 16)
            
            return QColor(rr, gg, bb)
            
        except Exception as e:
            logger.warning(f"Ошибка конвертации ASS в QColor {ass_color}: {e}")
            return QColor(255, 255, 255)  # Fallback на белый
    
    def _convert_qcolor_to_ass(self, qcolor: QColor) -> str:
        """Конвертация QColor в ASS формат &HBBGGRR"""
        try:
            r = qcolor.red()
            g = qcolor.green()
            b = qcolor.blue()
            
            # Формат ASS: &HBBGGRR
            return f"&H{b:02X}{g:02X}{r:02X}"
            
        except Exception as e:
            logger.warning(f"Ошибка конвертации QColor в ASS: {e}")
            return "&HFFFFFF"  # Fallback на белый