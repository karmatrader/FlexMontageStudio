import os
import sys
import logging
from pathlib import Path
import subprocess
import json  # Добавлен для get_media_duration
import re  # Добавлен для get_media_duration
from typing import Dict  # Добавлен для quick_media_info

logger = logging.getLogger(__name__)

# Функция для скрытия окон консоли на Windows
def run_subprocess_hidden(*args, **kwargs):
    """Запуск subprocess с скрытой консолью на Windows"""
    try:
        # Более универсальная проверка Windows (включая скомпилированные приложения)
        if (os.name == 'nt' or 'win' in sys.platform.lower()) and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass  # Если не удалось определить ОС, продолжаем без флагов
    return subprocess.run(*args, **kwargs)

# --- БАЗОВОЕ НАЗВАНИЕ ПАПКИ С БИНАРНИКАМИ FFmpeg ---
# Эта переменная указывает на название папки, где хранятся исполняемые файлы FFmpeg/FFprobe
# Ваш путь: /Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/ffmpeg/
# Это означает, что папка 'ffmpeg' находится прямо внутри директории проекта
# вашего скрипта.
FFMPEG_BIN_DIR_NAME = "ffmpeg"


def _get_base_ffmpeg_dir() -> Path:
    """
    Определяет базовый путь к папке с бинарниками FFmpeg.
    Учитывает запуск из скомпилированного приложения (Nuitka) или в режиме разработки.
    """
    if getattr(sys, "frozen", False):
        # Мы запущены из скомпилированного исполняемого файла (Nuitka).
        # Nuitka обычно помещает данные рядом с исполняемым файлом.
        # Path(sys.executable).resolve().parent - это директория, где лежит исполняемый файл.
        # Предполагаем, что папка 'ffmpeg' находится *рядом* с исполняемым файлом.
        base_dir = Path(sys.executable).resolve().parent / FFMPEG_BIN_DIR_NAME
        logger.debug(f"DEBUG: Обнаружен 'frozen' режим (Nuitka). Базовый путь для FFmpeg: {base_dir}")
        return base_dir
    else:
        # Мы запущены в обычной Python среде (например, через 'python main.py' или из IDE).
        # Path(__file__).resolve().parent - это директория, где лежит текущий скрипт (ffmpeg_utils.py).
        # Если ffmpeg_utils.py находится в FlexMontageStudio, и папка 'ffmpeg' тоже там,
        # то это будет Path('.../FlexMontageStudio') / 'ffmpeg'.
        base_dir = Path(__file__).resolve().parent / FFMPEG_BIN_DIR_NAME
        logger.debug(f"DEBUG: Обнаружен режим разработки. Базовый путь для FFmpeg: {base_dir}")

        # Дополнительная проверка, если base_dir не найден по этой стратегии,
        # попробовать относительно текущей рабочей директории (если main.py запускается из корня проекта)
        if not base_dir.exists():
            current_working_dir_base = Path(os.getcwd()) / FFMPEG_BIN_DIR_NAME
            if current_working_dir_base.exists():
                logger.warning(
                    f"⚠️ Базовая папка FFmpeg '{base_dir}' не найдена относительно ffmpeg_utils.py. Используем путь относительно CWD: {current_working_dir_base}")
                base_dir = current_working_dir_base
            else:
                logger.error(
                    f"❌ Критическая ошибка: Папка FFmpeg '{base_dir}' не найдена ни по одному из ожидаемых путей.")
                raise FileNotFoundError(f"Папка FFmpeg не найдена: {base_dir}")

        return base_dir


def get_ffmpeg_path() -> str:
    """
    Возвращает полный путь к исполняемому файлу FFmpeg.
    Автоматически определяет имя файла для текущей ОС.
    """
    base_dir = _get_base_ffmpeg_dir()

    # Определяем имя исполняемого файла в зависимости от ОС
    if sys.platform.startswith('win'):
        ffmpeg_exe_name = "ffmpeg.exe"
    else:  # macOS, Linux
        ffmpeg_exe_name = "ffmpeg"

    full_path = base_dir / ffmpeg_exe_name

    logger.debug(f"DEBUG: Ожидаемый путь к FFmpeg: {full_path}")
    if not full_path.exists():
        logger.error(f"ОШИБКА: Исполняемый файл FFmpeg НЕ НАЙДЕН по пути: {full_path}")
        logger.error(
            f"Пожалуйста, убедитесь, что '{FFMPEG_BIN_DIR_NAME}' папка находится рядом с вашим скриптом/исполняемым файлом и содержит '{ffmpeg_exe_name}'.")
        raise FileNotFoundError(f"Исполняемый файл FFmpeg не найден: {full_path}")

    # КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем работоспособность найденного FFmpeg
    if not _test_ffmpeg_working(str(full_path), debug=False):  # Передаем string для subprocess
        logger.error(f"ОШИБКА: Исполняемый файл FFmpeg найден по пути {full_path}, но не работает.")
        raise FileNotFoundError(f"Исполняемый файл FFmpeg найден, но не работает: {full_path}")

    return str(full_path)


def get_ffprobe_path() -> str:
    """
    Возвращает полный путь к исполняемому файлу FFprobe.
    Автоматически определяет имя файла для текущей операционной системы.
    """
    base_dir = _get_base_ffmpeg_dir()

    # Определяем имя исполняемого файла в зависимости от ОС
    if sys.platform.startswith('win'):
        ffprobe_exe_name = "ffprobe.exe"
    else:  # macOS, Linux
        ffprobe_exe_name = "ffprobe"

    full_path = base_dir / ffprobe_exe_name

    logger.debug(f"DEBUG: Ожидаемый путь к FFprobe: {full_path}")
    if not full_path.exists():
        logger.error(f"ОШИБКА: Исполняемый файл FFprobe НЕ НАЙДЕН по пути: {full_path}")
        logger.error(
            f"Пожалуйста, убедитесь, что '{FFMPEG_BIN_DIR_NAME}' папка находится рядом с вашим скриптом/исполняемым файлом и содержит '{ffprobe_exe_name}'.")
        raise FileNotFoundError(f"Исполняемый файл FFprobe не найден: {full_path}")

    # Для ffprobe не всегда нужна проверка _test_ffmpeg_working,
    # так как он используется для анализа, а не для генерации,
    # и иногда может быть сложнее протестировать его "работоспособность"
    # без входного файла. Достаточно убедиться, что он существует.
    return str(full_path)


def _test_ffmpeg_working(ffmpeg_path: str, debug: bool = False) -> bool:
    """
    Проверяет, работает ли исполняемый файл FFmpeg,
    запуская простую команду 'ffmpeg -version'.
    """
    try:
        if not Path(ffmpeg_path).exists():
            logger.warning(f"⚠️ _test_ffmpeg_working: файл не найден {ffmpeg_path}")
            return False

        result = run_subprocess_hidden(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10
        )

        if result.returncode == 0:
            if debug:
                logger.info(f"✅ FFmpeg успешно запущен. Версия: {result.stdout.splitlines()[0]}")
            return True
        else:
            logger.warning(
                f"❌ FFmpeg по пути '{ffmpeg_path}' вернул ошибку при проверке версии. Код: {result.returncode}, stderr: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired as e:
        logger.warning(f"⚠️ _test_ffmpeg_working: тайм-аут при тестировании {ffmpeg_path}: {e}")
        return False
    except FileNotFoundError as e:
        logger.warning(f"⚠️ _test_ffmpeg_working: файл не найден {ffmpeg_path}: {e}")
        return False
    except PermissionError as e:
        logger.warning(f"⚠️ _test_ffmpeg_working: нет прав на выполнение {ffmpeg_path}: {e}")
        return False
    except Exception as e:
        logger.warning(f"❌ Ошибка при попытке запустить FFmpeg по пути '{ffmpeg_path}': {e}")
        return False


def run_ffmpeg_command(cmd, description="FFmpeg command", timeout=300): # timeout добавлен как параметр
    logger.debug(f"Выполнение FFmpeg: {description} -> {' '.join(cmd)}")
    process = None # Инициализируем process
    try:
        # Запускаем процесс без ожидания завершения
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Ожидаем завершения процесса с проверкой флага остановки
        import time
        start_time = time.time()
        while process.poll() is None:
            # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ КАЖДЫЕ 0.05 секунды (в 2 раза чаще)!
            try:
                import montage_control
                if montage_control.check_stop_flag(f"FFmpeg utils {description}"):
                    logger.error(f"🛑🔥 ПРИНУДИТЕЛЬНАЯ ОСТАНОВКА FFmpeg utils: {description}")
                    # АГРЕССИВНО убиваем процесс СРАЗУ
                    try:
                        process.kill()  # Сразу KILL вместо terminate
                        logger.error(f"🔥 УБИТ FFmpeg процесс: {description}")
                    except:
                        pass
                    # И еще системной командой для надежности
                    try:
                        import subprocess as sp
                        sp.run(["pkill", "-9", "-f", description], capture_output=True)
                    except:
                        pass
                    raise RuntimeError(f"🛑 FFmpeg процесс ОСТАНОВЛЕН: {description}")
            except RuntimeError:
                raise
            except:
                pass
                
            # Проверяем таймаут
            if time.time() - start_time > timeout:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(cmd, timeout)
                
            time.sleep(0.05)  # Проверяем в 2 раза чаще
            
        stdout, stderr = process.communicate() # Получаем финальный вывод

        if process.returncode != 0:
            logger.error(f"❌ Ошибка при выполнении {description}: FFmpeg вернул ненулевой код {process.returncode}")
            logger.error(f"FFmpeg stdout:\n{stdout}")
            logger.error(f"FFmpeg stderr:\n{stderr}")
            raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)

        logger.debug(f"✅ {description} stdout:\n{stdout}")
        if stderr: # Логируем stderr даже при успехе
            logger.debug(f"⚠️ {description} stderr:\n{stderr}")

        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)

    except subprocess.TimeoutExpired:
        if process:
            process.kill() # Завершаем процесс, если таймаут
            stdout, stderr = process.communicate()
        logger.error(f"❌ Таймаут при выполнении {description} ({timeout}s). FFmpeg stdout (до таймаута):\n{stdout}")
        logger.error(f"FFmpeg stderr (до таймаута):\n{stderr}")
        raise
    except subprocess.CalledProcessError: # Перехватываем, чтобы не дублировать логирование
        raise # Просто перебрасываем, так как уже залогировано выше
    except FileNotFoundError:
        logger.error(f"❌ FFmpeg или ffprobe не найден. Проверьте путь: {cmd[0]}")
        raise
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при выполнении {description}: {e}")
        raise


def get_media_duration(file_path: str, timeout: int = 30) -> float:
    """
    ОПТИМИЗИРОВАННАЯ функция получения длительности медиа с быстрым ffprobe
    """
    if not file_path or not os.path.exists(file_path):
        logger.error(f"❌ Файл не найден: {file_path}")
        return 0.0

    try:
        # ОПТИМИЗАЦИЯ: Используем более быструю команду ffprobe
        cmd = [
            get_ffprobe_path(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]

        logger.debug(f"🔍 Получение длительности: {Path(file_path).name}")

        result = run_subprocess_hidden(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )

        duration_str = result.stdout.strip()
        if duration_str and duration_str != "N/A":
            duration = float(duration_str)
            logger.debug(f"   ✅ Длительность: {duration:.3f}с")
            return duration
        else:
            logger.warning(f"   ⚠️ Не удалось получить длительность из: '{duration_str}'")
            return 0.0
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Таймаут при получении длительности: {Path(file_path).name}")
        return 0.0
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Ошибка ffprobe для {Path(file_path).name}: {e.stderr}")
        return 0.0
    except ValueError as e:
        logger.error(f"❌ Ошибка парсинга длительности: {e}")
        return 0.0
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка получения длительности: {e}")
        return 0.0


def quick_media_info(file_path: str, timeout: int = 15) -> Dict[str, any]:
    """
    Быстрое получение базовой информации о медиафайле
    """
    info = {
        "exists": False,
        "size": 0,
        "duration": 0.0,
        "has_video": False,
        "has_audio": False,
        "error": None
    }

    try:
        file_obj = Path(file_path)
        info["exists"] = file_obj.exists()

        if not info["exists"]:
            info["error"] = "Файл не найден"
            return info

        info["size"] = file_obj.stat().st_size

        if info["size"] == 0:
            info["error"] = "Файл пуст"
            return info

        # Быстрая проверка потоков
        cmd = [
            get_ffprobe_path(),
            "-v", "error",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            file_path
        ]

        result = run_subprocess_hidden(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )

        streams = result.stdout.strip().split('\n')
        info["has_video"] = "video" in streams
        info["has_audio"] = "audio" in streams

        # Получаем длительность только если файл валидный
        if info["has_video"] or info["has_audio"]:
            info["duration"] = get_media_duration(file_path, timeout=10)

    except subprocess.TimeoutExpired:
        info["error"] = "Таймаут при анализе"
    except Exception as e:
        info["error"] = str(e)

    return info