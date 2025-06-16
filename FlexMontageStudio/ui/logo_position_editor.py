"""
Виджет для визуального редактирования позиций и размеров логотипов
"""
import math
from typing import Tuple, Optional, Dict, Any
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsTextItem,
    QPushButton, QFileDialog, QFrame
)
from PySide6.QtCore import Qt, QRectF, Signal, QPointF
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPixmap, QPainter, 
    QFont, QCursor
)
import logging

logger = logging.getLogger(__name__)

class ResizableLogoItem(QGraphicsPixmapItem):
    """Графический элемент логотипа с возможностью перемещения и изменения размера"""
    
    def __init__(self, logo_id: str, pixmap: QPixmap, parent=None):
        super().__init__(pixmap, parent)
        self.logo_id = logo_id
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)  # Включаем обработку hover событий
        
        # Настройки для изменения размера
        self.resize_handle_size = 20  # Увеличиваем размер для лучшего удобства
        self.resize_area_size = 50    # Значительно увеличиваем область для захвата
        self.resizing = False
        self.resize_start_pos = QPointF()
        self.resize_start_rect = QRectF()
        
        # Улучшенная обработка событий мыши
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        
        # Рамка выделения
        self.selection_pen = QPen(QColor(0, 120, 215), 2)
        self.selection_pen.setStyle(Qt.DashLine)
        
        # Установка курсора
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        
        # Включаем отслеживание наведения мыши для смены курсора
        self.setAcceptHoverEvents(True)
        
        # Начальный размер (будет установлен позже)
        self.original_size = self.pixmap().size()
        self.original_pixmap = pixmap.copy()
        
    def boundingRect(self) -> QRectF:
        """Возвращает границы элемента с учетом ручек изменения размера"""
        rect = super().boundingRect()
        if self.isSelected():
            # Расширяем границы для корректной обработки событий мыши в области resize
            rect = rect.adjusted(0, 0, 25, 25)
        return rect
        
    def paint(self, painter, option, widget=None):
        """Отрисовка логотипа без визуальных элементов выделения"""
        # Рисуем только основное изображение, никаких рамок и обводок
        super().paint(painter, option, widget)
    
    def _is_in_resize_handle(self, pos):
        """Проверить, находится ли позиция в ручке изменения размера"""
        if not self.isSelected():
            return False
        
        # Получаем границы элемента (пиксмапа)  
        rect = self.pixmap().rect()
        
        # КАРДИНАЛЬНО УПРОЩАЕМ - весь правый-нижний квадрант является областью resize
        # Для кнопки подписки делаем еще более щедрую область (она обычно маленькая)
        if self.logo_id.startswith("subscribe"):
            # Для кнопки подписки - правая и нижняя треть 
            is_in_right_half = pos.x() >= (rect.width() * 0.4)  # 40% справа
            is_in_bottom_half = pos.y() >= (rect.height() * 0.4)  # 40% снизу
        else:
            # Для обычных логотипов - как было
            is_in_right_half = pos.x() >= (rect.width() * 0.6)  # 60% справа
            is_in_bottom_half = pos.y() >= (rect.height() * 0.6)  # 60% снизу
        
        # Также проверяем что не выходим слишком далеко за границы (но довольно щедро)
        is_within_bounds = (pos.x() <= rect.right() + 30) and (pos.y() <= rect.bottom() + 30)
        
        # Результат: в правом-нижнем квадранте И в пределах границ
        result = is_within_bounds and is_in_right_half and is_in_bottom_half
        
        return result
    
    def contains(self, point):
        """Переопределяем contains для улучшенной обработки областей"""
        # Сначала проверяем базовый contains
        if super().contains(point):
            return True
        
        # Если элемент выделен, проверяем расширенную область resize
        if self.isSelected() and self._is_in_resize_handle(point):
            return True
            
        return False
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.MouseButton.LeftButton:
            logger.debug(f"Mouse press для {self.logo_id} в позиции {event.pos().x():.1f},{event.pos().y():.1f}")
            
            # Сначала выделяем элемент, если он не выделен
            if not self.isSelected():
                self.setSelected(True)
                # После выделения сразу проверяем, не в области ли resize мы нажали
                if self._is_in_resize_handle(event.pos()):
                    logger.debug(f"Элемент выделен и сразу начинаем resize для {self.logo_id}")
                    self.resizing = True
                    self.resize_start_pos = event.pos()
                    self.resize_start_rect = self.pixmap().rect()
                    self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
                    event.accept()
                    return
                    
            # Если элемент уже выделен, проверяем ручку resize
            elif self._is_in_resize_handle(event.pos()):
                # Начинаем resize
                logger.debug(f"Начинаем resize для уже выделенного {self.logo_id}")
                self.resizing = True
                self.resize_start_pos = event.pos()
                self.resize_start_rect = self.pixmap().rect()
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
                event.accept()
                return
        
        # Обычное перетаскивание
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши"""
        if self.resizing:
            try:
                # Выполняем resize
                delta = event.pos() - self.resize_start_pos
                new_width = max(50, self.resize_start_rect.width() + delta.x())
                new_height = max(50, self.resize_start_rect.height() + delta.y())
                
                # Проверяем валидность размеров
                if self.original_size.width() <= 0 or self.original_size.height() <= 0:
                    logger.warning(f"Невалидный original_size для {self.logo_id}")
                    return
                
                # Масштабируем с сохранением пропорций
                original_ratio = self.original_size.width() / self.original_size.height()
                
                if new_width / new_height > original_ratio:
                    final_height = new_height
                    final_width = final_height * original_ratio
                else:
                    final_width = new_width
                    final_height = final_width / original_ratio
                
                # Проверяем минимальные размеры
                final_width = max(20, final_width)
                final_height = max(20, final_height)
                
                # Применяем новый размер
                scaled_pixmap = self.original_pixmap.scaled(
                    int(final_width), int(final_height),
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                self.setPixmap(scaled_pixmap)
                # Принудительно обновляем всю область для корректного отображения ручки
                self.update(self.boundingRect())
                
            except Exception as e:
                logger.error(f"Ошибка в mouseMoveEvent для {self.logo_id}: {e}")
            
            event.accept()
        else:
            # Обычное перетаскивание
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши"""
        if self.resizing and event.button() == Qt.MouseButton.LeftButton:
            # Завершаем resize
            self.resizing = False
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            
            # Уведомляем об изменении
            if hasattr(self.scene(), 'views') and self.scene().views():
                view = self.scene().views()[0]
                if hasattr(view.parent(), 'emit_position_change'):
                    view.parent().emit_position_change(self)
            
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def hoverMoveEvent(self, event):
        """Обработка наведения мыши для смены курсора"""
        if not self.resizing:  # Не меняем курсор во время resize
            is_selected = self.isSelected()
            is_in_resize = self._is_in_resize_handle(event.pos()) if is_selected else False
            
            if is_selected and is_in_resize:
                # Находимся над ручкой изменения размера
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            else:
                # Находимся вне ручки - обычный курсор
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().hoverMoveEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Обработка покидания области элемента"""
        # Возвращаем обычный курсор при покидании элемента
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().hoverLeaveEvent(event)
        
    def setOriginalPixmap(self, pixmap: QPixmap):
        """Установка оригинального пиксмапа (для правильного масштабирования)"""
        self.original_pixmap = pixmap.copy()  # Создаем копию для безопасности
        self.original_size = pixmap.size()
        
        # Обновляем текущий отображаемый пиксмап
        self.setPixmap(pixmap)


class LogoPositionEditor(QWidget):
    """Виджет для визуального редактирования позиций логотипов"""
    
    # Сигналы для уведомления об изменениях
    logo_position_changed = Signal(str, int, int, int)  # logo_id, x, y, width
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_width = 1920
        self.video_height = 1080
        self.scale_factor = 0.3  # Масштаб для отображения
        
        # Элементы логотипов
        self.logo_items: Dict[str, ResizableLogoItem] = {}
        
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # Устанавливаем минимальное расстояние для идентичности
        
        # Заголовок убран - он добавляется автоматически в main_window.py
        
        # Графическая сцена
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setMinimumHeight(350)
        
        # Настройки выравнивания для идентичности с редактором субтитров
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setContentsMargins(0, 0, 0, 0)
        
        # Улучшаем обработку событий мыши для resize
        self.view.setMouseTracking(True)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)  # Отключаем стандартное перетаскивание view
        
        # Настройка сцены (пропорции 16:9)
        scene_width = self.video_width * self.scale_factor
        scene_height = self.video_height * self.scale_factor
        self.scene.setSceneRect(0, 0, scene_width, scene_height)
        
        # Фон сцены (имитация экрана)
        bg_rect = QGraphicsRectItem(0, 0, scene_width, scene_height)
        bg_rect.setBrush(QBrush(QColor(40, 40, 40)))
        bg_rect.setPen(QPen(QColor(100, 100, 100), 2))
        self.scene.addItem(bg_rect)
        
        # Подпись размера
        size_text = QGraphicsTextItem(f"{self.video_width}×{self.video_height}")
        size_text.setDefaultTextColor(QColor(200, 200, 200))
        size_text.setFont(QFont("Arial", 10))
        size_text.setPos(10, 10)
        self.scene.addItem(size_text)
        
        layout.addWidget(self.view)
        
        # Кнопки управления
        button_layout = QHBoxLayout()
        
        # Кнопки загрузки логотипов убраны - теперь логотипы загружаются автоматически
        # при выборе каналов через метод set_logo_image
        
        button_layout.addStretch()
        
        self.reset_btn = QPushButton("Сбросить позиции")
        self.reset_btn.clicked.connect(self.reset_positions)
        button_layout.addWidget(self.reset_btn)
        
        self.save_btn = QPushButton("Сохранить позиции")
        self.save_btn.clicked.connect(self.save_positions)
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)
        
    def load_logo(self, logo_id: str):
        """Загрузка логотипа из файла или папки"""
        if logo_id == "subscribe":
            # Для кнопки подписки выбираем папку
            folder_path = QFileDialog.getExistingDirectory(
                self, "Выберите папку с кадрами кнопки подписки"
            )
            
            if folder_path:
                # Ищем первый PNG файл в папке для превью
                from pathlib import Path
                subscribe_files = list(Path(folder_path).glob("*.png"))
                if subscribe_files:
                    self.set_logo_image(logo_id, str(subscribe_files[0]))
                else:
                    logger.warning(f"В папке {folder_path} не найдено PNG файлов")
        else:
            # Для логотипов выбираем файл
            file_path, _ = QFileDialog.getOpenFileName(
                self, f"Выберите {logo_id}",
                "", "Изображения (*.png *.jpg *.jpeg *.bmp *.svg)"
            )
            
            if file_path:
                self.set_logo_image(logo_id, file_path)
            
    def set_logo_image(self, logo_id: str, image_path: str, opacity: float = 1.0):
        """Установка изображения логотипа с возможностью установки прозрачности"""
        try:
            # Удаляем предыдущий логотип если есть
            if logo_id in self.logo_items:
                self.scene.removeItem(self.logo_items[logo_id])
                del self.logo_items[logo_id]
            
            # Загружаем новое изображение
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                logger.warning(f"Не удалось загрузить изображение: {image_path}")
                return
                
            # Масштабируем для отображения
            display_pixmap = pixmap.scaled(
                int(100 * self.scale_factor), int(100 * self.scale_factor),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            
            # Создаем элемент логотипа
            logo_item = ResizableLogoItem(logo_id, display_pixmap)
            logo_item.setOriginalPixmap(pixmap)
            
            # Устанавливаем прозрачность
            logo_item.setOpacity(opacity)
            
            # Устанавливаем начальную позицию в зависимости от типа логотипа
            if logo_id.startswith("logo1"):
                # Правый верхний угол
                x = self.scene.width() - display_pixmap.width() - 20
                y = 20
            elif logo_id.startswith("logo2"):
                # Левый верхний угол  
                x = 20
                y = 20
            elif logo_id.startswith("subscribe"):
                # Центр внизу
                x = (self.scene.width() - display_pixmap.width()) / 2
                y = self.scene.height() - display_pixmap.height() - 20
            else:
                # Дефолтная позиция для неизвестных типов
                x = 50
                y = 50
                
            logo_item.setPos(x, y)
            
            # Подключаем сигналы
            logo_item.itemChange = self.create_item_change_handler(logo_item)
            
            # Добавляем на сцену
            self.scene.addItem(logo_item)
            self.logo_items[logo_id] = logo_item
            
            logger.info(f"Логотип {logo_id} загружен: {image_path}")
            
        except Exception as e:
            logger.error(f"Ошибка загрузки логотипа {logo_id}: {e}")
            
    def create_item_change_handler(self, item: ResizableLogoItem):
        """Создание обработчика изменений элемента"""
        original_item_change = item.itemChange
        
        def item_change_handler(change, value):
            result = original_item_change(change, value)
            
            if change == QGraphicsItem.ItemPositionHasChanged:
                # Позиция изменилась - отправляем сигнал
                self.emit_position_change(item)
                
            return result
            
        return item_change_handler
        
    def emit_position_change(self, item: ResizableLogoItem):
        """Отправка сигнала об изменении позиции/размера"""
        # Преобразуем координаты обратно в пиксели видео
        scene_pos = item.pos()
        scene_rect = item.pixmap().rect()  # Используем размер пиксмапа, а не boundingRect
        
        video_x = int(scene_pos.x() / self.scale_factor)
        video_y = int(scene_pos.y() / self.scale_factor)
        video_width = int(scene_rect.width() / self.scale_factor)
        
        self.logo_position_changed.emit(item.logo_id, video_x, video_y, video_width)
        
    def set_logo_position(self, logo_id: str, x: int, y: int, width: int):
        """Установка позиции логотипа программно"""
        if logo_id not in self.logo_items:
            logger.debug(f"Логотип {logo_id} не найден в редакторе")
            return
            
        item = self.logo_items[logo_id]
        
        # Проверим валидность координат и размеров
        if width <= 0 or x < -10000 or x > 10000 or y < -10000 or y > 10000:
            logger.warning(f"Невалидные параметры для {logo_id}: x={x}, y={y}, width={width}")
            return
        
        # Преобразуем в координаты сцены
        scene_x = x * self.scale_factor
        scene_y = y * self.scale_factor
        scene_width = width * self.scale_factor
        
        # Масштабируем логотип
        if hasattr(item, 'original_pixmap'):
            original_size = item.original_pixmap.size()
            scale_ratio = scene_width / original_size.width()
            
            new_height = original_size.height() * scale_ratio
            scaled_pixmap = item.original_pixmap.scaled(
                int(scene_width), int(new_height),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            item.setPixmap(scaled_pixmap)
        
        # Устанавливаем позицию
        item.setPos(scene_x, scene_y)
        
    def reset_positions(self):
        """Сброс позиций логотипов к центру экрана"""
        center_x = self.video_width // 2
        center_y = self.video_height // 2
        
        for logo_id in self.logo_items.keys():
            if logo_id.startswith("logo1"):
                # Центр экрана, немного сдвинуто вправо и вверх
                self.set_logo_position(logo_id, center_x + 100, center_y - 100, 200)
            elif logo_id.startswith("logo2"):
                # Центр экрана, немного сдвинуто влево и вверх
                self.set_logo_position(logo_id, center_x - 300, center_y - 100, 200)
            elif logo_id.startswith("subscribe"):
                # Центр экрана, внизу
                self.set_logo_position(logo_id, center_x - 200, center_y + 200, 400)
            
    def get_logo_positions(self) -> Dict[str, Dict[str, int]]:
        """Получение текущих позиций всех логотипов"""
        positions = {}
        
        for logo_id, item in self.logo_items.items():
            scene_pos = item.pos()
            scene_rect = item.pixmap().rect()  # Используем размер пиксмапа
            
            positions[logo_id] = {
                'x': int(scene_pos.x() / self.scale_factor),
                'y': int(scene_pos.y() / self.scale_factor),
                'width': int(scene_rect.width() / self.scale_factor)
            }
            
        return positions
        
    def save_positions(self):
        """Принудительное сохранение текущих позиций логотипов"""
        try:
            # Отправляем сигналы для всех логотипов, чтобы обновить конфигурацию
            for logo_id, item in self.logo_items.items():
                self.emit_position_change(item)
            
            logger.info("Позиции логотипов принудительно сохранены")
            
            # Можно добавить визуальное уведомление
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Сохранение", "Позиции логотипов сохранены")
            
        except Exception as e:
            logger.error(f"Ошибка при принудительном сохранении позиций: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить позиции: {e}")
        
    def clear_all_logos(self):
        """Очистка всех логотипов из редактора"""
        try:
            # Удаляем все элементы со сцены
            for logo_id, item in list(self.logo_items.items()):
                self.scene.removeItem(item)
                del self.logo_items[logo_id]
            
            logger.debug("Все логотипы очищены из редактора")
        except Exception as e:
            logger.error(f"Ошибка при очистке логотипов: {e}")


def convert_ffmpeg_coords_to_pixels(expression: str, video_width: int = 1920, video_height: int = 1080, 
                                   logo_width: int = 200, logo_height: int = 100) -> int:
    """Преобразование FFmpeg выражений в пиксельные координаты"""
    try:
        if not expression or expression == "":
            return 0
            
        # Заменяем дополнительные переменные сначала (более длинные)
        expr = expression.replace('main_h', str(video_height))
        expr = expr.replace('main_w', str(video_width))
        expr = expr.replace('overlay_h', str(logo_height))
        expr = expr.replace('overlay_w', str(logo_width))
        
        # Заменяем переменные FFmpeg (короткие)
        expr = expr.replace('W', str(video_width))
        expr = expr.replace('H', str(video_height))
        expr = expr.replace('w', str(logo_width))
        expr = expr.replace('h', str(logo_height))
        
        # Исправляем двойные знаки (например, W-w+-20 -> W-w-20)
        expr = expr.replace('+-', '-')
        expr = expr.replace('-+', '-')
        
        # Вычисляем выражение
        result = eval(expr)
        # Разрешаем отрицательные координаты для элементов за границами экрана
        final_result = int(result)
        logger.debug(f"🔧 Конвертация FFmpeg->пиксели: '{expression}' -> {final_result}")
        return final_result
        
    except Exception as e:
        logger.warning(f"Ошибка преобразования координат '{expression}': {e}")
        return 0
        

def convert_pixels_to_ffmpeg_coords(pixel_value: int, coord_type: str, 
                                   video_width: int = 1920, video_height: int = 1080,
                                   logo_width: int = 200, logo_height: int = 100) -> str:
    """Преобразование пиксельных координат в FFmpeg выражения"""
    try:
        # Разрешаем отрицательные значения для элементов за границами экрана
        if coord_type == 'x':
            # Для X координаты
            if pixel_value <= 50 and pixel_value >= 0:
                return str(pixel_value)  # Близко к левому краю
            elif pixel_value >= video_width - logo_width - 50:
                offset = video_width - pixel_value - logo_width
                if offset >= 0:
                    return f"W-w-{offset}"
                else:
                    # Логотип выходит за правую границу
                    return f"W-w+{abs(offset)}"
            else:
                return str(max(0, pixel_value))  # Где-то посередине, но не отрицательное
                
        elif coord_type == 'y':
            # Для Y координаты
            if pixel_value <= 50 and pixel_value >= 0:
                return str(pixel_value)  # Близко к верхнему краю
            elif pixel_value >= video_height - 150:  # Упрощенная проверка - в нижней части экрана
                # Для элементов в нижней части используем выражение относительно дна
                offset = video_height - pixel_value - logo_height
                return f"main_h-overlay_h{'+' if offset < 0 else '-'}{abs(offset)}"
            else:
                return str(max(0, pixel_value))  # Где-то посередине, но не отрицательное
                
        final_result = str(max(0, pixel_value))
        logger.debug(f"🔧 Конвертация пиксели->FFmpeg: {pixel_value} -> '{final_result}' (тип: {coord_type})")
        return final_result
        
    except Exception as e:
        logger.warning(f"Ошибка преобразования в FFmpeg координаты: {e}")
        return str(max(0, pixel_value))