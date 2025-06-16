#!/usr/bin/env python3
"""
Итеративное исправление FFmpeg - копирует недостающие библиотеки до тех пор,
пока не будут найдены все зависимости
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
    try:
        matches = subprocess.run(["find", "/usr/local", "-name", lib_name], 
                               capture_output=True, text=True, timeout=10)
        if matches.returncode == 0 and matches.stdout.strip():
            files = matches.stdout.strip().split('\n')
            # Возвращаем первый найденный файл
            return files[0] if files[0] else None
    except:
        pass
    return None

def get_missing_libraries(ffmpeg_path):
    """Получение списка недостающих библиотек"""
    try:
        result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return []  # Нет недостающих библиотек
    except subprocess.TimeoutExpired:
        pass
    
    # Парсим ошибки
    stderr = result.stderr if hasattr(result, 'stderr') else ""
    missing_libs = []
    
    for line in stderr.split('\n'):
        if "Library not loaded:" in line:
            # Извлекаем имя библиотеки
            if "@rpath/" in line:
                lib_name = line.split("@rpath/")[1].split()[0]
                missing_libs.append(lib_name)
            elif "@executable_path/" in line:
                lib_name = line.split("@executable_path/")[1].split()[0]
                missing_libs.append(lib_name)
    
    return missing_libs

def copy_missing_libraries(lib_dir, missing_libs):
    """Копирование недостающих библиотек"""
    copied = 0
    
    for lib_name in missing_libs:
        dest_path = lib_dir / lib_name
        
        # Если библиотека уже есть, пропускаем
        if dest_path.exists():
            continue
            
        # Ищем библиотеку в системе
        source_path = find_library(lib_name)
        
        if source_path:
            print(f"Копируем недостающую библиотеку {lib_name} из {source_path}...")
            try:
                shutil.copy2(source_path, dest_path)
                copied += 1
            except Exception as e:
                print(f"ОШИБКА копирования {lib_name}: {e}")
        else:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Недостающая библиотека не найдена: {lib_name}")
    
    return copied

def fix_library_paths_for_libs(lib_dir, lib_names):
    """Исправление путей для конкретных библиотек"""
    for lib_name in lib_names:
        lib_path = lib_dir / lib_name
        if not lib_path.exists():
            continue
            
        print(f"Исправляем пути для {lib_name}...")
        
        try:
            result = run_command(["otool", "-L", str(lib_path)], check=False)
            if result.returncode != 0:
                continue
                
            dependencies = result.stdout.strip().split('\n')[1:]
            
            for dep_line in dependencies:
                dep_line = dep_line.strip()
                if not dep_line:
                    continue
                    
                lib_path_in_dep = dep_line.split(' (')[0].strip()
                
                # Пропускаем системные библиотеки
                if lib_path_in_dep.startswith('/System/') or lib_path_in_dep.startswith('/usr/lib/'):
                    continue
                    
                dep_lib_name = os.path.basename(lib_path_in_dep)
                local_dep_path = lib_dir / dep_lib_name
                
                if local_dep_path.exists():
                    new_path = f"@executable_path/lib/{dep_lib_name}"
                    
                    try:
                        run_command([
                            "install_name_tool",
                            "-change", lib_path_in_dep, new_path,
                            str(lib_path)
                        ], check=False)
                        print(f"  ✅ {dep_lib_name}: {lib_path_in_dep} -> {new_path}")
                    except:
                        pass
                        
        except Exception as e:
            print(f"ОШИБКА обработки {lib_name}: {e}")

def main():
    """Основная функция"""
    app_path = Path("/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/dist/FlexMontageStudio.app")
    ffmpeg_path = app_path / "Contents/MacOS/ffmpeg/ffmpeg"
    lib_dir = app_path / "Contents/MacOS/ffmpeg/lib"
    
    if not ffmpeg_path.exists():
        print(f"ОШИБКА: FFmpeg не найден: {ffmpeg_path}")
        return
    
    iteration = 1
    max_iterations = 10
    
    print("🔧 Итеративное исправление FFmpeg...")
    
    while iteration <= max_iterations:
        print(f"\n--- Итерация {iteration} ---")
        
        # Получаем список недостающих библиотек
        missing_libs = get_missing_libraries(str(ffmpeg_path))
        
        if not missing_libs:
            print("✅ Все библиотеки найдены!")
            
            # Финальная проверка
            try:
                result = subprocess.run([str(ffmpeg_path), "-version"], 
                                     capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    print("🎉 FFmpeg успешно работает!")
                    print("Версия:", result.stdout.split('\n')[0])
                    return
                else:
                    print("❌ FFmpeg все еще не работает:")
                    print(result.stderr)
                    return
            except Exception as e:
                print(f"❌ Ошибка тестирования FFmpeg: {e}")
                return
        
        print(f"Найдено недостающих библиотек: {len(missing_libs)}")
        for lib in missing_libs:
            print(f"  - {lib}")
        
        # Копируем недостающие библиотеки
        copied = copy_missing_libraries(lib_dir, missing_libs)
        
        if copied == 0:
            print("❌ Не удалось найти недостающие библиотеки в системе")
            return
        
        # Исправляем пути для новых библиотек
        fix_library_paths_for_libs(lib_dir, missing_libs)
        
        iteration += 1
    
    print(f"❌ Превышено максимальное количество итераций ({max_iterations})")

if __name__ == "__main__":
    main()