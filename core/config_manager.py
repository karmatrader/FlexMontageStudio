"""
Менеджер конфигурации каналов с File API
"""
import json
import ast
import logging
import sys
from typing import Dict, List, Optional, Any
from pathlib import Path
from utils.app_paths import get_config_file_path
from core.file_api import file_api

logger = logging.getLogger(__name__)


class ConfigValidator:
    """Валидатор конфигурации"""

    @staticmethod
    def validate_integer_field(value: str, field_name: str) -> int:
        """Валидация целочисленного поля"""
        if not value or value.strip() == "":
            return 0  # Значение по умолчанию для пустых строк
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Некорректное значение для {field_name}: должно быть целым числом")

    @staticmethod
    def validate_float_field(value: str, field_name: str) -> float:
        """Валидация поля с плавающей точкой"""
        if not value or value.strip() == "":
            return 0.0  # Значение по умолчанию для пустых строк
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Некорректное значение для {field_name}: должно быть числом")

    @staticmethod
    def validate_list_field(value: str, field_name: str) -> List[int]:
        """Валидация списка с использованием ast.literal_eval вместо eval"""
        if not value.strip():
            return [1920, 1080]  # Значение по умолчанию

        try:
            result = ast.literal_eval(value)
            if not isinstance(result, list) or len(result) != 2:
                raise ValueError
            return result
        except (ValueError, SyntaxError):
            raise ValueError(f"Некорректное значение для {field_name}: должно быть списком [x, y]")

    @staticmethod
    def validate_channel_column(value: str) -> str:
        """Валидация столбца канала"""
        value = value.upper()
        if not value or not value.isalpha() or ord(value) < ord('B'):
            raise ValueError("Столбец канала должен быть буквой B или выше!")
        return value

    @staticmethod
    def validate_preserve_audio_videos(value: str) -> List[int]:
        """Валидация списка номеров видео для сохранения аудио"""
        if not value.strip():
            return []

        try:
            return [int(num.strip()) for num in value.split(",") if num.strip()]
        except ValueError:
            raise ValueError("Некорректный формат номеров видео. Используйте формат '3,5'.")


class ConfigManager:
    """Менеджер конфигурации каналов"""

    def __init__(self, config_path: str = "channels.json"):
        # Определяем правильный путь к channels.json в зависимости от режима запуска
        if not Path(config_path).is_absolute():
            config_path = self._find_config_file(config_path)
        
        self.config_path = Path(config_path)
        self._config_cache = None
        self.validator = ConfigValidator()

    def _find_config_file(self, filename: str) -> str:
        """Поиск файла конфигурации используя общую утилиту"""
        return str(get_config_file_path(filename))

    def load_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации через File API с автоматическим кешированием"""
        if self._config_cache is None:
            try:
                # File API автоматически кэширует и проверяет изменения файла
                self._config_cache = file_api.read_json(self.config_path, default={})
                logger.info(f"Конфигурация загружена через File API из {self.config_path}")
            except FileNotFoundError:
                logger.error(f"Файл {self.config_path} не найден!")
                raise FileNotFoundError(f"Файл {self.config_path} не найден!")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Ошибка парсинга {self.config_path}: {e}")
                raise ValueError(f"Ошибка парсинга {self.config_path}: {e}")
        return self._config_cache

    def save_config(self, config: Dict[str, Any]) -> None:
        """Сохранение конфигурации через File API"""
        try:
            # File API автоматически создает backup и инвалидирует кэш
            success = file_api.write_json(self.config_path, config, backup=True)
            
            if success:
                self._config_cache = config
                logger.debug(f"Конфигурация сохранена через File API в {self.config_path}")
            else:
                raise IOError("Не удалось сохранить конфигурацию через File API")

        except Exception as e:
            logger.error(f"Не удалось сохранить конфигурацию: {e}")
            raise IOError(f"Не удалось сохранить конфигурацию: {e}")

    def get_channel_config(self, channel_name: str) -> Dict[str, Any]:
        """Получение конфигурации канала"""
        import unicodedata
        
        config = self.load_config()
        
        # Нормализуем название канала для поиска
        normalized_channel_name = unicodedata.normalize('NFC', channel_name)
        
        # Сначала пробуем точное совпадение
        if channel_name in config["channels"]:
            channel_config = config["channels"][channel_name]
        # Затем пробуем нормализованное название
        elif normalized_channel_name in config["channels"]:
            channel_config = config["channels"][normalized_channel_name]
        else:
            # Ищем среди нормализованных ключей
            channel_config = {}
            for key in config["channels"]:
                normalized_key = unicodedata.normalize('NFC', key)
                if normalized_key == normalized_channel_name or normalized_key == channel_name:
                    channel_config = config["channels"][key]
                    logger.info(f"🔄 Найден канал через нормализацию Unicode: '{key}' -> '{channel_name}'")
                    break
            
            if not channel_config:
                logger.warning(f"⚠️ Канал '{channel_name}' не найден в конфигурации")
                logger.debug(f"Доступные каналы: {list(config['channels'].keys())}")
        
        logger.debug(f"Загружена конфигурация канала {channel_name}")
        return channel_config

    def get_proxy_config(self) -> Dict[str, Any]:
        """Получение конфигурации прокси"""
        config = self.load_config()
        return config.get("proxy_config", {})

    def get_all_channels(self) -> List[str]:
        """Получение списка всех каналов"""
        config = self.load_config()
        return list(config.get("channels", {}).keys())

    def channel_exists(self, channel_name: str) -> bool:
        """Проверка существования канала"""
        config = self.load_config()
        return channel_name in config.get("channels", {})

    def add_channel(self, channel_name: str, channel_config: Dict[str, Any]) -> None:
        """Добавление нового канала"""
        if self.channel_exists(channel_name):
            raise ValueError(f"Канал '{channel_name}' уже существует!")

        config = self.load_config()
        config["channels"][channel_name] = channel_config
        self.save_config(config)
        logger.info(f"Канал '{channel_name}' добавлен")

    def delete_channel(self, channel_name: str) -> None:
        """Удаление канала"""
        if not self.channel_exists(channel_name):
            raise ValueError(f"Канал '{channel_name}' не найден!")

        config = self.load_config()
        del config["channels"][channel_name]
        self.save_config(config)
        logger.info(f"Канал '{channel_name}' удален")

    def update_channel_config(self, channel_name: str, channel_config: Dict[str, Any]) -> None:
        """Обновление конфигурации канала"""
        if not self.channel_exists(channel_name):
            raise ValueError(f"Канал '{channel_name}' не найден!")

        config = self.load_config()
        
        # Защита от перезаписи полей позиций логотипов пустыми значениями
        existing_config = config["channels"][channel_name]
        position_fields = ["logo_position_x", "logo_position_y", "logo2_position_x", 
                          "logo2_position_y", "subscribe_position_x", "subscribe_position_y"]
        
        for field in position_fields:
            # Если новое значение пустое, а старое есть - сохраняем старое
            if field in existing_config and (field not in channel_config or not channel_config.get(field, "").strip()):
                channel_config[field] = existing_config[field]
                logger.debug(f"Сохранено существующее значение {field}: {existing_config[field]}")
        
        config["channels"][channel_name] = channel_config
        self.save_config(config)
        logger.debug(f"Конфигурация канала '{channel_name}' обновлена")

    def update_proxy_config(self, proxy_config: Dict[str, Any]) -> None:
        """Обновление конфигурации прокси"""
        config = self.load_config()
        config["proxy_config"] = proxy_config
        self.save_config(config)
        logger.debug("Конфигурация прокси обновлена")

    def validate_and_convert_config(self, raw_config: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация и конвертация конфигурации"""
        config = {}

        # Валидация целочисленных полей
        int_fields = [
            "num_videos", "audio_sample_rate", "audio_channels", "frame_rate", "video_crf",
            "logo_width", "logo2_width", "subscribe_width", "subscribe_display_duration",
            "subscribe_interval_gap", "subtitle_fontsize", "subtitle_outline_thickness",
            "subtitle_shadow_thickness", "subtitle_shadow_alpha", "subtitle_shadow_offset_x",
            "subtitle_shadow_offset_y", "subtitle_margin_v", "subtitle_margin_l",
            "subtitle_margin_r", "subtitle_max_words", "max_retries", "ban_retry_delay",
            # Новые целочисленные параметры эффектов
            "bokeh_transition_smoothness", "brightness_delta"
        ]

        for field in int_fields:
            if field in raw_config:
                config[field] = self.validator.validate_integer_field(str(raw_config[field]), field)

        # Валидация полей с плавающей точкой
        float_fields = [
            "default_stability", "default_similarity", "default_voice_speed",
            "background_music_volume", "subtitle_time_offset",
            # Новые параметры эффектов OpenCV
            "bokeh_intensity", "sharpen_strength", "contrast_factor", 
            "saturation_factor", "vignette_strength"
        ]

        for field in float_fields:
            if field in raw_config:
                config[field] = self.validator.validate_float_field(str(raw_config[field]), field)

        # Валидация списков
        list_fields = ["bokeh_image_size", "bokeh_blur_kernel"]
        for field in list_fields:
            if field in raw_config:
                config[field] = self.validator.validate_list_field(str(raw_config[field]), field)

        # Валидация столбца канала
        if "channel_column" in raw_config:
            config["channel_column"] = self.validator.validate_channel_column(str(raw_config["channel_column"]))

        # Копирование остальных полей
        for key, value in raw_config.items():
            if key not in config:
                config[key] = value

        return config

    def get_default_channel_config(self) -> Dict[str, Any]:
        """Получение конфигурации канала по умолчанию"""
        return {
            "num_videos": 10,
            "default_lang": "RU",
            "default_stability": 1.0,
            "default_similarity": 1.0,
            "default_voice_speed": 1.0,
            "default_voice_style": None,
            "standard_voice_id": "AB9XsbSA4eLG12t2myjN",
            "use_library_voice": True,
            "original_voice_id": "AB9XsbSA4eLG12t2myjN",
            "public_owner_id": "d0fd99854e7517a8890c2f536b4fb89a9408d2dfa8cd7c7be15e4692e72a2a57",
            "max_retries": 10,
            "ban_retry_delay": 120,
            "photo_folder_fallback": "error",
            "audio_bitrate": "192k",
            "audio_sample_rate": 44100,
            "audio_channels": 1,
            "silence_duration": "1.0-2.5",
            "background_music_volume": 0.3,
            "preserve_video_duration": True,
            "preserve_clip_audio": False,
            "adjust_videos_to_audio": True,
            "video_resolution": "1920:1080",
            "frame_rate": 30,
            "video_crf": 23,
            "video_preset": "fast",
            "photo_order": "order",
            "bokeh_enabled": True,
            "bokeh_image_size": [1920, 1080],
            "bokeh_blur_kernel": [99, 99],
            "bokeh_blur_sigma": 30,
            # Новые параметры эффекта боке
            "bokeh_blur_method": "gaussian",
            "bokeh_intensity": 0.8,
            "bokeh_focus_area": "center",
            "bokeh_transition_smoothness": 50,
            "bokeh_sides_enabled": False,  # Боке по бокам для вертикальных фото
            # Дополнительные эффекты изображений
            "sharpen_enabled": False,
            "sharpen_strength": 1.5,
            "contrast_enabled": False,
            "contrast_factor": 1.2,
            "brightness_enabled": False,
            "brightness_delta": 10,
            "saturation_enabled": False,
            "saturation_factor": 1.1,
            "vignette_enabled": False,
            "vignette_strength": 0.3,
            "edge_enhancement": False,
            "noise_reduction": False,
            # Цветовая коррекция
            "histogram_equalization": False,
            # Фильтры стиля
            "style_filter": "none",
            "logo_width": 200,
            "logo_position_x": "W-w-20",
            "logo_position_y": "20",
            "logo_duration": "all",
            "logo2_width": 150,
            "logo2_position_x": "20",
            "logo2_position_y": "20",
            "logo2_duration": "all",
            "subscribe_width": 1400,
            "subscribe_position_x": "-50",
            "subscribe_position_y": "main_h-overlay_h+150",
            "subscribe_display_duration": 7,
            "subscribe_interval_gap": 30,
            "subscribe_duration": "all",
            "subtitles_enabled": True,
            "subtitle_language": "ru",
            "subtitle_model": "medium",
            "subtitle_fontsize": 110,
            "subtitle_font_color": "&HFFFFFF",
            "subtitle_use_backdrop": False,
            "subtitle_back_color": "&HFFFFFF",
            "subtitle_outline_thickness": 4,
            "subtitle_outline_color": "&H000000",
            "subtitle_shadow_thickness": 1,
            "subtitle_shadow_color": "&H333333",
            "subtitle_shadow_alpha": 50,
            "subtitle_shadow_offset_x": 2,
            "subtitle_shadow_offset_y": 2,
            "subtitle_margin_v": 20,
            "subtitle_margin_l": 10,
            "subtitle_margin_r": 10,
            "subtitle_max_words": 3,
            "subtitle_time_offset": -0.3,
            # Эффекты видео
            "video_effects_enabled": False,
            "video_zoom_effect": "none",
            "video_zoom_intensity": 1.1,
            "video_rotation_effect": "none", 
            "video_rotation_angle": 5.0,
            "video_color_effect": "none",
            "video_filter_effect": "none",
            # Переходы между клипами
            "video_transitions_enabled": False,
            "transition_type": "fade",
            "transition_duration": 0.5,
            "auto_zoom_alternation": True
        }

    def clear_cache(self) -> None:
        """Очистка кэша конфигурации"""
        self._config_cache = None
        logger.info("Кэш конфигурации очищен")


# Функции для обратной совместимости с voice_proxy_OG.py
_config_manager = ConfigManager()


def get_channel_config(channel_name: str) -> Dict[str, Any]:
    """Получение конфигурации канала для обратной совместимости"""
    return _config_manager.get_channel_config(channel_name)


def get_proxy_config() -> Dict[str, Any]:
    """Получение конфигурации прокси для обратной совместимости"""
    return _config_manager.get_proxy_config()