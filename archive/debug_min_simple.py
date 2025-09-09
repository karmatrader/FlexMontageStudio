#!/usr/bin/env python3
"""
Простой отладчик min() вызовов без рекурсии
"""
import logging
import traceback
import sys
from typing import Any, Iterable

# Настройка логирования
logger = logging.getLogger(__name__)

# Счетчики для статистики
call_count = 0
error_count = 0

def debug_min_call(iterable, default=None, key=None, context="unknown"):
    """
    Отладочная версия min() вызова
    
    Args:
        iterable: Итерируемый объект
        default: Значение по умолчанию
        key: Функция для сравнения
        context: Контекст вызова для отладки
        
    Returns:
        Минимальное значение
    """
    global call_count, error_count
    call_count += 1
    
    # Получаем информацию о вызове
    frame = sys._getframe(1)
    filename = frame.f_code.co_filename
    line_number = frame.f_lineno
    function_name = frame.f_code.co_name
    
    logger.debug(f"🔍 MIN #{call_count}: Вызов в {function_name} ({filename}:{line_number})")
    logger.debug(f"🔍 MIN #{call_count}: Контекст: {context}")
    
    # Конвертируем в список для анализа
    try:
        items = list(iterable)
    except Exception as e:
        error_count += 1
        logger.error(f"❌ MIN #{call_count}: Ошибка конвертации в список: {e}")
        raise
    
    # Проверяем на пустоту
    if not items:
        error_count += 1
        logger.error(f"❌ MIN #{call_count}: ПУСТАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ!")
        logger.error(f"❌ MIN #{call_count}: Файл: {filename}:{line_number}")
        logger.error(f"❌ MIN #{call_count}: Функция: {function_name}")
        logger.error(f"❌ MIN #{call_count}: Контекст: {context}")
        
        # Трассировка стека
        logger.error(f"❌ MIN #{call_count}: Стек вызовов:")
        for line in traceback.format_stack()[:-1]:  # Исключаем текущий кадр
            logger.error(f"❌ MIN #{call_count}: {line.strip()}")
        
        if default is not None:
            logger.warning(f"⚠️ MIN #{call_count}: Возвращаем default: {default}")
            return default
        
        raise ValueError(f"min() arg is an empty sequence at {filename}:{line_number} in {function_name}")
    
    # Показываем содержимое
    logger.debug(f"🔍 MIN #{call_count}: Длина: {len(items)}")
    if len(items) <= 5:
        logger.debug(f"🔍 MIN #{call_count}: Содержимое: {items}")
    else:
        logger.debug(f"🔍 MIN #{call_count}: Первые 3: {items[:3]}, последние 2: {items[-2:]}")
    
    # Вызываем встроенный min()
    try:
        # Используем полный путь к встроенной функции
        builtin_min = __builtins__['min'] if isinstance(__builtins__, dict) else __builtins__.min
        
        if key is not None:
            result = builtin_min(items, key=key)
        else:
            result = builtin_min(items)
        
        logger.debug(f"✅ MIN #{call_count}: Результат: {result}")
        return result
        
    except Exception as e:
        error_count += 1
        logger.error(f"❌ MIN #{call_count}: Ошибка в min(): {e}")
        raise

def get_min_stats():
    """Получить статистику min() вызовов"""
    return {
        'total_calls': call_count,
        'errors': error_count,
        'success_rate': ((call_count - error_count) / call_count * 100) if call_count > 0 else 0
    }

def log_min_stats():
    """Логировать статистику min() вызовов"""
    stats = get_min_stats()
    logger.info(f"📊 Статистика min() вызовов:")
    logger.info(f"   Всего вызовов: {stats['total_calls']}")
    logger.info(f"   Ошибок: {stats['errors']}")
    logger.info(f"   Успешность: {stats['success_rate']:.1f}%")

# Удобные функции для добавления в код
def safe_min_with_context(iterable, context="unknown", default=None, key=None):
    """Безопасный min() с контекстом"""
    return debug_min_call(iterable, default, key, context)

def safe_min_video_rows(video_rows, context="video_rows"):
    """Специальная функция для video_rows"""
    return debug_min_call(video_rows, context=context)

def safe_min_audio_files(audio_files, context="audio_files"):
    """Специальная функция для audio_files"""
    return debug_min_call(audio_files, context=context)

if __name__ == "__main__":
    # Тестирование
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    print("🔧 Тестирование простого отладчика min()")
    
    # Тест 1: Нормальный вызов
    try:
        result = debug_min_call([3, 1, 4, 1, 5], context="test_normal")
        print(f"✅ Нормальный: {result}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    # Тест 2: Пустая последовательность
    try:
        result = debug_min_call([], context="test_empty")
        print(f"✅ Пустая: {result}")
    except Exception as e:
        print(f"❌ Ожидаемая ошибка: {e}")
    
    # Тест 3: Пустая с default
    try:
        result = debug_min_call([], default=0, context="test_empty_default")
        print(f"✅ Пустая с default: {result}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    # Статистика
    log_min_stats()