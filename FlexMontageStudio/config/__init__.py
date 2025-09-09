# config/__init__.py
"""
Пакет конфигурации FlexMontage Studio
Обеспечивает обратную совместимость со старыми импортами
"""

# Импортируем из env_manager для обратной совместимости
from .env_manager import EnvironmentManager, SecurityManager

# Создаем глобальный экземпляр для обратной совместимости
_config_manager = None


def get_config_manager():
    """Получение глобального экземпляра менеджера конфигурации"""
    global _config_manager
    if _config_manager is None:
        from .env_manager import EnvironmentManager
        _config_manager = EnvironmentManager()
    return _config_manager


def get_channel_config(channel_name):
    """
    Обратная совместимость со старым API
    Загружает конфигурацию канала из channels.json с умным поиском
    """
    # Используем новый ConfigManager для правильного поиска файла
    from core.config_manager import ConfigManager
    
    try:
        config_manager = ConfigManager()
        return config_manager.get_channel_config(channel_name)
    except Exception as e:
        raise ValueError(f"Ошибка загрузки конфигурации канала {channel_name}: {e}")


def get_proxy_config():
    """
    Обратная совместимость со старым API
    Загружает конфигурацию прокси из channels.json с умным поиском
    """
    # Используем новый ConfigManager для правильного поиска файла
    from core.config_manager import ConfigManager
    
    try:
        config_manager = ConfigManager()
        config = config_manager.load_config()
        return config.get("proxy_config", {})
    except Exception:
        return {}


# Экспортируем основные функции для обратной совместимости
__all__ = [
    'get_channel_config',
    'get_proxy_config',
    'EnvironmentManager',
    'SecurityManager',
    'get_config_manager'
]