"""
Главное окно FlexMontage Studio
ОБНОВЛЕНО: Интегрированы ползунки для настроек голоса
"""
import sys
import logging
from typing import Dict, List, Optional, Any
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QScrollArea, QSplitter, QLabel, QTextEdit,
    QMessageBox, QGridLayout, QLineEdit, QCheckBox, QFrame,
    QFileDialog, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import QSettings, Qt, Signal, QObject, QTimer
from PySide6.QtGui import QStandardItemModel, QStandardItem

from core.config_manager import ConfigManager
from core.logging_config import LoggingConfig
from ui.config_widgets import CheckableComboBox, ConfigTabsWidget
from ui.dialog_widgets import AddChannelDialog
from ui.worker_threads import ConfigLoader, MontageThread, MassVoiceoverManager
from ui.logo_position_editor import LogoPositionEditor, convert_ffmpeg_coords_to_pixels, convert_pixels_to_ffmpeg_coords
from parallel_montage_manager import ParallelMontageManager
import pandas as pd
from pathlib import Path
from voice_library_manager import APIKeyManager
from ui.voice_selector_widget import VoiceSelectorWidget

# Попытка импорта VoiceSettingsWidget с обработкой ошибок
try:
    from voice_settings_widget import VoiceSettingsWidget
    VOICE_SETTINGS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"VoiceSettingsWidget недоступен: {e}")
    VOICE_SETTINGS_AVAILABLE = False

    # Создаем заглушку
    class VoiceSettingsWidget(QWidget):
        stability_changed = Signal()
        similarity_changed = Signal()
        speed_changed = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setMinimumHeight(180)
            layout = QVBoxLayout(self)
            label = QLabel("Виджет настроек голоса недоступен")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)

        def load_from_config(self, config):
            pass

        def get_settings_for_config(self):
            return {}

logger = logging.getLogger(__name__)


class QTextEditLogger(logging.Handler, QObject):
    """Обработчик логов для QTextEdit"""
    append_text = Signal(str)

    def __init__(self, text_edit):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.text_edit = text_edit
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.append_text.connect(self.text_edit.append)

    def emit(self, record):
        msg = self.format(record)
        self.append_text.emit(msg)
        self.text_edit.verticalScrollBar().setValue(
            self.text_edit.verticalScrollBar().maximum()
        )


class StreamToQTextEdit(QObject):
    """Перенаправление stdout/stderr в QTextEdit"""
    append_text = Signal(str)

    def __init__(self, text_edit):
        super().__init__()
        self.text_edit = text_edit
        self.append_text.connect(self.text_edit.append)

    def write(self, text):
        if text.strip():
            self.append_text.emit(text.strip())
            self.text_edit.verticalScrollBar().setValue(
                self.text_edit.verticalScrollBar().maximum()
            )

    def flush(self):
        pass


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FlexMontage Studio")
        self.settings = QSettings("MyCompany", "AutoMontageApp")
        
        # Специальные настройки для macOS
        if sys.platform == "darwin":
            # Убираем unified title bar для лучшей совместимости
            self.setUnifiedTitleAndToolBarOnMac(False)
            # Устанавливаем минимальный размер для предотвращения невидимости
            self.setMinimumSize(800, 600)
            # Устанавливаем window flags для корректного отображения
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)

        # Инициализация менеджеров и состояния
        self.config_manager = ConfigManager()
        self.current_logging_config: Optional[LoggingConfig] = None

        # Состояние выполнения задач
        self.is_montage_running = False
        self.is_voiceover_running = False
        self.is_config_loading = False

        # Рабочие потоки
        self.config_loader: Optional[ConfigLoader] = None
        self.montage_thread: Optional[MontageThread] = None
        self.voiceover_manager: Optional[MassVoiceoverManager] = None
        self.parallel_montage_thread = None

        # UI компоненты
        self.param_entries: Dict[str, Any] = {}
        self.voice_selector_widget: Optional[VoiceSelectorWidget] = None
        self.voice_settings_widget: Optional[VoiceSettingsWidget] = None
        self.logo_position_editor: Optional[LogoPositionEditor] = None
        
        # Таймер для дебаунсинга обновлений субтитров
        self.subtitle_update_timer = QTimer()
        self.subtitle_update_timer.setSingleShot(True)
        self.subtitle_update_timer.timeout.connect(self._delayed_subtitle_update)
        self.subtitle_update_timer.setInterval(300)  # 300ms задержка

        # Инициализация интерфейса
        self.setup_ui()
        self.setup_logging()
        self.restore_window_geometry()

        # Загрузка начальной конфигурации
        self.load_initial_config()

    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Основной layout
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(5)

        # Создание компонентов интерфейса
        self.create_channel_controls()
        self.create_main_interface()
        self.create_control_buttons()
        self.create_status_bar()

    def create_channel_controls(self):
        """Создание элементов управления каналами"""
        self.channel_layout = QHBoxLayout()
        self.channel_layout.setContentsMargins(0, 0, 0, 0)
        self.channel_layout.setSpacing(5)

        # Метка
        self.channel_label = QLabel("Выберите каналы:")
        self.channel_layout.addWidget(self.channel_label)

        # Комбобокс выбора каналов
        self.channel_combo = CheckableComboBox()
        self.channel_combo.setFixedWidth(300)
        self.channel_combo.currentTextChanged.connect(self.load_channel_config)
        self.channel_layout.addWidget(self.channel_combo)

        # Кнопки управления каналами
        self.add_channel_button = QPushButton("Добавить канал")
        self.add_channel_button.clicked.connect(self.add_channel)
        self.channel_layout.addWidget(self.add_channel_button)

        self.delete_channel_button = QPushButton("Удалить канал")
        self.delete_channel_button.clicked.connect(self.delete_channel)
        self.channel_layout.addWidget(self.delete_channel_button)


        self.layout.addLayout(self.channel_layout)

    def create_main_interface(self):
        """Создание основного интерфейса с вкладками и логами"""
        # Сплиттер для разделения вкладок и логов
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setContentsMargins(0, 0, 0, 0)

        # Виджет с вкладками параметров
        self.create_tabs_widget()

        # Виджет с логами
        self.create_log_widget()

        # Настройка размеров
        self.splitter.setSizes([600, 200])
        self.splitter.setStretchFactor(0, 1)  # Вкладки растягиваются
        self.splitter.setStretchFactor(1, 0)  # Логи не растягиваются
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)

        self.layout.addWidget(self.splitter)

    def create_tabs_widget(self):
        """Создание виджета с вкладками"""
        self.tabs_widget = QWidget()
        self.tabs_layout = QVBoxLayout(self.tabs_widget)
        self.tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setSpacing(0)

        # Создаем горизонтальный ряд кнопок-табов (как кнопки монтажа) - АДАПТИВНЫЕ!
        self.custom_tab_buttons_layout = QHBoxLayout()
        self.custom_tab_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_tab_buttons_layout.setSpacing(5)
        self.tabs_layout.addLayout(self.custom_tab_buttons_layout)

        # Создаем обычный QTabWidget, но скроем его табы через CSS
        self.tabs = QTabWidget()
        self.tabs_layout.addWidget(self.tabs)

        # Создание вкладок параметров
        self.create_param_tabs()

        self.tabs_widget.setMinimumHeight(600)
        self.splitter.addWidget(self.tabs_widget)

    def create_log_widget(self):
        """Создание виджета с логами"""
        self.log_widget = QWidget()
        self.log_layout = QVBoxLayout(self.log_widget)
        self.log_layout.setContentsMargins(0, 0, 0, 0)
        self.log_layout.setSpacing(5)

        self.log_label = QLabel("Лог выполнения:")
        self.log_label.setObjectName("bold")
        self.log_layout.addWidget(self.log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_layout.addWidget(self.log_text)

        self.splitter.addWidget(self.log_widget)

    def create_control_buttons(self):
        """Создание кнопок управления"""
        self.button_layout = QHBoxLayout()
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(5)

        self.montage_button = QPushButton("Запустить монтаж")
        self.montage_button.clicked.connect(self.toggle_montage)
        self.montage_button.setEnabled(False)
        self.button_layout.addWidget(self.montage_button)

        self.voiceover_button = QPushButton("Запустить озвучку")
        self.voiceover_button.clicked.connect(self.toggle_voiceover)
        self.voiceover_button.setEnabled(False)
        self.button_layout.addWidget(self.voiceover_button)


        self.layout.addLayout(self.button_layout)

    def create_status_bar(self):
        """Создание строки состояния"""
        self.status_label = QLabel("Загрузка...")
        self.status_label.setStyleSheet("padding: 5px 0 0 0;")
        self.layout.addWidget(self.status_label)

    def setup_logging(self):
        """Настройка логирования"""
        # Настройка обработчика для QTextEdit
        log_handler = QTextEditLogger(self.log_text)
        logging.getLogger().addHandler(log_handler)

        # Перенаправление stdout/stderr
        self.stdout_redirect = StreamToQTextEdit(self.log_text)
        self.stderr_redirect = StreamToQTextEdit(self.log_text)
        sys.stdout = self.stdout_redirect
        sys.stderr = self.stderr_redirect

    def load_initial_config(self):
        """Загрузка начальной конфигурации"""
        try:
            # Загрузка списка каналов
            channels = self.config_manager.get_all_channels()
            for channel in channels:
                self.channel_combo.addItem(channel)

            # Загрузка конфигурации первого канала
            if channels:
                self.load_channel_config()

            logger.info(f"Загружено каналов: {len(channels)}")

        except Exception as e:
            logger.error(f"Ошибка загрузки начальной конфигурации: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки конфигурации: {e}")

    def create_param_tabs(self):
        """Создание вкладок с параметрами"""
        categories = self.get_parameter_categories()

        for category, subgroups in categories.items():
            scroll_area = QScrollArea()
            # ДЛЯ ВСЕХ КАТЕГОРИЙ включаем вертикальный скролл
            scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            scroll_widget = QWidget()
            if category in ["Логотипы", "Субтитры"]:
                scroll_widget.setObjectName("fixed_scroll_widget")  # Специальный CSS для центрирования
            else:
                scroll_widget.setObjectName("scroll_widget")  # Для CSS селектора
            main_layout = QVBoxLayout(scroll_widget)
            main_layout.setContentsMargins(2, 2, 2, 2)  # Минимальные отступы для визуальных редакторов
            main_layout.setSpacing(4)  # Минимальное расстояние между элементами
            main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)  # Выравнивание по верху
            
            # ДЛЯ ВСЕХ КАТЕГОРИЙ разрешаем растяжение (нужно для скролла)
            scroll_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            

            for subgroup_name, params in subgroups.items():
                subgroup_label = QLabel(subgroup_name)
                subgroup_label.setObjectName("subgroup")
                
                # Подтягиваем настройки ближе к визуальным редакторам
                if subgroup_name == "Визуальный редактор позиций":
                    subgroup_label.setObjectName("visual-editor-title")  # Используем специальный CSS стиль
                    subgroup_label.setStyleSheet("margin-top: 0px; margin-bottom: 0px; padding: 0px;")  # Минимальные отступы для визуального редактора
                elif subgroup_name == "Пути к файлам логотипов":
                    subgroup_label.setStyleSheet("margin-top: 0px;")  # Отрицательный отступ для логотипов
                elif subgroup_name == "Основные настройки субтитров":
                    subgroup_label.setStyleSheet("margin-top: 0px;")  # Минимальный отступ для субтитров
                
                main_layout.addWidget(subgroup_label)

                # Специальная обработка для виджета выбора голоса
                if params == "voice_selector":
                    voice_selector = VoiceSelectorWidget()
                    voice_selector.voice_selected.connect(self.on_voice_selected)
                    main_layout.addWidget(voice_selector)

                    # Сохраняем ссылку на виджет
                    self.voice_selector_widget = voice_selector

                    # Добавляем разделитель
                    separator = self.create_separator()
                    main_layout.addWidget(separator)
                    continue

                # Специальная обработка для виджета настроек голоса
                elif params == "voice_settings":
                    voice_settings = VoiceSettingsWidget()

                    # Подключаем сигналы для автоматического сохранения (только если доступны)
                    if VOICE_SETTINGS_AVAILABLE:
                        try:
                            voice_settings.stability_changed.connect(self.on_voice_setting_changed)
                            voice_settings.similarity_changed.connect(self.on_voice_setting_changed)
                            voice_settings.speed_changed.connect(self.on_voice_setting_changed)
                        except AttributeError as e:
                            logger.warning(f"Не удалось подключить сигналы VoiceSettingsWidget: {e}")

                    main_layout.addWidget(voice_settings)

                    # Сохраняем ссылку на виджет
                    self.voice_settings_widget = voice_settings

                    # Добавляем разделитель
                    separator = self.create_separator()
                    main_layout.addWidget(separator)
                    continue

                # Специальная обработка для визуального редактора логотипов
                elif params == "logo_position_editor":
                    # Добавляем отрицательный спейсер перед logo_editor для уменьшения отступа от заголовка
                    negative_spacer = QSpacerItem(0, -2, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                    main_layout.addItem(negative_spacer)
                    
                    logo_editor = LogoPositionEditor()
                    logo_editor.logo_position_changed.connect(self.on_logo_position_changed)
                    
                    
                    # Добавляем logo_editor с минимальными отступами и центрированием
                    main_layout.addWidget(logo_editor, 0, Qt.AlignmentFlag.AlignHCenter)
                    
                    # Устанавливаем минимальные отступы для logo_editor
                    logo_editor.setContentsMargins(0, 0, 0, 0)

                    # Сохраняем ссылку на виджет
                    self.logo_position_editor = logo_editor

                    # Убираем разделитель после визуального редактора логотипов для минимизации отступов
                    # separator = self.create_separator()
                    # main_layout.addWidget(separator)
                    continue

                # Специальная обработка для предпросмотра субтитров
                elif params == "subtitle_preview":
                    try:
                        from ui.subtitle_preview_widget import SubtitlePreviewWidget
                        subtitle_preview = SubtitlePreviewWidget()
                        
                        main_layout.addWidget(subtitle_preview, 0, Qt.AlignmentFlag.AlignHCenter)
                        
                        # Сохраняем ссылку на виджет
                        self.subtitle_preview_widget = subtitle_preview
                        
                        # Убираем разделитель после предпросмотра субтитров для минимизации отступов
                        # separator = self.create_separator()
                        # main_layout.addWidget(separator)
                        continue
                    except ImportError:
                        # Fallback если виджет недоступен
                        fallback_label = QLabel("Предпросмотр субтитров недоступен")
                        main_layout.addWidget(fallback_label)
                        continue

                # Стандартная обработка параметров
                grid_layout = self.create_parameters_grid(params, category)
                
                # Стандартная обработка параметров - БЕЗ КОНТЕЙНЕРОВ как в старом файле
                main_layout.addLayout(grid_layout)

                # Добавляем разделитель
                separator = self.create_separator()
                main_layout.addWidget(separator)

            # Удаляем последний разделитель
            if main_layout.count() > 0:
                last_item = main_layout.takeAt(main_layout.count() - 1)
                if last_item.widget():
                    last_item.widget().deleteLater()

            scroll_area.setWidget(scroll_widget)
            scroll_area.setWidgetResizable(True)  # Позволяем resize для правильной центровки
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # Убираем горизонтальную прокрутку
            
            # ДЛЯ ВСЕХ КАТЕГОРИЙ разрешаем скролл (НЕ фиксируем высоту)
            
            # Принудительно убираем все отступы у QScrollArea
            scroll_area.setContentsMargins(0, 0, 0, 0)
            scroll_area.setViewportMargins(0, 0, 0, 0)
            scroll_area.setFrameStyle(0)  # Убираем рамку
            
            
            # ДЛЯ ВСЕХ КАТЕГОРИЙ одинаковое выравнивание для корректной работы скролла
            scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            
            # Добавляем в обычный QTabWidget
            tab_index = self.tabs.addTab(scroll_area, category)
            
            # Создаем кастомную кнопку-таб (как кнопки монтажа) - АДАПТИВНАЯ!
            custom_tab_button = QPushButton(category)
            custom_tab_button.setCheckable(True)
            custom_tab_button.clicked.connect(lambda checked, idx=tab_index: self.on_custom_tab_clicked(idx))
            self.custom_tab_buttons_layout.addWidget(custom_tab_button)
            
            # Делаем первую кнопку активной
            if tab_index == 0:
                custom_tab_button.setChecked(True)
        
        # Сохраняем ссылки на кастомные кнопки для управления
        self.custom_tab_buttons = []
        for i in range(self.custom_tab_buttons_layout.count()):
            item = self.custom_tab_buttons_layout.itemAt(i)
            if item and item.widget():
                self.custom_tab_buttons.append(item.widget())
    
    def on_custom_tab_clicked(self, tab_index):
        """Обработчик клика на кастомную кнопку-таб"""
        # Переключаем активную вкладку в QTabWidget
        self.tabs.setCurrentIndex(tab_index)
        
        # Обновляем состояние всех кнопок
        for i, button in enumerate(self.custom_tab_buttons):
            button.setChecked(i == tab_index)

    def on_voice_setting_changed(self):
        """Обработка изменения настроек голоса"""
        try:
            # Автоматически сохраняем настройки при изменении ползунков
            if hasattr(self, 'voice_settings_widget') and self.voice_settings_widget:
                settings = self.voice_settings_widget.get_settings_for_config()

                # Обновляем соответствующие поля в конфигурации (если они существуют)
                for key, value in settings.items():
                    if key in self.param_entries:
                        widget = self.param_entries[key]
                        # Проверяем тип виджета и вызываем соответствующий метод
                        if hasattr(widget, 'set_color'):  # ColorPickerWidget
                            widget.set_color(str(value))
                        elif hasattr(widget, 'setText'):  # QLineEdit и подобные
                            widget.setText(str(value))

                # Автоматическое сохранение настроек голоса
                self.auto_save_parameters()
                logger.debug(f"Настройки голоса автоматически обновлены и сохранены: {settings}")
        except Exception as e:
            logger.error(f"Ошибка обновления настроек голоса: {e}")

    def on_subtitle_color_changed(self, color: str):
        """Обработка изменения цвета субтитров"""
        try:
            # Автоматически сохраняем настройки при изменении цвета
            self.auto_save_parameters()
            
            # Обновляем предпросмотр субтитров если он доступен
            if hasattr(self, 'subtitle_preview_widget') and self.subtitle_preview_widget:
                # Собираем все настройки субтитров
                subtitle_config = {}
                color_fields = self.get_color_fields()
                for field in color_fields:
                    if field in self.param_entries:
                        if hasattr(self.param_entries[field], 'get_color'):
                            subtitle_config[field] = self.param_entries[field].get_color()
                        elif hasattr(self.param_entries[field], 'text'):
                            subtitle_config[field] = self.param_entries[field].text()
                
                # Добавляем другие параметры субтитров
                subtitle_params = [
                    'subtitle_fontsize', 'subtitle_use_backdrop', 'subtitle_outline_thickness',
                    'subtitle_shadow_thickness', 'subtitle_shadow_alpha', 'subtitle_shadow_offset_x',
                    'subtitle_shadow_offset_y', 'subtitle_margin_v', 'subtitle_margin_l', 
                    'subtitle_margin_r', 'subtitle_line_spacing'
                ]
                for param in subtitle_params:
                    if param in self.param_entries:
                        if hasattr(self.param_entries[param], 'isChecked'):
                            subtitle_config[param] = self.param_entries[param].isChecked()
                        elif hasattr(self.param_entries[param], 'text'):
                            subtitle_config[param] = self.param_entries[param].text()
                
                # Обновляем предпросмотр
                self.subtitle_preview_widget.update_subtitle_preview(subtitle_config)
                
                # Принудительно очищаем визуальные артефакты после смены цвета
                self.subtitle_preview_widget.force_clear_artifacts()
                
            logger.debug(f"Цвет субтитров изменен: {color}")
        except Exception as e:
            logger.error(f"Ошибка изменения цвета субтитров: {e}")

    def on_subtitle_font_changed(self, font_name: str):
        """Обработка изменения шрифта субтитров"""
        try:
            logger.debug(f"🔤 СМЕНА ШРИФТА СУБТИТРОВ: {font_name}")
            # Автоматически сохраняем настройки при изменении шрифта
            self.auto_save_parameters()
            
            # Обновляем предпросмотр субтитров если он доступен
            if hasattr(self, 'subtitle_preview_widget') and self.subtitle_preview_widget:
                logger.debug(f"🔍 ПРЕДПРОСМОТР НАЙДЕН, ОБНОВЛЯЕМ...")
                # Собираем все настройки субтитров
                subtitle_config = {}
                
                # Добавляем шрифт
                subtitle_config['subtitle_font_family'] = font_name
                
                # Собираем цветовые параметры
                color_fields = self.get_color_fields()
                for field in color_fields:
                    if field in self.param_entries:
                        if hasattr(self.param_entries[field], 'get_color'):
                            subtitle_config[field] = self.param_entries[field].get_color()
                        elif hasattr(self.param_entries[field], 'text'):
                            subtitle_config[field] = self.param_entries[field].text()
                
                # ИСПОЛЬЗУЕМ СОХРАНЕННУЮ КОНФИГУРАЦИЮ вместо значений из UI
                # Это предотвращает проблемы со значениями, которые могли быть изменены в UI
                # Получаем имя текущего канала из комбобокса
                checked_channels = self.channel_combo.checkedItems()
                current_channel = checked_channels[0] if checked_channels else None
                if current_channel:
                    current_config = self.config_manager.get_channel_config(current_channel)
                    if current_config:
                        logger.debug(f"🔧 Используем сохраненную конфигурацию для subtitle_line_spacing: {current_config.get('subtitle_line_spacing', 'НЕТ')}")
                        subtitle_config.update({
                            'subtitle_fontsize': current_config.get('subtitle_fontsize', 110),
                            'subtitle_use_backdrop': current_config.get('subtitle_use_backdrop', False),
                            'subtitle_outline_thickness': current_config.get('subtitle_outline_thickness', 4),
                            'subtitle_shadow_thickness': current_config.get('subtitle_shadow_thickness', 1),
                            'subtitle_shadow_alpha': current_config.get('subtitle_shadow_alpha', 50),
                            'subtitle_shadow_offset_x': current_config.get('subtitle_shadow_offset_x', 2),
                            'subtitle_shadow_offset_y': current_config.get('subtitle_shadow_offset_y', 2),
                            'subtitle_margin_v': current_config.get('subtitle_margin_v', 20),
                            'subtitle_margin_l': current_config.get('subtitle_margin_l', 10),
                            'subtitle_margin_r': current_config.get('subtitle_margin_r', 10),
                            'subtitle_line_spacing': current_config.get('subtitle_line_spacing', 1.2) / 10.0 if isinstance(current_config.get('subtitle_line_spacing', 1.2), (int, float)) and current_config.get('subtitle_line_spacing', 1.2) >= 5 else current_config.get('subtitle_line_spacing', 1.2)
                        })
                    else:
                        # Fallback к старому способу если нет конфигурации канала
                        current_config = None
                else:
                    # Fallback к старому способу если нет текущего канала
                    current_config = None
                
                if current_config is None:
                    # Fallback к старому способу если нет конфигурации
                    subtitle_params = [
                        'subtitle_fontsize', 'subtitle_use_backdrop', 'subtitle_outline_thickness',
                        'subtitle_shadow_thickness', 'subtitle_shadow_alpha', 'subtitle_shadow_offset_x',
                        'subtitle_shadow_offset_y', 'subtitle_margin_v', 'subtitle_margin_l', 
                        'subtitle_margin_r', 'subtitle_line_spacing'
                    ]
                    for param in subtitle_params:
                        if param in self.param_entries:
                            if hasattr(self.param_entries[param], 'isChecked'):
                                subtitle_config[param] = self.param_entries[param].isChecked()
                            elif hasattr(self.param_entries[param], 'value'):
                                raw_value = self.param_entries[param].value()
                                # Специальная обработка для межстрочного интервала
                                if param == 'subtitle_line_spacing':
                                    converted_value = raw_value / 10.0  # Преобразуем из диапазона 5-30 в 0.5-3.0
                                    subtitle_config[param] = converted_value
                                    logger.debug(f"🔍 on_subtitle_font_changed: {param} = {raw_value} → {converted_value}")
                                else:
                                    subtitle_config[param] = raw_value
                            elif hasattr(self.param_entries[param], 'text'):
                                subtitle_config[param] = self.param_entries[param].text()
                
                # Обновляем предпросмотр
                logger.debug(f"🔄 ВЫЗЫВАЕМ update_subtitle_preview с конфигом: {len(subtitle_config)} параметров")
                self.subtitle_preview_widget.update_subtitle_preview(subtitle_config)
                
                # Принудительно очищаем визуальные артефакты после смены шрифта
                self.subtitle_preview_widget.force_clear_artifacts()
                
            logger.debug(f"Шрифт субтитров изменен: {font_name}")
        except Exception as e:
            logger.error(f"Ошибка изменения шрифта субтитров: {e}")

    def on_subtitle_setting_changed(self):
        """Обработка изменения настроек субтитров через слайдеры"""
        try:
            # Автоматически сохраняем настройки
            self.auto_save_parameters()
            
            # Обновляем предпросмотр субтитров если он доступен
            if hasattr(self, 'subtitle_preview_widget') and self.subtitle_preview_widget:
                # Собираем все настройки субтитров
                subtitle_config = {}
                
                # Собираем цветовые параметры
                color_fields = self.get_color_fields()
                for field in color_fields:
                    if field in self.param_entries:
                        if hasattr(self.param_entries[field], 'get_color'):
                            subtitle_config[field] = self.param_entries[field].get_color()
                        elif hasattr(self.param_entries[field], 'text'):
                            subtitle_config[field] = self.param_entries[field].text()
                
                # Собираем параметры слайдеров и другие
                subtitle_params = [
                    'subtitle_font_family', 'subtitle_fontsize', 'subtitle_use_backdrop', 
                    'subtitle_outline_thickness', 'subtitle_shadow_thickness', 'subtitle_shadow_alpha', 
                    'subtitle_shadow_offset_x', 'subtitle_shadow_offset_y', 'subtitle_margin_v',
                    'subtitle_margin_l', 'subtitle_margin_r', 'subtitle_line_spacing'
                ]
                for param in subtitle_params:
                    if param in self.param_entries:
                        if hasattr(self.param_entries[param], 'isChecked'):
                            subtitle_config[param] = self.param_entries[param].isChecked()
                        elif hasattr(self.param_entries[param], 'currentText'):
                            subtitle_config[param] = self.param_entries[param].currentText()
                        elif hasattr(self.param_entries[param], 'text'):
                            subtitle_config[param] = self.param_entries[param].text()
                        elif hasattr(self.param_entries[param], 'value'):
                            raw_value = self.param_entries[param].value()
                            # Специальная обработка для межстрочного интервала
                            if param == 'subtitle_line_spacing':
                                subtitle_config[param] = raw_value / 10.0  # Преобразуем из диапазона 5-30 в 0.5-3.0
                            else:
                                subtitle_config[param] = raw_value
                
                # Обновляем предпросмотр
                self.subtitle_preview_widget.update_subtitle_preview(subtitle_config)
                
            logger.debug("Настройки субтитров обновлены через слайдеры")
        except Exception as e:
            logger.error(f"Ошибка изменения настроек субтитров: {e}")

    def _delayed_subtitle_update(self):
        """Отложенное обновление субтитров с дебаунсингом"""
        self.on_subtitle_setting_changed()

    def on_logo_position_changed(self, logo_id: str, x: int, y: int, width: int):
        """Обработка изменения позиции логотипа в визуальном редакторе"""
        try:
            # При множественном выборе каналов сохраняем позицию только для первого канала
            # Извлекаем базовый тип логотипа из logo_id (убираем индекс канала)
            base_logo_type = logo_id.split('_')[0]  # logo1_0 -> logo1
            
            logger.debug(f"🔄 Изменение позиции: logo_id='{logo_id}', base_type='{base_logo_type}'")
            
            # Сохраняем только если это логотипы первого канала (индекс 0)
            if not logo_id.endswith('_0'):
                logger.debug(f"Пропускаем сохранение для {logo_id} - не первый канал")
                return
            # ИСПРАВЛЕНИЕ: Всегда получаем размеры из конфигурации, а не от редактора
            # Получаем реальные размеры из текущей конфигурации (приоритет над редактором)
            config_width = width  # Fallback значение
            
            if base_logo_type == "logo1" and "logo_width" in self.param_entries:
                try:
                    saved_width = self.param_entries["logo_width"].text().strip()
                    if saved_width:  # Если поле не пустое, используем сохраненное значение
                        config_width = int(saved_width)
                        logger.debug(f"🔧 Использую сохраненную ширину logo1: {config_width}")
                    else:
                        logger.debug(f"⚠️ Поле logo_width пустое, использую от редактора: {width}")
                except (ValueError, AttributeError):
                    logger.warning(f"⚠️ Ошибка чтения logo_width, использую от редактора: {width}")
                    config_width = width
            elif base_logo_type == "logo2" and "logo2_width" in self.param_entries:
                try:
                    saved_width = self.param_entries["logo2_width"].text().strip()
                    if saved_width:  # Если поле не пустое, используем сохраненное значение
                        config_width = int(saved_width)
                        logger.debug(f"🔧 Использую сохраненную ширину logo2: {config_width}")
                    else:
                        logger.debug(f"⚠️ Поле logo2_width пустое, использую от редактора: {width}")
                except (ValueError, AttributeError):
                    logger.warning(f"⚠️ Ошибка чтения logo2_width, использую от редактора: {width}")
                    config_width = width
            elif base_logo_type == "subscribe" and "subscribe_width" in self.param_entries:
                try:
                    saved_width = self.param_entries["subscribe_width"].text().strip()
                    if saved_width:  # Если поле не пустое, используем сохраненное значение
                        config_width = int(saved_width)
                        logger.debug(f"🔧 Использую сохраненную ширину subscribe: {config_width}")
                    else:
                        logger.debug(f"⚠️ Поле subscribe_width пустое, использую от редактора: {width}")
                except (ValueError, AttributeError):
                    logger.warning(f"⚠️ Ошибка чтения subscribe_width, использую от редактора: {width}")
                    config_width = width
            
            config_height = int(config_width * 0.5)  # Примерная пропорция
            
            # Вычисляем высоту на основе ширины
            config_height = int(config_width * 0.5)
            
            # Преобразуем пиксельные координаты в FFmpeg выражения
            ffmpeg_x = convert_pixels_to_ffmpeg_coords(x, 'x', 1920, 1080, config_width, config_height)
            ffmpeg_y = convert_pixels_to_ffmpeg_coords(y, 'y', 1920, 1080, config_width, config_height)

            # Обновляем соответствующие поля (используем базовый тип)
            if base_logo_type == "logo1":
                if "logo_position_x" in self.param_entries:
                    self.param_entries["logo_position_x"].setText(ffmpeg_x)
                if "logo_position_y" in self.param_entries:
                    self.param_entries["logo_position_y"].setText(ffmpeg_y)
                if "logo_width" in self.param_entries:
                    self.param_entries["logo_width"].setText(str(config_width))
            elif base_logo_type == "logo2":
                if "logo2_position_x" in self.param_entries:
                    self.param_entries["logo2_position_x"].setText(ffmpeg_x)
                if "logo2_position_y" in self.param_entries:
                    self.param_entries["logo2_position_y"].setText(ffmpeg_y)
                if "logo2_width" in self.param_entries:
                    self.param_entries["logo2_width"].setText(str(config_width))
            elif base_logo_type == "subscribe":
                if "subscribe_position_x" in self.param_entries:
                    self.param_entries["subscribe_position_x"].setText(ffmpeg_x)
                if "subscribe_position_y" in self.param_entries:
                    self.param_entries["subscribe_position_y"].setText(ffmpeg_y)
                if "subscribe_width" in self.param_entries:
                    self.param_entries["subscribe_width"].setText(str(config_width))
            
            # ПОЛНОСТЬЮ ОТКЛЮЧАЕМ автосохранение при множественном выборе каналов
            # для предотвращения краша - сохранение только по кнопке
            checked_items = self.channel_combo.checkedItems()
            if len(checked_items) == 1:
                # Только для одного канала включаем автосохранение
                self.auto_save_parameters()
            else:
                logger.debug(f"⚠️ Автосохранение ОТКЛЮЧЕНО для {logo_id} при множественном выборе каналов ({len(checked_items)} каналов). Используйте кнопку 'Сохранить параметры'.")

            logger.info(f"💾 Позиция {logo_id} обновлена: x='{ffmpeg_x}', y='{ffmpeg_y}', width={config_width} (сохранённая), width_from_editor={width}")
        except Exception as e:
            logger.error(f"Ошибка обновления позиции логотипа: {e}")

    def create_parameters_grid(self, params: List, category: str = "") -> QGridLayout:
        """Создание сетки параметров"""
        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        
        # Настройки растяжения для разных групп
        if category in ["Логотипы", "Субтитры"]:
            # Для логотипов и субтитров делаем как в группе "Аудио" - с растяжением
            grid_layout.setColumnStretch(0, 1)
            grid_layout.setColumnStretch(2, 1)
            # УБИРАЕМ setSizeConstraint - он блокирует адаптивность!
            # grid_layout.setSizeConstraint(QGridLayout.SizeConstraint.SetMinimumSize)
        else:
            # Для остальных групп: полностью адаптивные
            grid_layout.setColumnStretch(0, 1)
            grid_layout.setColumnStretch(2, 1)

        for i, param in enumerate(params):
            if isinstance(param, tuple):
                param_key, param_label = param
            else:
                param_key = param
                param_label = param

            row = i // 2
            col = (i % 2) * 2

            # Создание элемента ввода
            entry_widget = self.create_parameter_widget(param_key, category)
            
            # Специальная обработка для чекбоксов - объединяем с меткой
            if param_key in self.get_checkbox_fields():
                from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget
                
                # Создаем контейнер для чекбокса и метки
                checkbox_container = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setSpacing(10)  # Нормальный spacing между чекбоксом и текстом
                
                # Добавляем чекбокс
                checkbox_layout.addWidget(entry_widget)
                
                # Добавляем метку сразу после чекбокса
                label = QLabel(param_label)
                tooltip = self.get_tooltip_for_parameter(param_key)
                label.setToolTip(tooltip)
                checkbox_layout.addWidget(label)
                
                # Добавляем растяжение справа
                checkbox_layout.addStretch()
                
                # Обычное размещение для всех групп
                grid_layout.addWidget(checkbox_container, row, col, 1, 2)
            else:
                # Обычная обработка для других элементов
                label = QLabel(f"{param_label}:")
                tooltip = self.get_tooltip_for_parameter(param_key)
                label.setToolTip(tooltip)
                
                # Фиксируем только высоту метки для неадаптивных групп
                if category in ["Логотипы", "Субтитры"]:
                    label.setFixedHeight(30)
                    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                
                # Обычное размещение для всех групп (как в "Аудио")
                grid_layout.addWidget(label, row, col)
                grid_layout.addWidget(entry_widget, row, col + 1)

        return grid_layout

    def create_parameter_widget(self, param_key: str, category: str = "") -> QWidget:
        """Создание виджета для параметра"""
        path_fields = self.get_path_fields()
        checkbox_fields = self.get_checkbox_fields()
        combo_fields = self.get_combo_fields()
        slider_fields = self.get_slider_fields()
        color_fields = self.get_color_fields()
        
        # Определяем нужна ли фиксированная высота для неадаптивных групп
        is_fixed_height = category in ["Логотипы", "Субтитры"]

        if param_key in color_fields:
            try:
                from ui.color_picker_widget import ColorPickerWidget
                entry = ColorPickerWidget()
                if is_fixed_height:
                    entry.setFixedHeight(30)  # Только фиксированная высота
                    entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                entry.setMinimumWidth(200)  # Минимальная ширина для всех
                entry.color_changed.connect(self.on_subtitle_color_changed)
                self.param_entries[param_key] = entry
                return entry
            except ImportError:
                # Fallback на обычное текстовое поле
                entry = QLineEdit()
                entry.setMinimumWidth(200)
                if is_fixed_height:
                    entry.setFixedHeight(30)  # Только фиксированная высота
                    entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                entry.setPlaceholderText("&HFFFFFF")
                entry.textChanged.connect(self.auto_save_parameters)
                self.param_entries[param_key] = entry
                return entry
        elif param_key in path_fields:
            entry_widget, entry = self.create_path_widget(param_key)
            self.param_entries[param_key] = entry
            return entry_widget
        elif param_key in checkbox_fields:
            entry = QCheckBox()
            if is_fixed_height:
                entry.setFixedHeight(30)
                # УБИРАЕМ setSizePolicy - он растягивает чекбокс и создает большое пространство!
                # entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            entry.stateChanged.connect(self.auto_save_parameters)
            self.param_entries[param_key] = entry
            return entry
        elif param_key in combo_fields:
            entry = self.create_combo_widget(param_key, is_fixed_height)
            entry.currentTextChanged.connect(self.auto_save_parameters)
            self.param_entries[param_key] = entry
            return entry
        elif param_key in slider_fields:
            entry_widget, entry = self.create_slider_widget(param_key)
            entry.valueChanged.connect(self.auto_save_parameters)
            self.param_entries[param_key] = entry
            return entry_widget
        else:
            entry = QLineEdit()
            entry.setMinimumWidth(200)
            if is_fixed_height:
                entry.setFixedHeight(30)  # Только фиксированная высота
                entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            entry.textChanged.connect(self.auto_save_parameters)
            if param_key == "preserve_clip_audio_videos":
                entry.setPlaceholderText("Например: 3,5")
            elif param_key == "video_numbers":
                entry.setPlaceholderText("Например: 1,3,5-8,10")
                entry.setToolTip("Номера видео для генерации. Можно указать отдельные номера через запятую (1,3,5) или диапазоны (1-5,8,10-12)")
            elif param_key == "max_concurrent_montages":
                entry.setPlaceholderText("3")
                entry.setToolTip("Максимальное количество одновременных процессов монтажа")
            self.param_entries[param_key] = entry
            return entry

    def create_path_widget(self, param_key: str) -> tuple:
        """Создание виджета для выбора пути"""
        entry_widget = QWidget()
        entry_layout = QHBoxLayout(entry_widget)
        entry_layout.setContentsMargins(0, 0, 0, 0)

        entry = QLineEdit()
        entry.setMinimumWidth(200)
        entry.textChanged.connect(self.auto_save_parameters)
        entry_layout.addWidget(entry)

        browse_button = QPushButton("...")
        browse_button.setObjectName("browse")
        browse_button.setFixedWidth(30)
        is_file = param_key.endswith("_path")
        browse_button.clicked.connect(
            lambda checked, e=entry, file=is_file: self.browse_path(e, file)
        )
        entry_layout.addWidget(browse_button)

        return entry_widget, entry

    def create_separator(self) -> QFrame:
        """Создание разделителя"""
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        return separator

    def browse_path(self, entry: QLineEdit, is_file: bool):
        """Обзор пути к файлу или папке"""
        if is_file:
            path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        else:
            path = QFileDialog.getExistingDirectory(self, "Выберите папку")

        if path:
            entry.setText(path)

    def on_voice_selected(self, original_voice_id: str, public_owner_id: str):
        """Обработка выбора голоса из библиотеки"""
        # Обновляем поля в настройках
        if "original_voice_id" in self.param_entries:
            self.param_entries["original_voice_id"].setText(original_voice_id)
        if "public_owner_id" in self.param_entries:
            self.param_entries["public_owner_id"].setText(public_owner_id)

        # Автоматическое сохранение настроек голоса
        self.auto_save_parameters()
        logger.info(f"Выбран голос из библиотеки и сохранен: {original_voice_id}, владелец: {public_owner_id}")

    def load_channel_config(self):
        """Загрузка конфигурации канала"""
        if self.is_config_loading and self.config_loader and self.config_loader.isRunning():
            self.config_loader.quit()
            self.config_loader.wait()

        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            self.montage_button.setEnabled(False)
            self.voiceover_button.setEnabled(False)
            return

        channel_name = checked_items[0]
        self.is_config_loading = True

        self.config_loader = ConfigLoader(channel_name, self.config_manager)
        self.config_loader.config_loaded.connect(self.load_channel_config_complete)
        self.config_loader.error_occurred.connect(self.show_error)
        self.config_loader.start()

    def load_channel_config_complete(self, channel_config: Dict, proxy_config: Dict, logging_config: LoggingConfig):
        """Завершение загрузки конфигурации канала"""
        try:
            self.current_logging_config = logging_config

            # Загрузка параметров в UI
            default_config = self.config_manager.get_default_channel_config()
            for key, entry in self.param_entries.items():
                if key in ["proxy", "proxy_login", "proxy_password", "use_proxy"]:
                    value = proxy_config.get(key, True if key == "use_proxy" else "")
                elif key in ["debug_video_processing", "debug_audio_processing",
                             "debug_subtitles_processing", "debug_final_assembly"]:
                    value = proxy_config.get("debug_config", {}).get(key, False)
                else:
                    # ИСПРАВЛЕНИЕ: Используем правильные значения по умолчанию вместо пустой строки
                    default_value = default_config.get(key, "")
                    value = channel_config.get(key, default_value)

                if isinstance(entry, QCheckBox):
                    entry.setChecked(bool(value))
                elif key in self.get_combo_fields():
                    # Для выпадающих списков
                    from PySide6.QtWidgets import QComboBox
                    if isinstance(entry, QComboBox):
                        # Проверяем есть ли internal_values
                        internal_values = entry.property("internal_values")
                        if internal_values:
                            # Используем internal_values для поиска соответствующего индекса
                            try:
                                index = internal_values.index(str(value))
                                entry.setCurrentIndex(index)
                            except ValueError:
                                # Если значение не найдено, используем первое
                                entry.setCurrentIndex(0)
                        else:
                            # Преобразуем английское значение в русское для отображения
                            russian_value = self.get_combo_translation(key, str(value), to_english=False)
                            index = entry.findText(russian_value)
                            if index >= 0:
                                entry.setCurrentIndex(index)
                elif key in self.get_slider_fields():
                    # Для слайдеров
                    from PySide6.QtWidgets import QSlider
                    if isinstance(entry, QSlider):
                        try:
                            if key in ["bokeh_intensity", "vignette_strength", "video_zoom_intensity"]:
                                # Умножаем на 100 для слайдера
                                entry.setValue(int(float(value) * 100))
                            elif key in ["sharpen_strength", "contrast_factor", "saturation_factor", "transition_duration", "video_rotation_angle"]:
                                # Умножаем на 10 для слайдера
                                entry.setValue(int(float(value) * 10))
                            elif key == "bokeh_blur_kernel":
                                # Извлекаем первое значение из списка [x, y] для слайдера
                                if isinstance(value, list) and len(value) >= 1:
                                    entry.setValue(int(value[0]))
                                else:
                                    entry.setValue(int(value))
                            else:
                                # Другие используются как есть
                                entry.setValue(int(value))
                        except (ValueError, TypeError):
                            # Устанавливаем значение по умолчанию при ошибке
                            pass
                else:
                    entry.setText(str(value))

            # Загрузка настроек в виджет ползунков (с защитой от ошибок)
            if hasattr(self, 'voice_settings_widget') and self.voice_settings_widget and VOICE_SETTINGS_AVAILABLE:
                try:
                    self.voice_settings_widget.load_from_config(channel_config)
                except Exception as e:
                    logger.warning(f"Не удалось загрузить настройки в VoiceSettingsWidget: {e}")

            # Настройка виджета выбора голоса
            self.setup_voice_selector(channel_config, proxy_config)

            # Настройка визуального редактора логотипов
            self.setup_logo_editor(channel_config)
            
            # Создание скрытых полей для позиций логотипов ПОСЛЕ загрузки основных полей
            self.create_hidden_position_fields(channel_config)

            # Обновление состояния UI
            self.status_label.setText("Загрузка завершена")
            self.montage_button.setEnabled(True)
            self.voiceover_button.setEnabled(True)
            self.channel_combo.setEnabled(True)
            self.is_config_loading = False

        except Exception as e:
            logger.error(f"Ошибка в load_channel_config_complete: {e}")
            self.show_error(str(e))

    def create_hidden_position_fields(self, channel_config: Dict):
        """Создание скрытых полей для позиций логотипов"""
        position_fields = [
            "logo_position_x", "logo_position_y",
            "logo2_position_x", "logo2_position_y", 
            "subscribe_position_x", "subscribe_position_y"
        ]
        
        # Получаем имя текущего канала для загрузки актуальной конфигурации
        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            return
            
        channel_name = checked_items[0]
        actual_config = self.config_manager.get_channel_config(channel_name)
        
        for field in position_fields:
            if field not in self.param_entries:
                # Создаем скрытое поле
                entry = QLineEdit()
                entry.setVisible(False)  # Делаем невидимым
                entry.textChanged.connect(self.auto_save_parameters)
                
                # Берём значение из АКТУАЛЬНОЙ конфигурации файла
                value = actual_config.get(field, "")
                # Если значения нет в конфигурации, устанавливаем дефолтное значение
                if not value:
                    if field == "logo_position_x":
                        value = "W-w-20"
                    elif field == "logo_position_y":
                        value = "20"
                    elif field == "logo2_position_x":
                        value = "20"
                    elif field == "logo2_position_y":
                        value = "20"
                    elif field == "subscribe_position_x":
                        value = "-50"
                    elif field == "subscribe_position_y":
                        value = "main_h-overlay_h+150"
                entry.setText(str(value))
                
                # Добавляем в param_entries
                self.param_entries[field] = entry
                
                logger.debug(f"✅ Создано скрытое поле {field} со значением из файла: '{value}'")
            else:
                # Поле уже существует - проверяем, не обновилось ли значение в файле
                actual_value = actual_config.get(field, "")
                current_value = self.param_entries[field].text()
                if current_value != str(actual_value):
                    self.param_entries[field].setText(str(actual_value))
                    logger.debug(f"Обновлено скрытое поле {field}: {current_value} -> {actual_value}")

    def setup_voice_selector(self, channel_config: Dict, proxy_config: Dict):
        """Настройка виджета выбора голоса"""
        if not hasattr(self, 'voice_selector_widget') or not self.voice_selector_widget:
            return

        try:
            # Получение API ключа из CSV файла
            csv_file_path = channel_config.get("csv_file_path", "")
            if not csv_file_path:
                logger.warning("Не указан путь к CSV файлу с API ключами")
                return

            api_key_manager = APIKeyManager(csv_file_path)
            api_key = api_key_manager.get_api_key()

            if not api_key:
                logger.warning("Не удалось получить API ключ для загрузки голосов")
                return

            # Передача конфигурации в виджет
            self.voice_selector_widget.set_api_config(api_key, proxy_config)

            # Установка текущего голоса
            original_voice_id = channel_config.get("original_voice_id", "")
            public_owner_id = channel_config.get("public_owner_id", "")

            if original_voice_id and public_owner_id:
                self.voice_selector_widget.set_current_voice(original_voice_id, public_owner_id)

        except Exception as e:
            logger.error(f"Ошибка настройки виджета выбора голоса: {e}")

    def setup_logo_editor(self, channel_config: Dict):
        """Настройка визуального редактора логотипов"""
        if not hasattr(self, 'logo_position_editor') or not self.logo_position_editor:
            return

        try:
            # Получаем все выбранные каналы для наложения логотипов как слоев
            checked_items = self.channel_combo.checkedItems()
            
            # Очищаем предыдущие логотипы
            self.logo_position_editor.clear_all_logos()
            
            # Ограничиваем количество одновременно загружаемых каналов для предотвращения краша
            max_channels = 3  # Максимум 3 канала одновременно
            channels_to_load = checked_items[:max_channels]
            
            if len(checked_items) > max_channels:
                logger.warning(f"Загружаем только первые {max_channels} каналов из {len(checked_items)} выбранных для предотвращения перегрузки")
            
            # Загружаем логотипы для выбранных каналов
            for i, channel_name in enumerate(channels_to_load):
                try:
                    channel_cfg = self.config_manager.get_channel_config(channel_name)
                    if channel_cfg:
                        self._load_channel_logos(channel_cfg, channel_name, i)
                    else:
                        logger.warning(f"Конфигурация для канала '{channel_name}' не найдена")
                except Exception as e:
                    logger.error(f"Ошибка загрузки логотипов для канала '{channel_name}': {e}")
                    continue
                
        except Exception as e:
            logger.error(f"Ошибка настройки визуального редактора логотипов: {e}")
    
    def _load_channel_logos(self, channel_config: Dict, channel_name: str, channel_index: int):
        """Загружает логотипы для одного канала с уникальными ID"""
        try:
            # Проверяем валидность конфигурации
            if not channel_config:
                logger.warning(f"Пустая конфигурация для канала {channel_name}")
                return
            # Создаем уникальные ID для логотипов каждого канала
            logo1_id = f"logo1_{channel_index}"
            logo2_id = f"logo2_{channel_index}"
            subscribe_id = f"subscribe_{channel_index}"
            
            # Загружаем логотипы если пути указаны
            logo_path = channel_config.get("logo_path", "")
            logo2_path = channel_config.get("logo2_path", "")
            subscribe_frames_folder = channel_config.get("subscribe_frames_folder", "")

            logger.debug(f"Канал {channel_index}: Пути логотипов: logo1='{logo_path}', logo2='{logo2_path}', subscribe='{subscribe_frames_folder}'")

            # Определяем прозрачность - первый канал непрозрачный, остальные полупрозрачные
            opacity = 1.0 if channel_index == 0 else 0.7

            if logo_path and Path(logo_path).exists():
                self.logo_position_editor.set_logo_image(logo1_id, logo_path, opacity)
                logger.debug(f"Логотип 1 канала {channel_index} загружен: {logo_path}")
            else:
                logger.debug(f"Логотип 1 канала {channel_index} не загружен: пусть={'пустой' if not logo_path else logo_path}, существует={Path(logo_path).exists() if logo_path else False}")

            if logo2_path and Path(logo2_path).exists():
                self.logo_position_editor.set_logo_image(logo2_id, logo2_path, opacity)
                logger.debug(f"Логотип 2 канала {channel_index} загружен: {logo2_path}")
            else:
                logger.debug(f"Логотип 2 канала {channel_index} не загружен: пусть={'пустой' if not logo2_path else logo2_path}, существует={Path(logo2_path).exists() if logo2_path else False}")
                
            # Для кнопки подписки используем первый кадр из папки
            if subscribe_frames_folder and Path(subscribe_frames_folder).exists():
                subscribe_files = list(Path(subscribe_frames_folder).glob("*.png"))
                if subscribe_files:
                    # Берем первый найденный файл для превью
                    self.logo_position_editor.set_logo_image(subscribe_id, str(subscribe_files[0]), opacity)
                    logger.debug(f"Кнопка подписки канала {channel_index} загружена: {subscribe_files[0]}")
                else:
                    logger.debug(f"В папке кнопки подписки канала {channel_index} нет PNG файлов: {subscribe_frames_folder}")
            else:
                logger.debug(f"Папка кнопки подписки канала {channel_index} не найдена: пусть={'пустой' if not subscribe_frames_folder else subscribe_frames_folder}, существует={Path(subscribe_frames_folder).exists() if subscribe_frames_folder else False}")

            # Устанавливаем позиции - БЕРЕМ ИЗ ТЕКУЩИХ ПОЛЕЙ UI, А НЕ ИЗ ФАЙЛА
            # Для первого канала (channel_index == 0) используем текущие значения из param_entries
            if channel_index == 0:
                # Берем значения из текущих полей UI (они уже загружены из конфигурации)
                def get_param_value(key, default):
                    entry = self.param_entries.get(key)
                    if entry and hasattr(entry, 'text'):
                        return entry.text()
                    return default
                
                logo_width = int(get_param_value("logo_width", channel_config.get("logo_width", 200)))
                logo_position_x = get_param_value("logo_position_x", channel_config.get("logo_position_x", "W-w-20"))
                logo_position_y = get_param_value("logo_position_y", channel_config.get("logo_position_y", "20"))
                
                logo2_width = int(get_param_value("logo2_width", channel_config.get("logo2_width", 200)))
                logo2_position_x = get_param_value("logo2_position_x", channel_config.get("logo2_position_x", "20"))
                logo2_position_y = get_param_value("logo2_position_y", channel_config.get("logo2_position_y", "20"))
                
                subscribe_width = int(get_param_value("subscribe_width", channel_config.get("subscribe_width", 1400)))
                subscribe_position_x = get_param_value("subscribe_position_x", channel_config.get("subscribe_position_x", "-50"))
                subscribe_position_y = get_param_value("subscribe_position_y", channel_config.get("subscribe_position_y", "main_h-overlay_h+150"))
                
                logger.info(f"🔄 ЗАГРУЖАЕМ ПОЗИЦИИ ИЗ UI: subscribe_x='{subscribe_position_x}', subscribe_y='{subscribe_position_y}'")
            else:
                # Для остальных каналов используем конфигурацию из файла
                logo_width = int(channel_config.get("logo_width", 200))
                logo_position_x = channel_config.get("logo_position_x", "W-w-20") or "W-w-20"
                logo_position_y = channel_config.get("logo_position_y", "20") or "20"
                
                logo2_width = int(channel_config.get("logo2_width", 200))
                logo2_position_x = channel_config.get("logo2_position_x", "20") or "20"
                logo2_position_y = channel_config.get("logo2_position_y", "20") or "20"
                
                subscribe_width = int(channel_config.get("subscribe_width", 1400))
                subscribe_position_x = channel_config.get("subscribe_position_x", "-50") or "-50"
                subscribe_position_y = channel_config.get("subscribe_position_y", "main_h-overlay_h+150") or "main_h-overlay_h+150"
            
            logo_height = int(logo_width * 0.5)  # Примерная пропорция
            
            logo_x = convert_ffmpeg_coords_to_pixels(
                logo_position_x,
                video_width=1920, video_height=1080,
                logo_width=logo_width, logo_height=logo_height
            )
            logo_y = convert_ffmpeg_coords_to_pixels(
                logo_position_y,
                video_width=1920, video_height=1080,
                logo_width=logo_width, logo_height=logo_height
            )

            logo2_height = int(logo2_width * 0.5)  # Примерная пропорция
            
            logo2_x = convert_ffmpeg_coords_to_pixels(
                logo2_position_x,
                video_width=1920, video_height=1080,
                logo_width=logo2_width, logo_height=logo2_height
            )
            logo2_y = convert_ffmpeg_coords_to_pixels(
                logo2_position_y,
                video_width=1920, video_height=1080,
                logo_width=logo2_width, logo_height=logo2_height
            )

            # Позиция кнопки подписки
            subscribe_height = int(subscribe_width * 0.15)  # Примерная пропорция для кнопки
            
            subscribe_x = convert_ffmpeg_coords_to_pixels(
                subscribe_position_x,
                video_width=1920, video_height=1080,
                logo_width=subscribe_width, logo_height=subscribe_height
            )
            subscribe_y = convert_ffmpeg_coords_to_pixels(
                subscribe_position_y,
                video_width=1920, video_height=1080,
                logo_width=subscribe_width, logo_height=subscribe_height
            )

            # Устанавливаем позиции в редакторе с использованием уникальных ID
            self.logo_position_editor.set_logo_position(logo1_id, logo_x, logo_y, logo_width)
            self.logo_position_editor.set_logo_position(logo2_id, logo2_x, logo2_y, logo2_width)
            
            # Устанавливаем позицию кнопки подписки только если она загружена
            if subscribe_id in self.logo_position_editor.logo_items:
                self.logo_position_editor.set_logo_position(subscribe_id, subscribe_x, subscribe_y, subscribe_width)

            logger.debug(f"Логотипы канала {channel_index} настроены в визуальном редакторе")

        except Exception as e:
            logger.error(f"Ошибка настройки логотипов канала {channel_index}: {e}")

    def save_parameters(self):
        """Сохранение параметров канала"""
        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            QMessageBox.critical(self, "Ошибка", "Выберите канал для сохранения параметров!")
            return

        # При множественном выборе сохраняем для первого канала, но уведомляем пользователя
        if len(checked_items) > 1:
            reply = QMessageBox.question(
                self, "Множественный выбор",
                f"Выбрано {len(checked_items)} каналов. Сохранить параметры для канала '{checked_items[0]}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        channel_name = checked_items[0]

        try:
            # Сбор данных из UI
            raw_config = {}
            for key, entry in self.param_entries.items():
                if isinstance(entry, QCheckBox):
                    raw_config[key] = entry.isChecked()
                elif key in self.get_combo_fields():
                    # Для выпадающих списков
                    from PySide6.QtWidgets import QComboBox
                    if isinstance(entry, QComboBox):
                        # Проверяем есть ли internal_values
                        internal_values = entry.property("internal_values")
                        if internal_values:
                            # Используем internal_values для получения внутреннего значения
                            current_index = entry.currentIndex()
                            if 0 <= current_index < len(internal_values):
                                raw_config[key] = internal_values[current_index]
                            else:
                                raw_config[key] = internal_values[0] if internal_values else ""
                        else:
                            # Преобразуем русское значение в английское для сохранения
                            russian_value = entry.currentText()
                            english_value = self.get_combo_translation(key, russian_value, to_english=True)
                            raw_config[key] = english_value
                elif key in self.get_slider_fields():
                    # Для слайдеров
                    from PySide6.QtWidgets import QSlider
                    if isinstance(entry, QSlider):
                        value = entry.value()
                        if key in ["bokeh_intensity", "vignette_strength", "video_zoom_intensity"]:
                            # Делим на 100 для получения десятичных значений
                            raw_config[key] = value / 100.0
                        elif key in ["sharpen_strength", "contrast_factor", "saturation_factor", "transition_duration", "video_rotation_angle"]:
                            # Делим на 10 для получения десятичных значений
                            raw_config[key] = value / 10.0
                        elif key == "bokeh_blur_kernel":
                            # Преобразуем одиночное значение в список [x, x] для корректной валидации
                            raw_config[key] = [value, value]
                        else:
                            # Другие сохраняются как есть
                            raw_config[key] = value
                else:
                    raw_config[key] = entry.text()

            # Добавляем настройки из виджета ползунков (с защитой от ошибок)
            if hasattr(self, 'voice_settings_widget') and self.voice_settings_widget and VOICE_SETTINGS_AVAILABLE:
                try:
                    voice_settings = self.voice_settings_widget.get_settings_for_config()
                    raw_config.update(voice_settings)
                except Exception as e:
                    logger.warning(f"Не удалось получить настройки из VoiceSettingsWidget: {e}")

            # Валидация конфигурации (пропускаем ошибки в автосохранении)
            try:
                validated_config = self.config_manager.validate_and_convert_config(raw_config)
            except ValueError as ve:
                logger.debug(f"Ошибка валидации при автосохранении (пропущена): {ve}")
                return  # Пропускаем сохранение при ошибках валидации

            # Разделение конфигурации на канальную и прокси
            channel_config = {}
            proxy_config = {"debug_config": {}}

            for key, value in validated_config.items():
                if key in ["proxy", "proxy_login", "proxy_password", "use_proxy", 
                           "proxy_type", "rotate_endpoint", "rotate_min_interval"]:
                    proxy_config[key] = value
                elif key in ["debug_video_processing", "debug_audio_processing",
                             "debug_subtitles_processing", "debug_final_assembly"]:
                    proxy_config["debug_config"][key] = value
                else:
                    channel_config[key] = value

            # Валидация preserve_clip_audio_videos отдельно
            preserve_audio_text = self.param_entries.get("preserve_clip_audio_videos", "")
            if hasattr(preserve_audio_text, 'text'):
                preserve_audio_text = preserve_audio_text.text()

            preserve_clip_audio_videos = self.config_manager.validator.validate_preserve_audio_videos(
                str(preserve_audio_text))

            # Сохранение конфигурации
            self.config_manager.update_channel_config(channel_name, channel_config)
            self.config_manager.update_proxy_config(proxy_config)

            QMessageBox.information(self, "Успех", "Параметры сохранены!")
            self.load_channel_config()

        except ValueError as e:
            QMessageBox.critical(self, "Ошибка валидации", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить параметры: {e}")

    def auto_save_parameters(self):
        """Автоматическое сохранение параметров без уведомлений"""
        # ИСПРАВЛЕНИЕ: Не сохраняем во время загрузки конфигурации
        if self.is_config_loading:
            return
            
        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            return

        # Защита от краша при множественном выборе каналов
        if len(checked_items) > 1:
            logger.debug(f"Автосохранение пропущено при множественном выборе каналов: {len(checked_items)}")
            return

        channel_name = checked_items[0]

        try:
            # Сбор данных из UI
            raw_config = {}
            for key, entry in self.param_entries.items():
                if isinstance(entry, QCheckBox):
                    raw_config[key] = entry.isChecked()
                elif key in self.get_combo_fields():
                    # Для выпадающих списков
                    from PySide6.QtWidgets import QComboBox
                    if isinstance(entry, QComboBox):
                        # Проверяем есть ли internal_values
                        internal_values = entry.property("internal_values")
                        if internal_values:
                            # Используем internal_values для получения внутреннего значения
                            current_index = entry.currentIndex()
                            if 0 <= current_index < len(internal_values):
                                raw_config[key] = internal_values[current_index]
                            else:
                                raw_config[key] = internal_values[0] if internal_values else ""
                        else:
                            # Преобразуем русское значение в английское для сохранения
                            russian_value = entry.currentText()
                            english_value = self.get_combo_translation(key, russian_value, to_english=True)
                            raw_config[key] = english_value
                elif key in self.get_slider_fields():
                    # Для слайдеров
                    from PySide6.QtWidgets import QSlider
                    if isinstance(entry, QSlider):
                        value = entry.value()
                        if key in ["bokeh_intensity", "vignette_strength", "video_zoom_intensity"]:
                            # Делим на 100 для получения десятичных значений
                            raw_config[key] = value / 100.0
                        elif key in ["sharpen_strength", "contrast_factor", "saturation_factor", "transition_duration", "video_rotation_angle"]:
                            # Делим на 10 для получения десятичных значений
                            raw_config[key] = value / 10.0
                        elif key == "bokeh_blur_kernel":
                            # Преобразуем одиночное значение в список [x, x] для корректной валидации
                            raw_config[key] = [value, value]
                        else:
                            # Другие сохраняются как есть
                            raw_config[key] = value
                else:
                    text_value = entry.text()
                    # Не сохраняем пустые значения для полей позиций логотипов
                    if key.endswith(('_position_x', '_position_y')) and not text_value.strip():
                        continue
                    raw_config[key] = text_value

            # Добавляем настройки из виджета ползунков (с защитой от ошибок)
            if hasattr(self, 'voice_settings_widget') and self.voice_settings_widget and VOICE_SETTINGS_AVAILABLE:
                try:
                    voice_settings = self.voice_settings_widget.get_settings_for_config()
                    raw_config.update(voice_settings)
                except Exception as e:
                    logger.warning(f"Не удалось получить настройки из VoiceSettingsWidget: {e}")

            # Валидация конфигурации (пропускаем ошибки в автосохранении)
            try:
                validated_config = self.config_manager.validate_and_convert_config(raw_config)
            except ValueError as ve:
                logger.debug(f"Ошибка валидации при автосохранении (пропущена): {ve}")
                return  # Пропускаем сохранение при ошибках валидации

            # Разделение конфигурации на канальную и прокси
            channel_config = {}
            proxy_config = {"debug_config": {}}

            for key, value in validated_config.items():
                if key in ["proxy", "proxy_login", "proxy_password", "use_proxy", 
                           "proxy_type", "rotate_endpoint", "rotate_min_interval"]:
                    proxy_config[key] = value
                elif key in ["debug_video_processing", "debug_audio_processing",
                             "debug_subtitles_processing", "debug_final_assembly"]:
                    proxy_config["debug_config"][key] = value
                else:
                    channel_config[key] = value

            # Сохранение конфигурации без уведомлений
            self.config_manager.update_channel_config(channel_name, channel_config)
            self.config_manager.update_proxy_config(proxy_config)

            # Обновляем предпросмотр субтитров если настройки касаются субтитров
            try:
                if hasattr(self, 'subtitle_preview_widget') and self.subtitle_preview_widget:
                    subtitle_keys = [k for k in validated_config.keys() if k.startswith('subtitle_')]
                    if subtitle_keys:  # Если есть настройки субтитров
                        self.subtitle_preview_widget.update_subtitle_preview(validated_config)
            except Exception as se:
                logger.debug(f"Ошибка обновления предпросмотра субтитров: {se}")

            logger.debug(f"Параметры автоматически сохранены для канала: {channel_name}")

        except Exception as e:
            logger.debug(f"Ошибка автоматического сохранения параметров (пропущена): {e}")

    def add_channel(self):
        """Добавление нового канала"""
        if self.is_config_loading and self.config_loader and self.config_loader.isRunning():
            self.config_loader.quit()
            self.config_loader.wait()

        dialog = AddChannelDialog(self)
        if dialog.exec():
            channel_data = dialog.get_channel_data()
            channel_name = channel_data["name"]
            channel_column = channel_data["channel_column"]
            paths = channel_data["paths"]

            try:
                # Создание конфигурации канала
                default_config = self.config_manager.get_default_channel_config()
                default_config.update({
                    "channel_name": channel_name,
                    "channel_column": channel_column,
                    **paths
                })

                # Добавление канала
                self.config_manager.add_channel(channel_name, default_config)
                self.channel_combo.addItem(channel_name)

                QMessageBox.information(self, "Успех", f"Канал '{channel_name}' успешно добавлен!")

            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось добавить канал: {e}")

    def delete_channel(self):
        """Удаление канала"""
        if self.is_config_loading and self.config_loader and self.config_loader.isRunning():
            self.config_loader.quit()
            self.config_loader.wait()

        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            QMessageBox.critical(self, "Ошибка", "Нет каналов для удаления!")
            return

        channel_name = checked_items[0]
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Вы уверены, что хотите удалить канал '{channel_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Удаление канала
            self.config_manager.delete_channel(channel_name)

            # Обновление списка каналов
            self.channel_combo.clear()
            channels = self.config_manager.get_all_channels()
            for channel in channels:
                self.channel_combo.addItem(channel)

            # Загрузка конфигурации если остались каналы
            if channels:
                self.load_channel_config()
            else:
                self.montage_button.setEnabled(False)
                self.voiceover_button.setEnabled(False)

            QMessageBox.information(self, "Успех", f"Канал '{channel_name}' успешно удалён!")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить канал: {e}")

    def toggle_montage(self):
        """Переключение монтажа"""
        print(f"🔄🔄🔄 TOGGLE_MONTAGE ВЫЗВАНА!!! is_montage_running = {self.is_montage_running} 🔄🔄🔄")
        logger.error(f"🔄🔄🔄 TOGGLE_MONTAGE ВЫЗВАНА!!! is_montage_running = {self.is_montage_running} 🔄🔄🔄")
        print(f"🔄🔄🔄 КНОПКА ГОВОРИТ: {self.montage_button.text()} 🔄🔄🔄")
        logger.error(f"🔄🔄🔄 КНОПКА ГОВОРИТ: {self.montage_button.text()} 🔄🔄🔄")
        
        if not self.is_montage_running:
            # Определяем тип монтажа по наличию поля video_numbers
            video_numbers_text = self.param_entries.get("video_numbers", "")
            if hasattr(video_numbers_text, 'text'):
                video_numbers_text = video_numbers_text.text().strip()
            
            # ВАЖНОЕ ПРИМЕЧАНИЕ: Параллельный монтаж может вызывать проблемы с GUI
            # Если возникают проблемы с дублированием окон, используйте обычный монтаж
            if video_numbers_text:
                # Если указаны номера видео - запускаем параллельный монтаж
                logger.info(f"🔀 Запуск параллельного монтажа для видео: {video_numbers_text}")
                
                # КРИТИЧЕСКИ ВАЖНО: СБРАСЫВАЕМ флаг остановки перед запуском!!!
                try:
                    import montage_control
                    montage_control.reset_stop_montage_flag()
                    logger.info("🔄 Флаг остановки СБРОШЕН перед запуском монтажа!")
                except Exception as e:
                    logger.error(f"Ошибка сброса флага: {e}")
                
                # ВАЖНО: Устанавливаем флаг ПЕРЕД запуском
                self.is_montage_running = True
                self.montage_button.setText("Остановить монтаж")
                
                self.start_parallel_montage()
            else:
                # Иначе обычный монтаж
                logger.info("▶️ Запуск обычного монтажа")
                
                # КРИТИЧЕСКИ ВАЖНО: СБРАСЫВАЕМ флаг остановки перед запуском!!!
                try:
                    import montage_control
                    montage_control.reset_stop_montage_flag()
                    logger.info("🔄 Флаг остановки СБРОШЕН перед обычным монтажом!")
                except Exception as e:
                    logger.error(f"Ошибка сброса флага: {e}")
                    
                self.start_montage()
        else:
            self.stop_montage()

    def start_montage(self):
        """Запуск монтажа"""
        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            QMessageBox.critical(self, "Ошибка", "Выберите канал для монтажа!")
            return

        channel_name = checked_items[0]

        try:
            # Сбор и валидация конфигурации
            raw_config = {}
            for key, entry in self.param_entries.items():
                if key in ["proxy", "proxy_login", "proxy_password", "use_proxy",
                           "debug_video_processing", "debug_audio_processing",
                           "debug_subtitles_processing", "debug_final_assembly"]:
                    continue
                if isinstance(entry, QCheckBox):
                    raw_config[key] = entry.isChecked()
                elif key in self.get_combo_fields():
                    # Для выпадающих списков
                    from PySide6.QtWidgets import QComboBox
                    if isinstance(entry, QComboBox):
                        # Проверяем есть ли internal_values
                        internal_values = entry.property("internal_values")
                        if internal_values:
                            # Используем internal_values для получения внутреннего значения
                            current_index = entry.currentIndex()
                            if 0 <= current_index < len(internal_values):
                                raw_config[key] = internal_values[current_index]
                            else:
                                raw_config[key] = internal_values[0] if internal_values else ""
                        else:
                            # Преобразуем русское значение в английское для сохранения
                            russian_value = entry.currentText()
                            english_value = self.get_combo_translation(key, russian_value, to_english=True)
                            raw_config[key] = english_value
                elif key in self.get_slider_fields():
                    # Для слайдеров
                    from PySide6.QtWidgets import QSlider
                    if isinstance(entry, QSlider):
                        value = entry.value()
                        if key in ["bokeh_intensity", "vignette_strength", "video_zoom_intensity"]:
                            # Делим на 100 для получения десятичных значений
                            raw_config[key] = value / 100.0
                        elif key in ["sharpen_strength", "contrast_factor", "saturation_factor", "transition_duration", "video_rotation_angle"]:
                            # Делим на 10 для получения десятичных значений
                            raw_config[key] = value / 10.0
                        elif key == "bokeh_blur_kernel":
                            # Преобразуем одиночное значение в список [x, x] для корректной валидации
                            raw_config[key] = [value, value]
                        else:
                            # Другие сохраняются как есть
                            raw_config[key] = value
                else:
                    raw_config[key] = entry.text()

            # Добавляем настройки из виджета ползунков (с защитой от ошибок)
            if hasattr(self, 'voice_settings_widget') and self.voice_settings_widget and VOICE_SETTINGS_AVAILABLE:
                try:
                    voice_settings = self.voice_settings_widget.get_settings_for_config()
                    raw_config.update(voice_settings)
                except Exception as e:
                    logger.warning(f"Не удалось получить настройки из VoiceSettingsWidget: {e}")

            config = self.config_manager.validate_and_convert_config(raw_config)

            # Валидация preserve_clip_audio_videos
            preserve_audio_text = self.param_entries.get("preserve_clip_audio_videos", "")
            if hasattr(preserve_audio_text, 'text'):
                preserve_audio_text = preserve_audio_text.text()

            preserve_clip_audio_videos = self.config_manager.validator.validate_preserve_audio_videos(
                str(preserve_audio_text))

            # Создание и запуск потока монтажа
            self.montage_thread = MontageThread(channel_name, config, preserve_clip_audio_videos)
            self.montage_thread.finished.connect(self.montage_finished)
            self.montage_thread.error_occurred.connect(self.show_error)
            self.montage_thread.start()

            # Обновление UI
            self.is_montage_running = True
            self.montage_button.setText("Остановить монтаж")
            self.status_label.setText("Выполняется монтаж...")
            self.channel_combo.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))


    def start_parallel_montage(self):
        """Запуск параллельного монтажа"""
        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            QMessageBox.critical(self, "Ошибка", "Выберите каналы для монтажа!")
            return

        try:
            # Получение номеров видео из поля video_numbers
            video_numbers_text = self.param_entries.get("video_numbers", "")
            if hasattr(video_numbers_text, 'text'):
                video_numbers_text = video_numbers_text.text().strip()
            
            if not video_numbers_text:
                QMessageBox.critical(self, "Ошибка", "Укажите номера видео для монтажа!")
                return

            # Получение максимального количества параллельных процессов
            max_concurrent_text = self.param_entries.get("max_concurrent_montages", "")
            if hasattr(max_concurrent_text, 'text'):
                max_concurrent_text = max_concurrent_text.text().strip()
            
            max_concurrent = 3  # значение по умолчанию
            if max_concurrent_text:
                try:
                    max_concurrent = int(max_concurrent_text)
                    if max_concurrent <= 0:
                        raise ValueError("Количество должно быть больше 0")
                except ValueError:
                    QMessageBox.critical(self, "Ошибка", "Некорректное значение максимального количества процессов!")
                    return

            # Простая валидация номеров видео (без Excel проверки)
            logger.info(f"Параллельный монтаж: каналы {checked_items}, видео {video_numbers_text}")
            
            # Проверяем, что номера видео разумные
            video_numbers = ParallelMontageManager.parse_video_numbers(video_numbers_text)
            if not video_numbers:
                QMessageBox.critical(self, "Ошибка", "Не удалось распарсить номера видео!")
                return
                
            invalid_numbers = [n for n in video_numbers if n <= 0 or n > 1000]
            if invalid_numbers:
                QMessageBox.critical(self, "Ошибка", f"Некорректные номера видео: {invalid_numbers}")
                return

            # Предупреждение о нагрузке при >5 процессах
            if max_concurrent > 5:
                reply = QMessageBox.question(
                    self, "Предупреждение",
                    f"Вы указали {max_concurrent} параллельных процессов. "
                    "Это может сильно нагрузить систему. Продолжить?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            # Сбор конфигурации из UI
            raw_config = {}
            for key, entry in self.param_entries.items():
                if key in ["proxy", "proxy_login", "proxy_password", "use_proxy",
                           "debug_video_processing", "debug_audio_processing",
                           "debug_subtitles_processing", "debug_final_assembly",
                           "video_numbers", "max_concurrent_montages"]:
                    continue
                if isinstance(entry, QCheckBox):
                    raw_config[key] = entry.isChecked()
                elif key in self.get_combo_fields():
                    # Для выпадающих списков
                    from PySide6.QtWidgets import QComboBox
                    if isinstance(entry, QComboBox):
                        # Проверяем есть ли internal_values
                        internal_values = entry.property("internal_values")
                        if internal_values:
                            # Используем internal_values для получения внутреннего значения
                            current_index = entry.currentIndex()
                            if 0 <= current_index < len(internal_values):
                                raw_config[key] = internal_values[current_index]
                            else:
                                raw_config[key] = internal_values[0] if internal_values else ""
                        else:
                            # Преобразуем русское значение в английское для сохранения
                            russian_value = entry.currentText()
                            english_value = self.get_combo_translation(key, russian_value, to_english=True)
                            raw_config[key] = english_value
                elif key in self.get_slider_fields():
                    # Для слайдеров
                    from PySide6.QtWidgets import QSlider
                    if isinstance(entry, QSlider):
                        value = entry.value()
                        if key in ["bokeh_intensity", "vignette_strength", "video_zoom_intensity"]:
                            # Делим на 100 для получения десятичных значений
                            raw_config[key] = value / 100.0
                        elif key in ["sharpen_strength", "contrast_factor", "saturation_factor", "transition_duration", "video_rotation_angle"]:
                            # Делим на 10 для получения десятичных значений
                            raw_config[key] = value / 10.0
                        elif key == "bokeh_blur_kernel":
                            # Преобразуем одиночное значение в список [x, x] для корректной валидации
                            raw_config[key] = [value, value]
                        else:
                            # Другие сохраняются как есть
                            raw_config[key] = value
                else:
                    raw_config[key] = entry.text()

            # Добавляем настройки из виджета ползунков
            if hasattr(self, 'voice_settings_widget') and self.voice_settings_widget and VOICE_SETTINGS_AVAILABLE:
                try:
                    voice_settings = self.voice_settings_widget.get_settings_for_config()
                    raw_config.update(voice_settings)
                except Exception as e:
                    logger.warning(f"Не удалось получить настройки из VoiceSettingsWidget: {e}")

            config = self.config_manager.validate_and_convert_config(raw_config)

            # Валидация preserve_clip_audio_videos
            preserve_audio_text = self.param_entries.get("preserve_clip_audio_videos", "")
            if hasattr(preserve_audio_text, 'text'):
                preserve_audio_text = preserve_audio_text.text()

            preserve_clip_audio_videos = self.config_manager.validator.validate_preserve_audio_videos(
                str(preserve_audio_text))

            # video_numbers уже парсятся выше в валидации

            # Создание и запуск менеджера параллельного монтажа через ParallelMontageThread
            from parallel_montage_manager import create_montage_tasks, ParallelMontageThread
            
            # Создаем задачи
            tasks = create_montage_tasks(checked_items, video_numbers, preserve_clip_audio_videos)
            
            # Создаем поток для выполнения
            self.parallel_montage_thread = ParallelMontageThread(tasks, max_concurrent)
            self.parallel_montage_thread.task_completed.connect(self.on_parallel_montage_task_completed) 
            self.parallel_montage_thread.all_tasks_completed.connect(self.on_parallel_montage_finished)
            self.parallel_montage_thread.error_occurred.connect(self.show_error)

            # Запуск потока
            self.parallel_montage_thread.start()

            # Обновление UI
            self.is_montage_running = True
            self.montage_button.setText("Остановить параллельный монтаж")
            self.status_label.setText(f"Выполняется параллельный монтаж для {len(checked_items)} каналов...")
            self.channel_combo.setEnabled(False)
            self.voiceover_button.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def stop_parallel_montage(self):
        """Мягкая остановка параллельного монтажа"""
        if hasattr(self, 'parallel_montage_thread') and self.parallel_montage_thread and self.parallel_montage_thread.isRunning():
            # Мягкая остановка через флаг вместо принудительного terminate()
            if hasattr(self.parallel_montage_thread, 'stop'):
                self.parallel_montage_thread.stop()
                # Даем время на завершение текущих операций
                self.parallel_montage_thread.wait(5000)  # Ждем до 5 секунд
                if self.parallel_montage_thread.isRunning():
                    logger.warning("⚠️ Параллельный монтаж не завершился за 5 секунд")
            else:
                # Fallback для старых потоков без метода stop()
                self.parallel_montage_thread.terminate()
                self.parallel_montage_thread.wait()

        self.is_montage_running = False
        self.montage_button.setText("Запустить монтаж")
        self.status_label.setText("Параллельный монтаж остановлен")
        self.channel_combo.setEnabled(True)
        self.voiceover_button.setEnabled(True)

    def on_parallel_montage_task_completed(self, task_id: str, success: bool, message: str):
        """Обработка завершения задачи параллельного монтажа"""
        if success:
            logger.info(f"[PARALLEL-{task_id}] {message}")
            self.log_text.append(f"✅ {message}")
        else:
            logger.error(f"[PARALLEL-{task_id}] {message}")
            self.log_text.append(f"❌ {message}")

    def on_parallel_montage_finished(self, total_tasks: int, successful_tasks: int):
        """Обработка завершения всех задач параллельного монтажа"""
        # ПРОВЕРЯЕМ - был ли запрос на остановку
        try:
            import montage_control
            was_stopped = montage_control.is_stop_montage_requested()
            montage_control.reset_stop_montage_flag()
        except:
            was_stopped = False
            
        self.is_montage_running = False
        self.montage_button.setText("Запустить монтаж")
        self.channel_combo.setEnabled(True)
        self.voiceover_button.setEnabled(True)
        
        # Показываем результат ТОЛЬКО если монтаж завершился естественно
        if was_stopped:
            self.status_label.setText("🛑 Параллельный монтаж остановлен")
            logger.info("🛑 Параллельный монтаж был остановлен пользователем")
        else:
            failed_tasks = total_tasks - successful_tasks
            message = f"Параллельный монтаж завершен: {successful_tasks} успешно, {failed_tasks} с ошибками из {total_tasks} всего"
            QMessageBox.information(self, "Завершено", message)
            self.status_label.setText("✅ Готово")
            logger.info("✅ Параллельный монтаж завершен успешно")

    def update_parallel_montage_progress(self, message: str):
        """Обновление прогресса параллельного монтажа"""
        self.log_text.append(message)

    def validate_video_numbers_against_excel(self, channel_names: List[str], video_numbers_text: str) -> List[str]:
        """Валидация номеров видео по Excel файлам"""
        errors = []
        
        try:
            # Парсим номера видео
            video_numbers = ParallelMontageManager.parse_video_numbers(video_numbers_text)
            
            if not video_numbers:
                return ["Не удалось распарсить номера видео"]
            
            # Проверяем каждый канал
            for channel_name in channel_names:
                try:
                    # Получаем конфигурацию канала
                    channel_config = self.config_manager.get_channel_config(channel_name)
                    if not channel_config:
                        errors.append(f"Конфигурация канала '{channel_name}' не найдена")
                        continue
                    
                    # Получаем путь к Excel файлу
                    excel_path = channel_config.get('global_xlsx_file_path', '')
                    if not excel_path:
                        errors.append(f"Канал '{channel_name}': не указан путь к Excel файлу")
                        continue
                    
                    if not Path(excel_path).exists():
                        errors.append(f"Канал '{channel_name}': Excel файл не найден: {excel_path}")
                        continue
                    
                    # Получаем столбец канала
                    channel_column = channel_config.get('channel_column', '')
                    if not channel_column:
                        errors.append(f"Канал '{channel_name}': не указан столбец канала")
                        continue
                    
                    # Читаем Excel файл
                    try:
                        df = pd.read_excel(excel_path, engine='openpyxl')
                        
                        # Отладка: выводим информацию о столбцах
                        logger.debug(f"Excel файл {excel_path} содержит столбцы: {list(df.columns)}")
                        logger.debug(f"Ищем столбец: '{channel_column}'")
                        
                        # Проверяем наличие столбца (с учетом возможного индексного обращения)
                        original_column = channel_column
                        if channel_column not in df.columns:
                            # Пытаемся найти столбец по индексу, если это буква (A, B, C, etc.)
                            if len(channel_column) == 1 and channel_column.isalpha():
                                column_index = ord(channel_column.upper()) - ord('A')
                                if 0 <= column_index < len(df.columns):
                                    # Используем реальное имя столбца из DataFrame
                                    channel_column = df.columns[column_index]
                                    logger.debug(f"Столбец '{original_column}' преобразован в '{channel_column}' (индекс {column_index})")
                                else:
                                    errors.append(f"Канал '{channel_name}': индекс столбца '{original_column}' выходит за границы. Доступно столбцов: {len(df.columns)}")
                                    continue
                            else:
                                errors.append(f"Канал '{channel_name}': столбец '{original_column}' не найден в Excel. Доступные столбцы: {list(df.columns)}")
                                continue
                        
                        # Получаем данные канала (непустые строки)
                        channel_data = df[df[channel_column].notna() & (df[channel_column] != '')]
                        available_videos = list(range(1, len(channel_data) + 1))
                        
                        # Проверяем каждый номер видео
                        invalid_numbers = []
                        for video_num in video_numbers:
                            if video_num not in available_videos:
                                invalid_numbers.append(str(video_num))
                        
                        if invalid_numbers:
                            errors.append(
                                f"Канал '{channel_name}': недоступные номера видео {', '.join(invalid_numbers)}. "
                                f"Доступно: 1-{len(available_videos)}"
                            )
                        
                    except Exception as excel_error:
                        errors.append(f"Канал '{channel_name}': ошибка чтения Excel: {excel_error}")
                        
                except Exception as channel_error:
                    errors.append(f"Канал '{channel_name}': ошибка валидации: {channel_error}")
            
        except Exception as general_error:
            errors.append(f"Общая ошибка валидации: {general_error}")
        
        return errors

    def stop_montage(self):
        """Мягкая остановка монтажа"""
        # Останавливаем обычный монтаж
        if hasattr(self, 'montage_thread') and self.montage_thread and self.montage_thread.isRunning():
            # Мягкая остановка через флаг
            if hasattr(self.montage_thread, 'stop'):
                self.montage_thread.stop()
                # Даем время на завершение текущих операций FFmpeg
                self.montage_thread.wait(10000)  # Ждем до 10 секунд для завершения FFmpeg
                if self.montage_thread.isRunning():
                    logger.warning("⚠️ Обычный монтаж не завершился за 10 секунд, принудительная остановка")
                    self.montage_thread.terminate()
                    self.montage_thread.wait()
            else:
                # Fallback для старых потоков
                self.montage_thread.terminate()
                self.montage_thread.wait()
        
        # Останавливаем параллельный монтаж
        if hasattr(self, 'parallel_montage_thread') and self.parallel_montage_thread:
            self.stop_parallel_montage()

        self.is_montage_running = False
        self.montage_button.setText("Запустить монтаж")
        self.status_label.setText("Остановлено")
        self.channel_combo.setEnabled(True)
        

    def montage_finished(self):
        """Завершение монтажа"""
        # ПРОВЕРЯЕМ - был ли запрос на остановку
        try:
            import montage_control
            was_stopped = montage_control.is_stop_montage_requested()
            montage_control.reset_stop_montage_flag()
        except:
            was_stopped = False
            
        self.is_montage_running = False
        self.montage_button.setText("Запустить монтаж")
        self.channel_combo.setEnabled(True)
        
        # Показываем окно ТОЛЬКО если монтаж завершился естественно (НЕ был остановлен)
        if was_stopped:
            self.status_label.setText("🛑 Монтаж остановлен")
            logger.info("🛑 Монтаж был остановлен пользователем")
        else:
            QMessageBox.information(self, "Успех", "Монтаж завершён!")
            self.status_label.setText("✅ Готово")
            logger.info("✅ Монтаж завершен успешно")

    def toggle_voiceover(self):
        """Переключение озвучки"""
        if not self.is_voiceover_running:
            self.start_voiceover()
        else:
            self.stop_voiceover()

    def start_voiceover(self):
        """Запуск озвучки"""
        checked_items = self.channel_combo.checkedItems()
        if not checked_items:
            QMessageBox.critical(self, "Ошибка", "Выберите хотя бы один канал для озвучки!")
            return

        # Создание и запуск менеджера массовой озвучки
        self.voiceover_manager = MassVoiceoverManager(checked_items)
        self.voiceover_manager.finished.connect(self.mass_voiceover_finished)
        self.voiceover_manager.stopped.connect(self.mass_voiceover_stopped)
        self.voiceover_manager.error_occurred.connect(self.show_mass_voiceover_error)
        self.voiceover_manager.progress.connect(self.update_mass_voiceover_progress)

        # Обновление UI
        self.is_voiceover_running = True
        self.voiceover_button.setText("Остановить озвучку")

        if len(checked_items) == 1:
            self.status_label.setText(f"Выполняется озвучка канала {checked_items[0]}...")
        else:
            self.status_label.setText("Выполняется массовая озвучка...")

        self.channel_combo.setEnabled(False)
        self.montage_button.setEnabled(False)
        self.voiceover_manager.start()

    def stop_voiceover(self):
        """Остановка озвучки"""
        if hasattr(self, 'voiceover_manager') and self.voiceover_manager.isRunning():
            self.voiceover_manager.stop()
            self.voiceover_manager.wait()

        self.is_voiceover_running = False
        self.voiceover_button.setText("Запустить озвучку")
        self.status_label.setText("Озвучка остановлена")
        self.channel_combo.setEnabled(True)
        self.montage_button.setEnabled(True)

    def mass_voiceover_finished(self):
        """Завершение массовой озвучки"""
        QMessageBox.information(self, "Успех", "Массовая озвучка завершена!")
        self.is_voiceover_running = False
        self.voiceover_button.setText("Запустить озвучку")
        self.status_label.setText("Готово")
        self.channel_combo.setEnabled(True)
        self.montage_button.setEnabled(True)

    def mass_voiceover_stopped(self):
        """Остановка массовой озвучки"""
        QMessageBox.information(self, "Остановлено", "Массовая озвучка остановлена!")
        self.is_voiceover_running = False
        self.voiceover_button.setText("Запустить озвучку")
        self.status_label.setText("Озвучка остановлена")
        self.channel_combo.setEnabled(True)
        self.montage_button.setEnabled(True)

    def show_mass_voiceover_error(self, channel_name: str, error: str):
        """Обработка ошибки массовой озвучки"""
        QMessageBox.critical(self, "Ошибка", f"Ошибка при озвучке канала {channel_name}: {error}")
        self.is_voiceover_running = False
        self.voiceover_button.setText("Запустить озвучку")
        self.status_label.setText("Ошибка")
        self.channel_combo.setEnabled(True)
        self.montage_button.setEnabled(True)

    def update_mass_voiceover_progress(self, message: str):
        """Обновление прогресса массовой озвучки"""
        self.log_text.append(message)

    def show_error(self, error_message):
        """Обработка ошибок"""
        if isinstance(error_message, tuple) and len(error_message) == 2:
            # Ошибка из озвучки (channel_name, error)
            channel_name, error = error_message
            QMessageBox.critical(self, "Ошибка", f"Ошибка при озвучке канала {channel_name}: {error}")
        else:
            # Общая ошибка
            QMessageBox.critical(self, "Ошибка", str(error_message))

        self.status_label.setText("Ошибка")

        # Сброс состояния
        if self.is_montage_running:
            self.is_montage_running = False
            self.montage_button.setText("Запустить монтаж")

        if self.is_voiceover_running:
            self.is_voiceover_running = False
            self.voiceover_button.setText("Запустить озвучку")

        self.is_config_loading = False
        self.channel_combo.setEnabled(True)
        self.montage_button.setEnabled(True)

    # Методы для работы с геометрией окна
    def save_window_geometry(self):
        """Сохранение геометрии окна"""
        self.settings.setValue("window_geometry", self.geometry())

    def restore_window_geometry(self):
        """Восстановление геометрии окна"""
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.setGeometry(geometry)
        else:
            self.setGeometry(100, 100, 1200, 800)

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        self.save_window_geometry()

        # Остановка всех потоков
        if self.is_config_loading and self.config_loader and self.config_loader.isRunning():
            self.config_loader.quit()
            self.config_loader.wait()

        if self.is_montage_running and self.montage_thread and self.montage_thread.isRunning():
            self.montage_thread.terminate()
            self.montage_thread.wait()

        if self.is_voiceover_running and self.voiceover_manager and self.voiceover_manager.isRunning():
            self.stop_voiceover()

        if self.is_montage_running and hasattr(self, 'parallel_montage_thread') and self.parallel_montage_thread:
            self.stop_parallel_montage()

        event.accept()

    # Вспомогательные методы
    def get_parameter_categories(self) -> Dict[str, Dict[str, Any]]:
        """Получение категорий параметров"""
        return {
            "Основные параметры": {
                "Общие настройки": [
                    ("channel_name", "Имя канала"),
                    ("proxy", "URL прокси-сервера"),
                    ("num_videos", "Количество видео"),
                    ("proxy_login", "Логин прокси"),
                    ("channel_column", "Столбец канала"),
                    ("proxy_password", "Пароль прокси"),
                    ("preserve_clip_audio_videos", "Сохранять аудио клипа для видео"),
                    ("video_numbers", "Номера видео для генерации"),
                    ("max_concurrent_montages", "Максимум параллельных монтажей"),
                    ("use_proxy", "Использовать прокси"),
                    ("proxy_type", "Тип прокси"),
                    ("rotate_endpoint", "URL для ротации IP"),
                    ("rotate_min_interval", "Мин. интервал ротации (сек)"),
                    ("max_concurrent_requests", "Макс. параллельных запросов"),
                    ("parallel_threads", "Количество потоков"),
                    ("debug_video_processing", "Отладка видео процессинга"),
                    ("debug_audio_processing", "Отладка аудио процессинга"),
                    ("debug_subtitles_processing", "Отладка субтитров"),
                    ("debug_final_assembly", "Отладка финальной сборки"),
                    ("debug_keep_temp_folder", "Сохранять временную папку")
                ],
                "Пути": [
                    ("global_xlsx_file_path", "Путь к Excel со сценариями"),
                    ("channel_folder", "Папка канала"),
                    ("base_path", "Корневая папка"),
                    ("csv_file_path", "Путь к файлу API ключей"),
                    ("output_directory", "Папка для аудио озвучки"),
                    ("photo_folder", "Папка с фото"),
                    ("audio_folder", "Папка с аудио"),
                    ("output_folder", "Папка для готового видео"),
                    ("background_music_path", "Путь к фоновой музыке")
                ]
            },
            "Озвучка": {
                "Настройки голоса": [
                    ("default_lang", "Язык по умолчанию"),
                    ("default_voice_style", "Стиль голоса"),
                    ("standard_voice_id", "ID стандартного голоса"),
                    ("use_library_voice", "Использовать голос из библиотеки"),
                    ("max_retries", "Максимум попыток"),
                    ("ban_retry_delay", "Задержка после бана IP (сек)")
                ],
                "Параметры диктора": "voice_settings",
                "Выбор голоса из библиотеки": "voice_selector"
            },
            "Аудио": {
                "Настройки качества аудио": [
                    ("audio_bitrate", "Битрейт аудио"),
                    ("audio_sample_rate", "Частота дискретизации"),
                    ("audio_channels", "Количество каналов"),
                    ("silence_duration", "Длительность пауз между фразами")
                ],
                "Фоновая музыка": [
                    ("background_music_volume", "Громкость фоновой музыки"),
                    ("background_music_fade_in", "Плавное появление музыки (сек)"),
                    ("background_music_fade_out", "Плавное затухание музыки (сек)")
                ],
                "Нормализация и выравнивание": [
                    ("audio_normalize", "Нормализация громкости финального аудио"),
                    ("audio_normalize_method", "Метод нормализации"),
                    ("audio_normalize_target", "Целевая громкость нормализации"),
                    ("audio_peak_limiting", "Пиковое ограничение (лимитер)"),
                    ("audio_peak_limit_db", "Порог пикового ограничения (dB)"),
                    ("audio_loudness_matching", "Выравнивание громкости по LUFS"),
                    ("audio_lufs_target", "Целевая громкость LUFS")
                ],
                "Компрессор и динамика": [
                    ("audio_compressor", "Применить компрессор звука"),
                    ("audio_compressor_type", "Тип компрессора"),
                    ("audio_compressor_ratio", "Степень сжатия компрессора"),
                    ("audio_compressor_attack", "Время атаки компрессора (мс)"),
                    ("audio_compressor_release", "Время восстановления (мс)"),
                    ("audio_gate_enabled", "Включить гейт (шумовые ворота)"),
                    ("audio_gate_threshold", "Порог срабатывания гейта (dB)")
                ],
                "Эквалайзер": [
                    ("audio_eq_enabled", "Включить эквалайзер"),
                    ("audio_eq_preset", "Предустановка эквалайзера"),
                    ("audio_eq_bass", "Усиление низких частот (dB)"),
                    ("audio_eq_mid", "Усиление средних частот (dB)"),
                    ("audio_eq_treble", "Усиление высоких частот (dB)"),
                    ("audio_eq_presence", "Усиление присутствия (dB)")
                ],
                "Обработка голоса": [
                    ("voice_noise_reduction", "Шумоподавление голоса"),
                    ("voice_denoise_strength", "Сила шумоподавления"),
                    ("voice_enhancement", "Улучшение качества голоса"),
                    ("voice_clarity_boost", "Увеличение разборчивости"),
                    ("voice_warmth", "Теплота голоса"),
                    ("voice_de_esser", "Де-эссер (убирание свистящих)"),
                    ("voice_de_esser_threshold", "Порог де-эссера (dB)")
                ]
            },
            "Видео": {
                "Настройки видео": [
                    ("video_resolution", "Разрешение видео"),
                    ("frame_rate", "Частота кадров"),
                    ("video_crf", "Качество видео (CRF)"),
                    ("video_preset", "Пресет кодирования"),
                    ("photo_order", "Порядок фото"),
                    ("preserve_video_duration", "Сохранять длительность видео"),
                    ("adjust_videos_to_audio", "Подстраивать видео под аудио")
                ],
                "Эффекты видео": [
                    ("video_effects_enabled", "Включить эффекты видео"),
                    ("video_zoom_effect", "Эффект масштабирования"),
                    ("video_zoom_intensity", "Интенсивность зума (0.8-1.2)"),
                    ("video_rotation_effect", "Эффект вращения"),
                    ("video_rotation_angle", "Угол вращения (-15.0° до +15.0°)"),
                    ("video_color_effect", "Цветовой эффект"),
                    ("video_filter_effect", "Фильтр эффект")
                ],
                "Переходы между клипами": [
                    ("video_transitions_enabled", "Включить переходы"),
                    ("transition_method", "Метод переходов"),
                    ("transition_type", "Тип перехода"),
                    ("transition_duration", "Длительность перехода (сек)"),
                ]
            },
            "Фото": {
                "Настройки эффекта боке": [
                    ("bokeh_enabled", "Включить эффект боке"),
                    ("bokeh_sides_enabled", "Боке по бокам"),
                    ("bokeh_image_size", "Размер изображения"),
                    ("bokeh_blur_kernel", "Ядро размытия"),
                    ("bokeh_blur_sigma", "Сила размытия"),
                    ("bokeh_blur_method", "Метод размытия"),
                    ("bokeh_intensity", "Интенсивность эффекта"),
                    ("bokeh_focus_area", "Область фокуса"),
                    ("bokeh_transition_smoothness", "Плавность перехода")
                ],
                "Дополнительные эффекты": [
                    ("sharpen_enabled", "Повышение резкости"),
                    ("sharpen_strength", "Сила резкости"),
                    ("contrast_enabled", "Коррекция контраста"),
                    ("contrast_factor", "Фактор контраста"),
                    ("brightness_enabled", "Коррекция яркости"),
                    ("brightness_delta", "Изменение яркости"),
                    ("saturation_enabled", "Коррекция насыщенности"),
                    ("saturation_factor", "Фактор насыщенности"),
                    ("vignette_enabled", "Виньетирование"),
                    ("vignette_strength", "Сила виньетки"),
                    ("edge_enhancement", "Улучшение краев"),
                    ("noise_reduction", "Подавление шума")
                ],
                "Цветовая коррекция": [
                    ("histogram_equalization", "Коррекция по гистограмме")
                ],
                "Фильтры стиля": [
                    ("style_filter", "Фильтр стиля")
                ]
            },
            "Логотипы": {
                "Визуальный редактор позиций": "logo_position_editor",
                "Пути к файлам логотипов": [
                    ("logo_path", "Путь к основному логотипу"),
                    ("logo2_path", "Путь к дополнительному логотипу"),
                    ("subscribe_frames_folder", "Папка с кадрами кнопки подписки")
                ],
                "Настройки длительности": [
                    ("logo_duration", "Длительность показа логотипа"),
                    ("logo2_duration", "Длительность доп. логотипа")
                ],
                "Размеры логотипов": [
                    ("logo_width", "Ширина логотипа"),
                    ("logo2_width", "Ширина доп. логотипа")
                ],
                "Настройки кнопки подписки": [
                    ("subscribe_width", "Ширина кнопки подписки"),
                    ("subscribe_display_duration", "Длительность показа кнопки"),
                    ("subscribe_interval_gap", "Интервал появления кнопки"),
                    ("subscribe_duration", "Общее время показа кнопки")
                ],
            },
            "Субтитры": {
                "Предпросмотр субтитров": "subtitle_preview",
                "Основные настройки субтитров": [
                    ("subtitles_enabled", "Включить субтитры"),
                    ("subtitle_language", "Язык субтитров"),
                    ("subtitle_model", "Модель субтитров"),
                    ("subtitle_font_family", "Семейство шрифта"),
                    ("subtitle_fontsize", "Размер шрифта"),
                    ("subtitle_font_color", "Цвет шрифта"),
                    ("subtitle_use_backdrop", "Использовать подложку"),
                    ("subtitle_back_color", "Цвет подложки")
                ],
                "Оформление субтитров": [
                    ("subtitle_outline_thickness", "Толщина обводки"),
                    ("subtitle_outline_color", "Цвет обводки"),
                    ("subtitle_shadow_thickness", "Толщина тени"),
                    ("subtitle_shadow_color", "Цвет тени"),
                    ("subtitle_shadow_alpha", "Интенсивность тени"),
                    ("subtitle_shadow_offset_x", "Смещение тени X"),
                    ("subtitle_shadow_offset_y", "Смещение тени Y"),
                    ("subtitle_margin_v", "Вертикальный отступ"),
                    ("subtitle_margin_l", "Левый отступ"),
                    ("subtitle_margin_r", "Правый отступ"),
                    ("subtitle_line_spacing", "Межстрочный интервал"),
                    ("subtitle_max_words", "Максимум слов"),
                    ("subtitle_time_offset", "Сдвиг времени")
                ]
            }
        }

    def get_path_fields(self) -> List[str]:
        """Получение списка полей с путями"""
        return [
            "global_xlsx_file_path", "channel_folder", "base_path", "csv_file_path",
            "output_directory", "photo_folder", "audio_folder", "output_folder",
            "background_music_path", "logo_path", "logo2_path", "subscribe_frames_folder"
        ]

    def get_checkbox_fields(self) -> List[str]:
        """Получение списка полей с чекбоксами"""
        return [
            "use_library_voice", "bokeh_enabled", "bokeh_sides_enabled", "subtitles_enabled",
            "subtitle_use_backdrop", "preserve_video_duration",
            "adjust_videos_to_audio", "use_proxy", "debug_video_processing",
            # Новые чекбоксы для эффектов изображений
            "sharpen_enabled", "contrast_enabled", "brightness_enabled", 
            "saturation_enabled", "vignette_enabled", "edge_enhancement", 
            "noise_reduction", "histogram_equalization",
            # Чекбоксы для эффектов видео
            "video_effects_enabled", "video_transitions_enabled",
            # Чекбоксы для аудио эффектов
            "audio_normalize", "audio_peak_limiting", "audio_loudness_matching",
            "audio_compressor", "audio_gate_enabled", "audio_eq_enabled",
            "voice_noise_reduction", "voice_enhancement", "voice_clarity_boost",
            "voice_warmth", "voice_de_esser",
            "debug_audio_processing", "debug_subtitles_processing", "debug_final_assembly",
            "debug_keep_temp_folder"
        ]
    
    def get_color_fields(self) -> List[str]:
        """Получение списка полей с цветами для субтитров"""
        return [
            "subtitle_font_color", "subtitle_back_color", 
            "subtitle_outline_color", "subtitle_shadow_color"
        ]

    def create_combo_widget(self, param_key: str, is_fixed_height: bool = False):
        """Создание выпадающего списка для параметра"""
        from PySide6.QtWidgets import QComboBox
        
        combo = QComboBox()
        combo.setMinimumWidth(200)
        if is_fixed_height:
            combo.setFixedHeight(30)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Определяем опции для каждого параметра
        if param_key == "bokeh_blur_method":
            combo.addItems(["гауссово", "движения", "радиальное"])
            # Сохраняем соответствие для внутреннего использования
            combo.setProperty("internal_values", ["gaussian", "motion", "radial"])
        elif param_key == "bokeh_focus_area":
            combo.addItems(["центр", "верх", "низ", "лево", "право"])
            combo.setProperty("internal_values", ["center", "top", "bottom", "left", "right"])
        elif param_key == "style_filter":
            combo.addItems(["нет", "сепия", "ч/б", "винтаж", "холодный", "теплый"])
            combo.setProperty("internal_values", ["none", "sepia", "grayscale", "vintage", "cool", "warm"])
        elif param_key == "video_zoom_effect":
            combo.addItems(["Нет", "Zoom In", "Zoom Out", "Автоматическое чередование"])
            combo.setProperty("internal_values", ["none", "zoom_in", "zoom_out", "auto"])
        elif param_key == "video_rotation_effect":
            combo.addItems(["Нет", "Покачивание", "Вращение влево", "Вращение вправо"])
            combo.setProperty("internal_values", ["none", "sway", "rotate_left", "rotate_right"])
        elif param_key == "video_color_effect":
            combo.addItems(["Нет", "Сепия", "Черно-белое", "Инверсия", "Винтаж"])
            combo.setProperty("internal_values", ["none", "sepia", "grayscale", "invert", "vintage"])
        elif param_key == "video_filter_effect":
            combo.addItems(["Нет", "Размытие", "Резкость", "Шум", "Виньетка"])
            combo.setProperty("internal_values", ["none", "blur", "sharpen", "noise", "vignette"])
        elif param_key == "transition_method":
            combo.addItems(["Overlay (наложение, медленнее но стабильнее)", "XFade (нативные переходы FFmpeg, быстрее)"])
            combo.setProperty("internal_values", ["overlay", "xfade"])
        elif param_key == "transition_type":
            combo.addItems(["Затухание", "Растворение", "Стирание влево", "Стирание вправо", 
                           "Стирание вверх", "Стирание вниз", "Скольжение влево", "Скольжение вправо",
                           "Скольжение вверх", "Скольжение вниз"])
            combo.setProperty("internal_values", ["fade", "dissolve", "wipeleft", "wiperight",
                                                 "wipeup", "wipedown", "slideleft", "slideright",
                                                 "slideup", "slidedown"])
        elif param_key == "subtitle_font_family":
            from PySide6.QtGui import QFontDatabase
            font_db = QFontDatabase()
            system_fonts = font_db.families()
            combo.addItems(system_fonts)
            combo.setProperty("internal_values", system_fonts)
            # Подключаем изменения к обновлению предпросмотра субтитров
            combo.currentTextChanged.connect(self.on_subtitle_font_changed)
        elif param_key == "subtitle_model":
            # Доступные модели Whisper для субтитров
            combo.addItems(["Tiny", "Base", "Small", "Medium", "Large", "Large-v2", "Large-v3"])
            combo.setProperty("internal_values", ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"])
            # Устанавливаем Medium как значение по умолчанию
            combo.setCurrentText("Medium")
        elif param_key == "audio_bitrate":
            combo.addItems(["128 kbps (низкое качество)", "192 kbps (хорошее качество)", 
                           "256 kbps (высокое качество)", "320 kbps (отличное качество)",
                           "448 kbps (профессиональное)", "640 kbps (максимальное)"])
            combo.setProperty("internal_values", ["128k", "192k", "256k", "320k", "448k", "640k"])
            # Устанавливаем 192k как значение по умолчанию
            combo.setCurrentText("192 kbps (хорошее качество)")
        elif param_key == "audio_sample_rate":
            combo.addItems(["22.05 kHz (экономия места)", "44.1 kHz (CD качество)",
                           "48 kHz (DVD/профессиональное)", "96 kHz (высококачественное)"])
            combo.setProperty("internal_values", ["22050", "44100", "48000", "96000"])
            # Устанавливаем 44.1 kHz как значение по умолчанию
            combo.setCurrentText("44.1 kHz (CD качество)")
        elif param_key == "audio_compressor_ratio":
            combo.addItems(["2:1 (мягкое сжатие)", "3:1 (умеренное сжатие)", 
                           "4:1 (стандартное сжатие)", "6:1 (сильное сжатие)",
                           "8:1 (очень сильное сжатие)", "10:1 (лимитер)"])
            combo.setProperty("internal_values", ["2:1", "3:1", "4:1", "6:1", "8:1", "10:1"])
            # Устанавливаем 4:1 как значение по умолчанию
            combo.setCurrentText("4:1 (стандартное сжатие)")
        elif param_key == "audio_normalize_method":
            combo.addItems(["Peak (по пикам)", "RMS (среднеквадратичная)", 
                           "LUFS (стандарт вещания)", "EBU R128 (европейский стандарт)"])
            combo.setProperty("internal_values", ["peak", "rms", "lufs", "ebu"])
            combo.setCurrentText("LUFS (стандарт вещания)")
        elif param_key == "audio_compressor_type":
            combo.addItems(["Soft (мягкое сжатие)", "Hard (жёсткое сжатие)", 
                           "Vintage (аналоговое звучание)", "Optical (оптический компрессор)",
                           "VCA (быстрый и точный)"])
            combo.setProperty("internal_values", ["soft", "hard", "vintage", "optical", "vca"])
            combo.setCurrentText("Soft (мягкое сжатие)")
        elif param_key == "audio_eq_preset":
            combo.addItems(["Flat (без изменений)", "Мужской голос", "Женский голос",
                           "Тёплый голос", "Яркий голос", "Радио голос", "Подкаст",
                           "Поп музыка", "Рок музыка", "Классическая музыка",
                           "Усиление басов", "Усиление высоких", "Подавление вокала", "Телефонный звонок"])
            combo.setProperty("internal_values", ["flat", "voice_male", "voice_female",
                                                "voice_warm", "voice_bright", "voice_radio", "podcast",
                                                "music_pop", "music_rock", "music_classical",
                                                "bass_boost", "treble_boost", "vocal_cut", "phone_call"])
            combo.setCurrentText("Flat (без изменений)")
        elif param_key == "photo_order":
            combo.addItems(["По порядку", "Случайно"])
            combo.setProperty("internal_values", ["order", "random"])
            combo.setCurrentText("По порядку")
        elif param_key == "video_preset":
            combo.addItems(["Ультрабыстрый", "Быстрый", "Средний", "Медленный", "Очень медленный"])
            combo.setProperty("internal_values", ["ultrafast", "fast", "medium", "slow", "veryslow"])
            combo.setCurrentText("Средний")
        elif param_key == "default_voice_style":
            combo.addItems(["Нет", "Нейтральный", "Взволнованный", "Новостной", "Дружелюбный", 
                           "Грустный", "Злой", "Испуганный", "Удивленный", "Отвращение"])
            combo.setProperty("internal_values", ["none", "neutral", "excited", "news", "friendly",
                                                "sad", "angry", "fearful", "surprised", "disgust"])
            combo.setCurrentText("Нет")
        elif param_key == "proxy_type":
            combo.addItems(["Обычные", "Резидентские"])
            combo.setProperty("internal_values", ["standard", "residential"])
            combo.setCurrentText("Обычные")
        elif param_key == "audio_channels":
            combo.addItems(["Моно (1)", "Стерео (2)"])
            combo.setProperty("internal_values", ["1", "2"])
            combo.setCurrentText("Стерео (2)")
        elif param_key == "bokeh_image_size":
            combo.addItems(["HD 1280×720", "Full HD 1920×1080", "2K 2560×1440", "4K 3840×2160",
                           "Instagram Story 1080×1920", "TikTok 1080×1920", "YouTube Shorts 1080×1920",
                           "Instagram Post 1080×1080", "Facebook Post 1200×630", "Twitter Post 1024×512"])
            combo.setProperty("internal_values", ["[1280, 720]", "[1920, 1080]", "[2560, 1440]", "[3840, 2160]",
                                                "[1080, 1920]", "[1080, 1920]", "[1080, 1920]",
                                                "[1080, 1080]", "[1200, 630]", "[1024, 512]"])
            combo.setCurrentText("Full HD 1920×1080")
        elif param_key == "video_resolution":
            combo.addItems(["HD 1280×720", "Full HD 1920×1080", "2K 2560×1440", "4K UHD 3840×2160",
                           "YouTube Shorts 1080×1920", "Instagram Story 1080×1920", "TikTok 1080×1920", 
                           "Instagram Post 1080×1080"])
            combo.setProperty("internal_values", ["1280x720", "1920x1080", "2560x1440", "3840x2160",
                                                "1080x1920", "1080x1920", "1080x1920", "1080x1080"])
            combo.setCurrentText("Full HD 1920×1080")
        
        return combo
    
    def create_slider_widget(self, param_key: str):
        """Создание слайдера для параметра"""
        from PySide6.QtWidgets import QSlider, QLabel, QHBoxLayout, QWidget
        from PySide6.QtCore import Qt
        
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        slider = QSlider(Qt.Horizontal)
        value_label = QLabel("0.0")
        value_label.setMinimumWidth(50)
        
        # Настройки для разных параметров
        if param_key == "bokeh_intensity":
            slider.setRange(0, 100)  # 0.0 - 1.0, умножаем на 100
            slider.setValue(80)  # по умолчанию 0.8
            value_label.setText("0.8")
        elif param_key == "bokeh_transition_smoothness":
            slider.setRange(0, 100)  # 0 - 100
            slider.setValue(50)  # по умолчанию 50
            value_label.setText("50")
        elif param_key == "sharpen_strength":
            slider.setRange(10, 30)  # 1.0 - 3.0, умножаем на 10
            slider.setValue(15)  # по умолчанию 1.5
            value_label.setText("1.5")
        elif param_key == "contrast_factor":
            slider.setRange(5, 20)  # 0.5 - 2.0, умножаем на 10
            slider.setValue(12)  # по умолчанию 1.2
            value_label.setText("1.2")
        elif param_key == "brightness_delta":
            slider.setRange(-50, 50)  # -50 - +50
            slider.setValue(10)  # по умолчанию +10
            value_label.setText("10")
        elif param_key == "saturation_factor":
            slider.setRange(5, 20)  # 0.5 - 2.0, умножаем на 10
            slider.setValue(11)  # по умолчанию 1.1
            value_label.setText("1.1")
        elif param_key == "vignette_strength":
            slider.setRange(0, 50)  # 0.0 - 0.5, умножаем на 100
            slider.setValue(30)  # по умолчанию 0.3
            value_label.setText("0.3")
        elif param_key == "video_zoom_intensity":
            slider.setRange(80, 120)  # 0.8 - 1.2, умножаем на 100
            slider.setValue(110)  # по умолчанию 1.1
            value_label.setText("1.1")
        elif param_key == "video_rotation_angle":
            slider.setRange(-150, 150)  # -15.0° до +15.0°, умножаем на 10 для поддержки десятых
            slider.setValue(50)  # по умолчанию 5.0°
            value_label.setText("5.0°")
        elif param_key == "transition_duration":
            slider.setRange(1, 20)  # 0.1 - 2.0 сек, умножаем на 10
            slider.setValue(5)  # по умолчанию 0.5 сек
            value_label.setText("0.5")
        elif param_key == "subtitle_fontsize":
            slider.setRange(20, 200)  # 20 - 200 пикселей
            slider.setValue(110)  # по умолчанию 110
            value_label.setText("110")
        elif param_key == "subtitle_outline_thickness":
            slider.setRange(0, 20)  # 0 - 20 пикселей
            slider.setValue(4)  # по умолчанию 4
            value_label.setText("4")
        elif param_key == "subtitle_shadow_thickness":
            slider.setRange(0, 10)  # 0 - 10 пикселей
            slider.setValue(1)  # по умолчанию 1
            value_label.setText("1")
        elif param_key == "subtitle_shadow_alpha":
            slider.setRange(0, 100)  # 0 - 100%
            slider.setValue(50)  # по умолчанию 50%
            value_label.setText("50")
        elif param_key == "subtitle_shadow_offset_x":
            slider.setRange(-20, 20)  # -20 до +20 пикселей
            slider.setValue(2)  # по умолчанию 2
            value_label.setText("2")
        elif param_key == "subtitle_shadow_offset_y":
            slider.setRange(-20, 20)  # -20 до +20 пикселей
            slider.setValue(2)  # по умолчанию 2
            value_label.setText("2")
        elif param_key == "subtitle_margin_v":
            slider.setRange(0, 100)  # 0 - 100 пикселей
            slider.setValue(20)  # по умолчанию 20
            value_label.setText("20")
        elif param_key == "subtitle_margin_l":
            slider.setRange(0, 100)  # 0 - 100 пикселей
            slider.setValue(10)  # по умолчанию 10
            value_label.setText("10")
        elif param_key == "subtitle_margin_r":
            slider.setRange(0, 100)  # 0 - 100 пикселей
            slider.setValue(10)  # по умолчанию 10
            value_label.setText("10")
        elif param_key == "subtitle_line_spacing":
            slider.setRange(5, 30)  # 0.5 - 3.0, умножаем на 10
            slider.setValue(12)  # по умолчанию 1.2
            value_label.setText("1.2")
        elif param_key == "background_music_volume":
            slider.setRange(0, 10000)  # 0.00% - 100.00%, умножаем на 100
            slider.setValue(1500)  # по умолчанию 15.00%
            value_label.setText("15.00%")
        elif param_key == "audio_normalize_target":
            slider.setRange(-40, -10)  # от -40 до -10 dB
            slider.setValue(-23)  # по умолчанию -23 dB (стандарт YouTube)
            value_label.setText("-23 dB")
        elif param_key == "audio_eq_bass":
            slider.setRange(-100, 100)  # от -10.0 до +10.0 dB, умножаем на 10
            slider.setValue(0)  # по умолчанию 0.0 dB
            value_label.setText("0.0 dB")
        elif param_key == "audio_eq_treble":
            slider.setRange(-100, 100)  # от -10.0 до +10.0 dB, умножаем на 10
            slider.setValue(0)  # по умолчанию 0.0 dB
            value_label.setText("0.0 dB")
        elif param_key == "audio_peak_limit_db":
            slider.setRange(-60, 0)  # от -6 до 0 dB
            slider.setValue(-10)  # -1.0 dB по умолчанию
            value_label.setText("-1.0 dB")
        elif param_key == "audio_lufs_target":
            slider.setRange(-30, -10)  # от -30 до -10 LUFS
            slider.setValue(-14)  # -14 LUFS по умолчанию (YouTube стандарт)
            value_label.setText("-14 LUFS")
        elif param_key == "audio_compressor_attack":
            slider.setRange(1, 100)  # 1-100 мс
            slider.setValue(10)  # 10 мс по умолчанию
            value_label.setText("10 мс")
        elif param_key == "audio_compressor_release":
            slider.setRange(10, 1000)  # 10-1000 мс
            slider.setValue(100)  # 100 мс по умолчанию
            value_label.setText("100 мс")
        elif param_key == "audio_gate_threshold":
            slider.setRange(-600, -200)  # от -60 до -20 dB (умножено на 10)
            slider.setValue(-400)  # -40 dB по умолчанию
            value_label.setText("-40.0 dB")
        elif param_key == "audio_eq_mid":
            slider.setRange(-100, 100)  # от -10 до +10 dB (умножено на 10)
            slider.setValue(0)  # 0 dB по умолчанию
            value_label.setText("0.0 dB")
        elif param_key == "audio_eq_presence":
            slider.setRange(-100, 100)  # от -10 до +10 dB (умножено на 10)
            slider.setValue(0)  # 0 dB по умолчанию
            value_label.setText("0.0 dB")
        elif param_key == "voice_denoise_strength":
            slider.setRange(0, 100)  # 0-100%
            slider.setValue(50)  # 50% по умолчанию
            value_label.setText("50%")
        elif param_key == "voice_de_esser_threshold":
            slider.setRange(-400, -100)  # от -40 до -10 dB (умножено на 10)
            slider.setValue(-250)  # -25 dB по умолчанию
            value_label.setText("-25.0 dB")
        elif param_key == "bokeh_blur_kernel":
            slider.setRange(9, 299)  # от 9 до 299 (нечетные числа для размера ядра)
            slider.setValue(99)  # 99 по умолчанию
            value_label.setText("99")
        elif param_key == "bokeh_blur_sigma":
            slider.setRange(0, 100)  # от 0 до 100
            slider.setValue(30)  # 30 по умолчанию
            value_label.setText("30")
        elif param_key == "video_crf":
            slider.setRange(0, 51)  # от 0 до 51 (качество видео)
            slider.setValue(23)  # 23 по умолчанию (хорошее качество)
            value_label.setText("23")
        elif param_key == "background_music_fade_in":
            slider.setRange(0, 300)  # от 0 до 30 секунд (умножено на 10)
            slider.setValue(20)  # 2.0 сек по умолчанию
            value_label.setText("2.0 сек")
        elif param_key == "background_music_fade_out":
            slider.setRange(0, 300)  # от 0 до 30 секунд (умножено на 10)
            slider.setValue(30)  # 3.0 сек по умолчанию
            value_label.setText("3.0 сек")
        
        # Подключаем обновление значения
        def update_value():
            value = slider.value()
            if param_key in ["bokeh_intensity", "vignette_strength", "video_zoom_intensity"]:
                display_value = value / 100.0
                value_label.setText(f"{display_value:.1f}")
            elif param_key in ["sharpen_strength", "contrast_factor", "saturation_factor", "transition_duration"]:
                display_value = value / 10.0
                value_label.setText(f"{display_value:.1f}")
            elif param_key == "video_rotation_angle":
                display_value = value / 10.0  # Преобразуем обратно в градусы с десятыми
                value_label.setText(f"{display_value:.1f}°")
            elif param_key == "subtitle_line_spacing":
                display_value = value / 10.0
                value_label.setText(f"{display_value:.1f}")
                # Используем дебаунсинг для обновления предпросмотра
                self.subtitle_update_timer.stop()
                self.subtitle_update_timer.start()
            elif param_key == "background_music_volume":
                display_value = value / 100.0  # Делим на 100 для получения процентов с сотыми
                value_label.setText(f"{display_value:.2f}%")
            elif param_key in ["audio_normalize_target", "audio_peak_limit_db", "audio_lufs_target"]:
                if param_key == "audio_lufs_target":
                    value_label.setText(f"{value} LUFS")
                else:
                    value_label.setText(f"{value} dB")
            elif param_key in ["audio_compressor_attack", "audio_compressor_release"]:
                value_label.setText(f"{value} мс")
            elif param_key == "voice_denoise_strength":
                value_label.setText(f"{value}%")
            elif param_key in ["audio_eq_bass", "audio_eq_treble", "audio_eq_mid", "audio_eq_presence", 
                              "audio_gate_threshold", "voice_de_esser_threshold"]:
                display_value = value / 10.0  # Делим на 10 для получения децибел с десятыми
                value_label.setText(f"{display_value:+.1f} dB")
            elif param_key == "bokeh_blur_kernel":
                # Убеждаемся что значение нечетное (для правильной работы фильтра)
                adjusted_value = value if value % 2 == 1 else value + 1
                if adjusted_value != value:
                    slider.setValue(adjusted_value)
                value_label.setText(str(adjusted_value))
            elif param_key in ["bokeh_blur_sigma", "video_crf"]:
                value_label.setText(str(value))
            elif param_key in ["background_music_fade_in", "background_music_fade_out"]:
                display_value = value / 10.0  # Преобразуем в секунды
                value_label.setText(f"{display_value:.1f} сек")
            elif param_key.startswith("subtitle_"):
                value_label.setText(str(value))
                # Используем дебаунсинг для обновления предпросмотра
                self.subtitle_update_timer.stop()
                self.subtitle_update_timer.start()
            else:
                value_label.setText(str(value))
        
        slider.valueChanged.connect(update_value)
        
        # Принудительно применяем зеленые стили для всех слайдеров
        slider.setStyleSheet("""
            QSlider {
                background: transparent;
                outline: none;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 1px;
                background: #353535;
                margin: 8px 0;
                border-radius: 0px;
            }
            /* QSlider::handle:horizontal {
                background: #12BAC4;
                border: 1px solid #0F9AA3;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            } */
            /* QSlider::handle:horizontal:hover {
                background: #15D4E0;
                border: 1px solid #12BAC4;
            } */
            /* QSlider::handle:horizontal:pressed {
                background: #0F9AA3;
                border: 1px solid #12BAC4;
            } */
            QSlider::sub-page:horizontal {
                background: #12BAC4;
                border: none;
                height: 1px;
                border-radius: 0px;
            }
            QSlider::add-page:horizontal {
                background: #353535;
                border: none;
                height: 1px;
                border-radius: 0px;
            }
        """)
        
        layout.addWidget(slider)
        layout.addWidget(value_label)
        
        return widget, slider
    
    def get_combo_fields(self) -> List[str]:
        """Получение списка полей с выпадающими списками"""
        return [
            "bokeh_blur_method", "bokeh_focus_area", "style_filter", "bokeh_image_size",
            "video_zoom_effect", "video_rotation_effect", "video_color_effect", 
            "video_filter_effect", "transition_method", "transition_type", "subtitle_font_family", "subtitle_model",
            "audio_bitrate", "audio_sample_rate", "audio_compressor_ratio", "audio_channels",
            "audio_normalize_method", "audio_compressor_type", "audio_eq_preset",
            "photo_order", "video_preset", "default_voice_style", "video_resolution", "proxy_type"
        ]
    
    def get_combo_translation(self, param_key: str, value: str, to_english: bool = True) -> str:
        """Преобразование между русскими и английскими значениями комбобоксов"""
        translations = {
            "bokeh_blur_method": {
                "гауссово": "gaussian", "движения": "motion", "радиальное": "radial",
                "gaussian": "гауссово", "motion": "движения", "radial": "радиальное"
            },
            "bokeh_focus_area": {
                "центр": "center", "верх": "top", "низ": "bottom", "лево": "left", "право": "right",
                "center": "центр", "top": "верх", "bottom": "низ", "left": "лево", "right": "право"
            },
            "style_filter": {
                "нет": "none", "сепия": "sepia", "ч/б": "grayscale", "винтаж": "vintage", "холодный": "cool", "теплый": "warm",
                "none": "нет", "sepia": "сепия", "grayscale": "ч/б", "vintage": "винтаж", "cool": "холодный", "warm": "теплый"
            },
            "video_zoom_effect": {
                "Нет": "none", "Zoom In": "zoom_in", "Zoom Out": "zoom_out", "Автоматическое чередование": "auto",
                "none": "Нет", "zoom_in": "Zoom In", "zoom_out": "Zoom Out", "auto": "Автоматическое чередование"
            },
            "video_rotation_effect": {
                "Нет": "none", "Покачивание": "sway", "Вращение влево": "rotate_left", "Вращение вправо": "rotate_right",
                "none": "Нет", "sway": "Покачивание", "rotate_left": "Вращение влево", "rotate_right": "Вращение вправо"
            },
            "video_color_effect": {
                "Нет": "none", "Сепия": "sepia", "Черно-белое": "grayscale", "Инверсия": "invert", "Винтаж": "vintage",
                "none": "Нет", "sepia": "Сепия", "grayscale": "Черно-белое", "invert": "Инверсия", "vintage": "Винтаж"
            },
            "video_filter_effect": {
                "Нет": "none", "Размытие": "blur", "Резкость": "sharpen", "Шум": "noise", "Виньетка": "vignette",
                "none": "Нет", "blur": "Размытие", "sharpen": "Резкость", "noise": "Шум", "vignette": "Виньетка"
            },
            "transition_type": {
                "Затухание": "fade", "Растворение": "dissolve", "Стирание влево": "wipeleft", "Стирание вправо": "wiperight",
                "Стирание вверх": "wipeup", "Стирание вниз": "wipedown", "Скольжение влево": "slideleft", "Скольжение вправо": "slideright",
                "Скольжение вверх": "slideup", "Скольжение вниз": "slidedown",
                "fade": "Затухание", "dissolve": "Растворение", "wipeleft": "Стирание влево", "wiperight": "Стирание вправо",
                "wipeup": "Стирание вверх", "wipedown": "Стирание вниз", "slideleft": "Скольжение влево", "slideright": "Скольжение вправо",
                "slideup": "Скольжение вверх", "slidedown": "Скольжение вниз"
            },
            "photo_order": {
                "По порядку": "order", "Случайно": "random",
                "order": "По порядку", "random": "Случайно"
            },
            "video_preset": {
                "Ультрабыстрый": "ultrafast", "Быстрый": "fast", "Средний": "medium", 
                "Медленный": "slow", "Очень медленный": "veryslow",
                "ultrafast": "Ультрабыстрый", "fast": "Быстрый", "medium": "Средний",
                "slow": "Медленный", "veryslow": "Очень медленный"
            },
            "default_voice_style": {
                "Нет": "none", "Нейтральный": "neutral", "Взволнованный": "excited",
                "Новостной": "news", "Дружелюбный": "friendly", "Грустный": "sad",
                "Злой": "angry", "Испуганный": "fearful", "Удивленный": "surprised", "Отвращение": "disgust",
                "none": "Нет", "neutral": "Нейтральный", "excited": "Взволнованный",
                "news": "Новостной", "friendly": "Дружелюбный", "sad": "Грустный",
                "angry": "Злой", "fearful": "Испуганный", "surprised": "Удивленный", "disgust": "Отвращение"
            },
            "audio_channels": {
                "Моно (1)": "1", "Стерео (2)": "2",
                "1": "Моно (1)", "2": "Стерео (2)"
            },
            "bokeh_image_size": {
                "HD 1280×720": "[1280, 720]", "Full HD 1920×1080": "[1920, 1080]",
                "2K 2560×1440": "[2560, 1440]", "4K 3840×2160": "[3840, 2160]",
                "Instagram Story 1080×1920": "[1080, 1920]", "TikTok 1080×1920": "[1080, 1920]",
                "YouTube Shorts 1080×1920": "[1080, 1920]", "Instagram Post 1080×1080": "[1080, 1080]",
                "Facebook Post 1200×630": "[1200, 630]", "Twitter Post 1024×512": "[1024, 512]",
                "[1280, 720]": "HD 1280×720", "[1920, 1080]": "Full HD 1920×1080",
                "[2560, 1440]": "2K 2560×1440", "[3840, 2160]": "4K 3840×2160",
                "[1080, 1920]": "Instagram Story 1080×1920", "[1080, 1080]": "Instagram Post 1080×1080",
                "[1200, 630]": "Facebook Post 1200×630", "[1024, 512]": "Twitter Post 1024×512"
            },
            "video_resolution": {
                "HD 1280×720": "1280x720", "Full HD 1920×1080": "1920x1080",
                "2K 2560×1440": "2560x1440", "4K UHD 3840×2160": "3840x2160",
                "YouTube Shorts 1080×1920": "1080x1920", "Instagram Story 1080×1920": "1080x1920",
                "TikTok 1080×1920": "1080x1920", "Instagram Post 1080×1080": "1080x1080",
                "1280x720": "HD 1280×720", "1920x1080": "Full HD 1920×1080",
                "2560x1440": "2K 2560×1440", "3840x2160": "4K UHD 3840×2160",
                "1080x1920": "YouTube Shorts 1080×1920", "1080x1080": "Instagram Post 1080×1080"
            }
        }
        
        if param_key in translations and value in translations[param_key]:
            return translations[param_key][value]
        return value
    
    def get_slider_fields(self) -> List[str]:
        """Получение списка полей со слайдерами"""
        return [
            "bokeh_intensity", "bokeh_transition_smoothness", "sharpen_strength", "bokeh_blur_kernel", "bokeh_blur_sigma",
            "contrast_factor", "brightness_delta", "saturation_factor", "vignette_strength",
            "video_zoom_intensity", "video_rotation_angle", "transition_duration", "video_crf",
            "subtitle_fontsize", "subtitle_outline_thickness", "subtitle_shadow_thickness",
            "subtitle_shadow_alpha", "subtitle_shadow_offset_x", "subtitle_shadow_offset_y",
            "subtitle_margin_v", "subtitle_margin_l", "subtitle_margin_r", "subtitle_line_spacing",
            "background_music_volume", "audio_normalize_target", "audio_peak_limit_db",
            "audio_lufs_target", "audio_compressor_attack", "audio_compressor_release",
            "audio_gate_threshold", "audio_eq_bass", "audio_eq_mid", "audio_eq_treble",
            "audio_eq_presence", "voice_denoise_strength", "voice_de_esser_threshold",
            "background_music_fade_in", "background_music_fade_out"
        ]
    
    def get_tooltip_for_parameter(self, param_key: str) -> str:
        """Получение подробной подсказки для параметра с примерами"""
        tooltips = {
            # === ГРУППА: ОБЩИЕ НАСТРОЙКИ ===
            "num_videos": "Количество видео для обработки за один запуск.\n\nОпределяет сколько видеороликов будет создано в процессе монтажа. Например, если установить 5, то система создаст 5 готовых видео.\n\nПример: 3 (создаст 3 видеоролика)",
            
            "channel_name": "Уникальное имя канала для идентификации.\n\nИспользуется для различения каналов в системе и именования выходных файлов. Должно быть коротким и понятным.\n\nПример: 'ЗВЁЗДНЫЕ ТАЙНЫ TV'",
            
            "channel_column": "Столбец в Excel-файле с данными канала.\n\nУказывает на конкретный столбец в Excel таблице, где находятся данные для этого канала. Используется буквенное обозначение столбца.\n\nПример: 'B' (второй столбец), 'C' (третий столбец)",
            
            "preserve_clip_audio_videos": "Номера видео с сохранением оригинального аудио.\n\nДля указанных номеров видео будет сохранено оригинальное аудио без замены на сгенерированную озвучку. Полезно для сохранения музыки или важных звуков.\n\nПример: '1,3,5' (сохранит аудио в 1-м, 3-м и 5-м видео)",
            
            # === ГРУППА: ПУТИ К ФАЙЛАМ ===
            "global_xlsx_file_path": "Путь к основному Excel-файлу с данными.\n\nЭто главная таблица, содержащая информацию для всех каналов: тексты, заголовки, описания и другие данные для создания видео.\n\nПример: '/Users/user/Documents/channels_data.xlsx'",
            
            "channel_folder": "Папка с файлами конкретного канала.\n\nСодержит все ресурсы для данного канала: логотипы, фото, аудио, настройки. Обычно названа по имени канала.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/'",
            
            "base_path": "Корневая папка проекта.\n\nБазовый путь, от которого строятся относительные пути к другим папкам. Обычно это папка с названием канала.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV'",
            
            "csv_file_path": "Путь к файлу с API ключами ElevenLabs (CSV или TXT).\n\nПоддерживаются два формата:\n\n• CSV: столбцы API, Date, Email, Password\n• TXT: один API ключ на строку\n\nСистема автоматически выбирает доступные ключи.\n\nПримеры:\n'/Users/user/Youtube/api_keys.csv'\n'/Users/user/Youtube/500.txt'",
            
            "output_directory": "Папка для сохранения аудиофайлов.\n\nСюда сохраняются сгенерированные аудиофайлы озвучки перед их использованием в видеомонтаже.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/Audio'",
            
            "photo_folder": "Папка с изображениями для видео.\n\nСодержит фотографии, которые будут использоваться в качестве визуального контента в видеороликах. Поддерживает JPG, PNG, WEBP форматы.\n\nПример: '/Users/user/Youtube/Фото/Тайны'",
            
            "audio_folder": "Папка с готовыми аудиофайлами.\n\nМесто хранения озвученных текстов, готовых для использования в видеомонтаже. Обычно создается автоматически.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/Audio'",
            
            "output_folder": "Папка для готовых видеофайлов.\n\nСюда сохраняются финальные смонтированные видеоролики. Здесь будут файлы .mp4 готовые для загрузки.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/Output'",
            
            "background_music_path": "Путь к фоновой музыке.\n\nМузыкальный файл, который будет воспроизводиться на фоне озвучки. Поддерживает MP3, WAV, M4A форматы.\n\nПример: '/Users/user/Music/background_calm.mp3'",
            
            # === ГРУППА: ПРОКСИ ===
            "proxy": "URL прокси-сервера для обхода блокировок.\n\nИспользуется для доступа к ElevenLabs через прокси. Формат: протокол://адрес:порт\n\nПример: 'http://123.45.67.89:8080' или 'socks5://proxy.example.com:1080'",
            
            "proxy_login": "Логин для авторизации на прокси-сервере.\n\nИмя пользователя для доступа к прокси, если требуется аутентификация.\n\nПример: 'user123' или 'proxy_user'",
            
            "proxy_password": "Пароль для авторизации на прокси-сервере.\n\nПароль пользователя для доступа к прокси-серверу.\n\nПример: 'mySecretPassword123'",
            
            "use_proxy": "Включить использование прокси-сервера.\n\nЕсли включено, все запросы к ElevenLabs будут отправляться через указанный прокси-сервер.\n\nИспользуйте при блокировке ElevenLabs в вашем регионе.",
            
            "proxy_type": "Тип прокси-сервера.\n\n• standard - обычные прокси (по умолчанию)\n• residential - резидентские прокси с ротацией IP\n\nРезидентские прокси рекомендуются для обхода блокировок.",
            
            "rotate_endpoint": "URL для ротации IP адреса.\n\nАдрес API для смены IP резидентского прокси.\n\nПример для DataImpulse: 'https://gw.dataimpulse.com:777/api/rotate_ip'\n\nДля авторизации используются основные proxy_login и proxy_password.",
            
            "rotate_min_interval": "Минимальный интервал между ротациями IP.\n\nВремя в секундах, которое должно пройти между ротациями.\n\nМинимум: 30 секунд. Рекомендуется: 30-60",
            
            "max_concurrent_requests": "Максимум параллельных запросов к API.\n\nКоличество одновременных запросов к ElevenLabs API.\n\nРекомендуется: 1-2. Большие значения могут вызвать блокировку.",
            
            "parallel_threads": "Количество потоков обработки.\n\nКоличество параллельных потоков для обработки текста.\n\nРекомендуется: 2-4. Увеличивает скорость, но может вызвать блокировку.",
            
            # === ГРУППА: ОЗВУЧКА - НАСТРОЙКИ ГОЛОСА ===
            "default_lang": "Язык озвучки по умолчанию.\n\nОсновной язык для генерации речи. Влияет на произношение и интонации голоса.\n\nПример: 'ru' (русский), 'en' (английский), 'de' (немецкий)",
            
            "default_voice_style": "Стиль голоса для озвучки.\n\nОпределяет эмоциональную окраску и манеру речи. Влияет на интонацию и подачу текста.\n\n• Нет: Без специального стиля (по умолчанию)\n• Нейтральный: Спокойная, объективная речь\n• Взволнованный: Энергичная, эмоциональная подача\n• Новостной: Профессиональный, информационный стиль\n• Дружелюбный: Теплая, приветливая манера\n• Грустный/Злой/Испуганный: Соответствующие эмоции",
            
            "standard_voice_id": "ID стандартного голоса ElevenLabs.\n\nУникальный идентификатор голоса в системе ElevenLabs. Можно найти в личном кабинете ElevenLabs.\n\nПример: 'pNInz6obpgDQGcFmaJgB' (голос Adam)",
            
            "use_library_voice": "Использовать голос из встроенной библиотеки.\n\nЕсли включено, будет использоваться голос, выбранный в библиотеке голосов, вместо стандартного.\n\nРекомендуется для лучшего качества озвучки.",
            
            "max_retries": "Максимальное количество попыток при ошибках.\n\nСколько раз система попытается повторить запрос при сбоях сети или временных ошибках API.\n\nПример: 3 (три попытки), 5 (пять попыток)",
            
            "ban_retry_delay": "Задержка при блокировке IP (секунды).\n\nВремя ожидания после получения ошибки блокировки IP перед следующей попыткой.\n\nПример: 300 (5 минут), 600 (10 минут)",
            
            # === ГРУППА: АУДИО ===
            "audio_bitrate": "Битрейт аудио - качество сжатия звука.\n\n• 128k: Базовое качество, минимальный размер файла\n• 192k: Хорошее качество для речи (рекомендуется)\n• 256k: Высокое качество\n• 320k: Отличное качество для музыки\n• 448k: Профессиональное качество\n• 640k: Максимальное качество\n\nВыше битрейт = лучше качество = больше размер файла",
            
            "audio_sample_rate": "Частота дискретизации аудио.\n\n• 22.05 kHz: Экономия места, достаточно для речи\n• 44.1 kHz: CD качество, стандарт для большинства медиа\n• 48 kHz: DVD/профессиональное качество\n• 96 kHz: Высококачественная запись\n\nДля YouTube рекомендуется 44.1 или 48 kHz",
            
            "audio_channels": "Количество аудиоканалов.\n\n• 1: Моно - экономия места, подходит для речи\n• 2: Стерео - стандарт для видео и музыки\n\nДля большинства случаев используйте стерео (2)",
            
            "silence_duration": "Длительность пауз между фразами (секунды).\n\nВремя тишины, добавляемое между отдельными предложениями в озвучке для естественности речи.\n\nПример: 0.5 (полсекунды), 1.0 (секунда), 1.5 (полторы секунды)",
            
            "background_music_volume": "Громкость фоновой музыки (0.00% - 100.00%).\n\nОтносительная громкость фоновой музыки по отношению к основной озвучке.\n\n• 10-20%: Едва слышимый фон\n• 25-35%: Мягкий музыкальный фон (рекомендуется)\n• 40-60%: Заметная музыка\n• 70%+: Громкая музыка (может мешать речи)",
            
            "background_music_fade_in": "Плавное появление музыки (секунды).\n\nВремя, за которое фоновая музыка плавно нарастает от тишины до установленной громкости в начале видео.\n\nПример: 2.0 (2 секунды), 5.0 (5 секунд)",
            
            "background_music_fade_out": "Плавное затухание музыки (секунды).\n\nВремя плавного снижения громкости музыки до тишины в конце видео.\n\nПример: 3.0 (3 секунды), 5.0 (5 секунд)",
            
            # === НОРМАЛИЗАЦИЯ И ВЫРАВНИВАНИЕ ===
            "audio_normalize": "Нормализация громкости финального аудио.\n\nВыравнивает общую громкость аудиодорожки для получения консистентного уровня звука во всех видео.\n\nРекомендуется включать для профессионального звучания.",
            
            "audio_normalize_method": "Метод нормализации громкости.\n\n• Peak: По пиковым значениям - простой, быстрый\n• RMS: По среднеквадратичной мощности - более естественный\n• LUFS: Стандарт телевещания - профессиональный\n• EBU R128: Европейский стандарт - для ТВ и стриминга",
            
            "audio_normalize_target": "Целевая громкость нормализации (dB).\n\nЦелевой уровень громкости после нормализации.\n\n• -16 dB: YouTube/стриминг\n• -14 dB: Подкасты\n• -12 dB: Музыка\n• -23 dB: ТВ стандарт",
            
            "audio_peak_limiting": "Пиковое ограничение (лимитер).\n\nПредотвращает превышение максимального уровня громкости, защищая от искажений и клиппинга.\n\nРекомендуется включать для предотвращения искажений.",
            
            "audio_peak_limit_db": "Порог пикового ограничения (dB).\n\nМаксимальный уровень громкости, выше которого звук будет ограничен.\n\nПример: -1 dB (стандарт), -3 dB (более мягко), -0.1 dB (максимум)",
            
            "audio_loudness_matching": "Выравнивание громкости по LUFS.\n\nСовременный стандарт выравнивания громкости, используемый на YouTube, Spotify и других платформах.\n\nОбеспечивает одинаковую воспринимаемую громкость всех видео.",
            
            "audio_lufs_target": "Целевая громкость LUFS.\n\nЦелевой уровень громкости в стандарте LUFS.\n\n• -16 LUFS: YouTube, Spotify\n• -14 LUFS: Apple Music\n• -18 LUFS: Подкасты\n• -23 LUFS: ТВ стандарт",
            
            # === КОМПРЕССОР И ДИНАМИКА ===
            "audio_compressor": "Применить компрессор звука.\n\nСглаживает разницу между тихими и громкими частями аудио, делая звук более ровным и профессиональным.\n\nОсобенно полезно для речи и вокала.",
            
            "audio_compressor_type": "Тип компрессора.\n\n• Soft: Мягкое сжатие, естественный звук\n• Hard: Жёсткое сжатие, сильный эффект\n• Vintage: Аналоговое звучание, теплый тон\n• Optical: Плавное сжатие, для вокала\n• VCA: Быстрый и точный, универсальный",
            
            "audio_compressor_ratio": "Степень сжатия компрессора.\n\n• 2:1: Мягкое сжатие для естественного звука\n• 3:1: Умеренное сжатие для речи\n• 4:1: Стандартное сжатие (рекомендуется)\n• 6:1: Сильное сжатие\n• 8:1: Очень сильное сжатие\n• 10:1: Лимитер-режим",
            
            "audio_compressor_attack": "Время атаки компрессора (мс).\n\nВремя реакции компрессора на превышение порога.\n\n• 1-5 мс: Быстрая атака, контроль пиков\n• 10-30 мс: Средняя атака, для речи\n• 50-100 мс: Медленная атака, сохраняет естественность",
            
            "audio_compressor_release": "Время восстановления компрессора (мс).\n\nВремя возврата компрессора в исходное состояние.\n\n• 50-100 мс: Быстрое восстановление\n• 200-500 мс: Среднее восстановление (рекомендуется)\n• 1000+ мс: Медленное восстановление, плавный эффект",
            
            "audio_gate_enabled": "Включить гейт (шумовые ворота).\n\nУдаляет фоновый шум в паузах речи, пропуская только звук выше определенного уровня громкости.\n\nПолезно для улучшения качества записи в шумной обстановке.",
            
            "audio_gate_threshold": "Порог срабатывания гейта (dB).\n\nУровень громкости, ниже которого звук будет заглушен.\n\n• -60 dB: Мягкий гейт, убирает только тихий шум\n• -40 dB: Средний гейт (рекомендуется)\n• -30 dB: Сильный гейт, может обрезать тихую речь",
            
            # === ЭКВАЛАЙЗЕР ===
            "audio_eq_enabled": "Включить эквалайзер.\n\nПозволяет корректировать частотную характеристику звука: усиливать или ослаблять определенные частоты.\n\nПолезно для улучшения качества голоса и музыки.",
            
            "audio_eq_preset": "Предустановка эквалайзера.\n\n• Flat: Без изменений\n• Мужской/Женский голос: Оптимизация для типа голоса\n• Тёплый/Яркий голос: Характер звучания\n• Радио/Подкаст: Для речевого контента\n• Музыкальные пресеты: Для разных жанров\n• Усиление басов/высоких: Коррекция частот",
            
            "audio_eq_bass": "Усиление низких частот (dB).\n\nКоррекция басов (20-250 Гц).\n\n• +3 dB: Лёгкое усиление, теплота\n• +6 dB: Заметное усиление\n• -3 dB: Ослабление, убирает гул\n• -6 dB: Сильное ослабление",
            
            "audio_eq_mid": "Усиление средних частот (dB).\n\nКоррекция средних частот (250-4000 Гц) - основная область речи.\n\n• +2 dB: Улучшает разборчивость речи\n• +4 dB: Делает голос более присутствующим\n• -2 dB: Убирает резкость\n• -4 dB: Смягчает звучание",
            
            "audio_eq_treble": "Усиление высоких частот (dB).\n\nКоррекция высоких частот (4000-20000 Гц).\n\n• +3 dB: Добавляет ясности и воздуха\n• +6 dB: Яркое, детальное звучание\n• -3 dB: Убирает резкость и шипение\n• -6 dB: Мягкое, тёплое звучание",
            
            "audio_eq_presence": "Усиление присутствия (dB).\n\nКоррекция частот присутствия (1000-8000 Гц) - влияет на четкость и близость звука.\n\n• +2 dB: Голос звучит ближе\n• +4 dB: Очень четкий голос\n• -2 dB: Отодвигает голос назад\n• -4 dB: Мягкое, далекое звучание",
            
            # === ОБРАБОТКА ГОЛОСА ===
            "voice_noise_reduction": "Шумоподавление голоса.\n\nУдаляет фоновый шум из записи голоса: шипение, гул, шум вентилятора и другие нежелательные звуки.\n\nОсобенно эффективно для улучшения качества AI-генерированного голоса.",
            
            "voice_denoise_strength": "Сила шумоподавления (%).\n\nИнтенсивность применения шумоподавления.\n\n• 20-30%: Мягкое шумоподавление, сохраняет естественность\n• 40-60%: Стандартное шумоподавление (рекомендуется)\n• 70-80%: Сильное шумоподавление\n• 90%+: Максимальное шумоподавление (может исказить голос)",
            
            "voice_enhancement": "Улучшение качества голоса.\n\nОбщее улучшение звучания голоса: повышает четкость, убирает артефакты, делает звук более профессиональным.\n\nРекомендуется для AI-генерированных голосов.",
            
            "voice_clarity_boost": "Увеличение разборчивости.\n\nУлучшает понимание речи: подчеркивает согласные, делает произношение более четким.\n\nОсобенно полезно для быстрой речи или сложных текстов.",
            
            "voice_warmth": "Теплота голоса.\n\nДобавляет теплоты и объемности звучанию голоса, делает его более приятным и естественным.\n\nПолезно для создания доверительной атмосферы.",
            
            "voice_de_esser": "Де-эссер (убирание свистящих).\n\nУменьшает резкие свистящие звуки (с, ш, щ, ц), делая речь более комфортной для прослушивания.\n\nОсобенно важно для женских голосов и некоторых AI-голосов.",
            
            "voice_de_esser_threshold": "Порог де-эссера (dB).\n\nУровень, выше которого свистящие звуки будут подавляться.\n\n• -30 dB: Мягкое подавление\n• -25 dB: Стандартное подавление (рекомендуется)\n• -20 dB: Сильное подавление\n• -15 dB: Очень сильное подавление",
            
            # === ГРУППА: ВИДЕО ===
            "video_resolution": "Разрешение выходного видео.\n\nРазмер кадра в пикселях (ширина:высота).\n\n• 1280:720 (HD): Базовое качество, быстрый рендер\n• 1920:1080 (Full HD): Стандарт для YouTube (рекомендуется)\n• 2560:1440 (2K): Высокое качество\n• 3840:2160 (4K): Максимальное качество, медленный рендер",
            
            "frame_rate": "Частота кадров видео (FPS).\n\nКоличество кадров в секунду.\n\n• 24 fps: Кинематографический стандарт\n• 25 fps: Европейский ТВ стандарт\n• 30 fps: Стандарт для YouTube (рекомендуется)\n• 60 fps: Плавное видео, больше размер файла",
            
            "video_crf": "Качество видео CRF (0-51).\n\nКонстантный фактор качества. Меньше значение = лучше качество = больше размер файла.\n\n• 0-17: Визуально без потерь (огромные файлы)\n• 18-20: Высочайшее качество\n• 21-23: Отличное качество (рекомендуется для YouTube)\n• 24-26: Хорошее качество\n• 27-30: Среднее качество\n• 31-40: Низкое качество\n• 41-51: Очень низкое качество",
            
            "video_preset": "Пресет кодирования видео.\n\nБаланс между скоростью кодирования и качеством сжатия.\n\n• Ультрабыстрый: Очень быстро, большой размер файла\n• Быстрый: Быстро, хорошее сжатие\n• Средний: Баланс скорости и качества (рекомендуется)\n• Медленный: Медленно, отличное сжатие\n• Очень медленный: Максимальное качество, долго",
            
            "photo_order": "Порядок использования фотографий.\n\n• По порядку: Фото используются в алфавитном порядке имен файлов\n• Случайно: Фото выбираются в случайном порядке для каждого видео\n\nСлучайный порядок добавляет разнообразия в серию видео.",
            
            "preserve_video_duration": "Сохранять длительность видео.\n\nЕсли включено, все видео будут иметь одинаковую длительность, подгоняясь под самое длинное аудио.\n\nВыключите для автоматической длительности по аудио.",
            
            "adjust_videos_to_audio": "Подстраивать видео под длительность аудио.\n\nЕсли включено, видеоклипы будут растянуты или сжаты по времени для соответствия длительности аудиодорожки.\n\nРекомендуется для синхронизации контента.",
            
            # === ЭФФЕКТЫ ВИДЕО ===
            "video_effects_enabled": "Включить эффекты видео.\n\nПозволяет применять различные визуальные эффекты к видеоклипам для создания более динамичного контента.\n\nВключите для добавления профессиональных эффектов.",
            
            "video_zoom_effect": "Эффект масштабирования.\n\n• Нет: Без изменения масштаба\n• Zoom In: Медленное приближение (эффект Кена Бернса)\n• Zoom Out: Медленное отдаление\n• Автоматическое чередование: Случайное чередование эффектов",
            
            "video_zoom_intensity": "Интенсивность эффекта зума (0.8-1.2).\n\nСила эффекта масштабирования.\n\n• 0.8-0.9: Легкий зум\n• 0.9-1.1: Умеренный зум (рекомендуется)\n• 1.1-1.2: Сильный зум\n\n1.0 = исходный размер, <1.0 = уменьшение, >1.0 = увеличение",
            
            "video_rotation_effect": "Эффект вращения.\n\n• Нет: Без вращения\n• Покачивание: Легкое покачивание влево-вправо\n• Вращение влево: Постоянное вращение против часовой стрелки\n• Вращение вправо: Постоянное вращение по часовой стрелке",
            
            "video_rotation_angle": "Угол вращения (-15.0° до +15.0°).\n\nМаксимальный угол поворота для эффектов вращения.\n\n• ±2-5°: Легкое покачивание\n• ±5-10°: Заметное движение (рекомендуется)\n• ±10-15°: Сильное вращение\n\nОтрицательные значения = против часовой, положительные = по часовой",
            
            "video_color_effect": "Цветовой эффект.\n\n• Нет: Оригинальные цвета\n• Сепия: Тёплый коричневый тон (винтаж)\n• Черно-белое: Монохромное изображение\n• Инверсия: Обращение цветов\n• Винтаж: Состаренный вид с мягкими цветами",
            
            "video_filter_effect": "Фильтр эффект.\n\n• Нет: Без фильтров\n• Размытие: Легкое размытие для мягкости\n• Резкость: Повышение четкости деталей\n• Шум: Добавление пленочного зерна\n• Виньетка: Затемнение краев кадра",
            
            # === ПЕРЕХОДЫ ===
            "video_transitions_enabled": "Включить переходы между клипами.\n\nДобавляет плавные переходы между видеоклипами вместо резких смен кадра.\n\nДелает видео более профессиональным и приятным для просмотра.",
            
            "transition_method": "Метод создания переходов.\n\n• Overlay: Создаёт отдельные файлы переходов с наложением. Более стабильно, но медленнее и может вызывать небольшие лаги.\n• XFade: Использует встроенные переходы FFmpeg. Быстрее и плавнее, но менее предсказуемо с некоторыми форматами.",
            
            "transition_type": "Тип перехода.\n\n• Затухание: Плавное исчезновение и появление\n• Растворение: Наложение клипов друг на друга\n• Стирание: Один клип стирает другой в заданном направлении\n• Скольжение: Один клип сдвигает другой",
            
            "transition_duration": "Длительность перехода (секунды).\n\nВремя, за которое происходит переход между клипами.\n\n• 0.3-0.5 сек: Быстрый переход\n• 0.5-1.0 сек: Стандартный переход (рекомендуется)\n• 1.0-2.0 сек: Медленный переход",
            
            # === ГРУППА: ФОТО ===
            "bokeh_enabled": "Включить эффект боке.\n\nСоздает эффект размытого фона с фокусом на центральной части изображения, имитируя съемку с малой глубиной резкости.\n\nДелает фотографии более кинематографичными и профессиональными.",
            
            "bokeh_sides_enabled": "Боке по бокам изображения.\n\nПрименяет эффект боке только к боковым частям изображения, оставляя центр в фокусе.\n\nПолезно для портретных фото и крупных планов.",
            
            "bokeh_image_size": "Размер изображения для обработки.\n\nРазрешение, используемое при применении эффекта боке. Больше размер = лучше качество = медленнее обработка.\n\n• HD 1280×720: Быстрая обработка, базовое качество\n• Full HD 1920×1080: Стандарт (рекомендуется)\n• 2K/4K: Высокое качество, медленная обработка\n• Вертикальные форматы: Для Instagram, TikTok, YouTube Shorts\n• Квадратные: Для Instagram постов",
            
            "bokeh_blur_kernel": "Размер ядра размытия (9-299).\n\nОпределяет размер области размытия. Больше значение = сильнее размытие. Значение автоматически округляется до нечетного числа.\n\n• 9-49: Легкое размытие\n• 50-99: Среднее размытие (рекомендуется)\n• 100-199: Сильное размытие\n• 200-299: Очень сильное размытие",
            
            "bokeh_blur_sigma": "Сила размытия боке (0-100).\n\nИнтенсивность эффекта размытия. Больше значение = более размытый фон.\n\n• 0-20: Легкое размытие\n• 20-40: Среднее размытие (рекомендуется)\n• 40-70: Сильное размытие\n• 70-100: Максимальное размытие",
            
            "bokeh_blur_method": "Метод размытия.\n\n• Гауссово: Классическое равномерное размытие\n• Движения: Эффект размытия в движении\n• Радиальное: Размытие от центра к краям",
            
            "bokeh_intensity": "Интенсивность эффекта боке (0.0-1.0).\n\nОбщая сила применения эффекта.\n\n• 0.3-0.5: Легкий эффект\n• 0.6-0.8: Средний эффект (рекомендуется)\n• 0.8-1.0: Сильный эффект",
            
            "bokeh_focus_area": "Область фокуса.\n\n• Центр: Фокус в центре изображения\n• Верх/Низ: Фокус в верхней/нижней части\n• Лево/Право: Фокус в левой/правой части\n\nВыберите в зависимости от композиции ваших фото.",
            
            "bokeh_transition_smoothness": "Плавность перехода (0-100).\n\nНасколько плавно переходит резкость от фокусной области к размытой.\n\n• 20-40: Резкий переход\n• 50-70: Средняя плавность (рекомендуется)\n• 80-100: Очень плавный переход",
            
            # === ДОПОЛНИТЕЛЬНЫЕ ЭФФЕКТЫ ===
            "sharpen_enabled": "Повышение резкости изображения.\n\nУлучшает четкость деталей и контуров на фотографиях.\n\nПолезно для размытых или мягких изображений.",
            
            "sharpen_strength": "Сила повышения резкости (1.0-3.0).\n\n• 1.0-1.5: Легкое повышение резкости\n• 1.5-2.0: Среднее повышение (рекомендуется)\n• 2.0-3.0: Сильное повышение (может создать артефакты)",
            
            "contrast_enabled": "Коррекция контраста.\n\nИзменяет разность между светлыми и темными областями изображения.\n\nПовышает выразительность и глубину фотографий.",
            
            "contrast_factor": "Фактор контраста (0.5-2.0).\n\n• 0.5-0.8: Снижение контраста (мягкое изображение)\n• 0.9-1.1: Легкая коррекция\n• 1.2-1.5: Повышение контраста (рекомендуется)\n• 1.6-2.0: Сильное повышение контраста",
            
            "brightness_enabled": "Коррекция яркости.\n\nИзменяет общую яркость изображения.\n\nПолезно для коррекции недоэкспонированных или переэкспонированных фото.",
            
            "brightness_delta": "Изменение яркости (-50 до +50).\n\n• -20 до -10: Затемнение\n• -5 до +5: Легкая коррекция\n• +10 до +20: Осветление (рекомендуется для темных фото)\n• +25 до +50: Сильное осветление",
            
            "saturation_enabled": "Коррекция насыщенности цветов.\n\nИзменяет интенсивность цветов на изображении.\n\nПовышает выразительность цветных фотографий.",
            
            "saturation_factor": "Фактор насыщенности (0.5-2.0).\n\n• 0.5-0.8: Снижение насыщенности (приглушенные цвета)\n• 0.9-1.1: Легкая коррекция\n• 1.1-1.3: Повышение насыщенности (рекомендуется)\n• 1.4-2.0: Очень яркие цвета",
            
            "vignette_enabled": "Эффект виньетирования.\n\nЗатемняет края изображения, привлекая внимание к центру.\n\nСоздает художественный эффект и фокусирует взгляд.",
            
            "vignette_strength": "Сила виньетки (0.0-0.5).\n\n• 0.1-0.2: Легкое виньетирование\n• 0.2-0.3: Среднее виньетирование (рекомендуется)\n• 0.3-0.5: Сильное виньетирование",
            
            "edge_enhancement": "Улучшение краев.\n\nПодчеркивает контуры и границы объектов на изображении.\n\nДелает изображение более четким и детализированным.",
            
            "noise_reduction": "Подавление шума изображения.\n\nУдаляет цифровой шум и зернистость с фотографий.\n\nОсобенно полезно для фото, снятых при плохом освещении.",
            
            "histogram_equalization": "Коррекция по гистограмме.\n\nАвтоматически улучшает распределение яркости на изображении.\n\nПовышает контраст и детализацию в темных и светлых областях.",
            
            "style_filter": "Фильтр стиля изображения.\n\n• Нет: Оригинальные цвета\n• Сепия: Теплый коричневый тон (винтажный вид)\n• Ч/б: Черно-белое изображение\n• Винтаж: Состаренный вид с мягкими цветами\n• Холодный: Синеватые тона\n• Теплый: Оранжево-желтые тона",
            
            # === ГРУППА: ЛОГОТИПЫ ===
            "logo_path": "Путь к файлу основного логотипа.\n\nИзображение основного логотипа канала (PNG, JPG, SVG). Будет отображаться в углу видео.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/Logo/main_logo.png'",
            
            "logo2_path": "Путь к файлу дополнительного логотипа.\n\nВторой логотип (например, логотип 'Лайк' или призыв к действию). Отображается отдельно от основного.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/Logo/like_logo.png'",
            
            "subscribe_frames_folder": "Папка с кадрами анимации кнопки подписки.\n\nПапка содержит PNG файлы для анимированной кнопки подписки. Файлы должны быть пронумерованы последовательно.\n\nПример: '/Users/user/Youtube/ЗВЁЗДНЫЕ ТАЙНЫ TV/Subscribe_Animation/'",
            
            "logo_duration": "Длительность показа основного логотипа (секунды).\n\nВремя, в течение которого основной логотип будет виден на экране.\n\nПример: 10.0 (10 секунд), 15.0 (15 секунд), 0 (весь ролик)",
            
            "logo2_duration": "Длительность показа дополнительного логотипа (секунды).\n\nВремя отображения второго логотипа.\n\nПример: 5.0 (5 секунд), 8.0 (8 секунд)",
            
            "logo_width": "Ширина основного логотипа (пиксели).\n\nРазмер логотипа в пикселях. Высота вычисляется автоматически с сохранением пропорций.\n\nПример: 150 (маленький), 200 (средний), 300 (большой)",
            
            "logo2_width": "Ширина дополнительного логотипа (пиксели).\n\nРазмер второго логотипа.\n\nПример: 100 (маленький), 150 (средний), 250 (большой)",
            
            "subscribe_width": "Ширина кнопки подписки (пиксели).\n\nРазмер анимированной кнопки подписки.\n\nПример: 300 (маленькая), 400 (средняя), 500 (большая)",
            
            "subscribe_display_duration": "Длительность показа кнопки подписки (секунды).\n\nВремя, в течение которого кнопка подписки будет видна при каждом появлении.\n\nПример: 3.0 (3 секунды), 5.0 (5 секунд)",
            
            "subscribe_interval_gap": "Интервал между появлениями кнопки (секунды).\n\nВремя между исчезновением и следующим появлением кнопки подписки.\n\nПример: 15.0 (каждые 15 секунд), 30.0 (каждые 30 секунд)",
            
            "subscribe_duration": "Общее время показа кнопки в видео (секунды).\n\nСуммарное время, в течение которого кнопка подписки будет показываться в ролике.\n\nПример: 12.0 (12 секунд суммарно), 20.0 (20 секунд суммарно)",
            
            # === ГРУППА: СУБТИТРЫ ===
            "subtitles_enabled": "Включить генерацию субтитров.\n\nАвтоматически создает субтитры из аудиодорожки с помощью AI (Whisper).\n\nПолезно для улучшения доступности и SEO видео.",
            
            "subtitle_language": "Язык субтитров.\n\nЯзык для распознавания речи и генерации субтитров.\n\nПример: 'ru' (русский), 'en' (английский), 'auto' (автоопределение)",
            
            "subtitle_model": "Модель AI для субтитров.\n\n• Tiny: Самая быстрая, базовое качество\n• Base: Быстрая, хорошее качество\n• Small: Средняя скорость, хорошее качество\n• Medium: Баланс скорости и качества (рекомендуется)\n• Large: Медленная, отличное качество\n• Large-v2/v3: Новейшие модели, лучшее качество",
            
            "subtitle_font_family": "Семейство шрифта субтитров.\n\nВыберите шрифт из установленных в системе.\n\n• Arial: Универсальный, хорошая читаемость\n• Helvetica: Современный, четкий\n• Times New Roman: Классический, серифный\n• Roboto: Современный, оптимизированный для экрана",
            
            "subtitle_fontsize": "Размер шрифта субтитров.\n\nРазмер текста субтитров в пикселях.\n\n• 80-90: Маленький размер\n• 100-120: Средний размер (рекомендуется)\n• 130-150: Большой размер\n• 160+: Очень большой размер",
            
            "subtitle_font_color": "Цвет шрифта субтитров.\n\nЦвет текста субтитров в формате &HBBGGRR (обратный RGB).\n\nПример: '&HFFFFFF' (белый), '&H000000' (черный), '&H00FFFF' (желтый)",
            
            "subtitle_use_backdrop": "Использовать подложку под текст.\n\nДобавляет полупрозрачный фон под текстом субтитров для улучшения читаемости.\n\nРекомендуется для видео со сложным фоном.",
            
            "subtitle_back_color": "Цвет подложки субтитров.\n\nЦвет фона под текстом субтитров.\n\nПример: '&H000000' (черный), '&H808080' (серый), '&H000080' (темно-синий)",
            
            "subtitle_outline_thickness": "Толщина обводки текста.\n\nТолщина контура вокруг букв субтитров.\n\n• 2-3: Тонкая обводка\n• 4-5: Средняя обводка (рекомендуется)\n• 6-8: Толстая обводка",
            
            "subtitle_outline_color": "Цвет обводки текста.\n\nЦвет контура вокруг букв.\n\nПример: '&H000000' (черная обводка для белого текста)",
            
            "subtitle_shadow_thickness": "Толщина тени текста.\n\nИнтенсивность тени за текстом субтитров.\n\n• 1-2: Легкая тень\n• 3-4: Средняя тень (рекомендуется)\n• 5+: Сильная тень",
            
            "subtitle_shadow_color": "Цвет тени текста.\n\nЦвет тени за субтитрами.\n\nПример: '&H333333' (темно-серый), '&H000000' (черный)",
            
            "subtitle_shadow_alpha": "Прозрачность тени (0-255).\n\nУровень прозрачности тени.\n\n• 50-100: Легкая тень\n• 100-150: Средняя тень (рекомендуется)\n• 150-255: Плотная тень",
            
            "subtitle_shadow_offset_x": "Смещение тени по горизонтали.\n\nНасколько пикселей сдвинута тень вправо от текста.\n\nПример: 2 (легкий сдвиг), 4 (средний), 6 (сильный)",
            
            "subtitle_shadow_offset_y": "Смещение тени по вертикали.\n\nНасколько пикселей сдвинута тень вниз от текста.\n\nПример: 2 (легкий сдвиг), 4 (средний), 6 (сильный)",
            
            "subtitle_margin_v": "Вертикальный отступ субтитров.\n\nРасстояние от нижнего края экрана до субтитров.\n\nПример: 20 (близко к краю), 50 (средний отступ), 100 (высоко)",
            
            "subtitle_margin_l": "Левый отступ субтитров.\n\nРасстояние от левого края экрана.\n\nПример: 10 (минимальный), 20 (стандартный), 50 (большой)",
            
            "subtitle_margin_r": "Правый отступ субтитров.\n\nРасстояние от правого края экрана.\n\nПример: 10 (минимальный), 20 (стандартный), 50 (большой)",
            
            "subtitle_line_spacing": "Межстрочный интервал (0.5-3.0).\n\nРасстояние между строками в многострочных субтитрах.\n\n• 0.8-1.0: Плотный текст\n• 1.0-1.2: Стандартный интервал (рекомендуется)\n• 1.2-1.5: Свободный интервал\n• 1.5+: Очень свободный интервал",
            
            "subtitle_max_words": "Максимальное количество слов в субтитре.\n\nОграничивает длину каждого блока субтитров для лучшей читаемости.\n\nПример: 8 (короткие), 12 (средние), 16 (длинные)",
            
            "subtitle_time_offset": "Сдвиг времени субтитров (секунды).\n\nКорректирует синхронизацию субтитров с аудио.\n\n• -1.0: Субтитры появляются на секунду раньше\n• 0.0: Точная синхронизация\n• +1.0: Субтитры появляются на секунду позже",
            
            # === ОТЛАДКА ===
            "debug_video_processing": "Отладка обработки видео.\n\nВключает подробное логирование процесса обработки видео для диагностики проблем.\n\nВключайте только при возникновении ошибок.",
            
            "debug_audio_processing": "Отладка обработки аудио.\n\nВключает подробное логирование процесса обработки аудио.\n\nПомогает диагностировать проблемы с озвучкой и аудиоэффектами.",
            
            "debug_subtitles_processing": "Отладка генерации субтитров.\n\nВключает подробное логирование процесса создания субтитров.\n\nПолезно для решения проблем с распознаванием речи.",
            
            "debug_final_assembly": "Отладка финального монтажа.\n\nВключает подробное логирование процесса сборки итогового видео.\n\nПомогает найти проблемы на последнем этапе создания видео.",
            
            "debug_keep_temp_folder": "Сохранить временную папку после завершения.\n\nПо умолчанию временная папка удаляется после создания видео.\n\nВключите эту опцию для отладки - временные файлы останутся доступными для анализа."
        }
        return tooltips.get(param_key, "Описание отсутствует")

    def calculate_content_height(self, subgroups: Dict) -> int:
        """Вычисление высоты контента для скролл-области"""
        total_height = 0
        for subgroup_name, params in subgroups.items():
            total_height += 40  # Заголовок подгруппы с улучшенными отступами

            if params == "voice_selector":
                total_height += 320  # Увеличенная высота виджета выбора голоса
            elif params == "voice_settings":
                total_height += 200  # Увеличенная высота виджета с ползунками
            elif params == "logo_position_editor":
                total_height += 370  # Точная высота: 324 (view) + 30 (кнопки) + 16 (отступы)
            elif params == "subtitle_preview":
                total_height += 370  # Точная высота: 324 (view) + 30 (кнопки) + 16 (отступы)
            else:
                num_rows = (len(params) + 1) // 2
                total_height += num_rows * 50  # Увеличенная высота строки параметра для лучших отступов

            total_height += 10  # Минимальные отступы и разделитель

        return max(total_height, 500)  # Увеличиваем минимальную высоту для лучшего вида