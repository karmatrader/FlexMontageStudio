"""
Виджет для визуального предпросмотра субтитров
"""
import logging
import platform
from typing import Dict, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsRectItem, QFrame, QPushButton, QGraphicsPixmapItem,
    QTextEdit, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPen, QBrush, QColor, QFont, QPainter, QPainterPath
)

logger = logging.getLogger(__name__)

class OutlinedTextItem(QGraphicsTextItem):
    """Графический элемент текста с обводкой и тенью"""
    
    def __init__(self, text="", parent=None, draggable=False):
        super().__init__(text, parent)
        self.outline_color = QColor(0, 0, 0)
        self.outline_thickness = 2
        self.shadow_color = QColor(80, 80, 80)
        self.shadow_offset = QPointF(2, 2)
        self.shadow_alpha = 128
        self.is_dragging = False  # Флаг для отслеживания перетаскивания
        self.line_spacing = 1.2  # Множитель для межстрочного интервала
        
        # Делаем элемент перетаскиваемым если нужно
        if draggable:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QCursor
            self.setFlags(
                QGraphicsTextItem.ItemIsMovable | 
                QGraphicsTextItem.ItemIsSelectable |
                QGraphicsTextItem.ItemSendsGeometryChanges
            )
            self.setAcceptHoverEvents(True)
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
    
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
    
    def set_line_spacing(self, spacing: float):
        """Установка межстрочного интервала"""
        old_spacing = getattr(self, 'line_spacing', 1.2)
        self.line_spacing = max(0.5, min(3.0, spacing))  # Ограничиваем диапазон
        logger.debug(f"🔧 Line spacing: {old_spacing} → {self.line_spacing}")
        # Принудительно перерасчитываем размеры элемента
        self.prepareGeometryChange()
        # Принудительно обновляем отображение
        self.update()
        # Также обновляем сцену если она есть
        if self.scene():
            self.scene().update()
    
    def paint(self, painter, option, widget):
        """Отрисовка текста с обводкой и тенью"""
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Получаем текст и шрифт
        text = self.toPlainText()
        font = self.font()
        
        # Создаем путь для текста с поддержкой переносов строк и центрированием
        path = QPainterPath()
        lines = text.split('\n')
        base_line_height = font.pixelSize() if font.pixelSize() > 0 else font.pointSize() * 1.2
        line_height = base_line_height * self.line_spacing  # Применяем настраиваемый интервал
        # Убрали избыточное логирование
        
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
    
    def mousePressEvent(self, event):
        """Обработка начала перетаскивания"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Обработка движения при перетаскивании"""
        if self.is_dragging:
            # Принудительно обновляем сцену во время перетаскивания
            if self.scene():
                self.scene().update()
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Обработка окончания перетаскивания"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            # Принудительно очищаем все артефакты после завершения перетаскивания
            if self.scene():
                self.scene().update()
                if self.scene().views():
                    for view in self.scene().views():
                        view.update()
                        view.viewport().update()
        super().mouseReleaseEvent(event)

class SubtitlePreviewWidget(QWidget):
    """Виджет для предпросмотра субтитров"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SubtitlePreviewWidget")  # Для CSS селектора
        self.video_width = 1920
        self.video_height = 1080
        self.scale_factor = 0.3  # Масштаб для отображения - идентично редактору логотипов
        self.subtitle_item = None
        self.backdrop_item = None
        self.background_item = None  # Фоновое изображение
        
        # Текстовое поле для редактирования примера субтитров
        self.sample_text_edit = None
        
        # Таймер для отложенного применения line_spacing
        self.line_spacing_timer = QTimer()
        self.line_spacing_timer.setSingleShot(True)
        self.line_spacing_timer.timeout.connect(self._apply_delayed_line_spacing)
        self._pending_line_spacing = None
        
        # Настройка политики размера для корректного масштабирования  
        # Используем Preferred по высоте для лучшего поведения при изменении размера окна
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # Устанавливаем максимальную высоту, чтобы виджет не расширялся бесконечно (идентично LogoPositionEditor)
        self.setMaximumHeight(324 + 80 + 60)  # 324 (graphics view) + 80 (text edit) + 60 (buttons and margins)
        
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
        self.view.setMinimumHeight(324)  # Точно под размер сцены: 1080 * 0.3 = 324
        
        # Настройка политики размера для корректного масштабирования как у редактора логотипов
        # Используем Preferred по высоте, чтобы view корректно масштабировался в контексте других элементов
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # Центрируем по горизонтали, прижимаем к верху - убираем только отступы сверху и снизу
        self.view.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.view.setContentsMargins(0, 0, 0, 0)
        
        # Дополнительные настройки для минимизации отступов (идентично редактору логотипов)
        self.view.setViewportMargins(0, 0, 0, 0)
        self.view.setFrameStyle(0)  # Убираем рамку
        self.view.setStyleSheet("QGraphicsView { border: none; margin: 0px; padding: 0px; }")
        
        # Принудительно убираем все возможные отступы
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setRenderHint(QPainter.Antialiasing, False)  # Может уменьшить отступы рендеринга
        
        # Улучшаем обработку событий мыши для resize (идентично редактору логотипов)
        self.view.setMouseTracking(True)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)  # Отключаем стандартное перетаскивание view
        
        # Настройки для устранения визуальных артефактов
        self.view.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.view.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
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
        
        # Кнопки управления (перенесены вверх, над визуальным редактором)
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 4)  # Небольшой отступ снизу
        button_layout.setSpacing(8)  # Увеличенное расстояние между кнопками
        
        button_layout.addStretch()  # Прижимаем кнопки к правой стороне
        
        # Кнопки с одинаковым размером
        self.load_bg_btn = QPushButton("Загрузить фон")
        self.load_bg_btn.setMinimumWidth(160)  # Фиксированная ширина для одинакового размера
        self.load_bg_btn.setMaximumWidth(160)  # Фиксированная максимальная ширина
        self.load_bg_btn.setMinimumHeight(32)  # Фиксированная высота
        self.load_bg_btn.setMaximumHeight(32)  # Фиксированная максимальная высота
        self.load_bg_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.load_bg_btn.clicked.connect(self.load_background_image)
        button_layout.addWidget(self.load_bg_btn)
        
        self.reset_btn = QPushButton("Сбросить позицию")
        self.reset_btn.setMinimumWidth(160)  # Фиксированная ширина для одинакового размера
        self.reset_btn.setMaximumWidth(160)  # Фиксированная максимальная ширина
        self.reset_btn.setMinimumHeight(32)  # Фиксированная высота
        self.reset_btn.setMaximumHeight(32)  # Фиксированная максимальная высота
        self.reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.reset_btn.clicked.connect(self.reset_subtitle_position)
        button_layout.addWidget(self.reset_btn)
        
        layout.addLayout(button_layout, 0)  # Stretch factor 0 для кнопок
        
        # Визуальный редактор
        layout.addWidget(self.view, 1)  # Stretch factor 1 для основного view
        
        # Добавляем текстовое поле для редактирования примера субтитров
        text_edit_layout = QVBoxLayout()
        text_edit_layout.setContentsMargins(0, 4, 0, 4)
        text_edit_layout.setSpacing(2)
        
        # Заголовок для текстового поля
        text_label = QLabel("Текст для предпросмотра:")
        text_label.setStyleSheet("color: #CCCCCC; font-size: 11px;")
        text_edit_layout.addWidget(text_label)
        
        # Текстовое поле для ввода примера субтитров
        self.sample_text_edit = QTextEdit()
        self.sample_text_edit.setMinimumHeight(50)  # Минимальная высота
        self.sample_text_edit.setMaximumHeight(80)  # Максимальная высота как у info_label в LogoPositionEditor
        self.sample_text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  # Горизонтально растягивается, вертикально фиксирована
        self.sample_text_edit.setPlainText("Пример субтитров\nв два ряда")
        self.sample_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2B2B2B;
                color: #CCCCCC;
                border: 1px solid #12BAC4;
                border-radius: 4px;
                padding: 4px;
                font-size: 11px;
            }
        """)
        # Подключаем сигнал изменения текста к обновлению предпросмотра
        self.sample_text_edit.textChanged.connect(self.on_sample_text_changed)
        text_edit_layout.addWidget(self.sample_text_edit)
        
        layout.addLayout(text_edit_layout, 0)  # Stretch factor 0 для текстового поля
        
        # Показываем пример субтитров с настройками по умолчанию
        self.create_sample_subtitle()
    
    def on_sample_text_changed(self):
        """Обработка изменения текста в поле ввода"""
        # Автоматически обновляем предпросмотр при изменении текста
        if hasattr(self, '_last_config'):
            self.update_subtitle_preview(self._last_config)
        else:
            # Если нет сохраненной конфигурации, используем базовые настройки
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
            'subtitle_margin_v': 20,  # Стандартный отступ
            'subtitle_line_spacing': 1.2  # Добавляем межстрочный интервал по умолчанию
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
            logger.debug(f"📥 UPDATE_SUBTITLE_PREVIEW вызван с конфигом: {config}")
            # Сохраняем конфигурацию для повторного использования
            self._last_config = config.copy()
            # Сохраняем текущую позицию субтитров если они есть
            current_position = None
            if self.subtitle_item:
                current_position = self.subtitle_item.pos()
                self.scene.removeItem(self.subtitle_item)
                self.subtitle_item = None
                
            if self.backdrop_item:
                self.scene.removeItem(self.backdrop_item)
                self.backdrop_item = None
            
            # Принудительно очищаем всю сцену от визуальных артефактов
            self.scene.update()
            self.view.update()
            # Принудительное обновление viewport для устранения шлейфа
            self.view.viewport().update()
            
            # Получаем текст из поля ввода или используем значение по умолчанию
            if self.sample_text_edit:
                sample_text = self.sample_text_edit.toPlainText()
            else:
                sample_text = "Пример субтитров\nв два ряда"
            
            # Если текст пустой, используем заглушку
            if not sample_text.strip():
                sample_text = "Введите текст"
            
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
            
            # Новый параметр межстрочного интервала
            def safe_float(value, default):
                """Безопасное преобразование в float"""
                try:
                    if isinstance(value, str) and value.strip() == '':
                        return default
                    return float(value)
                except (ValueError, TypeError):
                    return default
            
            line_spacing = safe_float(config.get('subtitle_line_spacing', 1.2), 1.2)
            logger.debug(f"🔍 Line spacing: {config.get('subtitle_line_spacing', 'НЕТ')} → {line_spacing}")
            
            # Масштабируем размер шрифта для предпросмотра
            scaled_fontsize = int(fontsize * self.scale_factor)
            scaled_outline = max(1, int(outline_thickness * self.scale_factor))
            scaled_shadow_x = int(shadow_offset_x * self.scale_factor)
            scaled_shadow_y = int(shadow_offset_y * self.scale_factor)
            
            # Создаем элемент текста с эффектами (перетаскиваемый)
            self.subtitle_item = OutlinedTextItem(sample_text, draggable=True)
            
            # КРИТИЧЕСКИ ВАЖНО: Устанавливаем межстрочный интервал ПЕРЕД настройкой шрифта
            self.subtitle_item.set_line_spacing(line_spacing)
            
            # Настраиваем шрифт - используем выбранный или системный по умолчанию
            font_family = config.get('subtitle_font_family', self.get_system_font())
            font = QFont(font_family, scaled_fontsize, QFont.Bold)
            logger.debug(f"🔤 Шрифт: {font_family}, размер: {scaled_fontsize}")
            self.subtitle_item.setFont(font)
            self.subtitle_item.setDefaultTextColor(font_color)
            
            # КРИТИЧЕСКИ ВАЖНО: После смены шрифта принудительно пересчитываем геометрию
            self.subtitle_item.prepareGeometryChange()
            
            # Настраиваем эффекты
            self.subtitle_item.set_outline(outline_color, scaled_outline)
            self.subtitle_item.set_shadow(shadow_color, QPointF(scaled_shadow_x, scaled_shadow_y), shadow_alpha)
            
            # ПОВТОРНО устанавливаем межстрочный интервал после смены шрифта
            self.subtitle_item.set_line_spacing(line_spacing)
            
            # Принудительно обновляем элемент после установки всех параметров
            self.subtitle_item.update()
            
            # Позиционируем субтитры - используем сохраненную позицию или центр
            text_rect = self.subtitle_item.boundingRect()
            
            if current_position is not None:
                # Используем сохраненную позицию
                x = current_position.x()
                y = current_position.y()
            else:
                # Центрируем по умолчанию
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
            
            # Планируем отложенное применение межстрочного интервала
            self._pending_line_spacing = line_spacing
            self.line_spacing_timer.start(50)  # Применяем через 50мс
            
            # Финальная очистка всех визуальных артефактов
            self.scene.update()
            self.view.update()
            self.view.viewport().update()
            # Принудительно перерисовываем весь виджет
            self.update()
            
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
    
    def load_background_image(self):
        """Загрузка фонового изображения"""
        from PySide6.QtWidgets import QFileDialog
        from PySide6.QtGui import QPixmap
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите фоновое изображение",
            "", "Изображения (*.png *.jpg *.jpeg *.bmp)"
        )
        
        if file_path:
            try:
                # Удаляем предыдущий фон если есть
                if self.background_item:
                    self.scene.removeItem(self.background_item)
                    self.background_item = None
                
                # Загружаем новое изображение
                pixmap = QPixmap(file_path)
                if pixmap.isNull():
                    logger.warning(f"Не удалось загрузить изображение: {file_path}")
                    return
                
                # Масштабируем изображение под размер сцены
                scene_width = self.video_width * self.scale_factor
                scene_height = self.video_height * self.scale_factor
                scaled_pixmap = pixmap.scaled(
                    int(scene_width), int(scene_height),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Создаем элемент фона
                self.background_item = QGraphicsPixmapItem(scaled_pixmap)
                self.background_item.setPos(0, 0)
                self.background_item.setZValue(-1)  # Помещаем под все остальные элементы
                
                # Удаляем стандартный серый фон
                items_to_remove = []
                for item in self.scene.items():
                    if isinstance(item, QGraphicsRectItem) and item.brush().color() == QColor(40, 40, 40):
                        items_to_remove.append(item)
                
                for item in items_to_remove:
                    self.scene.removeItem(item)
                
                # Добавляем новый фон на сцену
                self.scene.addItem(self.background_item)
                
                logger.info(f"Фоновое изображение загружено: {file_path}")
                
            except Exception as e:
                logger.error(f"Ошибка загрузки фонового изображения: {e}")
    
    def reset_subtitle_position(self):
        """Сброс позиции субтитров к центру"""
        if self.subtitle_item:
            # Позиционируем субтитры по центру экрана
            text_rect = self.subtitle_item.boundingRect()
            x = (self.scene.width() - text_rect.width()) / 2
            y = (self.scene.height() - text_rect.height()) / 2
            self.subtitle_item.setPos(x, y)
            logger.debug("Позиция субтитров сброшена к центру")
    
    def get_subtitle_position(self):
        """Получение текущей позиции субтитров в координатах видео"""
        if self.subtitle_item:
            scene_pos = self.subtitle_item.pos()
            video_x = int(scene_pos.x() / self.scale_factor)
            video_y = int(scene_pos.y() / self.scale_factor)
            return video_x, video_y
        return None, None
    
    def force_clear_artifacts(self):
        """Принудительная очистка всех визуальных артефактов"""
        try:
            # Множественная очистка для гарантированного удаления шлейфов
            self.scene.update()
            self.view.update()
            self.view.viewport().update()
            self.update()
            
            # Дополнительная принудительная перерисовка
            self.view.viewport().repaint()
            self.repaint()
            
            # Очистка кэша сцены
            self.scene.invalidate()
            
            logger.debug("Принудительная очистка визуальных артефактов выполнена")
        except Exception as e:
            logger.error(f"Ошибка при очистке артефактов: {e}")
    
    def _apply_delayed_line_spacing(self):
        """Отложенное применение межстрочного интервала"""
        try:
            if self.subtitle_item and self._pending_line_spacing is not None:
                logger.debug(f"⏰ Отложенное применение: {self._pending_line_spacing}")
                self.subtitle_item.set_line_spacing(self._pending_line_spacing)
                self._pending_line_spacing = None
                
                # Принудительно обновляем все
                self.scene.update()
                self.view.update()
                self.view.viewport().update()
                self.update()
        except Exception as e:
            logger.error(f"Ошибка отложенного применения line_spacing: {e}")