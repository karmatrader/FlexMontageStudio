@echo off
echo 🚀 Улучшенная сборка FlexMontage Studio с автоконфигурацией для Windows...

REM Create dist folder
if not exist dist mkdir dist

REM Clean old build - улучшенная очистка
echo 🧹 Очищаем старые файлы сборки...
if exist dist\FlexMontageStudio.exe del /q dist\FlexMontageStudio.exe
if exist dist\startup.exe del /q dist\startup.exe
if exist dist\FlexMontageStudio.dist rd /s /q dist\FlexMontageStudio.dist
if exist dist\startup.dist rd /s /q dist\startup.dist
if exist dist\startup.app rd /s /q dist\startup.app
if exist dist\startup.build rd /s /q dist\startup.build
if exist dist\TestChannel rd /s /q dist\TestChannel

echo 📦 Сборка приложения без включения конфигурационных файлов...
echo ℹ️  Конфигурационные файлы будут созданы автоматически при первом запуске

REM Упрощенная сборка без избыточных параметров (копируем с macOS)
python -m nuitka ^
    --standalone ^
    --jobs=4 ^
    --assume-yes-for-downloads ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=icon.ico ^
    --output-dir=dist ^
    --output-filename=FlexMontageStudio ^
    --include-data-dir=ffmpeg=ffmpeg ^
    --include-data-dir=TestChannel=TestChannel ^
    --include-data-file=styles.qss=styles.qss ^
    --nofollow-import-to=test ^
    --nofollow-import-to=tests ^
    --nofollow-import-to=PyQt5 ^
    --nofollow-import-to=PyQt6 ^
    --nofollow-import-to=PySide2 ^
    --nofollow-import-to=IPython ^
    --nofollow-import-to=matplotlib ^
    --nofollow-import-to=scipy ^
    --nofollow-import-to=sklearn ^
    --nofollow-import-to=tqdm.notebook ^
    --nofollow-import-to=doctest ^
    --nofollow-import-to=_pytest ^
    --nofollow-import-to=pytest ^
    --nofollow-import-to=speechbrain.nnet.loss.transducer_loss ^
    --nofollow-import-to=transformers.testing_utils ^
    --nofollow-import-to=transformers.models ^
    --nofollow-import-to=transformers.models.nllb ^
    --nofollow-import-to=transformers.models.bert ^
    --nofollow-import-to=transformers.models.gpt2 ^
    --nofollow-import-to=transformers.models.roberta ^
    --nofollow-import-to=transformers.models.t5 ^
    --nofollow-import-to=transformers.pipelines ^
    --nofollow-import-to=transformers.trainer ^
    --nofollow-import-to=transformers.tokenization_utils ^
    --nofollow-import-to=transformers.utils ^
    --nofollow-import-to=numba.tests ^
    --nofollow-import-to=whisper.test ^
    --nofollow-import-to=whisper.tests ^
    --nofollow-import-to=cv2.test ^
    --nofollow-import-to=cv2.tests ^
    --nofollow-import-to=numpy.tests ^
    --nofollow-import-to=numpy.testing ^
    --nofollow-import-to=objc ^
    --nofollow-import-to=Foundation ^
    --nofollow-import-to=AppKit ^
    --nofollow-import-to=huggingface_hub.utils ^
    --nofollow-import-to=tokenizers ^
    --nofollow-import-to=datasets ^
    --nofollow-import-to=accelerate ^
    startup.py

REM Сохраняем статус выхода команды Nuitka
set build_status=%errorlevel%
echo.

if %build_status% equ 0 (
    echo ✅ Сборка завершена успешно!

    REM Переименовываем startup.exe в FlexMontageStudio.exe если нужно
    if exist "dist\startup.exe" (
        if not exist "dist\FlexMontageStudio.exe" (
            echo 🔄 Переименовываем startup.exe в FlexMontageStudio.exe...
            move "dist\startup.exe" "dist\FlexMontageStudio.exe"
        )
    )

    REM Переименовываем startup.dist в FlexMontageStudio.dist если нужно
    if exist "dist\startup.dist" (
        if not exist "dist\FlexMontageStudio.dist" (
            echo 🔄 Переименовываем startup.dist в FlexMontageStudio.dist...
            move "dist\startup.dist" "dist\FlexMontageStudio.dist"
        )
    )

    REM Проверяем что сборка действительно создана
    if not exist "dist\FlexMontageStudio.exe" (
        echo ❌ Исполняемый файл FlexMontageStudio.exe не найден!
        exit /b 1
    )

    if not exist "dist\FlexMontageStudio.dist" (
        echo ❌ Папка зависимостей FlexMontageStudio.dist не найдена!
        exit /b 1
    )

    REM Диагностика содержимого сборки
    echo.
    echo 🔍 Диагностика содержимого сборки...
    echo.
    echo === Основные файлы в сборке ===
    if exist "dist\FlexMontageStudio.dist\main.py" (
        echo ✅ main.py найден как файл данных
    ) else (
        echo ❌ main.py НЕ найден как файл данных
    )

    REM voice_proxy.py больше не используется и был удален

    echo.
    echo === Поиск скомпилированных модулей ===
    dir "dist\FlexMontageStudio.dist" | findstr /i main
    REM Поиск voice модулей больше не актуален

    echo.
    echo === Первые 20 файлов в сборке ===
    dir "dist\FlexMontageStudio.dist" | head -n 20

    REM Устанавливаем права на выполнение для статического FFmpeg (если применимо)
    if exist "dist\FlexMontageStudio.dist\ffmpeg\ffmpeg.exe" (
        echo 🔧 Проверяем FFmpeg в сборке...
        echo ✅ Статический FFmpeg готов
    )

    REM Проверяем что конфигурационные файлы НЕ включены в сборку
    echo.
    echo 🔍 Проверяем что конфигурационные файлы не включены в сборку...

    set config_files_found=false
    if exist "dist\FlexMontageStudio.dist\channels.json" (
        echo ⚠️  channels.json найден внутри .dist (не должен быть!)
        set config_files_found=true
    )

    if exist "dist\FlexMontageStudio.dist\license.json" (
        echo ⚠️  license.json найден внутри .dist (не должен быть!)
        set config_files_found=true
    )

    REM styles.qss и TestChannel ДОЛЖНЫ быть внутри .dist
    if exist "dist\FlexMontageStudio.dist\styles.qss" (
        echo ✅ styles.qss найден внутри .dist (как и должно быть)
    ) else (
        echo ⚠️  styles.qss НЕ найден внутри .dist (должен быть!)
        set config_files_found=true
    )

    if exist "dist\FlexMontageStudio.dist\TestChannel" (
        echo ✅ TestChannel найден внутри .dist (как и должно быть)
    ) else (
        echo ⚠️  TestChannel НЕ найден внутри .dist (должен быть!)
        set config_files_found=true
    )

    if "%config_files_found%"=="false" (
        echo ✅ Отлично! Внешние конфигурационные файлы не включены в сборку
        echo ℹ️  Они будут созданы автоматически при первом запуске
        echo ✅ styles.qss включен в сборку для стилизации интерфейса
        echo ✅ TestChannel включен в сборку и будет развернут при первом запуске
    )

    REM Удаляем старые файлы после успешной сборки
    echo.
    echo 🧹 Удаляем временные файлы...
    if exist dist\startup.app rd /s /q dist\startup.app
    if exist dist\startup.build rd /s /q dist\startup.build
    if exist dist\TestChannel rd /s /q dist\TestChannel

    REM Создаем простой README для пользователей
    echo.
    echo 📝 Создаем README для пользователей...
    (
        echo FlexMontage Studio - автоматический AI монтаж видео
        echo ================================================
        echo.
        echo ПЕРВЫЙ ЗАПУСК:
        echo 1. Просто запустите FlexMontageStudio.exe
        echo 2. При первом запуске автоматически создадутся все необходимые файлы
        echo 3. Приложение запустится с встроенной демо-лицензией
        echo 4. Готово к использованию!
        echo.
        echo ЛИЦЕНЗИРОВАНИЕ:
        echo • Встроенная демо-лицензия активируется автоматически
        echo • Для полного функционала приобретите лицензию на https://flexmontage.pro
        echo • Если у вас есть лицензионный ключ, поместите файл license.json рядом с приложением
        echo.
        echo НАСТРОЙКА:
        echo - Добавьте API ключи для ElevenLabs в файл TestChannel\api_keys.csv
        echo - Добавьте фотографии в папку TestChannel\Photos\
        echo - Начинайте создавать видео!
        echo.
        echo ФАЙЛЫ РЯДОМ С ПРИЛОЖЕНИЕМ:
        echo После первого запуска появятся:
        echo • channels.json - настройки каналов
        echo • license.json - лицензии (включая демо-лицензию^)
        echo • TestChannel\ - тестовые данные и структура папок
        echo.
        echo ВСТРОЕННЫЕ ФАЙЛЫ:
        echo • styles.qss - стили интерфейса (встроены в приложение^)
        echo.
        echo БЕЗОПАСНОСТЬ:
        echo Все ваши настройки и данные хранятся рядом с приложением,
        echo а не внутри него. Это означает что:
        echo - Обновления приложения не затрут ваши настройки
        echo - Легко делать резервные копии
        echo.
    ) > dist\README.txt

    echo ✅ README.txt создан

    echo.
    echo 🎉 Сборка полностью завершена!
    echo 📁 Результат в папке: dist\
    echo.
    echo 📦 Что готово к распространению:
    echo   • FlexMontageStudio.exe - основной исполняемый файл
    echo   • FlexMontageStudio.dist\ - папка с зависимостями (должна быть рядом с .exe^)
    echo   • README.txt - инструкция для пользователей
    echo.
    echo ℹ️  При первом запуске приложение создаст все необходимые файлы автоматически
    echo ℹ️  Пользователю нужно только добавить API ключ ElevenLabs

    echo.
    echo Итоговые файлы:
    dir dist\ /w
) else (
    echo ❌ Ошибка при сборке! Код ошибки: %build_status%
    echo.
    echo 🔍 Возможные причины:
    echo - Проблема с циклическими импортами
    echo - Конфликт версий библиотек
    echo - Недостаточно места на диске
    echo.
    echo 💡 Попробуйте:
    echo 1. Обновить Nuitka: pip install --upgrade nuitka
    echo 2. Очистить кэш Python: py -c "import sys; print(sys.path)" и удалить __pycache__
    echo 3. Запустить сборку еще раз
    echo.
    if exist nuitka-crash-report.xml (
        echo 📋 Отчет об ошибке сохранен в: nuitka-crash-report.xml
    )
    exit /b 1
)