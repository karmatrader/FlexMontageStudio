#!/usr/bin/env python3
"""
Модуль для отладки всех min() вызовов в проекте
Добавляет глобальную обработку и детальное логирование
"""

import logging
import traceback
import sys
from typing import Any, Iterable

# Настройка логирования
logger = logging.getLogger(__name__)

class MinCallDebugger:
    """Класс для отладки min() вызовов"""
    
    def __init__(self):
        self.call_count = 0
        self.error_count = 0
        
    def safe_min(self, iterable: Iterable[Any], default=None, key=None, original_min=None) -> Any:
        """
        Безопасная версия min() с детальным логированием
        
        Args:
            iterable: Итерируемый объект
            default: Значение по умолчанию если пустой
            key: Функция для сравнения
            
        Returns:
            Минимальное значение или default
        """
        self.call_count += 1
        
        # Получаем информацию о вызове
        frame = sys._getframe(1)
        filename = frame.f_code.co_filename
        line_number = frame.f_lineno
        function_name = frame.f_code.co_name
        
        # Конвертируем в список для анализа
        try:
            items = list(iterable)
        except Exception as e:
            logger.error(f"DEBUG MIN #{self.call_count}: Ошибка конвертации в список: {e}")
            logger.error(f"DEBUG MIN #{self.call_count}: Файл: {filename}:{line_number}")
            logger.error(f"DEBUG MIN #{self.call_count}: Функция: {function_name}")
            self.error_count += 1
            if default is not None:
                return default
            raise
        
        # Детальное логирование
        logger.debug(f"DEBUG MIN #{self.call_count}: Вызов min() в {function_name}")
        logger.debug(f"DEBUG MIN #{self.call_count}: Файл: {filename}:{line_number}")
        logger.debug(f"DEBUG MIN #{self.call_count}: Тип: {type(items)}")
        logger.debug(f"DEBUG MIN #{self.call_count}: Длина: {len(items)}")
        
        if len(items) == 0:
            self.error_count += 1
            logger.error(f"DEBUG MIN #{self.call_count}: ❌ ПУСТАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ!")
            logger.error(f"DEBUG MIN #{self.call_count}: Файл: {filename}:{line_number}")
            logger.error(f"DEBUG MIN #{self.call_count}: Функция: {function_name}")
            
            # Трассировка стека
            logger.error(f"DEBUG MIN #{self.call_count}: Стек вызовов:")
            for line in traceback.format_stack():
                logger.error(f"DEBUG MIN #{self.call_count}: {line.strip()}")
            
            if default is not None:
                logger.warning(f"DEBUG MIN #{self.call_count}: Возвращаем default: {default}")
                return default
            
            raise ValueError(f"min() arg is an empty sequence at {filename}:{line_number} in {function_name}")
        
        # Показываем содержимое если не слишком длинное
        if len(items) <= 10:
            logger.debug(f"DEBUG MIN #{self.call_count}: Содержимое: {items}")
        else:
            logger.debug(f"DEBUG MIN #{self.call_count}: Первые 5 элементов: {items[:5]}")
            logger.debug(f"DEBUG MIN #{self.call_count}: Последние 5 элементов: {items[-5:]}")
        
        # Вызываем оригинальный min()
        try:
            if original_min is None:
                # Fallback на встроенную функцию если original_min не передан
                import builtins
                original_min = builtins.__dict__.get('__min__', min)
            
            if key is not None:
                result = original_min(items, key=key)
            else:
                result = original_min(items)
            
            logger.debug(f"DEBUG MIN #{self.call_count}: ✅ Результат: {result}")
            return result
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"DEBUG MIN #{self.call_count}: ❌ Ошибка в min(): {e}")
            logger.error(f"DEBUG MIN #{self.call_count}: Файл: {filename}:{line_number}")
            logger.error(f"DEBUG MIN #{self.call_count}: Функция: {function_name}")
            
            if default is not None:
                return default
            raise
    
    def get_stats(self) -> dict:
        """Получить статистику вызовов"""
        return {
            'total_calls': self.call_count,
            'errors': self.error_count,
            'success_rate': (self.call_count - self.error_count) / self.call_count * 100 if self.call_count > 0 else 0
        }

# Глобальный экземпляр отладчика
min_debugger = MinCallDebugger()

def debug_min(iterable, default=None, key=None):
    """
    Отладочная версия min() функции
    
    Args:
        iterable: Итерируемый объект
        default: Значение по умолчанию
        key: Функция для сравнения
        
    Returns:
        Минимальное значение
    """
    return min_debugger.safe_min(iterable, default, key)

def patch_min_calls():
    """
    Заменяет все min() вызовы на отладочную версию
    ВНИМАНИЕ: Это глобальная замена, используйте осторожно!
    """
    import builtins
    
    # Сохраняем оригинальную функцию
    original_min = builtins.min
    
    def debug_min_wrapper(*args, **kwargs):
        if len(args) == 1:
            # min(iterable)
            return min_debugger.safe_min(args[0], kwargs.get('default'), kwargs.get('key'), original_min)
        else:
            # min(a, b, c, ...)
            return min_debugger.safe_min(args, kwargs.get('default'), kwargs.get('key'), original_min)
    
    # Заменяем глобальную функцию
    builtins.min = debug_min_wrapper
    
    logger.info("🔧 min() функция заменена на отладочную версию")
    return original_min

def restore_min(original_min):
    """Восстанавливает оригинальную min() функцию"""
    import builtins
    builtins.min = original_min
    logger.info("🔄 min() функция восстановлена")

def log_min_stats():
    """Логирует статистику вызовов min()"""
    stats = min_debugger.get_stats()
    logger.info(f"📊 Статистика min() вызовов:")
    logger.info(f"   Всего вызовов: {stats['total_calls']}")
    logger.info(f"   Ошибок: {stats['errors']}")
    logger.info(f"   Успешность: {stats['success_rate']:.2f}%")

if __name__ == "__main__":
    # Пример использования
    print("🔧 Тестирование отладки min() вызовов")
    
    # Настройка логирования
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Тест 1: Нормальный вызов
    print("\n✅ Тест 1: Нормальный вызов")
    result1 = debug_min([3, 1, 4, 1, 5])
    print(f"Результат: {result1}")
    
    # Тест 2: Пустая последовательность с default
    print("\n✅ Тест 2: Пустая последовательность с default")
    result2 = debug_min([], default=0)
    print(f"Результат: {result2}")
    
    # Тест 3: Пустая последовательность без default (должна вызвать ошибку)
    print("\n❌ Тест 3: Пустая последовательность без default")
    try:
        result3 = debug_min([])
        print(f"Результат: {result3}")
    except ValueError as e:
        print(f"Ожидаемая ошибка: {e}")
    
    # Статистика
    print("\n📊 Статистика:")
    log_min_stats()