#!/usr/bin/env python3
"""
Скрипт для исправления FFmpeg в app bundle
Копирует необходимые динамические библиотеки и изменяет пути загрузки
"""

import os
import shutil
import subprocess
from pathlib import Path

def run_command(cmd, check=True):
    """Выполнение команды с логированием"""
    print(f"Выполняем: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ОШИБКА: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result

def find_library(lib_name):
    """Поиск библиотеки в системе"""
    search_paths = [
        f"/usr/local/opt/{lib_name.split('.')[0]}/lib",
        f"/usr/local/lib",
        f"/usr/local/Cellar/*/lib"
    ]
    
    for search_path in search_paths:
        try:
            matches = subprocess.run(["find", "/usr/local", "-name", lib_name], 
                                   capture_output=True, text=True, timeout=10)
            if matches.returncode == 0 and matches.stdout.strip():
                files = matches.stdout.strip().split('\n')
                # Возвращаем первый найденный файл
                return files[0] if files[0] else None
        except:
            continue
    return None

def copy_ffmpeg_libraries():
    """Копирование библиотек FFmpeg в app bundle"""
    
    # Путь к app bundle
    app_path = Path("/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/dist/FlexMontageStudio.app")
    
    if not app_path.exists():
        print(f"ОШИБКА: App bundle не найден: {app_path}")
        return False
    
    # Путь к FFmpeg в bundle
    ffmpeg_path = app_path / "Contents/MacOS/ffmpeg/ffmpeg"
    
    if not ffmpeg_path.exists():
        print(f"ОШИБКА: FFmpeg не найден в bundle: {ffmpeg_path}")
        return False
    
    # Создаем папку для библиотек
    lib_dir = app_path / "Contents/MacOS/ffmpeg/lib"
    lib_dir.mkdir(exist_ok=True)
    
    print(f"Создана папка для библиотек: {lib_dir}")
    
    # Получаем список всех зависимостей из FFmpeg
    result = run_command(["otool", "-L", str(ffmpeg_path)])
    dependencies = result.stdout.strip().split('\n')[1:]  # Пропускаем первую строку с именем файла
    
    print("Анализируем зависимости FFmpeg...")
    
    for dep_line in dependencies:
        dep_line = dep_line.strip()
        if not dep_line:
            continue
            
        # Извлекаем путь к библиотеке
        lib_path = dep_line.split(' (')[0].strip()
        
        # Пропускаем системные библиотеки
        if lib_path.startswith('/System/') or lib_path.startswith('/usr/lib/'):
            continue
            
        # Получаем имя библиотеки
        lib_name = os.path.basename(lib_path)
        dest_path = lib_dir / lib_name
        
        # Если библиотека уже скопирована, пропускаем
        if dest_path.exists():
            continue
            
        # Пытаемся найти библиотеку
        source_path = None
        
        # Сначала пробуем оригинальный путь
        if Path(lib_path).exists():
            source_path = lib_path
        else:
            # Ищем библиотеку в системе
            found_path = find_library(lib_name)
            if found_path:
                source_path = found_path
        
        if source_path:
            print(f"Копируем {lib_name} из {source_path}...")
            try:
                shutil.copy2(source_path, dest_path)
            except Exception as e:
                print(f"ОШИБКА копирования {lib_name}: {e}")
        else:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Библиотека не найдена: {lib_name}")
    
    return True

def fix_library_paths():
    """Изменение путей к библиотекам в FFmpeg бинарнике и во всех библиотеках"""
    
    app_path = Path("/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/dist/FlexMontageStudio.app")
    ffmpeg_path = app_path / "Contents/MacOS/ffmpeg/ffmpeg"
    lib_dir = app_path / "Contents/MacOS/ffmpeg/lib"
    
    if not ffmpeg_path.exists():
        print(f"ОШИБКА: FFmpeg не найден: {ffmpeg_path}")
        return False
    
    # Список всех бинарников для обработки (включая сам FFmpeg и все библиотеки)
    binaries_to_fix = [ffmpeg_path]
    
    # Добавляем все .dylib файлы
    for lib_file in lib_dir.glob("*.dylib"):
        binaries_to_fix.append(lib_file)
    
    print("Изменяем пути к библиотекам...")
    
    for binary_path in binaries_to_fix:
        print(f"\nОбрабатываем: {binary_path.name}")
        
        # Получаем список всех зависимостей
        try:
            result = run_command(["otool", "-L", str(binary_path)])
            dependencies = result.stdout.strip().split('\n')[1:]  # Пропускаем первую строку с именем файла
        except subprocess.CalledProcessError:
            print(f"  ⚠️  Не удалось получить зависимости для {binary_path.name}")
            continue
        
        for dep_line in dependencies:
            dep_line = dep_line.strip()
            if not dep_line:
                continue
                
            # Извлекаем путь к библиотеке
            lib_path = dep_line.split(' (')[0].strip()
            
            # Пропускаем системные библиотеки
            if lib_path.startswith('/System/') or lib_path.startswith('/usr/lib/'):
                continue
                
            # Получаем имя библиотеки
            lib_name = os.path.basename(lib_path)
            
            # Проверяем, есть ли библиотека в нашей папке
            local_lib_path = lib_dir / lib_name
            if local_lib_path.exists():
                # Изменяем путь на относительный
                new_path = f"@executable_path/lib/{lib_name}"
                
                try:
                    run_command([
                        "install_name_tool",
                        "-change", lib_path, new_path,
                        str(binary_path)
                    ])
                    print(f"  ✅ {lib_name}: {lib_path} -> {new_path}")
                except subprocess.CalledProcessError as e:
                    print(f"  ❌ Ошибка изменения пути для {lib_name}: {e}")
            else:
                # Если это не системная библиотека, но её нет локально - предупреждение
                if not lib_path.startswith('/usr/') and not lib_path.startswith('/System/'):
                    print(f"  ⚠️  Библиотека не найдена локально: {lib_name}")
    
    return True

def test_ffmpeg():
    """Тестирование исправленного FFmpeg"""
    ffmpeg_path = "/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/dist/FlexMontageStudio.app/Contents/MacOS/ffmpeg/ffmpeg"
    
    try:
        result = run_command([ffmpeg_path, "-version"], check=False)
        if result.returncode == 0:
            print("✅ FFmpeg успешно работает!")
            print("Версия:", result.stdout.split('\n')[0])
            return True
        else:
            print("❌ FFmpeg не работает:")
            print("STDERR:", result.stderr)
            return False
    except Exception as e:
        print(f"❌ Ошибка тестирования FFmpeg: {e}")
        return False

def main():
    """Основная функция"""
    print("🔧 Исправление FFmpeg в app bundle...")
    
    print("\n1. Копирование библиотек...")
    if not copy_ffmpeg_libraries():
        print("❌ Ошибка копирования библиотек")
        return
    
    print("\n2. Изменение путей к библиотекам...")
    if not fix_library_paths():
        print("❌ Ошибка изменения путей")
        return
    
    print("\n3. Тестирование...")
    if test_ffmpeg():
        print("\n🎉 FFmpeg успешно исправлен!")
    else:
        print("\n❌ FFmpeg по-прежнему не работает")

if __name__ == "__main__":
    main()