"""
Виджеты для настройки параметров конфигурации
"""
import logging

logger = logging.getLogger(__name__)
from typing import Dict, Any, List, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QLineEdit, QCheckBox, QPushButton, QFrame, QComboBox, QSlider
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
            "csv_file_path": "Путь к файлу с API ключами ElevenLabs (CSV/TXT).",
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
            "audio_bitrate": "Битрейт аудио. Выше значение = лучше качество, больше размер файла.",
            "audio_sample_rate": "Частота дискретизации аудио. 44100 Гц для CD качества, 48000 Гц для профессионального аудио.",
            "audio_channels": "Количество аудиоканалов (1 для моно, 2 для стерео).",
            "silence_duration": "Длительность пауз между фразами озвучки (например, 1.0-2.5 секунд).",
            "background_music_volume": "Громкость фоновой музыки в процентах (0-100%).",
            "background_music_fade_in": "Длительность плавного появления фоновой музыки в начале видео (секунды).",
            "background_music_fade_out": "Длительность плавного затухания фоновой музыки в конце видео (секунды).",
            "audio_normalize": "Нормализация выравнивает громкость всего финального аудио до одного уровня.",
            "audio_normalize_method": "Выбор алгоритма нормализации: Peak (по пикам), RMS (среднеквадратичная), LUFS (стандарт вещания).",
            "audio_normalize_target": "Целевая громкость нормализации в децибелах (обычно от -23 до -16 dB).",
            "audio_peak_limiting": "Лимитер предотвращает превышение указанного порога, защищая от клиппинга.",
            "audio_peak_limit_db": "Максимальный уровень сигнала в dB. Всё выше будет ограничено (-6 до 0 dB).",
            "audio_loudness_matching": "Выравнивание громкости по стандарту LUFS (используется на YouTube, Netflix и ТВ).",
            "audio_lufs_target": "Целевая громкость по стандарту LUFS. YouTube: -14 LUFS, ТВ: -23 LUFS.",
            "audio_compressor": "Компрессор уменьшает разницу между тихими и громкими звуками, делая звук более ровным.",
            "audio_compressor_type": "Тип компрессора: Soft (мягкое сжатие), Hard (жёсткое), Vintage (винтажное звучание).",
            "audio_compressor_ratio": "Степень сжатия компрессора (2:1 мягкое, 4:1 умеренное, 8:1 сильное).",
            "audio_compressor_attack": "Скорость срабатывания компрессора в миллисекундах (1-100 мс).",
            "audio_compressor_release": "Время восстановления компрессора в миллисекундах (10-1000 мс).",
            "audio_gate_enabled": "Шумовые ворота обрезают сигнал ниже порога, убирая фоновый шум в паузах.",
            "audio_gate_threshold": "Уровень в dB ниже которого сигнал будет заглушён (-60 до -20 dB).",
            "audio_eq_enabled": "Эквалайзер позволяет корректировать частотную характеристику звука.",
            "audio_eq_preset": "Готовые настройки эквалайзера для разных типов контента.",
            "audio_eq_bass": "Усиление или ослабление низких частот (басов) в децибелах (-10 до +10 dB).",
            "audio_eq_mid": "Усиление или ослабление средних частот в децибелах (-10 до +10 dB).",
            "audio_eq_treble": "Усиление или ослабление высоких частот (верхов) в децибелах (-10 до +10 dB).",
            "audio_eq_presence": "Усиление частот присутствия (2-5 кГц) для разборчивости речи (-10 до +10 dB).",
            "voice_noise_reduction": "Шумоподавление удаляет фоновые шумы из голосовой дорожки.",
            "voice_denoise_strength": "Интенсивность шумоподавления от мягкого до агрессивного (0-100%).",
            "voice_enhancement": "Улучшение качества голоса с помощью фильтров и обработки.",
            "voice_clarity_boost": "Усиление разборчивости речи путём подчёркивания важных частот.",
            "voice_warmth": "Добавление теплоты голосу через усиление низко-средних частот.",
            "voice_de_esser": "Де-эссер убирает резкие свистящие звуки (с, ш, щ, ч).",
            "voice_de_esser_threshold": "Порог срабатывания де-эссера в dB (-40 до -10 dB).",
            "preserve_video_duration": "Если включено, сохраняет длительность исходного видео.",
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
            "subscribe_duration": "Общее время показа кнопки подписки ('all' для всего видео или число секунд).",
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
            "subtitle_line_spacing": "Межстрочный интервал для многострочных субтитров (0.5 - 3.0).",
            "subtitle_max_words": "Максимальное количество слов в строке субтитров.",
            "subtitle_time_offset": "Сдвиг времени субтитров (в секундах, может быть отрицательным).",
            "proxy": "URL прокси-сервера для HTTP/HTTPS запросов (например, http://65.109.79.15:25100).",
            "proxy_login": "Логин для доступа к прокси-серверу.",
            "proxy_password": "Пароль для доступа к прокси-серверу.",
            "use_proxy": "Если включено, запросы будут отправляться через прокси-сервер.",
            "proxy_type": "Тип прокси: standard (обычные) или residential (резидентские с ротацией IP).",
            "rotate_endpoint": "URL для ротации IP резидентских прокси. Для авторизации используются основные proxy_login и proxy_password.",
            "rotate_min_interval": "Минимальный интервал между ротациями IP в секундах (минимум 30).",
            "max_concurrent_requests": "Максимальное количество одновременных запросов к API (рекомендуется 1-2).",
            "parallel_threads": "Количество параллельных потоков для обработки текста (рекомендуется 2-4).",
            "debug_video_processing": "Включает отладочные сообщения для модуля обработки видео.",
            "debug_audio_processing": "Включает отладочные сообщения для модуля обработки аудио.",
            "debug_subtitles_processing": "Включает отладочные сообщения для модуля обработки субтитров.",
            "debug_final_assembly": "Включает отладочные сообщения для модуля финальной сборки.",
            "debug_keep_temp_folder": "Сохранять временную папку после завершения монтажа для отладки."
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
        elif param_key == "transition_method":
            options = [
                ("overlay", "Overlay (наложение, медленнее но стабильнее)"),
                ("xfade", "XFade (нативные переходы FFmpeg, быстрее)")
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
        elif param_key == "audio_bitrate":
            options = [
                ("128k", "128 kbps (низкое качество)"),
                ("192k", "192 kbps (хорошее качество)"),
                ("256k", "256 kbps (высокое качество)"),
                ("320k", "320 kbps (отличное качество)"),
                ("448k", "448 kbps (профессиональное)"),
                ("640k", "640 kbps (максимальное)")
            ]
        elif param_key == "audio_sample_rate":
            options = [
                ("22050", "22.05 kHz (экономия места)"),
                ("44100", "44.1 kHz (CD качество)"),
                ("48000", "48 kHz (DVD/профессиональное)"),
                ("96000", "96 kHz (высококачественное)")
            ]
        elif param_key == "audio_compressor_ratio":
            options = [
                ("2:1", "2:1 (мягкое сжатие)"),
                ("3:1", "3:1 (умеренное сжатие)"),
                ("4:1", "4:1 (стандартное сжатие)"),
                ("6:1", "6:1 (сильное сжатие)"),
                ("8:1", "8:1 (очень сильное сжатие)"),
                ("10:1", "10:1 (лимитер)")
            ]
        elif param_key == "audio_normalize_method":
            options = [
                ("peak", "Peak (по пикам)"),
                ("rms", "RMS (среднеквадратичная)"),
                ("lufs", "LUFS (стандарт вещания)"),
                ("ebu", "EBU R128 (европейский стандарт)")
            ]
        elif param_key == "audio_compressor_type":
            options = [
                ("soft", "Soft (мягкое сжатие)"),
                ("hard", "Hard (жёсткое сжатие)"),
                ("vintage", "Vintage (аналоговое звучание)"),
                ("optical", "Optical (оптический компрессор)"),
                ("vca", "VCA (быстрый и точный)")
            ]
        elif param_key == "audio_eq_preset":
            options = [
                ("flat", "Flat (без изменений)"),
                ("voice_male", "Мужской голос"),
                ("voice_female", "Женский голос"),
                ("voice_warm", "Тёплый голос"),
                ("voice_bright", "Яркий голос"),
                ("voice_radio", "Радио голос"),
                ("podcast", "Подкаст"),
                ("music_pop", "Поп музыка"),
                ("music_rock", "Рок музыка"),
                ("music_classical", "Классическая музыка"),
                ("bass_boost", "Усиление басов"),
                ("treble_boost", "Усиление высоких"),
                ("vocal_cut", "Подавление вокала"),
                ("phone_call", "Телефонный звонок")
            ]
        else:
            # Для неизвестных параметров используем базовые варианты
            options = [("none", "Нет")]
        
        # Добавляем варианты в комбобокс
        for value, display_text in options:
            combobox.addItem(display_text, value)
        
        return combobox
    
    def create_slider_widget(self, param_key: str) -> QWidget:
        """Создание виджета слайдера для аудио параметров"""
        slider_widget = QWidget()
        slider_layout = QHBoxLayout(slider_widget)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimumWidth(200)
        
        # Настройка диапазонов для разных параметров
        if param_key == "background_music_volume":
            slider.setRange(0, 10000)  # 0.00 до 100.00%
            slider.setValue(1500)  # 15% по умолчанию
            suffix = "%"
            divider = 100.0  # Делим на 100 для получения процентов с сотыми
        elif param_key == "audio_normalize_target":
            slider.setRange(-40, -10)  # от -40 до -10 dB
            slider.setValue(-23)  # -23 dB по умолчанию (стандарт YouTube)
            suffix = " dB"
            divider = 1.0
        elif param_key == "audio_eq_bass":
            slider.setRange(-100, 100)  # от -10 до +10 dB (умножено на 10)
            slider.setValue(0)  # 0 dB по умолчанию
            suffix = " dB"
            divider = 10.0
        elif param_key == "audio_eq_treble":
            slider.setRange(-100, 100)  # от -10 до +10 dB (умножено на 10)
            slider.setValue(0)  # 0 dB по умолчанию
            suffix = " dB"
            divider = 10.0
        elif param_key == "audio_peak_limit_db":
            slider.setRange(-60, 0)  # от -6 до 0 dB
            slider.setValue(-10)  # -1.0 dB по умолчанию
            suffix = " dB"
            divider = 1.0
        elif param_key == "audio_lufs_target":
            slider.setRange(-30, -10)  # от -30 до -10 LUFS
            slider.setValue(-14)  # -14 LUFS по умолчанию (YouTube стандарт)
            suffix = " LUFS"
            divider = 1.0
        elif param_key == "audio_compressor_attack":
            slider.setRange(1, 100)  # 1-100 мс
            slider.setValue(10)  # 10 мс по умолчанию
            suffix = " мс"
            divider = 1.0
        elif param_key == "audio_compressor_release":
            slider.setRange(10, 1000)  # 10-1000 мс
            slider.setValue(100)  # 100 мс по умолчанию
            suffix = " мс"
            divider = 1.0
        elif param_key == "audio_gate_threshold":
            slider.setRange(-600, -200)  # от -60 до -20 dB (умножено на 10)
            slider.setValue(-400)  # -40 dB по умолчанию
            suffix = " dB"
            divider = 10.0
        elif param_key == "audio_eq_mid":
            slider.setRange(-100, 100)  # от -10 до +10 dB (умножено на 10)
            slider.setValue(0)  # 0 dB по умолчанию
            suffix = " dB"
            divider = 10.0
        elif param_key == "audio_eq_presence":
            slider.setRange(-100, 100)  # от -10 до +10 dB (умножено на 10)
            slider.setValue(0)  # 0 dB по умолчанию
            suffix = " dB"
            divider = 10.0
        elif param_key == "voice_denoise_strength":
            slider.setRange(0, 100)  # 0-100%
            slider.setValue(50)  # 50% по умолчанию
            suffix = "%"
            divider = 1.0
        elif param_key == "voice_de_esser_threshold":
            slider.setRange(-400, -100)  # от -40 до -10 dB (умножено на 10)
            slider.setValue(-250)  # -25 dB по умолчанию
            suffix = " dB"
            divider = 10.0
        else:
            slider.setRange(0, 100)
            slider.setValue(50)
            suffix = ""
            divider = 1.0
        
        # Создаем label для отображения значения
        value_label = QLabel()
        value_label.setMinimumWidth(80)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        def update_label():
            value = slider.value() / divider
            if param_key == "background_music_volume":
                value_label.setText(f"{value:.2f}{suffix}")
            elif param_key in ["audio_eq_bass", "audio_eq_treble"]:
                value_label.setText(f"{value:+.1f}{suffix}")
            else:
                value_label.setText(f"{value:.0f}{suffix}")
        
        # Инициализируем label
        update_label()
        
        # Подключаем обновление label при изменении слайдера
        slider.valueChanged.connect(update_label)
        
        slider_layout.addWidget(slider)
        slider_layout.addWidget(value_label)
        
        # Сохраняем ссылки для доступа извне
        slider_widget.slider = slider
        slider_widget.value_label = value_label
        slider_widget.divider = divider
        slider_widget.suffix = suffix
        
        return slider_widget
    
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
                    ("proxy_type", "Тип прокси"),
                    ("rotate_endpoint", "URL для ротации IP"),
                    ("rotate_min_interval", "Мин. интервал ротации (сек)"),
                    ("max_concurrent_requests", "Макс. параллельных запросов"),
                    ("parallel_threads", "Количество потоков"),
                    ("debug_video_processing", "Отладка видео процессинга"),
                    ("debug_audio_processing", "Отладка аудио процессинга"),
                    ("debug_subtitles_processing", "Отладка субтитров"),
                    ("debug_final_assembly", "Отладка финальной сборки")
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
                    ("subscribe_interval_gap", "Интервал появления кнопки"),
                    ("subscribe_duration", "Общее время показа кнопки")
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
                    ("subtitle_line_spacing", "Межстрочный интервал"),
                    ("subtitle_max_words", "Максимум слов"),
                    ("subtitle_time_offset", "Сдвиг времени")
                ],
                "Предпросмотр субтитров": "subtitle_preview"  # Специальная метка
            },
            "Отладка": {
                "Настройки отладки": [
                    ("debug_keep_temp_folder", "Сохранять временную папку")
                ]
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
            "subtitle_use_backdrop", "preserve_video_duration",
            "adjust_videos_to_audio", "use_proxy", "debug_video_processing",
            "debug_audio_processing", "debug_subtitles_processing", "debug_final_assembly",
            "audio_normalize", "audio_peak_limiting", "audio_loudness_matching",
            "audio_compressor", "audio_gate_enabled", "audio_eq_enabled", 
            "voice_noise_reduction", "voice_enhancement", "voice_clarity_boost",
            "voice_warmth", "voice_de_esser", "debug_keep_temp_folder"
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
            "video_filter_effect", "transition_method", "transition_type", "audio_bitrate", "audio_sample_rate",
            "audio_compressor_ratio", "audio_normalize_method", "audio_compressor_type",
            "audio_eq_preset"
        ]
    
    def get_slider_fields(self) -> List[str]:
        """Получение списка полей со слайдерами"""
        return [
            "background_music_volume", "audio_normalize_target", "audio_peak_limit_db",
            "audio_lufs_target", "audio_compressor_attack", "audio_compressor_release",
            "audio_gate_threshold", "audio_eq_bass", "audio_eq_mid", "audio_eq_treble",
            "audio_eq_presence", "voice_denoise_strength", "voice_de_esser_threshold"
        ]