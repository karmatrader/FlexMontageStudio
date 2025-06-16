#!/usr/bin/env python3
"""
Скрипт для автоматической сборки FlexMontage Studio с Nuitka
"""
import os
import sys
import platform
import subprocess
from pathlib import Path

def main():
    print("🚀 FlexMontage Studio Build Script")
    print("=" * 50)
    
    # Проверяем что мы в правильной директории
    if not Path("startup.py").exists():
        print("❌ Ошибка: startup.py не найден. Запустите скрипт из корня проекта.")
        return 1
    
    # Проверяем Nuitka
    try:
        result = subprocess.run([sys.executable, '-m', 'nuitka', '--version'], 
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"✅ Nuitka найдена: {result.stdout.strip()}")
        else:
            print("❌ Nuitka не найдена. Устанавливаем...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'nuitka'], check=True)
    except Exception as e:
        print(f"❌ Ошибка при проверке Nuitka: {e}")
        return 1
    
    # Генерируем команду
    print("\n🔍 Анализируем проект и генерируем команду сборки...")
    
    try:
        result = subprocess.run([
            sys.executable, 'nuitka_command_generator.py', 
            'startup.py', 
            '--flexmontage',
            '--save-script', 'build_flexmontage.sh'
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print(f"❌ Ошибка при генерации команды: {result.stderr}")
            return 1
        
        print(result.stdout)
        
    except Exception as e:
        print(f"❌ Ошибка при генерации команды: {e}")
        return 1
    
    # Спрашиваем пользователя
    response = input("\n🔥 Начать сборку? (y/n): ").lower()
    if response not in ['y', 'yes', 'да']:
        print("⏸️  Сборка отменена.")
        return 0
    
    # Запускаем сборку
    print("\n🔧 Начинаем сборку...")
    
    if platform.system() == 'Windows':
        script_name = 'build_flexmontage.bat'
    else:
        script_name = 'build_flexmontage.sh'
    
    if not Path(script_name).exists():
        print(f"❌ Скрипт сборки {script_name} не найден!")
        return 1
    
    try:
        if platform.system() == 'Windows':
            subprocess.run([script_name], shell=True, check=True)
        else:
            subprocess.run([f'./{script_name}'], check=True)
        
        print("\n✅ Сборка завершена успешно!")
        print("📁 Результат в папке: dist/")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Ошибка при сборке: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())