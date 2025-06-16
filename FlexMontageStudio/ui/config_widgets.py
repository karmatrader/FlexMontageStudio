"""
Виджеты для настройки параметров конфигурации
"""
import logging

logger = logging.getLogger(__name__)
from typing import Dict, Any, List, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QLineEdit, QCheckBox, QPushButton, QFrame, QComboBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QStandardItemModel, QStandardItem

try:
    from .subtitle_preview_widget import SubtitlePreviewWidget
    from .color_picker_widget import ColorPickerWidget
except ImportError:
    # Fallback если модули не найдены
    SubtitlePreviewWidget = None
    ColorPickerWidget = None

logger = logging.getLogger(__name__)


class CheckableComboBox(QComboBox):
    """Комбобокс с возможностью множественного выбора"""

    def __init__(self):
        super().__init__()
        self.model = QStandardItemModel()
        self.setModel(self.model)
        self._checked_items = set()
        self.model.dataChanged.connect(self.on_data_changed)
        
        # Добавляем таймер для предотвращения слишком частых обновлений
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._delayed_update)
        self._pending_update = False

    def addItem(self, text: str):
        """Добавление элемента с чекбоксом"""
        item = QStandardItem(text)
        item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        item.setData(Qt.Unchecked, Qt.CheckStateRole)
        self.model.appendRow(item)

    def on_data_changed(self, top_left, bottom_right):
        """Обработка изменения состояния элементов"""
        try:
            for row in range(top_left.row(), bottom_right.row() + 1):
                item = self.model.item(row)
                if item is None:
                    continue
                    
                check_state = item.checkState()
                text = item.text()
                
                if not text:  # Пропускаем пустые элементы
                    continue
                    
                if check_state == Qt.Checked:
                    self._checked_items.add(text)
                else:
                    self._checked_items.discard(text)
            # Используем таймер для отложенного обновления
            self._pending_update = True
            self._update_timer.start(100)  # Задержка 100мс
        except Exception as e:
            logger.error(f"Ошибка в on_data_changed: {e}")
            # В случае ошибки просто продолжаем работу

    def _delayed_update(self):
        """Отложенное обновление с защитой от краша"""
        try:
            if self._pending_update:
                self.update_text()
                self._pending_update = False
        except Exception as e:
            logger.error(f"Ошибка в _delayed_update: {e}")

    def update_text(self):
        """Обновление отображаемого текста"""
        try:
            text = ", ".join(sorted(self._checked_items)) if self._checked_items else ""
            self.setCurrentText(text)
            self.currentTextChanged.emit(text)
        except Exception as e:
            logger.error(f"Ошибка в update_text: {e}")

    def checkedItems(self) -> List[str]:
        """Получение списка выбранных элементов"""
        return list(self._checked_items)

    def clear(self):
        """Очистка всех элементов"""
        self._checked_items.clear()
        self.model.clear()
        self.update_text()


class ConfigTabsWidget(QWidget):
    """Виджет с вкладками конфигурации"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.param_entries: Dict[str, Any] = {}
        self.tooltips = self._create_tooltips()
        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Здесь будут созданы вкладки конфигурации
        # Код будет добавлен в методе create_param_tabs

    def _create_tooltips(self) -> Dict[str, str]:
        """Создание подсказок для параметров"""
        return {
            "num_videos": "Количество видео, которые будут обработаны в одном запуске монтажа.",
            "channel_name": "Имя канала, используется для идентификации канала в конфигурации.",
            "channel_column": "Столбец в Excel-файле, где хранятся данные канала (например, B, C, D).",
            "preserve_clip_audio_videos": "Номера видео, для которых нужно сохранить оригинальное аудио (например, 3,5).",
            "video_numbers": "Номера видео для генерации. Можно указать отдельные номера через запятую (1,3,5) или диапазоны (1-5,8,10-12). Оставьте пустым для автоматического определения.",
            "max_concurrent_montages": "Максимальное количество видео, которые могут монтироваться одновременно (рекомендуется 2-5). При больших значениях система может замедлиться.",
            "global_xlsx_file_path": "Путь к основному Excel-файлу с данными для всех каналов.",
            "channel_folder": "Папка, где хранятся данные конкретного канала.",
            "base_path": "Базовый путь для всех файлов канала.",
            "csv_file_path": "Путь к CSV-файлу с API-ключами для 11labs.",
            "output_directory": "Папка, куда будут сохраняться итоговые файлы озвучки.",
            "photo_folder": "Папка с фотографиями, используемыми в видео.",
            "audio_folder": "Папка с аудиофайлами для видео.",
            "output_folder": "Папка для готовых видеофайлов после монтажа.",
            "logo_path": "Путь к файлу логотипа, который будет наложен на видео.",
            "logo2_path": "Путь к дополнительному логотипу для наложения на видео.",
            "subscribe_frames_folder": "Папка с кадрами для кнопки подписки.",
            "background_music_path": "Путь к фоновой музыке для видео.",
            "photo_folder_fallback": "Резервная папка для фото, если основная недоступна.",
            "default_lang": "Язык по умолчанию для озвучки (например, RU для русского).",
            "default_stability": "Стабильность голоса при озвучке (от 0 до 1).",
            "default_similarity": "Схожесть голоса с оригиналом (от 0 до 1).",
            "default_voice_speed": "Скорость голоса при озвучке (например, 1.0 для нормальной скорости).",
            "default_voice_style": "Стиль голоса для озвучки (если поддерживается).",
            "standard_voice_id": "ID стандартного голоса для озвучки.",
            "use_library_voice": "Если включено, используется голос из библиотеки, а не оригинальный.",
            "original_voice_id": "ID оригинального голоса для озвучки.",
            "public_owner_id": "ID владельца голоса (для доступа к голосам).",
            "max_retries": "Максимальное количество попыток для операций озвучки.",
            "ban_retry_delay": "Задержка (в секундах) перед повторной попыткой озвучки после бана IP.",
            "audio_bitrate": "Битрейт аудио (например, 192k).",
            "audio_sample_rate": "Частота дискретизации аудио (например, 44100 Гц).",
            "audio_channels": "Количество аудиоканалов (1 для моно, 2 для стерео).",
            "silence_duration": "Длительность пауз в аудио (например, 1.0-2.5 секунд).",
            "background_music_volume": "Громкость фоновой музыки (от 0 до 1).",
            "preserve_video_duration": "Если включено, сохраняет длительность исходного видео.",
            "preserve_clip_audio": "Если включено, сохраняет аудио исходных клипов.",
            "adjust_videos_to_audio": "Если включено, видео подстраивается под длительность аудио.",
            "video_resolution": "Разрешение видео (например, 1920:1080).",
            "frame_rate": "Частота кадров видео (например, 30 fps).",
            "video_crf": "Качество видео (CRF, от 0 до 51, меньше — лучше качество).",
            "video_preset": "Пресет кодирования видео (например, fast, slow).",
            "photo_order": "Порядок использования фотографий (например, order для последовательного).",
            "bokeh_enabled": "Если включено, применяется эффект боке к фотографиям.",
            "bokeh_image_size": "Размер изображения для эффекта боке (например, [1920, 1080]).",
            "bokeh_blur_kernel": "Размер ядра размытия для эффекта боке (например, [99, 99]).",
            "bokeh_blur_sigma": "Сила размытия для эффекта боке (например, 30).",
            "logo_width": "Ширина основного логотипа в пикселях.",
            "logo_position_x": "Позиция логотипа по оси X (например, W-w-20).",
            "logo_position_y": "Позиция логотипа по оси Y (например, 20).",
            "logo_duration": "Длительность отображения логотипа (например, all для всего видео).",
            "logo2_width": "Ширина дополнительного логотипа в пикселях.",
            "logo2_position_x": "Позиция доп. логотипа по оси X (например, 20).",
            "logo2_position_y": "Позиция доп. логотипа по оси Y (например, 20).",
            "logo2_duration": "Длительность доп. логотипа (например, all).",
            "subscribe_width": "Ширина кнопки подписки в пикселях.",
            "subscribe_position_x": "Позиция кнопки подписки по оси X.",
            "subscribe_position_y": "Позиция кнопки подписки по оси Y.",
            "subscribe_display_duration": "Длительность отображения кнопки подписки (в секундах).",
            "subscribe_interval_gap": "Интервал между появлениями кнопки подписки (в секундах).",
            "subtitles_enabled": "Если включено, добавляются субтитры к видео.",
            "subtitle_language": "Язык субтитров (например, ru для русского).",
            "subtitle_model": "Модель субтитров (например, medium).",
            "subtitle_fontsize": "Размер шрифта субтитров.",
            "subtitle_font_color": "Цвет шрифта субтитров (например, &HFFFFFF для белого).",
            "subtitle_use_backdrop": "Если включено, добавляется подложка под субтитры.",
            "subtitle_back_color": "Цвет подложки субтитров (например, &HFFFFFF).",
            "subtitle_outline_thickness": "Толщина обводки текста субтитров.",
            "subtitle_outline_color": "Цвет обводки текста субтитров (например, &H000000).",
            "subtitle_shadow_thickness": "Толщина тени субтитров.",
            "subtitle_shadow_color": "Цвет тени субтитров (например, &H333333).",
            "subtitle_shadow_alpha": "Прозрачность тени субтитров (0-100).",
            "subtitle_shadow_offset_x": "Смещение тени субтитров по оси X.",
            "subtitle_shadow_offset_y": "Смещение тени субтитров по оси Y.",
            "subtitle_margin_v": "Вертикальный отступ субтитров от края видео.",
            "subtitle_margin_l": "Левый отступ субтитров.",
            "subtitle_margin_r": "Правый отступ субтитров.",
            "subtitle_max_words": "Максимальное количество слов в строке субтитров.",
            "subtitle_time_offset": "Сдвиг времени субтитров (в секундах, может быть отрицательным).",
            "proxy": "URL прокси-сервера для HTTP/HTTPS запросов (например, http://65.109.79.15:25100).",
            "proxy_login": "Логин для доступа к прокси-серверу.",
            "proxy_password": "Пароль для доступа к прокси-серверу.",
            "use_proxy": "Если включено, запросы будут отправляться через прокси-сервер.",
            "debug_video_processing": "Включает отладочные сообщения для модуля обработки видео.",
            "debug_audio_processing": "Включает отладочные сообщения для модуля обработки аудио.",
            "debug_subtitles_processing": "Включает отладочные сообщения для модуля обработки субтитров.",
            "debug_final_assembly": "Включает отладочные сообщения для модуля финальной сборки."
        }

    def get_param_entries(self) -> Dict[str, Any]:
        """Получение словаря с элементами параметров"""
        return self.param_entries

    def browse_path(self, entry: QLineEdit, is_file: bool):
        """Обзор пути к файлу или папке"""
        from PySide6.QtWidgets import QFileDialog

        if is_file:
            path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        else:
            path = QFileDialog.getExistingDirectory(self, "Выберите папку")

        if path:
            entry.setText(path)

    def create_path_widget(self, param_key: str) -> QWidget:
        """Создание виджета для выбора пути"""
        entry_widget = QWidget()
        entry_layout = QHBoxLayout(entry_widget)
        entry_layout.setContentsMargins(0, 0, 0, 0)

        entry = QLineEdit()
        entry.setMinimumWidth(200)
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

    def create_checkbox_widget(self, param_key: str) -> QCheckBox:
        """Создание чекбокса"""
        return QCheckBox()

    def create_text_widget(self, param_key: str) -> QLineEdit:
        """Создание текстового поля"""
        entry = QLineEdit()
        entry.setMinimumWidth(200)

        if param_key == "preserve_clip_audio_videos":
            entry.setPlaceholderText("Например: 3,5")
        elif param_key == "video_numbers":
            entry.setPlaceholderText("Например: 1,3,5-8,10")
        elif param_key == "max_concurrent_montages":
            entry.setPlaceholderText("По умолчанию: 3")

        return entry
    
    def create_combobox_widget(self, param_key: str) -> QComboBox:
        """Создание выпадающего списка для эффектов"""
        combobox = QComboBox()
        combobox.setMinimumWidth(200)
        
        # Определяем варианты для разных типов эффектов
        if param_key == "video_zoom_effect":
            options = [
                ("none", "Нет"),
                ("zoom_in", "Zoom In"),
                ("zoom_out", "Zoom Out"),
                ("auto", "Автоматическое чередование")
            ]
        elif param_key == "video_rotation_effect":
            options = [
                ("none", "Нет"),
                ("sway", "Покачивание"),
                ("rotate_left", "Вращение влево"),
                ("rotate_right", "Вращение вправо")
            ]
        elif param_key == "video_color_effect":
            options = [
                ("none", "Нет"),
                ("sepia", "Сепия"),
                ("grayscale", "Черно-белое"),
                ("invert", "Инверсия"),
                ("vintage", "Винтаж")
            ]
        elif param_key == "video_filter_effect":
            options = [
                ("none", "Нет"),
                ("blur", "Размытие"),
                ("sharpen", "Резкость"),
                ("noise", "Шум"),
                ("vignette", "Виньетка")
            ]
        elif param_key == "transition_type":
            options = [
                ("fade", "Затухание"),
                ("dissolve", "Растворение"),
                ("wipeleft", "Стирание влево"),
                ("wiperight", "Стирание вправо"),
                ("wipeup", "Стирание вверх"),
                ("wipedown", "Стирание вниз"),
                ("slideleft", "Скольжение влево"),
                ("slideright", "Скольжение вправо"),
                ("slideup", "Скольжение вверх"),
                ("slidedown", "Скольжение вниз")
            ]
        else:
            # Для неизвестных параметров используем базовые варианты
            options = [("none", "Нет")]
        
        # Добавляем варианты в комбобокс
        for value, display_text in options:
            combobox.addItem(display_text, value)
        
        return combobox
    
    def create_color_picker_widget(self, param_key: str) -> QWidget:
        """Создание виджета выбора цвета"""
        if ColorPickerWidget is None:
            # Fallback на обычное текстовое поле
            return self.create_text_widget(param_key)
        
        try:
            return ColorPickerWidget()
        except Exception:
            return self.create_text_widget(param_key)
    
    def create_subtitle_preview_widget(self) -> QWidget:
        """Создание виджета предпросмотра субтитров"""
        if SubtitlePreviewWidget is None:
            # Fallback на обычный label
            return QLabel("Предпросмотр субтитров недоступен")
        
        try:
            return SubtitlePreviewWidget()
        except Exception:
            return QLabel("Предпросмотр субтитров недоступен")

    def create_separator(self) -> QFrame:
        """Создание разделителя"""
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        return separator

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
                    ("debug_video_processing", "Отладка видео процессинга"),
                    ("debug_audio_processing", "Отладка аудио процессинга"),
                    ("debug_subtitles_processing", "Отладка субтитров"),
                    ("debug_final_assembly", "Отладка финальной сборки")
                ],
                "Пути": [
                    ("global_xlsx_file_path", "Путь к Excel со сценариями"),
                    ("channel_folder", "Папка канала"),
                    ("base_path", "Корневая папка"),
                    ("csv_file_path", "Путь к CSV-файлу"),
                    ("output_directory", "Папка для аудио озвучки"),
                    ("photo_folder", "Папка с фото"),
                    ("audio_folder", "Папка с аудио"),
                    ("output_folder", "Папка для готового видео"),
                    ("logo_path", "Путь к логотипу"),
                    ("logo2_path", "Путь к дополнительному логотипу"),
                    ("subscribe_frames_folder", "Папка с кадрами подписки"),
                    ("background_music_path", "Путь к фоновой музыке"),
                    ("photo_folder_fallback", "Резервная папка для фото")
                ]
            },
            "Озвучка": {
                "Настройки голоса": [
                    ("default_lang", "Язык по умолчанию"),
                    ("default_stability", "Стабильность голоса"),
                    ("default_similarity", "Схожесть голоса"),
                    ("default_voice_speed", "Скорость голоса"),
                    ("default_voice_style", "Стиль голоса"),
                    ("standard_voice_id", "ID стандартного голоса"),
                    ("use_library_voice", "Использовать голос из библиотеки"),
                    ("max_retries", "Максимум попыток"),
                    ("ban_retry_delay", "Задержка после бана IP (сек)")
                ],
                "Выбор голоса из библиотеки": "voice_selector"  # Специальная метка
            },
            "Аудио": {
                "Настройки аудио": [
                    ("audio_bitrate", "Битрейт аудио"),
                    ("audio_sample_rate", "Частота дискретизации"),
                    ("audio_channels", "Количество каналов"),
                    ("silence_duration", "Длительность тишины"),
                    ("background_music_volume", "Громкость фоновой музыки")
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
                    ("preserve_clip_audio", "Сохранять аудио клипов"),
                    ("adjust_videos_to_audio", "Подстраивать видео под аудио")
                ]
            },
            "Фото": {
                "Настройки эффекта боке": [
                    ("bokeh_enabled", "Включить эффект боке"),
                    ("bokeh_image_size", "Размер изображения"),
                    ("bokeh_blur_kernel", "Ядро размытия"),
                    ("bokeh_blur_sigma", "Сила размытия")
                ]
            },
            "Логотипы": {
                "Настройки логотипа": [
                    ("logo_width", "Ширина логотипа"),
                    ("logo_position_x", "Позиция логотипа X"),
                    ("logo_position_y", "Позиция логотипа Y"),
                    ("logo_duration", "Длительность показа логотипа"),
                    ("logo2_width", "Ширина доп. логотипа"),
                    ("logo2_position_x", "Позиция доп. логотипа X"),
                    ("logo2_position_y", "Позиция доп. логотипа Y"),
                    ("logo2_duration", "Длительность доп. логотипа")
                ]
            },
            "Подписка": {
                "Настройки кнопки": [
                    ("subscribe_width", "Ширина кнопки подписки"),
                    ("subscribe_position_x", "Позиция кнопки X"),
                    ("subscribe_position_y", "Позиция кнопки Y"),
                    ("subscribe_display_duration", "Длительность показа кнопки"),
                    ("subscribe_interval_gap", "Интервал появления кнопки")
                ]
            },
            "Субтитры": {
                "Основные настройки субтитров": [
                    ("subtitles_enabled", "Включить субтитры"),
                    ("subtitle_language", "Язык субтитров"),
                    ("subtitle_model", "Модель субтитров"),
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
                    ("subtitle_max_words", "Максимум слов"),
                    ("subtitle_time_offset", "Сдвиг времени")
                ],
                "Предпросмотр субтитров": "subtitle_preview"  # Специальная метка
            }
        }

    def get_path_fields(self) -> List[str]:
        """Получение списка полей с путями"""
        return [
            "global_xlsx_file_path", "channel_folder", "base_path", "csv_file_path",
            "output_directory", "photo_folder", "audio_folder", "output_folder",
            "logo_path", "logo2_path", "subscribe_frames_folder", "background_music_path"
        ]

    def get_checkbox_fields(self) -> List[str]:
        """Получение списка полей с чекбоксами"""
        return [
            "use_library_voice", "bokeh_enabled", "subtitles_enabled",
            "subtitle_use_backdrop", "preserve_video_duration", "preserve_clip_audio",
            "adjust_videos_to_audio", "use_proxy", "debug_video_processing",
            "debug_audio_processing", "debug_subtitles_processing", "debug_final_assembly"
        ]
    
    def get_color_fields(self) -> List[str]:
        """Получение списка полей с цветами для субтитров"""
        return [
            "subtitle_font_color", "subtitle_back_color", 
            "subtitle_outline_color", "subtitle_shadow_color"
        ]
    
    def get_combobox_fields(self) -> List[str]:
        """Получение списка полей с выпадающими списками для эффектов"""
        return [
            "video_zoom_effect", "video_rotation_effect", "video_color_effect",
            "video_filter_effect", "transition_type"
        ]