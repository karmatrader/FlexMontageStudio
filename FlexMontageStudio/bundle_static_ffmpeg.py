#!/usr/bin/env python3
"""
Скрипт для интеграции статического FFmpeg от imageio-ffmpeg в app bundle
Это гарантирует работу FFmpeg на любом macOS без зависимостей
"""

import sys
import shutil
import subprocess
from pathlib import Path


def get_imageio_ffmpeg_path():
    """Получить путь к статическому FFmpeg от imageio-ffmpeg"""
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"Найден imageio-ffmpeg: {ffmpeg_path}")
        return ffmpeg_path
    except ImportError:
        print("ОШИБКА: imageio-ffmpeg не установлен")
        return None
    except Exception as e:
        print(f"ОШИБКА получения imageio-ffmpeg: {e}")
        return None


def install_static_ffmpeg(app_bundle_path):
    """Установка статического FFmpeg в app bundle"""
    app_path = Path(app_bundle_path)
    if not app_path.exists():
        print(f"ОШИБКА: App bundle не найден: {app_path}")
        return False
    
    # Получаем статический FFmpeg от imageio-ffmpeg
    imageio_ffmpeg_path = get_imageio_ffmpeg_path()
    if not imageio_ffmpeg_path:
        return False
    
    source_ffmpeg = Path(imageio_ffmpeg_path)
    if not source_ffmpeg.exists():
        print(f"ОШИБКА: Статический FFmpeg не найден: {source_ffmpeg}")
        return False
    
    # Целевая папка для FFmpeg
    target_ffmpeg_dir = app_path / "Contents/MacOS/ffmpeg"
    target_ffmpeg_path = target_ffmpeg_dir / "ffmpeg"
    
    try:
        # Создаем папку
        target_ffmpeg_dir.mkdir(exist_ok=True, parents=True)
        print(f"Папка FFmpeg создана: {target_ffmpeg_dir}")
        
        # Копируем статический FFmpeg
        shutil.copy2(source_ffmpeg, target_ffmpeg_path)
        print(f"Статический FFmpeg скопирован: {target_ffmpeg_path}")
        
        # Устанавливаем права выполнения
        target_ffmpeg_path.chmod(0o755)
        print("Права выполнения установлены")
        
        # Проверяем работоспособность
        result = subprocess.run([str(target_ffmpeg_path), "-version"], 
                              capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            first_line = result.stdout.split('\n')[0]
            print(f"\n🎉 Статический FFmpeg успешно установлен!")
            print(f"Версия: {first_line}")
            print(f"Размер: {target_ffmpeg_path.stat().st_size / 1024 / 1024:.1f} MB")
            return True
        else:
            print(f"ОШИБКА: Статический FFmpeg не работает: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"ОШИБКА установки статического FFmpeg: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print("Использование: python bundle_static_ffmpeg.py <path_to_app_bundle>")
        sys.exit(1)
    
    app_bundle_path = sys.argv[1]
    print(f"🔧 Установка статического FFmpeg в {app_bundle_path}")
    
    success = install_static_ffmpeg(app_bundle_path)
    if success:
        print("✅ Готово! FFmpeg будет работать на любом macOS")
        sys.exit(0)
    else:
        print("❌ Ошибка установки статического FFmpeg")
        sys.exit(1)


if __name__ == "__main__":
    main()