#!/bin/bash
echo "🚀 Улучшенная сборка FlexMontage Studio с автоконфигурацией..."

# Создаем папку dist
mkdir -p dist

# Очищаем старую сборку
rm -rf dist/FlexMontageStudio.app
rm -rf dist/FlexMontageStudio

echo "📦 Сборка приложения без включения конфигурационных файлов..."
echo "ℹ️  Конфигурационные файлы будут созданы автоматически при первом запуске"

# Команда сборки (БЕЗ channels.json, license.json; С styles.qss и TestChannel)
python -m nuitka \
    --standalone \
    --jobs=8 \
    --assume-yes-for-downloads \
    --enable-plugin=pyside6 \
    --macos-create-app-bundle \
    --macos-app-name=FlexMontageStudio \
    --macos-app-version=1.2.0 \
    --macos-app-icon=icon.icns \
    --output-dir=dist \
    --output-filename=FlexMontageStudio \
    --include-data-dir=ffmpeg=ffmpeg \
    --include-data-dir=TestChannel=TestChannel \
    --include-data-file=styles.qss=styles.qss \
    --nofollow-import-to=test \
    --nofollow-import-to=tests \
    --nofollow-import-to=PyQt5 \
    --nofollow-import-to=PyQt6 \
    --nofollow-import-to=PySide2 \
    --nofollow-import-to=IPython \
    --nofollow-import-to=matplotlib \
    --nofollow-import-to=scipy \
    --nofollow-import-to=sklearn \
    --nofollow-import-to=tqdm.notebook \
    --nofollow-import-to=doctest \
    --nofollow-import-to=_pytest \
    --nofollow-import-to=pytest \
    --nofollow-import-to=speechbrain.nnet.loss.transducer_loss \
    --nofollow-import-to=transformers.testing_utils \
    --nofollow-import-to=numba.tests \
    --nofollow-import-to=whisper.test \
    --nofollow-import-to=whisper.tests \
    --nofollow-import-to=cv2.test \
    --nofollow-import-to=cv2.tests \
    --nofollow-import-to=numpy.tests \
    --nofollow-import-to=numpy.testing \
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
    
    # Проверяем что конфигурационные файлы НЕ включены в сборку
    echo ""
    echo "🔍 Проверяем что конфигурационные файлы не включены в сборку..."
    
    config_files_found=false
    if [ -f "dist/FlexMontageStudio.app/Contents/MacOS/channels.json" ]; then
        echo "⚠️  channels.json найден внутри .app (не должен быть!)"
        config_files_found=true
    fi
    
    if [ -f "dist/FlexMontageStudio.app/Contents/MacOS/license.json" ]; then
        echo "⚠️  license.json найден внутри .app (не должен быть!)"
        config_files_found=true
    fi
    
    # styles.qss и TestChannel ДОЛЖНЫ быть внутри .app
    if [ -f "dist/FlexMontageStudio.app/Contents/MacOS/styles.qss" ]; then
        echo "✅ styles.qss найден внутри .app (как и должно быть)"
    else
        echo "⚠️  styles.qss НЕ найден внутри .app (должен быть!)"
        config_files_found=true
    fi
    
    if [ -d "dist/FlexMontageStudio.app/Contents/MacOS/TestChannel" ]; then
        echo "✅ TestChannel найден внутри .app (как и должно быть)"
    else
        echo "⚠️  TestChannel НЕ найден внутри .app (должен быть!)"
        config_files_found=true
    fi
    
    if [ "$config_files_found" = false ]; then
        echo "✅ Отлично! Внешние конфигурационные файлы не включены в сборку"
        echo "ℹ️  Они будут созданы автоматически при первом запуске"
        echo "✅ styles.qss включен в сборку для стилизации интерфейса"
        echo "✅ TestChannel включен в сборку и будет развернут при первом запуске"
    fi
    
    # Создаем простой README для пользователей
    echo ""
    echo "📝 Создаем README для пользователей..."
    cat > dist/README.txt << 'EOL'
FlexMontage Studio - автоматический AI монтаж видео
================================================

ПЕРВЫЙ ЗАПУСК:
1. Просто запустите FlexMontageStudio.app
2. При первом запуске автоматически создадутся все необходимые файлы
3. Приложение запустится с встроенной демо-лицензией
4. Готово к использованию!

ЛИЦЕНЗИРОВАНИЕ:
• Встроенная демо-лицензия активируется автоматически
• Для полного функционала приобретите лицензию на https://flexmontage.pro
• Если у вас есть лицензионный ключ, поместите файл license.json рядом с приложением

НАСТРОЙКА:
- Добавьте API ключи для ElevenLabs в файл TestChannel/api_keys.csv
- Добавьте фотографии в папку TestChannel/Photos/
- Начинайте создавать видео!

ФАЙЛЫ РЯДОМ С ПРИЛОЖЕНИЕМ:
После первого запуска появятся:
• channels.json - настройки каналов
• license.json - лицензии (включая демо-лицензию)
• TestChannel/ - тестовые данные и структура папок

ВСТРОЕННЫЕ ФАЙЛЫ:
• styles.qss - стили интерфейса (встроены в приложение)

БЕЗОПАСНОСТЬ:
Все ваши настройки и данные хранятся рядом с приложением,
а не внутри него. Это означает что:
- Обновления приложения не затрут ваши настройки
- Легко делать резервные копии

EOL
    
    echo "✅ README.txt создан"
    
    echo ""
    echo "🎉 Сборка полностью завершена!"
    echo "📁 Результат в папке: dist/"
    echo ""
    echo "📦 Что готово к распространению:"
    echo "  • FlexMontageStudio.app - основное приложение"
    echo "  • README.txt - инструкция для пользователей"
    echo ""
    echo "ℹ️  При первом запуске приложение создаст все необходимые файлы автоматически"
    echo "ℹ️  Пользователю нужно только добавить API ключ ElevenLabs"
    
    ls -la dist/
else
    echo "❌ Ошибка при сборке!"
    exit 1
fi