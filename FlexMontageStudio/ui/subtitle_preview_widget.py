"""
Виджет для визуального предпросмотра субтитров
"""
import logging
import platform
from typing import Dict, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsRectItem, QFrame, QPushButton
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPen, QBrush, QColor, QFont, QPainter, QPainterPath
)

logger = logging.getLogger(__name__)

class OutlinedTextItem(QGraphicsTextItem):
    """Графический элемент текста с обводкой и тенью"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.outline_color = QColor(0, 0, 0)
        self.outline_thickness = 2
        self.shadow_color = QColor(80, 80, 80)
        self.shadow_offset = QPointF(2, 2)
        self.shadow_alpha = 128
    
    def set_outline(self, color: QColor, thickness: int):
        """Установка параметров обводки"""
        self.outline_color = color
        self.outline_thickness = thickness
        self.update()
    
    def set_shadow(self, color: QColor, offset: QPointF, alpha: int):
        """Установка параметров тени"""
        self.shadow_color = color
        self.shadow_offset = offset
        self.shadow_alpha = alpha
        self.update()
    
    def paint(self, painter, option, widget):
        """Отрисовка текста с обводкой и тенью"""
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Получаем текст и шрифт
        text = self.toPlainText()
        font = self.font()
        
        # Создаем путь для текста с поддержкой переносов строк и центрированием
        path = QPainterPath()
        lines = text.split('\n')
        line_height = font.pixelSize() if font.pixelSize() > 0 else font.pointSize() * 1.2
        
        # Вычисляем ширину каждой строки для центрирования
        from PySide6.QtGui import QFontMetrics
        font_metrics = QFontMetrics(font)
        line_widths = [font_metrics.horizontalAdvance(line) for line in lines]
        max_width = max(line_widths) if line_widths else 0
        
        for i, line in enumerate(lines):
            y_offset = i * line_height
            # Центрируем каждую строку относительно самой широкой строки
            x_offset = (max_width - line_widths[i]) / 2
            path.addText(x_offset, y_offset, font, line)
        
        # Рисуем тень
        if self.shadow_alpha > 0:
            shadow_color = QColor(self.shadow_color)
            shadow_color.setAlpha(self.shadow_alpha)
            painter.setPen(QPen(shadow_color, 1))
            painter.setBrush(QBrush(shadow_color))
            
            painter.save()
            painter.translate(self.shadow_offset)
            painter.drawPath(path)
            painter.restore()
        
        # Рисуем обводку
        if self.outline_thickness > 0:
            pen = QPen(self.outline_color, self.outline_thickness * 2)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        
        # Рисуем основной текст
        painter.setPen(QPen(self.defaultTextColor()))
        painter.setBrush(QBrush(self.defaultTextColor()))
        painter.drawPath(path)

class SubtitlePreviewWidget(QWidget):
    """Виджет для предпросмотра субтитров"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_width = 1920
        self.video_height = 1080
        self.scale_factor = 0.3  # Масштаб для отображения - идентично редактору логотипов
        self.subtitle_item = None
        self.backdrop_item = None
        
        self.setup_ui()
    
    def get_system_font(self) -> str:
        """Получение системного шрифта в зависимости от ОС"""
        system = platform.system().lower()
        
        if system == 'windows':
            # Windows - поддержка кириллицы
            return 'Segoe UI'
        elif system == 'darwin':  # macOS
            # macOS - системный шрифт San Francisco или Helvetica Neue
            return 'SF Pro Display'
        else:  # Linux и другие
            return 'DejaVu Sans'
        
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # Устанавливаем точно такое же расстояние как в редакторе логотипов
        
        # Заголовок убран - он добавляется автоматически в main_window.py
        
        # Графическая сцена - полностью идентичная редактору логотипов
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setMinimumHeight(350)
        
        # Настройки выравнивания для идентичности с редактором логотипов
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setContentsMargins(0, 0, 0, 0)
        
        # Настройка сцены (пропорции 16:9) - полностью идентично редактору логотипов
        scene_width = self.video_width * self.scale_factor
        scene_height = self.video_height * self.scale_factor
        self.scene.setSceneRect(0, 0, scene_width, scene_height)
        
        # Фон сцены (имитация экрана) - полностью идентично редактору логотипов
        bg_rect = QGraphicsRectItem(0, 0, scene_width, scene_height)
        bg_rect.setBrush(QBrush(QColor(40, 40, 40)))
        bg_rect.setPen(QPen(QColor(100, 100, 100), 2))
        self.scene.addItem(bg_rect)
        
        # Подпись размера - полностью идентично редактору логотипов
        size_text = QGraphicsTextItem(f"{self.video_width}×{self.video_height}")
        size_text.setDefaultTextColor(QColor(200, 200, 200))
        size_text.setFont(QFont("Arial", 10))
        size_text.setPos(10, 10)
        self.scene.addItem(size_text)
        
        layout.addWidget(self.view)
        
        # Область кнопок - идентичная структуре редактора логотипов
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Невидимая кнопка для идентичного layout с редактором логотипов
        invisible_btn = QPushButton("Placeholder")
        invisible_btn.setVisible(False)  # Скрываем кнопку
        button_layout.addWidget(invisible_btn)
        
        layout.addLayout(button_layout)
        
        # Показываем пример субтитров с настройками по умолчанию
        self.create_sample_subtitle()
        
    def create_sample_subtitle(self):
        """Создание примера субтитров для демонстрации"""
        self.update_subtitle_preview({
            'subtitle_fontsize': 100,  # Оптимальный размер для предпросмотра
            'subtitle_font_color': '&HFFFFFF',
            'subtitle_use_backdrop': False,
            'subtitle_back_color': '&H000000',
            'subtitle_outline_thickness': 4,  # Стандартная толщина обводки
            'subtitle_outline_color': '&H000000',
            'subtitle_shadow_thickness': 1,
            'subtitle_shadow_color': '&H333333',
            'subtitle_shadow_alpha': 50,
            'subtitle_shadow_offset_x': 2,
            'subtitle_shadow_offset_y': 2,
            'subtitle_margin_v': 20  # Стандартный отступ
        })
        
    def hex_color_to_rgb(self, hex_color: str) -> QColor:
        """Преобразование цвета из формата &HBBGGRR в QColor"""
        try:
            # Убираем префикс &H
            if hex_color.startswith('&H'):
                hex_color = hex_color[2:]
            
            # Если цвет в формате BBGGRR (6 символов)
            if len(hex_color) == 6:
                # Конвертируем из BBGGRR в RRGGBB
                bb = hex_color[0:2]
                gg = hex_color[2:4]
                rr = hex_color[4:6]
                rgb_hex = rr + gg + bb
                
                # Создаем QColor
                return QColor(f"#{rgb_hex}")
            else:
                # Если формат не распознан, возвращаем белый
                return QColor(255, 255, 255)
                
        except Exception as e:
            logger.warning(f"Ошибка преобразования цвета {hex_color}: {e}")
            return QColor(255, 255, 255)
    
    def update_subtitle_preview(self, config: Dict[str, Any]):
        """Обновление предпросмотра субтитров"""
        try:
            # Удаляем предыдущие субтитры если есть
            if self.subtitle_item:
                self.scene.removeItem(self.subtitle_item)
                self.subtitle_item = None
                
            if self.backdrop_item:
                self.scene.removeItem(self.backdrop_item)
                self.backdrop_item = None
            
            # Пример текста субтитров (два ряда для демонстрации)
            sample_text = "Пример субтитров\nв два ряда"
            
            # Получаем параметры с безопасным преобразованием
            def safe_int(value, default):
                """Безопасное преобразование в int"""
                try:
                    if isinstance(value, str) and value.strip() == '':
                        return default
                    return int(value)
                except (ValueError, TypeError):
                    return default
            
            fontsize = safe_int(config.get('subtitle_fontsize', 110), 110)
            font_color = self.hex_color_to_rgb(config.get('subtitle_font_color', '&HFFFFFF'))
            use_backdrop = config.get('subtitle_use_backdrop', False)
            back_color = self.hex_color_to_rgb(config.get('subtitle_back_color', '&H000000'))
            outline_thickness = safe_int(config.get('subtitle_outline_thickness', 4), 4)
            outline_color = self.hex_color_to_rgb(config.get('subtitle_outline_color', '&H000000'))
            shadow_color = self.hex_color_to_rgb(config.get('subtitle_shadow_color', '&H333333'))
            shadow_offset_x = safe_int(config.get('subtitle_shadow_offset_x', 2), 2)
            shadow_offset_y = safe_int(config.get('subtitle_shadow_offset_y', 2), 2)
            shadow_alpha = safe_int(config.get('subtitle_shadow_alpha', 50), 50)
            margin_v = safe_int(config.get('subtitle_margin_v', 20), 20)
            
            # Масштабируем размер шрифта для предпросмотра
            scaled_fontsize = int(fontsize * self.scale_factor)
            scaled_outline = max(1, int(outline_thickness * self.scale_factor))
            scaled_shadow_x = int(shadow_offset_x * self.scale_factor)
            scaled_shadow_y = int(shadow_offset_y * self.scale_factor)
            
            # Создаем элемент текста с эффектами
            self.subtitle_item = OutlinedTextItem(sample_text)
            
            # Настраиваем шрифт с системным шрифтом
            system_font = self.get_system_font()
            font = QFont(system_font, scaled_fontsize, QFont.Bold)
            self.subtitle_item.setFont(font)
            self.subtitle_item.setDefaultTextColor(font_color)
            
            # Настраиваем эффекты
            self.subtitle_item.set_outline(outline_color, scaled_outline)
            self.subtitle_item.set_shadow(shadow_color, QPointF(scaled_shadow_x, scaled_shadow_y), shadow_alpha)
            
            # Позиционируем субтитры по центру экрана для лучшего предпросмотра
            text_rect = self.subtitle_item.boundingRect()
            x = (self.scene.width() - text_rect.width()) / 2
            y = (self.scene.height() - text_rect.height()) / 2
            
            # Убеждаемся что текст помещается в сцену
            if x < 0:
                x = 5  # Минимальный отступ слева
            if x + text_rect.width() > self.scene.width():
                x = self.scene.width() - text_rect.width() - 5  # Минимальный отступ справа
            if y < 0:
                y = 5  # Минимальный отступ сверху
            
            # Создаем подложку если нужно
            if use_backdrop:
                backdrop_rect = QRectF(
                    x - 10, y - 5,
                    text_rect.width() + 20, text_rect.height() + 10
                )
                self.backdrop_item = QGraphicsRectItem(backdrop_rect)
                self.backdrop_item.setBrush(QBrush(back_color))
                self.backdrop_item.setPen(QPen(Qt.NoPen))
                self.backdrop_item.setOpacity(0.7)
                self.scene.addItem(self.backdrop_item)
            
            # Устанавливаем позицию текста
            self.subtitle_item.setPos(x, y)
            
            # Добавляем на сцену
            self.scene.addItem(self.subtitle_item)
            
            logger.debug(f"Субтитры обновлены: размер={scaled_fontsize}, цвет={font_color.name()}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления предпросмотра субтитров: {e}")
    
    def clear_preview(self):
        """Очистка предпросмотра"""
        if self.subtitle_item:
            self.scene.removeItem(self.subtitle_item)
            self.subtitle_item = None
            
        if self.backdrop_item:
            self.scene.removeItem(self.backdrop_item)
            self.backdrop_item = None