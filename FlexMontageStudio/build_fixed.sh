#!/bin/bash
echo "🚀 Исправленная сборка FlexMontage Studio с Nuitka..."

# Создаем папку dist
mkdir -p dist

# Очищаем старую сборку
rm -rf dist/FlexMontageStudio.app
rm -rf dist/FlexMontageStudio

# Команда сборки
python -m nuitka \
    --standalone \
    --jobs=8 \
    --assume-yes-for-downloads \
    --enable-plugin=pyside6 \
    --include-package=numpy \
    --include-package=whisper \
    --include-package=pandas \
    --include-package=cv2 \
    --include-package=aiohttp \
    --include-package=requests \
    --include-package=openpyxl \
    --include-package=cryptography \
    --include-package=torch \
    --include-package=transformers \
    --include-package=speechbrain \
    --include-package=tqdm \
    --include-package=numba \
    --macos-create-app-bundle \
    --macos-app-name=FlexMontageStudio \
    --macos-app-version=1.1.16 \
    --macos-app-icon=icon.icns \
    --output-dir=dist \
    --output-filename=FlexMontageStudio \
    --include-data-dir=ffmpeg=ffmpeg \
    --include-data-file=channels.json=channels.json \
    --include-data-file=styles.qss=styles.qss \
    --include-data-file=licenses.json=licenses.json \
    --nofollow-import-to=test \
    --nofollow-import-to=tests \
    --nofollow-import-to=PyQt5 \
    --nofollow-import-to=PyQt6 \
    --nofollow-import-to=PySide2 \
    --nofollow-import-to=IPython \
    --nofollow-import-to=tqdm.notebook \
    --nofollow-import-to=doctest \
    --nofollow-import-to=_pytest \
    --nofollow-import-to=pytest \
    --nofollow-import-to=speechbrain.nnet.loss.transducer_loss \
    --nofollow-import-to=transformers.testing_utils \
    startup.py

# Сохраняем статус выхода команды Nuitka
build_status=$?
echo ""
if [ $build_status -eq 0 ]; then
    echo "✅ Сборка завершена успешно!"
    
    # Переименовываем startup.app в FlexMontageStudio.app если нужно
    if [ -d "dist/startup.app" ] && [ ! -d "dist/FlexMontageStudio.app" ]; then
        echo "🔄 Переименовываем startup.app в FlexMontageStudio.app..."
        mv dist/startup.app dist/FlexMontageStudio.app
    fi
    
    # Устанавливаем права на выполнение для статического FFmpeg
    if [ -f "dist/FlexMontageStudio.app/Contents/MacOS/ffmpeg/ffmpeg" ]; then
        echo "🔧 Устанавливаем права на выполнение для статического FFmpeg..."
        chmod +x dist/FlexMontageStudio.app/Contents/MacOS/ffmpeg/ffmpeg
        chmod +x dist/FlexMontageStudio.app/Contents/MacOS/ffmpeg/ffprobe
        echo "✅ Статический FFmpeg готов"
    fi
    
    echo "📁 Результат в папке: dist/"
    ls -la dist/
else
    echo "❌ Ошибка при сборке!"
    exit 1
fi