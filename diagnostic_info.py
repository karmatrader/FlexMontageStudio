#!/usr/bin/env python3
"""
Диагностическая информация для отладки проблем с путями в скомпилированном приложении
"""
import sys
import os
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def get_all_environment_variables() -> Dict[str, str]:
    """Получение всех переменных окружения, которые могут быть полезны для отладки"""
    relevant_vars = {}
    for key, value in os.environ.items():
        if any(keyword in key.upper() for keyword in [
            'RESOURCE', 'BUNDLE', 'APP', 'PATH', 'HOME', 'USER', 'TMPDIR',
            'NUITKA', 'PYTHON', 'QT', 'MACOS', 'EXECUTABLE'
        ]):
            relevant_vars[key] = value
    return relevant_vars


def analyze_sys_executable_path() -> Dict[str, Any]:
    """Детальный анализ sys.executable для понимания структуры Nuitka"""
    executable_path = Path(sys.executable)
    
    analysis = {
        'raw_path': str(executable_path),
        'absolute_path': str(executable_path.absolute()),
        'resolved_path': str(executable_path.resolve()),
        'exists': executable_path.exists(),
        'is_file': executable_path.is_file(),
        'is_symlink': executable_path.is_symlink(),
        'parent': str(executable_path.parent),
        'name': executable_path.name,
        'suffix': executable_path.suffix,
        'parts': list(executable_path.parts),
        'path_depth': len(executable_path.parts)
    }
    
    # Анализируем структуру директорий
    current = executable_path
    path_structure = []
    for i in range(10):  # Максимум 10 уровней вверх
        if current.parent == current:
            break
        path_structure.append({
            'level': i,
            'path': str(current),
            'name': current.name,
            'suffix': current.suffix,
            'is_app_bundle': current.suffix == '.app',
            'contents': []
        })
        
        # Пытаемся получить содержимое директории
        try:
            if current.is_dir():
                contents = [item.name for item in current.iterdir()][:20]  # Первые 20 элементов
                path_structure[-1]['contents'] = contents
        except (PermissionError, OSError):
            path_structure[-1]['contents'] = ['<access_denied>']
        
        current = current.parent
    
    analysis['path_structure'] = path_structure
    return analysis


def analyze_working_directory() -> Dict[str, Any]:
    """Анализ текущей рабочей директории"""
    cwd = Path.cwd()
    
    analysis = {
        'cwd_path': str(cwd),
        'cwd_absolute': str(cwd.absolute()),
        'cwd_resolved': str(cwd.resolve()),
        'cwd_exists': cwd.exists(),
        'cwd_contents': []
    }
    
    # Получаем содержимое текущей директории
    try:
        contents = [item.name for item in cwd.iterdir()][:50]  # Первые 50 элементов
        analysis['cwd_contents'] = contents
    except (PermissionError, OSError) as e:
        analysis['cwd_contents'] = [f'<error: {e}>']
    
    return analysis


def detect_app_bundle_locations() -> List[Dict[str, Any]]:
    """Поиск возможных местоположений .app bundle"""
    candidates = []
    
    # 1. Анализ sys.executable
    executable_path = Path(sys.executable)
    current = executable_path
    while current.parent != current:
        if current.suffix == '.app':
            candidates.append({
                'method': 'sys.executable_traversal',
                'app_bundle': str(current),
                'app_directory': str(current.parent),
                'distance_from_executable': len(executable_path.parts) - len(current.parts)
            })
        current = current.parent
    
    # 2. Анализ переменных окружения
    env_vars = get_all_environment_variables()
    for key, value in env_vars.items():
        if '.app' in value:
            path = Path(value)
            if path.exists() and path.suffix == '.app':
                candidates.append({
                    'method': f'environment_variable_{key}',
                    'app_bundle': str(path),
                    'app_directory': str(path.parent),
                    'env_var': key,
                    'env_value': value
                })
    
    # 3. Анализ текущей рабочей директории
    cwd = Path.cwd()
    current = cwd
    while current.parent != current:
        if current.suffix == '.app':
            candidates.append({
                'method': 'cwd_traversal',
                'app_bundle': str(current),
                'app_directory': str(current.parent),
                'distance_from_cwd': len(cwd.parts) - len(current.parts)
            })
        current = current.parent
    
    # 4. Поиск в стандартных местах macOS
    standard_locations = [
        Path.home() / 'Desktop',
        Path.home() / 'Downloads',
        Path.home() / 'Applications',
        Path('/Applications')
    ]
    
    for location in standard_locations:
        if location.exists():
            try:
                for item in location.iterdir():
                    if item.suffix == '.app' and 'FlexMontage' in item.name:
                        candidates.append({
                            'method': f'standard_location_{location.name}',
                            'app_bundle': str(item),
                            'app_directory': str(item.parent),
                            'search_location': str(location)
                        })
            except (PermissionError, OSError):
                pass
    
    return candidates


def test_config_file_access(app_directory: Path) -> Dict[str, Any]:
    """Тестирование доступа к конфигурационным файлам в указанной директории"""
    config_files = ['channels.json', 'licenses.json', 'styles.qss']
    
    results = {
        'directory': str(app_directory),
        'directory_exists': app_directory.exists(),
        'directory_writable': False,
        'files': {}
    }
    
    # Проверяем права на запись в директорию
    try:
        test_file = app_directory / '.test_write_access'
        test_file.touch()
        test_file.unlink()
        results['directory_writable'] = True
    except (PermissionError, OSError, FileNotFoundError):
        results['directory_writable'] = False
    
    # Проверяем каждый конфигурационный файл
    for filename in config_files:
        file_path = app_directory / filename
        file_result = {
            'path': str(file_path),
            'exists': file_path.exists(),
            'readable': False,
            'writable': False,
            'size': None
        }
        
        if file_path.exists():
            try:
                # Тест чтения
                with open(file_path, 'r', encoding='utf-8') as f:
                    f.read(100)  # Читаем первые 100 символов
                file_result['readable'] = True
                file_result['size'] = file_path.stat().st_size
            except (PermissionError, OSError, UnicodeDecodeError):
                pass
            
            try:
                # Тест записи (открываем в режиме добавления чтобы не повредить файл)
                with open(file_path, 'a', encoding='utf-8') as f:
                    pass
                file_result['writable'] = True
            except (PermissionError, OSError):
                pass
        
        results['files'][filename] = file_result
    
    return results


def log_diagnostic_info():
    """Записывает полную диагностическую информацию в лог и отдельный файл"""
    logger.info("=== ДИАГНОСТИЧЕСКАЯ ИНФОРМАЦИЯ ===")
    
    # Базовая информация о системе
    logger.info(f"🖥️  Платформа: {sys.platform}")
    logger.info(f"🐍 Python версия: {sys.version}")
    logger.info(f"❄️  Frozen (компиляция): {getattr(sys, 'frozen', False)}")
    logger.info(f"📁 Текущая директория: {os.getcwd()}")
    
    # Анализ sys.executable
    logger.info("\n=== АНАЛИЗ SYS.EXECUTABLE ===")
    executable_analysis = analyze_sys_executable_path()
    for key, value in executable_analysis.items():
        if key != 'path_structure':
            logger.info(f"{key}: {value}")
    
    logger.info("\n=== СТРУКТУРА ПУТЕЙ ===")
    for level_info in executable_analysis['path_structure']:
        level = level_info['level']
        path = level_info['path']
        name = level_info['name']
        suffix = level_info['suffix']
        is_app = level_info['is_app_bundle']
        contents = level_info['contents'][:5]  # Первые 5 элементов для лога
        
        logger.info(f"Уровень {level}: {name} {suffix} {'[APP BUNDLE]' if is_app else ''}")
        logger.info(f"  Путь: {path}")
        logger.info(f"  Содержимое: {contents}")
    
    # Анализ рабочей директории
    logger.info("\n=== АНАЛИЗ РАБОЧЕЙ ДИРЕКТОРИИ ===")
    cwd_analysis = analyze_working_directory()
    for key, value in cwd_analysis.items():
        if key != 'cwd_contents':
            logger.info(f"{key}: {value}")
    logger.info(f"Содержимое CWD: {cwd_analysis['cwd_contents'][:10]}")  # Первые 10 элементов
    
    # Переменные окружения
    logger.info("\n=== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ===")
    env_vars = get_all_environment_variables()
    for key, value in env_vars.items():
        logger.info(f"{key} = {value}")
    
    # Поиск .app bundle
    logger.info("\n=== ПОИСК .APP BUNDLE ===")
    app_candidates = detect_app_bundle_locations()
    if app_candidates:
        for i, candidate in enumerate(app_candidates):
            logger.info(f"Кандидат {i+1} ({candidate['method']}):")
            logger.info(f"  .app bundle: {candidate['app_bundle']}")
            logger.info(f"  Директория приложения: {candidate['app_directory']}")
            if 'distance_from_executable' in candidate:
                logger.info(f"  Расстояние от executable: {candidate['distance_from_executable']} уровней")
    else:
        logger.warning("❌ Не найдено кандидатов для .app bundle")
    
    # Тестирование доступа к файлам
    logger.info("\n=== ТЕСТИРОВАНИЕ ДОСТУПА К КОНФИГУРАЦИОННЫМ ФАЙЛАМ ===")
    
    # Текущая логика приложения
    try:
        from utils.app_paths import get_app_directory
        current_app_dir = get_app_directory()
        logger.info(f"Текущая логика get_app_directory(): {current_app_dir}")
        
        current_access = test_config_file_access(current_app_dir)
        logger.info("Результат текущей логики:")
        logger.info(f"  Директория существует: {current_access['directory_exists']}")
        logger.info(f"  Директория доступна для записи: {current_access['directory_writable']}")
        for filename, file_info in current_access['files'].items():
            logger.info(f"  {filename}: существует={file_info['exists']}, читается={file_info['readable']}, записывается={file_info['writable']}")
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании текущей логики: {e}")
    
    # Тестирование кандидатов
    for i, candidate in enumerate(app_candidates[:3]):  # Тестируем только первые 3 кандидата
        app_dir = Path(candidate['app_directory'])
        logger.info(f"\nТестирование кандидата {i+1} ({candidate['method']}):")
        access_result = test_config_file_access(app_dir)
        logger.info(f"  Директория существует: {access_result['directory_exists']}")
        logger.info(f"  Директория доступна для записи: {access_result['directory_writable']}")
        for filename, file_info in access_result['files'].items():
            logger.info(f"  {filename}: существует={file_info['exists']}, читается={file_info['readable']}")
    
    # Создание отдельного файла диагностики
    try:
        # Определяем где создать файл диагностики
        if app_candidates:
            diagnostic_dir = Path(app_candidates[0]['app_directory'])
        else:
            diagnostic_dir = Path.cwd()
        
        diagnostic_file = diagnostic_dir / 'diagnostic_info.txt'
        
        with open(diagnostic_file, 'w', encoding='utf-8') as f:
            f.write("ДИАГНОСТИЧЕСКАЯ ИНФОРМАЦИЯ FlexMontage Studio\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"Платформа: {sys.platform}\n")
            f.write(f"Python версия: {sys.version}\n")
            f.write(f"Frozen (компиляция): {getattr(sys, 'frozen', False)}\n")
            f.write(f"Текущая директория: {os.getcwd()}\n\n")
            
            f.write("SYS.EXECUTABLE АНАЛИЗ:\n")
            f.write("-" * 30 + "\n")
            for key, value in executable_analysis.items():
                if key != 'path_structure':
                    f.write(f"{key}: {value}\n")
            
            f.write("\nСТРУКТУРА ПУТЕЙ:\n")
            f.write("-" * 30 + "\n")
            for level_info in executable_analysis['path_structure']:
                level = level_info['level']
                path = level_info['path']
                name = level_info['name']
                suffix = level_info['suffix']
                is_app = level_info['is_app_bundle']
                contents = level_info['contents']
                
                f.write(f"Уровень {level}: {name} {suffix} {'[APP BUNDLE]' if is_app else ''}\n")
                f.write(f"  Путь: {path}\n")
                f.write(f"  Содержимое: {contents}\n")
            
            f.write("\nПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:\n")
            f.write("-" * 30 + "\n")
            for key, value in env_vars.items():
                f.write(f"{key} = {value}\n")
            
            f.write("\nКАНДИДАТЫ .APP BUNDLE:\n")
            f.write("-" * 30 + "\n")
            for i, candidate in enumerate(app_candidates):
                f.write(f"Кандидат {i+1} ({candidate['method']}):\n")
                for key, value in candidate.items():
                    f.write(f"  {key}: {value}\n")
                f.write("\n")
        
        logger.info(f"✅ Диагностическая информация сохранена в: {diagnostic_file}")
        
    except Exception as e:
        logger.error(f"❌ Не удалось создать файл диагностики: {e}")
    
    logger.info("=== ДИАГНОСТИКА ЗАВЕРШЕНА ===")


if __name__ == "__main__":
    # Настройка логирования для standalone запуска
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    log_diagnostic_info()