"""
Модуль для управления состоянием монтажа
Глобальные переменные для синхронизации между GUI и процессами монтажа
"""
import threading
import logging
import os

logger = logging.getLogger(__name__)

# ФАЙЛ-ФЛАГ для остановки (абсолютно надежный способ!)
STOP_FLAG_FILE = os.path.join(os.path.dirname(__file__), "STOP_MONTAGE_NOW.flag")

# Глобальный флаг остановки монтажа
_STOP_MONTAGE_FLAG = False
_lock = threading.Lock()

def set_stop_montage_flag():
    """Устанавливает флаг для остановки монтажа (потокобезопасно)"""
    global _STOP_MONTAGE_FLAG
    with _lock:
        _STOP_MONTAGE_FLAG = True
    
    # РАДИКАЛЬНО: Создаем физический файл-флаг
    try:
        with open(STOP_FLAG_FILE, 'w') as f:
            f.write("STOP_MONTAGE_REQUESTED")
        print("🛑🔥🔥 СОЗДАН ФАЙЛ-ФЛАГ ОСТАНОВКИ!!! 🔥🔥🛑")
        logger.error("🛑🔥🔥 СОЗДАН ФАЙЛ-ФЛАГ ОСТАНОВКИ!!! 🔥🔥🛑")
    except Exception as e:
        logger.error(f"Ошибка создания файла-флага: {e}")
        
    print("🛑🛑🛑 STOP_MONTAGE_FLAG УСТАНОВЛЕН!!! 🛑🛑🛑")
    logger.error("🛑🛑🛑 STOP_MONTAGE_FLAG УСТАНОВЛЕН!!! 🛑🛑🛑")

def reset_stop_montage_flag():
    """Сбрасывает флаг остановки монтажа (потокобезопасно)"""
    global _STOP_MONTAGE_FLAG
    with _lock:
        _STOP_MONTAGE_FLAG = False
        
    # Удаляем физический файл-флаг
    try:
        if os.path.exists(STOP_FLAG_FILE):
            os.remove(STOP_FLAG_FILE)
        logger.info("🔄 Файл-флаг удален")
    except Exception as e:
        logger.error(f"Ошибка удаления файла-флага: {e}")
        
    logger.info("🔄 Флаг остановки монтажа сброшен")

def is_stop_montage_requested():
    """Проверяет, установлен ли флаг остановки монтажа (потокобезопасно)"""
    # ДВОЙНАЯ ПРОВЕРКА: память И файл!
    file_exists = os.path.exists(STOP_FLAG_FILE)
    global _STOP_MONTAGE_FLAG
    with _lock:
        memory_flag = _STOP_MONTAGE_FLAG
    
    # Если хотя бы один флаг установлен - СТОП!
    return memory_flag or file_exists

def check_stop_flag(context_name=""):
    """Проверяет флаг остановки и выводит отладочную информацию если установлен"""
    if is_stop_montage_requested():
        msg = f"🛑🔥 ОСТАНОВКА МОНТАЖА: флаг установлен в {context_name}"
        print(msg)
        logger.error(msg)  # Используем ERROR уровень для видимости
        return True
    return False