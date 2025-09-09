#!/usr/bin/env python3
"""
Добавляет debug логирование в main.py для отслеживания переходов
"""

from pathlib import Path

def add_debug():
    main_py = Path("main.py")
    
    if not main_py.exists():
        print("main.py не найден")
        return
    
    with open(main_py, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Ищем строку с условием переходов
    target_line = None
    for i, line in enumerate(lines):
        if "if effects_config and getattr(effects_config, 'transitions_enabled', False):" in line:
            target_line = i
            break
    
    if target_line is None:
        print("Не найдена строка с условием переходов")
        return
    
    # Добавляем debug логирование перед условием
    debug_lines = [
        '                logger.info("🔍 DEBUG TRANSITIONS: Проверка условий для переходов")\n',
        '                logger.info(f"   effects_config: {effects_config}")\n',
        '                if effects_config:\n',
        '                    logger.info(f"   transitions_enabled: {getattr(effects_config, \'transitions_enabled\', \'NOT_FOUND\')}")\n',
        '                    logger.info(f"   transition_type: {getattr(effects_config, \'transition_type\', \'NOT_FOUND\')}")\n',
        '                    logger.info(f"   transition_duration: {getattr(effects_config, \'transition_duration\', \'NOT_FOUND\')}")\n',
    ]
    
    # Проверяем, не добавлено ли уже логирование
    if "🔍 DEBUG TRANSITIONS:" in lines[max(0, target_line-10):target_line]:
        print("Debug логирование уже добавлено")
        return
    
    # Вставляем debug логирование
    lines = lines[:target_line] + debug_lines + lines[target_line:]
    
    # Сохраняем файл
    with open(main_py, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print("✅ Debug логирование добавлено")

if __name__ == "__main__":
    add_debug()