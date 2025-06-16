"""
Конфигурация системы логирования
"""
import logging
from typing import Dict, Any
from dataclasses import dataclass


@dataclass
class LoggingConfig:
    """Конфигурация системы логирования"""
    debug_video_processing: bool = False
    debug_audio_processing: bool = False
    debug_subtitles_processing: bool = False
    debug_final_assembly: bool = False

    @classmethod
    def from_dict(cls, debug_config: Dict[str, Any]) -> 'LoggingConfig':
        """Создание конфигурации из словаря"""
        return cls(
            debug_video_processing=debug_config.get("debug_video_processing", False),
            debug_audio_processing=debug_config.get("debug_audio_processing", False),
            debug_subtitles_processing=debug_config.get("debug_subtitles_processing", False),
            debug_final_assembly=debug_config.get("debug_final_assembly", False)
        )

    def setup_module_logging(self, module_name: str) -> logging.Logger:
        """Настройка логирования для конкретного модуля"""
        logger = logging.getLogger(module_name)
        debug_attr = f"debug_{module_name}"

        if hasattr(self, debug_attr) and getattr(self, debug_attr):
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)

        return logger

    def _should_module_debug(self, module_name: str) -> bool:
        """Проверка, нужна ли отладка для конкретного модуля"""
        # Извлекаем базовое имя модуля
        base_name = module_name.split('.')[-1]
        
        # Проверяем соответствие модуля настройкам отладки
        debug_mapping = {
            'video_processing': self.debug_video_processing,
            'video_processing_lite': self.debug_video_processing,
            'audio_processing': self.debug_audio_processing,
            'subtitles_processing': self.debug_subtitles_processing,
            'final_assembly': self.debug_final_assembly
        }
        
        return debug_mapping.get(base_name, False)

    def is_any_debug_enabled(self) -> bool:
        """Проверка, включена ли отладка хотя бы для одного модуля"""
        return any([
            self.debug_video_processing,
            self.debug_audio_processing,
            self.debug_subtitles_processing,
            self.debug_final_assembly
        ])

    def setup_global_logging(self) -> None:
        """Настройка глобального уровня логирования"""
        root_logger = logging.getLogger()
        
        if self.is_any_debug_enabled():
            root_logger.setLevel(logging.DEBUG)
        else:
            root_logger.setLevel(logging.INFO)
            
        # Также устанавливаем уровень для всех существующих логгеров
        for name in logging.Logger.manager.loggerDict:
            logger = logging.getLogger(name)
            if not self.is_any_debug_enabled():
                # При выключенной отладке устанавливаем INFO для всех логгеров
                logger.setLevel(logging.INFO)
            else:
                # При включенной отладке проверяем конкретные модули
                module_debug = self._should_module_debug(name)
                logger.setLevel(logging.DEBUG if module_debug else logging.INFO)

    def to_dict(self) -> Dict[str, bool]:
        """Преобразование в словарь"""
        return {
            "debug_video_processing": self.debug_video_processing,
            "debug_audio_processing": self.debug_audio_processing,
            "debug_subtitles_processing": self.debug_subtitles_processing,
            "debug_final_assembly": self.debug_final_assembly
        }