"""
Виджет с ползунками для настройки параметров голоса
Заменяет текстовые поля на удобные ползунки с отображением значений
"""
import logging
from typing import Dict, Callable, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton
)
from PySide6.QtCore import Signal, Qt

logger = logging.getLogger(__name__)


class VoiceSettingsWidget(QWidget):
    """Виджет для настройки параметров голоса с ползунками"""

    # Сигналы для уведомления об изменении значений
    stability_changed = Signal(float)  # 0.0 - 1.0
    similarity_changed = Signal(float)  # 0.0 - 1.0
    speed_changed = Signal(float)  # 0.7 - 1.2

    def __init__(self, parent=None):
        super().__init__(parent)

        # Значения по умолчанию
        self.default_stability = 50  # 50% = 0.5
        self.default_similarity = 75  # 75% = 0.75
        self.default_speed = 100  # 100% = 1.0 (диапазон от 70% до 120%)

        # Текущие значения
        self.current_stability = self.default_stability
        self.current_similarity = self.default_similarity
        self.current_speed = self.default_speed

        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Заголовок
        header_label = QLabel("Настройки голоса:")
        header_label.setObjectName("voice-settings-header")
        header_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header_label)

        # Ползунок стабильности
        stability_widget, stability_slider = self._create_slider_group(
            "Стабильность голоса:",
            0, 100, self.default_stability,
            self._format_percentage,
            self._on_stability_changed
        )
        
        # Добавляем метку и слайдер как на фото вкладке
        stability_label = QLabel("Стабильность голоса:")
        stability_label.setStyleSheet("color: #B8B8B8; font-size: 12px;")
        layout.addWidget(stability_label)
        layout.addWidget(stability_widget)

        # Ползунок схожести
        similarity_widget, similarity_slider = self._create_slider_group(
            "Схожесть голоса:",
            0, 100, self.default_similarity,
            self._format_percentage,
            self._on_similarity_changed
        )
        
        similarity_label = QLabel("Схожесть голоса:")
        similarity_label.setStyleSheet("color: #B8B8B8; font-size: 12px;")
        layout.addWidget(similarity_label)
        layout.addWidget(similarity_widget)

        # Ползунок скорости (70-120 для диапазона 0.7-1.2)
        speed_widget, speed_slider = self._create_slider_group(
            "Скорость голоса:",
            70, 120, self.default_speed,
            self._format_speed,
            self._on_speed_changed
        )
        
        speed_label = QLabel("Скорость голоса:")
        speed_label.setStyleSheet("color: #B8B8B8; font-size: 12px;")
        layout.addWidget(speed_label)
        layout.addWidget(speed_widget)

        # Кнопка сброса
        reset_layout = QHBoxLayout()
        reset_layout.addStretch()

        self.reset_button = QPushButton("↻ Сброс к умолчанию")
        self.reset_button.setObjectName("reset-voice-settings")
        self.reset_button.setToolTip("Восстановить значения по умолчанию")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        reset_layout.addWidget(self.reset_button)

        layout.addLayout(reset_layout)

        # Устанавливаем минимальную высоту
        self.setMinimumHeight(180)

    def _create_slider_group(self, label_text: str, min_val: int, max_val: int,
                             default_val: int, format_func: Callable,
                             change_callback: Callable) -> tuple:
        """
        Создание группы элементов для одного ползунка в точно таком же стиле как на фото вкладке

        Args:
            label_text: Текст метки
            min_val: Минимальное значение
            max_val: Максимальное значение
            default_val: Значение по умолчанию
            format_func: Функция форматирования значения для отображения
            change_callback: Callback для обработки изменений

        Returns:
            tuple: (widget, slider) - точно как на фото вкладке
        """
        from PySide6.QtWidgets import QWidget
        
        # Создаем виджет точно как на фото вкладке
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Ползунок
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default_val)
        slider.setObjectName("voice-setting-slider")
        
        # Принудительно применяем зеленые стили для всех частей слайдера
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
        
        # Метка значения
        value_label = QLabel(format_func(default_val))
        value_label.setMinimumWidth(50)
        
        # Подключаем обновление значения
        def update_value():
            value = slider.value()
            value_label.setText(format_func(value))
            change_callback(value)
        
        slider.valueChanged.connect(update_value)
        
        layout.addWidget(slider)
        layout.addWidget(value_label)

        # Сохраняем ссылки для доступа извне
        if "стабильность" in label_text.lower():
            self.stability_slider = slider
            self.stability_value_label = value_label
        elif "схожесть" in label_text.lower():
            self.similarity_slider = slider
            self.similarity_value_label = value_label
        elif "скорость" in label_text.lower():
            self.speed_slider = slider
            self.speed_value_label = value_label

        return widget, slider

    def _format_percentage(self, value: int) -> str:
        """Форматирование значения как процент"""
        return f"{value}%"

    def _format_speed(self, value: int) -> str:
        """Форматирование значения скорости"""
        speed_float = value / 100.0
        return f"{speed_float:.1f}x"

    def _on_stability_changed(self, value: int):
        """Обработка изменения стабильности"""
        self.current_stability = value
        stability_float = value / 100.0  # Конвертируем в 0.0-1.0
        self.stability_changed.emit(stability_float)
        logger.debug(f"Стабильность голоса изменена на {stability_float}")

    def _on_similarity_changed(self, value: int):
        """Обработка изменения схожести"""
        self.current_similarity = value
        similarity_float = value / 100.0  # Конвертируем в 0.0-1.0
        self.similarity_changed.emit(similarity_float)
        logger.debug(f"Схожесть голоса изменена на {similarity_float}")

    def _on_speed_changed(self, value: int):
        """Обработка изменения скорости"""
        self.current_speed = value
        speed_float = value / 100.0  # Конвертируем в 0.7-1.2 (70-120 -> 0.7-1.2)
        self.speed_changed.emit(speed_float)
        logger.debug(f"Скорость голоса изменена на {speed_float}")

    def reset_to_defaults(self):
        """Сброс всех значений к умолчанию"""
        try:
            logger.debug("Сброс настроек голоса к значениям по умолчанию")

            self.stability_slider.setValue(self.default_stability)
            self.similarity_slider.setValue(self.default_similarity)
            self.speed_slider.setValue(self.default_speed)

            logger.info("Настройки голоса сброшены к значениям по умолчанию")

        except Exception as e:
            logger.error(f"Ошибка при сбросе настроек: {e}")

    def get_current_settings(self) -> Dict[str, float]:
        """
        Получение текущих настроек голоса

        Returns:
            Dict[str, float]: Словарь с настройками в формате API
        """
        return {
            "stability": self.current_stability / 100.0,
            "similarity_boost": self.current_similarity / 100.0,
            "speed": self.current_speed / 100.0
        }

    def set_settings(self, stability: float = None, similarity: float = None, speed: float = None):
        """
        Установка настроек голоса программно

        Args:
            stability: Стабильность (0.0-1.0)
            similarity: Схожесть (0.0-1.0)
            speed: Скорость (0.7-1.2)
        """
        try:
            if stability is not None:
                stability_percent = max(0, min(100, int(stability * 100)))
                self.stability_slider.setValue(stability_percent)

            if similarity is not None:
                similarity_percent = max(0, min(100, int(similarity * 100)))
                self.similarity_slider.setValue(similarity_percent)

            if speed is not None:
                # Конвертируем диапазон 0.7-1.2 в 70-120
                speed_percent = max(70, min(120, int(speed * 100)))
                self.speed_slider.setValue(speed_percent)

            logger.debug(f"Настройки голоса установлены программно: stability={stability}, similarity={similarity}, speed={speed}")

        except Exception as e:
            logger.error(f"Ошибка установки настроек: {e}")

    def get_settings_for_config(self) -> Dict[str, str]:
        """
        Получение настроек в формате для сохранения в конфигурации

        Returns:
            Dict[str, str]: Настройки в строковом формате
        """
        settings = self.get_current_settings()
        return {
            "default_stability": str(settings["stability"]),
            "default_similarity": str(settings["similarity_boost"]),
            "default_voice_speed": str(settings["speed"])
        }

    def load_from_config(self, config: Dict[str, Any]):
        """
        Загрузка настроек из конфигурации

        Args:
            config: Словарь с настройками канала
        """
        try:
            # Загружаем стабильность
            if "default_stability" in config:
                stability = float(config["default_stability"])
                self.set_settings(stability=stability)

            # Загружаем схожесть
            if "default_similarity" in config:
                similarity = float(config["default_similarity"])
                self.set_settings(similarity=similarity)

            # Загружаем скорость
            if "default_voice_speed" in config:
                speed = float(config["default_voice_speed"])
                self.set_settings(speed=speed)

            logger.info("Настройки голоса загружены из конфигурации")

        except (ValueError, KeyError) as e:
            logger.warning(f"Ошибка загрузки настроек голоса из конфигурации: {e}")
            self.reset_to_defaults()