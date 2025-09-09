import os
import sys
import subprocess
import json
import logging
import signal
import psutil
from pathlib import Path
from typing import Any
from ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_media_duration as ffmpeg_get_media_duration

# Настройка логгера для модуля
logger = logging.getLogger(__name__)

# Глобальный реестр активных FFmpeg процессов
active_ffmpeg_processes = set()

class ProcessingError(Exception):
    """Исключение для ошибок обработки"""
    pass


def kill_all_ffmpeg_processes():
    """Принудительное завершение всех FFmpeg процессов (РАДИКАЛЬНЫЙ МЕТОД)"""
    print("🔥🔥🔥 KILL_ALL_FFMPEG_PROCESSES ВЫЗВАНА!!! 🔥🔥🔥")
    logger.error("🔥🔥🔥 KILL_ALL_FFMPEG_PROCESSES ВЫЗВАНА!!! 🔥🔥🔥")
    
    try:
        # 1. Быстро завершаем процессы из нашего реестра
        killed_count = 0
        for process in list(active_ffmpeg_processes):
            try:
                if process.poll() is None:  # Процесс еще работает
                    logger.warning(f"Завершаю процесс PID: {process.pid}")
                    process.kill()  # Сразу убиваем
                    killed_count += 1
                active_ffmpeg_processes.discard(process)
            except Exception as e:
                logger.error(f"Ошибка при завершении процесса: {e}")
        
        logger.info(f"✅ Завершено {killed_count} FFmpeg процессов из реестра")
        
        # 2. РАДИКАЛЬНЫЙ МЕТОД - используем системные команды
        import subprocess
        
        if os.name == 'posix':  # Linux/macOS
            try:
                print("🔥🔥🔥 ВЫПОЛНЯЮ KILLALL FFMPEG!!! 🔥🔥🔥")
                logger.error("🔥🔥🔥 ВЫПОЛНЯЮ KILLALL FFMPEG!!! 🔥🔥🔥")
                result1 = subprocess.run(['killall', '-9', 'ffmpeg'], check=False, capture_output=True, text=True)
                result2 = subprocess.run(['killall', '-9', 'ffprobe'], check=False, capture_output=True, text=True)
                print(f"killall ffmpeg result: {result1.returncode}, stderr: {result1.stderr}")
                print(f"killall ffprobe result: {result2.returncode}, stderr: {result2.stderr}")
                logger.error(f"killall ffmpeg result: {result1.returncode}, stderr: {result1.stderr}")
                logger.error(f"killall ffprobe result: {result2.returncode}, stderr: {result2.stderr}")
            except Exception as e:
                print(f"🔥🔥🔥 ОШИБКА KILLALL: {e} 🔥🔥🔥")
                logger.error(f"🔥🔥🔥 ОШИБКА KILLALL: {e} 🔥🔥🔥")
                
            try:
                print("🔥🔥🔥 ВЫПОЛНЯЮ PKILL PROCESS_AUTO_MONTAGE!!! 🔥🔥🔥")
                logger.error("🔥🔥🔥 ВЫПОЛНЯЮ PKILL PROCESS_AUTO_MONTAGE!!! 🔥🔥🔥")
                result3 = subprocess.run(['pkill', '-f', 'process_auto_montage'], check=False, capture_output=True, text=True)
                print(f"pkill result: {result3.returncode}, stderr: {result3.stderr}")
                logger.error(f"pkill result: {result3.returncode}, stderr: {result3.stderr}")
            except Exception as e:
                print(f"🔥🔥🔥 ОШИБКА PKILL: {e} 🔥🔥🔥")
                logger.error(f"🔥🔥🔥 ОШИБКА PKILL: {e} 🔥🔥🔥")
                
        elif os.name == 'nt':  # Windows
            try:
                logger.warning("🔥 РАДИКАЛЬНО убиваем ВСЕ ffmpeg процессы через taskkill...")
                subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], check=False, capture_output=True)
                subprocess.run(['taskkill', '/F', '/IM', 'ffprobe.exe'], check=False, capture_output=True)
                logger.info("✅ taskkill ffmpeg.exe/ffprobe.exe выполнен")
            except Exception as e:
                logger.error(f"Ошибка taskkill: {e}")
                
        logger.info("✅ РАДИКАЛЬНАЯ остановка завершена")
        
        # Проверяем процессы ПОСЛЕ остановки
        try:
            print("🔍 ПРОВЕРЯЕМ ПРОЦЕССЫ ПОСЛЕ ОСТАНОВКИ:")
            logger.error("🔍 ПРОВЕРЯЕМ ПРОЦЕССЫ ПОСЛЕ ОСТАНОВКИ:")
            result_after = subprocess.run(['ps', 'aux'], check=False, capture_output=True, text=True)
            ffmpeg_lines_after = [line for line in result_after.stdout.split('\n') if 'ffmpeg' in line.lower()]
            python_lines_after = [line for line in result_after.stdout.split('\n') if 'python' in line.lower() and 'main' in line]
            
            print(f"ПОСЛЕ: FFmpeg процессов: {len(ffmpeg_lines_after)}")
            print(f"ПОСЛЕ: Python процессов с main: {len(python_lines_after)}")
            logger.error(f"ПОСЛЕ: FFmpeg процессов: {len(ffmpeg_lines_after)}")
            logger.error(f"ПОСЛЕ: Python процессов с main: {len(python_lines_after)}")
            
            if ffmpeg_lines_after:
                print("❌ FFMPEG ПРОЦЕССЫ ВСЕ ЕЩЕ РАБОТАЮТ:")
                logger.error("❌ FFMPEG ПРОЦЕССЫ ВСЕ ЕЩЕ РАБОТАЮТ:")
                for line in ffmpeg_lines_after:
                    print(f"АКТИВНЫЙ FFmpeg: {line}")
                    logger.error(f"АКТИВНЫЙ FFmpeg: {line}")
            else:
                print("✅ FFmpeg процессы остановлены")
                logger.error("✅ FFmpeg процессы остановлены")
                
        except Exception as e:
            print(f"Ошибка проверки процессов после: {e}")
            logger.error(f"Ошибка проверки процессов после: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при завершении FFmpeg процессов: {e}")

BLUE = "\033[94m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
RED = "\033[91m"
RESET = "\033[0m"


def validate_inputs(subscribe_frames_folder, temp_video_path, final_audio_path, logo_path=None, logo2_path=None,
                    subtitles_path=None):
    """Валидация входных файлов и папок"""
    errors = []

    # ИСПРАВЛЕНО: Пропускаем проверку subscribe_frames_folder если он None
    # так как frame_list.txt уже создан и валидирован ранее
    if subscribe_frames_folder is not None and not os.path.exists(subscribe_frames_folder):
        errors.append(f"Папка с кадрами кнопки не найдена: {subscribe_frames_folder}")

    if not os.path.exists(temp_video_path):
        errors.append(f"Временное видео не найдено: {temp_video_path}")

    if not os.path.exists(final_audio_path):
        errors.append(f"Финальное аудио не найдено: {final_audio_path}")

    if logo_path and not os.path.exists(logo_path):
        errors.append(f"Первый логотип не найден: {logo_path}")

    if logo2_path and not os.path.exists(logo2_path):
        errors.append(f"Второй логотип не найден: {logo2_path}")

    if subtitles_path and not os.path.exists(subtitles_path):
        errors.append(f"Файл субтитров не найден: {subtitles_path}")

    return errors


def get_media_duration(file_path):
    """Получить длительность медиафайла"""
    try:
        duration = ffmpeg_get_media_duration(file_path)
        return duration if duration > 0 else None
    except Exception as e:
        logger.error(f"Ошибка при получении длительности {file_path}: {e}")
        return None


def check_audio_streams(file_path):
    """Проверить наличие аудиопотоков в файле"""
    try:
        # Используем простую проверку через FFmpeg вместо ffprobe
        cmd = [get_ffmpeg_path(), "-i", file_path, "-f", "null", "-"]
        # Windows: скрываем командные окна
        kwargs = {'capture_output': True, 'text': True, 'timeout': 180}
        # Более универсальная проверка Windows (включая скомпилированные приложения)
        if (os.name == 'nt' or 'win' in sys.platform.lower()) and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(cmd, **kwargs)
        
        # Ищем информацию об аудиопотоках в stderr
        stderr = result.stderr
        audio_streams = []
        stream_count = 0
        
        for line in stderr.split('\n'):
            if 'Stream #' in line and 'Audio:' in line:
                stream_count += 1
                # Извлекаем базовую информацию о потоке
                if 'mp3' in line.lower():
                    codec = 'mp3'
                elif 'aac' in line.lower():
                    codec = 'aac'
                elif 'wav' in line.lower():
                    codec = 'pcm'
                else:
                    codec = 'unknown'
                
                audio_streams.append({
                    'index': stream_count - 1,
                    'codec_name': codec
                })
        
        logger.info(f"Аудиопотоки в {file_path}: {stream_count} потоков")
        for i, stream in enumerate(audio_streams):
            logger.info(f"  Поток {i}: {stream.get('codec_name', 'unknown')} (индекс: {stream.get('index', 'unknown')})")
        
        return stream_count > 0, audio_streams
        
    except Exception as e:
        logger.error(f"Ошибка при проверке аудиопотоков в {file_path}: {e}")
        return False, []


def run_ffmpeg_command(cmd, description="FFmpeg команда", timeout=1800):  # 30 минут таймаут
    """Безопасное выполнение FFmpeg команды с логированием и возможностью принудительной остановки"""
    logger.info(f"Выполнение: {description}")
    logger.debug(f"Команда: {' '.join(cmd)}")

    process = None
    try:
        # Windows: скрываем командные окна
        kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'text': True}
        # Более универсальная проверка Windows (включая скомпилированные приложения)
        if (os.name == 'nt' or 'win' in sys.platform.lower()) and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            
        # Используем Popen для контроля процесса
        process = subprocess.Popen(cmd, **kwargs)
        
        # Регистрируем процесс в глобальном реестре
        active_ffmpeg_processes.add(process)
        
        # Ждем завершения процесса с проверкой флага остановки И ТАЙМАУТОМ
        import time
        start_time = time.time()
        last_log_time = start_time
        
        while process.poll() is None:
            current_time = time.time()
            elapsed_time = current_time - start_time
            
            # Логируем прогресс каждые 30 секунд
            if current_time - last_log_time >= 30:
                logger.info(f"⏳ FFmpeg выполняется {elapsed_time:.1f}с: {description}")
                last_log_time = current_time
            
            # ПРОВЕРКА ТАЙМАУТА
            if elapsed_time > timeout:
                logger.error(f"⏰ ТАЙМАУТ FFmpeg процесса ({timeout}с): {description}")
                try:
                    process.kill()
                    active_ffmpeg_processes.discard(process)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                except:
                    pass
                break
            
            # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ КАЖДЫЕ 0.05 секунды!
            try:
                import montage_control
                if montage_control.check_stop_flag(f"FFmpeg процесс {description}"):
                    logger.error(f"🛑🔥 ПРИНУДИТЕЛЬНАЯ ОСТАНОВКА FFmpeg: {description}")
                    # СРАЗУ УБИВАЕМ БЕЗ ПОЩАДЫ
                    try:
                        process.kill()
                        logger.error(f"🔥 УБИТ FFmpeg: {description}")
                    except:
                        pass
                    # Убираем из реестра
                    active_ffmpeg_processes.discard(process)
                    # Дополнительно убиваем системной командой
                    try:
                        import subprocess as sp
                        sp.run(["pkill", "-9", "-f", "ffmpeg"], capture_output=True)
                    except:
                        pass
                    raise RuntimeError(f"🛑 FFmpeg процесс ОСТАНОВЛЕН: {description}")
            except RuntimeError:
                raise
            except:
                pass
            time.sleep(0.05)  # В 2 раза чаще проверяем
            
        # Если процесс еще жив после цикла - пытаемся получить результат с таймаутом
        if process.poll() is None:
            logger.warning(f"Процесс все еще выполняется, попытка завершения: {description}")
            try:
                stdout, stderr = process.communicate(timeout=60)  # Дополнительный таймаут на communicate
            except subprocess.TimeoutExpired:
                logger.error(f"Процесс не завершился даже после communicate timeout: {description}")
                process.kill()
                stdout, stderr = process.communicate()
        else:
            stdout, stderr = process.communicate()
        
        # Убираем процесс из реестра после завершения
        active_ffmpeg_processes.discard(process)
        
        # Логируем время выполнения
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"✅ FFmpeg завершен за {execution_time:.1f}с: {description}")
        
        if process.returncode != 0:
            logger.error(f"Ошибка при выполнении {description}: {stderr}")
            logger.error(f"Полная FFmpeg команда: {' '.join(cmd)}")
            raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)
            
        logger.debug(f"stdout: {stdout}")
        if stderr:
            logger.debug(f"stderr: {stderr}")
            
        # Создаем результат как в subprocess.run
        result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
        return result
        
    except subprocess.CalledProcessError as e:
        if process:
            active_ffmpeg_processes.discard(process)
        logger.error(f"Ошибка при выполнении {description}: {e.stderr}")
        logger.error(f"Полная FFmpeg команда: {' '.join(cmd)}")
        raise
    except Exception as e:
        if process:
            active_ffmpeg_processes.discard(process)
        logger.error(f"Неожиданная ошибка при выполнении {description}: {e}")
        logger.error(f"Полная FFmpeg команда: {' '.join(cmd)}")
        raise


def create_subscribe_frame_list(subscribe_frames_folder, temp_folder, frame_rate):
    """Создание списка кадров для кнопки подписки"""
    frame_files = sorted([f for f in os.listdir(subscribe_frames_folder) if f.endswith('.png')])
    num_frames = len(frame_files)

    if num_frames == 0:
        logger.warning(f"Не найдено кадров в папке {subscribe_frames_folder}")
        return None, 0

    logger.info(f"Найдено кадров кнопки 'ПОДПИСЫВАЙТЕСЬ': {num_frames}")

    frame_list_path = os.path.join(temp_folder, "frame_list.txt")
    try:
        with open(frame_list_path, "w", encoding='utf-8') as f:
            for frame_file in frame_files:
                f.write(f"file '{os.path.join(subscribe_frames_folder, frame_file)}'\n")
                f.write(f"duration {1 / frame_rate}\n")
        return frame_list_path, num_frames
    except IOError as e:
        logger.error(f"Ошибка при создании списка кадров: {e}")
        return None, 0


def extract_and_process_clip_audio(clips_info, temp_folder):
    """Извлечение и обработка аудио из клипов"""
    audio_segments = []
    current_time = 0
    last_audio_clip_end_time = 0

    for idx, clip in enumerate(clips_info):
        clip_start_time = current_time
        current_time += clip["duration"]
        
        # Защита от tuple в path
        clip_path = str(clip['path']) if not isinstance(clip['path'], tuple) else str(clip['path'][0]) if clip['path'] else ""
        clip['path'] = clip_path
        
        logger.info(f"🔍 Проверяем клип {idx}: {Path(clip_path).name}, has_audio={clip.get('has_audio', False)}")

        if not clip.get("has_audio", False):
            continue
            
        logger.info(f"🎵 Обрабатываем клип с аудио: {clip_path}")
        
        # Проверяем существование файла
        if not os.path.exists(clip_path):
            logger.error(f"❌ Файл клипа не найден: {clip_path}. Пропускаем извлечение аудио.")
            continue

        # Дополнительная проверка на наличие аудиопотоков прямо перед извлечением
        clip_has_audio_actual, _ = check_audio_streams(clip_path)  # Используем check_audio_streams из final_assembly.py
        if not clip_has_audio_actual:
            logger.warning(f"⚠️ Клип {Path(clip_path).name} помечен как 'has_audio', но FFprobe/FFmpeg не находит аудиопотоков. Пропускаем извлечение аудио.")
            clip["has_audio"] = False  # Обновляем информацию о клипе
            continue

        temp_clip_audio = os.path.join(temp_folder, f"clip_audio_{idx}.mp3")
        temp_clip_audio_mono = os.path.join(temp_folder, f"clip_audio_{idx}_mono.mp3")

        try:
            # Извлечение аудио
            extract_cmd = [
                get_ffmpeg_path(), "-i", clip_path,
                "-map", "0:a:0", "-c:a", "mp3", "-b:a", "128k",
                "-t", str(clip["duration"]),
                "-y", temp_clip_audio
            ]
            run_ffmpeg_command(extract_cmd, f"Извлечение аудио из клипа {idx}")

            # КРИТИЧЕСКАЯ ПРОВЕРКА: Убедимся, что извлеченный файл содержит аудио
            if not os.path.exists(temp_clip_audio) or ffmpeg_get_media_duration(temp_clip_audio) == 0:
                logger.error(f"❌ Извлеченный аудиофайл пуст или не создан: {temp_clip_audio}. Пропускаем.")
                continue

            has_extracted_audio, _ = check_audio_streams(temp_clip_audio)
            if not has_extracted_audio:
                logger.error(f"❌ Извлеченный аудиофайл {temp_clip_audio} не содержит аудиопотоков! Это ошибка FFmpeg. Пропускаем.")
                continue

            # Конвертация в моно (если нужна)
            mono_cmd = [
                get_ffmpeg_path(), "-i", temp_clip_audio,
                "-ac", "1", "-c:a", "mp3", "-b:a", "128k",
                "-y", temp_clip_audio_mono
            ]
            run_ffmpeg_command(mono_cmd, f"Конвертация аудио в моно для клипа {idx}")

            # Проверяем, что моно файл создался
            if not os.path.exists(temp_clip_audio_mono) or ffmpeg_get_media_duration(temp_clip_audio_mono) == 0:
                logger.error(f"❌ Моно аудиофайл пуст или не создан: {temp_clip_audio_mono}. Пропускаем.")
                continue

            audio_segments.append((temp_clip_audio_mono, clip_start_time, clip["duration"]))
            last_audio_clip_end_time = current_time
            logger.info(f"✅ Аудио извлечено из клипа {idx}: {clip_start_time:.2f}с - {current_time:.2f}с")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки аудио для клипа {idx}: {e}. Продолжаем без этого клипа.")
            continue

    return audio_segments, last_audio_clip_end_time


def _parse_silence_duration(silence_duration: str):
    """Парсинг настроек длительности тишины"""
    if isinstance(silence_duration, str) and '-' in silence_duration:
        try:
            min_dur, max_dur = map(float, silence_duration.split('-'))
            if min_dur < 0 or max_dur < 0 or min_dur > max_dur:
                return 0.0, 0.0
            return min_dur, max_dur
        except ValueError:
            return 0.0, 0.0
    elif isinstance(silence_duration, (int, float)):
        if silence_duration < 0:
            return 0.0, 0.0
        return float(silence_duration), float(silence_duration)
    else:
        return 0.0, 0.0


def _folder_sort_key(folder_name: str):
    """Ключ сортировки папок"""
    if folder_name == "root":
        return (0, 0)
    try:
        # Убираем префикс папки если он есть (например "2-11/1-2" -> "1-2")
        clean_folder_name = folder_name.split('/')[-1] if '/' in folder_name else folder_name
        if '-' in clean_folder_name:
            parts = clean_folder_name.split('-')
            start = int(parts[0])
            end = int(parts[1])
        else:
            start = end = int(clean_folder_name)
        return (start, end)
    except (ValueError, IndexError):
        return (float('inf'), float('inf'))


def _parse_folder_range(folder_name: str, overall_range_start: int):
    """Парсинг диапазона папки"""
    if folder_name == "root":
        return (overall_range_start, overall_range_start)
    
    try:
        # Убираем префикс папки если он есть
        clean_folder_name = folder_name.split('/')[-1] if '/' in folder_name else folder_name
        if '-' in clean_folder_name:
            folder_start, folder_end = map(int, clean_folder_name.split('-'))
        else:
            folder_start = folder_end = int(clean_folder_name)
        
        # Абсолютные номера строк
        abs_start = overall_range_start + folder_start - 1
        abs_end = overall_range_start + folder_end - 1
        return (abs_start, abs_end)
    except (ValueError, IndexError):
        return (overall_range_start, overall_range_start)


def _create_silence_segment(output_path: str, duration: float):
    """Создание сегмента тишины"""
    cmd = [
        get_ffmpeg_path(), "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-c:a", "mp3", "-b:a", "128k",
        "-y", output_path
    ]
    run_ffmpeg_command(cmd, f"Создание тишины {duration:.2f}с")


def _concatenate_audio_segments(segments: list, output_path: str, target_duration: float):
    """Объединение аудиосегментов"""
    import tempfile
    
    # Создаем список файлов для конкатенации
    concat_list_path = os.path.join(os.path.dirname(output_path), "sync_audio_concat_list.txt")
    with open(concat_list_path, "w", encoding='utf-8') as f:
        for segment in segments:
            f.write(f"file '{segment}'\n")
    
    # Объединяем все сегменты
    cmd = [
        get_ffmpeg_path(), "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:a", "mp3", "-b:a", "128k", "-ac", "2",
        "-t", str(target_duration),
        "-avoid_negative_ts", "make_zero",
        "-y", output_path
    ]
    
    try:
        run_ffmpeg_command(cmd, "Объединение синхронизированных аудиосегментов")
        return True
    except Exception as e:
        logger.error(f"Ошибка объединения аудиосегментов: {e}")
        return False


def create_synchronized_audio(audio_segments, last_audio_clip_end_time, temp_audio_duration, temp_folder,
                            folder_durations, audio_folder, overall_range_start, overall_range_end, silence_duration):
    """Создание синхронизированной аудиодорожки, соответствующей структуре видео"""
    from pathlib import Path
    
    logger.info("🔍 ЧЕРНЫЙ ЭКРАН DEBUG: create_synchronized_audio")
    logger.info(f"   audio_segments: {len(audio_segments) if audio_segments else 0}")
    logger.info(f"   last_audio_clip_end_time: {last_audio_clip_end_time:.3f}с")
    logger.info(f"   temp_audio_duration (входная): {temp_audio_duration:.3f}с")
    logger.info(f"   folder_durations: {folder_durations}")
    logger.info(f"   audio_folder: {audio_folder}")
    logger.info(f"   overall_range: {overall_range_start}-{overall_range_end}")
    
    logger.info("🎯 Создание синхронизированной аудиодорожки")
    logger.info(f"   folder_durations: {folder_durations}")
    
    # Парсим настройки пауз
    min_silence, max_silence = _parse_silence_duration(silence_duration)
    avg_silence = (min_silence + max_silence) / 2.0
    logger.info(f"🔍 DEBUG: Пауза между аудиофайлами: {avg_silence:.3f}с")
    
    # Создаем отдельные аудиосегменты согласно структуре папок
    audio_segments_list = []
    
    # Сначала добавляем тишину для смещения (если есть клипы с аудио)
    if last_audio_clip_end_time > 0:
        silence_path = os.path.join(temp_folder, "sync_silence_padding.mp3")
        _create_silence_segment(silence_path, last_audio_clip_end_time)
        audio_segments_list.append(silence_path)
        logger.info(f"   🔇 Добавлена тишина смещения: {last_audio_clip_end_time:.2f}с")
    
    # Создаем сегменты для каждой папки
    # Защита от tuple в audio_folder
    safe_audio_folder = str(audio_folder) if not isinstance(audio_folder, tuple) else str(audio_folder[0]) if audio_folder else ""
    audio_folder_path = Path(safe_audio_folder)
    current_row = overall_range_start
    
    for folder_name in sorted(folder_durations.keys(), key=_folder_sort_key):
        if folder_durations[folder_name] <= 0:
            continue
            
        logger.info(f"   📁 Обрабатываем папку: {folder_name}")
        
        # Определяем диапазон строк для папки  
        folder_range = _parse_folder_range(folder_name, overall_range_start)
        
        for row_num in range(folder_range[0], folder_range[1] + 1):
            # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ!
            try:
                import montage_control
                if montage_control.check_stop_flag(f"final_assembly аудио цикл строка {row_num}"):
                    logger.error("🛑 ОСТАНОВКА МОНТАЖА в final_assembly!")
                    return None
            except:
                pass
                
            audio_filename = f"{str(row_num).zfill(3)}.mp3"
            audio_file = audio_folder_path / audio_filename
            
            if audio_file.exists():
                audio_segments_list.append(str(audio_file))
                logger.info(f"     🎵 Добавлен: {audio_filename}")
                
                # Добавляем паузу после файла (кроме последнего в папке)
                if row_num < folder_range[1] and avg_silence > 0:
                    pause_path = os.path.join(temp_folder, f"sync_pause_{row_num}.mp3")
                    _create_silence_segment(pause_path, avg_silence)
                    audio_segments_list.append(pause_path)
                    logger.info(f"     🔇 Добавлена пауза: {avg_silence:.2f}с")
    
    # Объединяем все сегменты в основную дорожку
    main_audio_path = os.path.join(temp_folder, "synchronized_main_audio.mp3")
    if not _concatenate_audio_segments(audio_segments_list, main_audio_path, temp_audio_duration):
        logger.error("❌ Ошибка создания синхронизированной основной дорожки")
        return None
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавляем смешивание аудио из клипов
    if audio_segments and len(audio_segments) > 0:
        logger.info(f"🎵 Смешиваем аудио из {len(audio_segments)} клипов с основной дорожкой")
        
        # Создание объединенного аудио с клипами
        combined_audio_path = os.path.join(temp_folder, "synchronized_combined_audio.mp3")
        
        # Создание команды для микширования
        inputs = []
        filter_parts = []
        input_count = 0
        
        # Добавляем основное аудио как базовый слой
        inputs.extend(["-i", main_audio_path])
        filter_parts.append(f"[{input_count}:a]volume=1.0[main_audio]")
        input_count += 1
        
        # Добавление аудио клипов поверх основного
        clip_filters = []
        for i, (clip_audio, start_time, duration) in enumerate(audio_segments):
            inputs.extend(["-i", clip_audio])
            # Создаем фильтр для каждого клипа с точным позиционированием
            filter_parts.append(
                f"[{input_count}:a]adelay={int(start_time * 1000)}|0,asetpts=PTS-STARTPTS,apad=pad_dur={temp_audio_duration - start_time - duration}[clip{i}]")
            clip_filters.append(f"[clip{i}]")
            input_count += 1
        
        # Объединяем основное аудио с клипами
        if clip_filters:
            all_inputs = "[main_audio]" + "".join(clip_filters)
            filter_parts.append(f"{all_inputs}amix=inputs={len(clip_filters) + 1}:duration=longest:normalize=0[outa]")
            output_map = "[outa]"
        else:
            output_map = "[main_audio]"
        
        logger.info(f"Создаем микс из {len(clip_filters) + 1} аудиодорожек")
        
        mix_cmd = [get_ffmpeg_path()] + inputs + [
            "-filter_complex", ";".join(filter_parts),
            "-map", output_map, "-c:a", "mp3", "-b:a", "128k",
            "-t", str(temp_audio_duration),
            "-avoid_negative_ts", "make_zero",
            "-y", combined_audio_path
        ]
        
        run_ffmpeg_command(mix_cmd, "Смешивание синхронизированного аудио с клипами")
        
        # Проверяем результат
        if os.path.exists(combined_audio_path):
            combined_actual_duration = get_media_duration(combined_audio_path)
            logger.info("✅ Синхронизированная аудиодорожка с клипами создана успешно")
            logger.info(f"🔍 DEBUG: Возврат combined_audio: {combined_audio_path}, {temp_audio_duration:.3f}с (фактически: {combined_actual_duration:.3f}с)")
            return combined_audio_path, combined_actual_duration
        else:
            main_actual_duration = get_media_duration(main_audio_path) if os.path.exists(main_audio_path) else 0
            logger.error("❌ Ошибка смешивания синхронизированного аудио")
            logger.info(f"🔍 DEBUG: Возврат main_audio: {main_audio_path}, {temp_audio_duration:.3f}с (фактически: {main_actual_duration:.3f}с)")
            return main_audio_path, main_actual_duration
    else:
        main_actual_duration = get_media_duration(main_audio_path) if os.path.exists(main_audio_path) else 0
        logger.info("📻 Нет аудио из клипов для смешивания, используем только основную дорожку")
        logger.info(f"🔍 DEBUG: Возврат main_audio (без клипов): {main_audio_path}, {temp_audio_duration:.3f}с (фактически: {main_actual_duration:.3f}с)")
        return main_audio_path, main_actual_duration


def create_combined_audio(final_audio_path, audio_segments, last_audio_clip_end_time, temp_audio_duration, temp_folder, folder_durations=None, audio_folder=None, overall_range_start=None, overall_range_end=None, silence_duration="1.0-2.5"):
    """Создание объединенного аудиофайла с правильным смещением озвучки"""
    logger.info("🔍 ЧЕРНЫЙ ЭКРАН DEBUG: create_combined_audio")
    logger.info(f"   final_audio_path: {final_audio_path}")
    logger.info(f"   audio_segments: {len(audio_segments) if audio_segments else 0}")
    logger.info(f"   last_audio_clip_end_time: {last_audio_clip_end_time:.3f}с")
    logger.info(f"   temp_audio_duration: {temp_audio_duration:.3f}с")
    logger.info(f"   folder_durations: {folder_durations is not None}")
    logger.info(f"   audio_folder: {audio_folder}")
    logger.info(f"   overall_range: {overall_range_start}-{overall_range_end}")
    
    logger.info("Создание объединенного аудио...")
    logger.info(
        f"Параметры: last_audio_clip_end_time={last_audio_clip_end_time:.2f}с, temp_audio_duration={temp_audio_duration:.2f}с")

    # НОВАЯ ЛОГИКА: Если переданы параметры синхронизации, создаем синхронизированную аудиодорожку
    if folder_durations and audio_folder and overall_range_start is not None and overall_range_end is not None:
        logger.info("🔄 Создание синхронизированной аудиодорожки с учетом структуры видео")
        return create_synchronized_audio(audio_segments, last_audio_clip_end_time, temp_audio_duration, temp_folder, 
                                       folder_durations, audio_folder, overall_range_start, overall_range_end, silence_duration)

    # СТАРАЯ ЛОГИКА: Используем готовую аудиодорожку
    logger.info("📻 Используем готовую аудиодорожку (старая логика)")
    
    # Проверяем исходное аудио
    has_audio, streams = check_audio_streams(final_audio_path)
    if not has_audio:
        logger.error(f"В файле {final_audio_path} отсутствуют аудиопотоки!")
        return None

    # Перекодирование основного аудио с явным указанием потока
    reencoded_audio_path = os.path.join(temp_folder, "reencoded_final_audio.mp3")
    reencode_cmd = [
        get_ffmpeg_path(), "-i", final_audio_path,
        "-map", "0:a:0",  # Явно указываем первый аудиопоток
        "-c:a", "mp3", "-b:a", "128k", "-ac", "2",  # Стерео
        "-avoid_negative_ts", "make_zero",
        "-y", reencoded_audio_path
    ]
    run_ffmpeg_command(reencode_cmd, "Перекодирование основного аудио")

    # Проверяем перекодированное аудио
    has_audio_reenc, _ = check_audio_streams(reencoded_audio_path)
    if not has_audio_reenc:
        logger.error("Перекодированное аудио не содержит звука!")
        return None

    reencoded_duration = get_media_duration(reencoded_audio_path)
    if reencoded_duration is None:
        raise ValueError("Не удалось получить длительность перекодированного аудио")

    logger.info(f"Длительность перекодированного аудио: {reencoded_duration:.2f}с")

    # Если нет аудио клипов, основное аудио начинается с начала
    if not audio_segments:
        logger.info("Аудио клипов нет, используем только основное аудио с начала")

        # Создаем финальное аудио нужной длительности
        combined_audio_path = os.path.join(temp_folder, "combined_audio.mp3")

        if reencoded_duration >= temp_audio_duration:
            # Обрезаем до нужной длительности
            final_cmd = [
                get_ffmpeg_path(), "-i", reencoded_audio_path,
                "-t", str(temp_audio_duration),
                "-c:a", "copy",
                "-avoid_negative_ts", "make_zero",
                "-y", combined_audio_path
            ]
        else:
            # Добавляем тишину до нужной длительности
            padding_duration = temp_audio_duration - reencoded_duration
            final_cmd = [
                get_ffmpeg_path(), "-i", reencoded_audio_path,
                "-af", f"apad=pad_dur={padding_duration}",
                "-c:a", "mp3", "-b:a", "128k",
                "-t", str(temp_audio_duration),
                "-avoid_negative_ts", "make_zero",
                "-y", combined_audio_path
            ]

        run_ffmpeg_command(final_cmd, "Создание финального аудио")
        
        # ИСПРАВЛЕНИЕ: Возвращаем фактическую длительность
        actual_duration = get_media_duration(combined_audio_path)
        logger.info(f"Теоретическая длительность была: {temp_audio_duration:.2f}с, фактическая: {actual_duration:.2f}с")
        return combined_audio_path, actual_duration

    # ИСПРАВЛЕННАЯ ЛОГИКА: Основное аудио смещается на время клипов с аудио
    logger.info(f"Есть аудио клипы, основное аудио начнется с {last_audio_clip_end_time:.2f}с")
    
    # Пересчитываем общую длительность: время клипов + полная длительность основного аудио
    new_total_duration = last_audio_clip_end_time + reencoded_duration
    logger.info(f"Новая общая длительность видео: {new_total_duration:.2f}с (клипы: {last_audio_clip_end_time:.2f}с + основное аудио: {reencoded_duration:.2f}с)")
    
    # Обновляем temp_audio_duration для корректной работы остальной логики
    temp_audio_duration = new_total_duration

    # Создаем основное аудио со смещением (тишина + полное аудио)
    delayed_main_audio_path = os.path.join(temp_folder, "delayed_main_audio.mp3")
    
    # Используем ПОЛНУЮ длительность основного аудио без обрезки
    main_audio_duration = reencoded_duration

    # Сначала создаем тишину нужной длительности
    silence_path = os.path.join(temp_folder, "silence_padding.mp3")
    silence_cmd = [
        get_ffmpeg_path(), "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(last_audio_clip_end_time),
        "-c:a", "mp3", "-b:a", "128k",
        "-y", silence_path
    ]
    run_ffmpeg_command(silence_cmd, "Создание тишины для смещения")

    # Не обрезаем основное аудио - используем полностью
    # trimmed_main_audio_path = reencoded_audio_path  # Просто ссылаемся на полное аудио
    
    # Создаем список файлов для конкатенации
    concat_list_path = os.path.join(temp_folder, "audio_concat_list.txt")
    with open(concat_list_path, "w", encoding='utf-8') as f:
        f.write(f"file '{silence_path}'\n")
        f.write(f"file '{reencoded_audio_path}'\n")  # Используем полное аудио

    # Объединяем тишину и полное основное аудио
    concat_cmd = [
        get_ffmpeg_path(), "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:a", "mp3", "-b:a", "128k",
        "-t", str(temp_audio_duration),
        "-avoid_negative_ts", "make_zero",
        "-y", delayed_main_audio_path
    ]
    run_ffmpeg_command(concat_cmd, "Объединение тишины и полного основного аудио")

    # Создание объединенного аудио с клипами
    combined_audio_path = os.path.join(temp_folder, "combined_audio.mp3")

    # Создание команды для микширования
    inputs = []
    filter_parts = []
    input_count = 0

    # Добавляем основное аудио со смещением как базовый слой
    inputs.extend(["-i", delayed_main_audio_path])
    filter_parts.append(f"[{input_count}:a]volume=1.0[main_audio]")
    input_count += 1

    # Добавление аудио клипов поверх основного
    clip_filters = []
    for i, (clip_audio, start_time, duration) in enumerate(audio_segments):
        inputs.extend(["-i", clip_audio])
        # Создаем фильтр для каждого клипа с точным позиционированием
        filter_parts.append(
            f"[{input_count}:a]adelay={int(start_time * 1000)}|0,asetpts=PTS-STARTPTS,apad=pad_dur={temp_audio_duration - start_time - duration}[clip{i}]")
        clip_filters.append(f"[clip{i}]")
        input_count += 1

    # Объединяем основное аудио с клипами
    if clip_filters:
        all_inputs = "[main_audio]" + "".join(clip_filters)
        filter_parts.append(f"{all_inputs}amix=inputs={len(clip_filters) + 1}:duration=longest:normalize=0[outa]")
        output_map = "[outa]"
    else:
        output_map = "[main_audio]"

    logger.info(f"Создаем микс из {len(clip_filters) + 1} аудиодорожек")

    mix_cmd = [get_ffmpeg_path()] + inputs + [
        "-filter_complex", ";".join(filter_parts),
        "-map", output_map, "-c:a", "mp3", "-b:a", "128k",
        "-t", str(temp_audio_duration),
        "-avoid_negative_ts", "make_zero",
        "-y", combined_audio_path
    ]

    run_ffmpeg_command(mix_cmd, "Объединение всех аудиодорожек")

    # Проверяем финальное аудио
    has_final_audio, _ = check_audio_streams(combined_audio_path)
    if not has_final_audio:
        logger.error("Финальное объединенное аудио не содержит звука!")
        return None

    final_combined_duration = get_media_duration(combined_audio_path)
    logger.info(f"Длительность финального объединенного аудио: {final_combined_duration:.2f}с")
    logger.info(f"Основное аудио будет играть с {last_audio_clip_end_time:.2f}с до конца видео")

    # ИСПРАВЛЕНИЕ: Возвращаем фактическую длительность вместо теоретической
    logger.info(f"Теоретическая длительность была: {temp_audio_duration:.2f}с, фактическая: {final_combined_duration:.2f}с")
    return combined_audio_path, final_combined_duration


def verify_audio_quality(audio_path, expected_duration, test_times=[60, 120]):
    """Проверка качества аудио в определенные моменты времени"""
    has_audio, streams = check_audio_streams(audio_path)
    if not has_audio:
        logger.error(f"В файле {audio_path} отсутствуют аудиопотоки!")
        return False

    audio_duration = get_media_duration(audio_path)
    if audio_duration is None:
        return False

    logger.info(f"Длительность аудио: {audio_duration:.2f}с (ожидалось: {expected_duration:.2f}с)")

    # Допуск в 0.1 секунды (100 миллисекунд) обычно достаточен.
    DURATION_TOLERANCE_SECONDS = 60.0
    
    if abs(audio_duration - expected_duration) > DURATION_TOLERANCE_SECONDS:
        logger.warning(f"Длительность аудио не соответствует ожидаемой. Ожидалось: {expected_duration:.2f}с, Фактически: {audio_duration:.2f}с, Разница: {abs(audio_duration - expected_duration):.2f}с. Допуск: {DURATION_TOLERANCE_SECONDS:.2f}с")
        return False
    else:
        logger.info(f"✅ Проверка длительности аудио пройдена. Ожидалось: {expected_duration:.2f}с, Фактически: {audio_duration:.2f}с, Разница: {abs(audio_duration - expected_duration):.2f}с.")

    # Проверка наличия звука в указанные моменты времени
    for test_time in test_times:
        if test_time >= audio_duration:
            continue

        # Кроссплатформенный временный файл (Windows/macOS/Linux)
        import tempfile
        test_segment_path = tempfile.mktemp(suffix=f"_test_segment_{test_time}.mp3")
        try:
            test_cmd = [
                get_ffmpeg_path(), "-i", audio_path,
                "-ss", str(test_time), "-t", "5",
                "-map", "0:a:0", "-c:a", "mp3",
                "-y", test_segment_path
            ]
            run_ffmpeg_command(test_cmd, f"Проверка звука на {test_time}с")

            segment_duration = get_media_duration(test_segment_path)
            if segment_duration is None or segment_duration < 1.0:
                logger.warning(f"Звук отсутствует на {test_time}с")
                return False

        except Exception as e:
            logger.error(f"Ошибка при проверке звука на {test_time}с: {e}")
            return False
        finally:
            if os.path.exists(test_segment_path):
                os.remove(test_segment_path)

    return True


def assemble_final_video(video_path: str, audio_path: str, output_folder: str, output_filename: str, config: Any) -> str:
    """Функция финальной сборки видео с аудио с улучшенной диагностикой"""
    logger.info(f"🎥 Собираем финальное видео: {Path(video_path).name} + {Path(audio_path).name}")
    final_output_path = os.path.join(output_folder, output_filename)

    # --- КРИТИЧЕСКАЯ ДИАГНОСТИКА: Проверка входных файлов ---
    logger.debug(f"DEBUG: Проверяем существование video_path: {video_path}")
    if not Path(video_path).exists():
        logger.error(f"❌ Видеофайл для сборки не найден: {video_path}")
        raise ProcessingError(f"Видеофайл для сборки не найден: {video_path}")

    logger.debug(f"DEBUG: Проверяем существование audio_path: {audio_path}")
    if not Path(audio_path).exists():
        logger.error(f"❌ Аудиофайл для сборки не найден: {audio_path}")
        raise ProcessingError(f"Аудиофайл для сборки не найден: {audio_path}")

    # Получим информацию о потоках в аудиофайле перед сборкой
    try:
        logger.debug(f"DEBUG: Выполняем ffprobe для проверки аудиофайла: {audio_path}")
        ffprobe_audio_check_cmd = [
            get_ffprobe_path(), "-v", "error",
            "-show_entries", "stream=codec_name,channels,duration",
            "-of", "json",
            str(audio_path)
        ]
        ffprobe_audio_check_result = subprocess.run(ffprobe_audio_check_cmd, capture_output=True, text=True, check=True, timeout=10)
        audio_data = json.loads(ffprobe_audio_check_result.stdout)

        logger.debug(f"DEBUG: ffprobe вывод для {Path(audio_path).name}:\n{json.dumps(audio_data, indent=2)}")

        audio_streams_found = 0
        for stream in audio_data.get('streams', []):
            if stream.get('codec_type') == 'audio':
                audio_streams_found += 1
                logger.debug(f"DEBUG: Найден аудиопоток в {Path(audio_path).name}: кодек={stream.get('codec_name')}, каналов={stream.get('channels')}, длительность={stream.get('duration')}")

        if audio_streams_found == 0:
            logger.error(f"❌ Аудиофайл {Path(audio_path).name} не содержит аудиопотоков. Невозможно собрать видео с аудио.")
            raise ProcessingError(f"Аудиофайл {Path(audio_path).name} не содержит аудиопотоков.")

    except Exception as e:
        logger.error(f"❌ Ошибка ffprobe при проверке аудиофайла {audio_path}: {e}")
        raise ProcessingError(f"Ошибка ffprobe при проверке аудиофайла {audio_path}.")
    # --- КОНЕЦ ДИАГНОСТИКИ ---

    try:
        # --- КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ ФИНАЛЬНОЙ КОМАНДЫ FFmpeg ---
        cmd = [
            get_ffmpeg_path(),
            "-v", "debug", # Максимальный уровень отладки для финальной сборки
            "-i", video_path,  # Вход 0: Видео
            "-i", audio_path,  # Вход 1: Аудио (наш final_audio_with_music.mp3)
            "-c:v", "copy",    # Копируем видео без перекодировки
            "-c:a", "aac",     # Оставляем AAC здесь, так как MP3 может быть проблемой для MP4 контейнера
            "-b:a", "192k",    # Битрейт аудио
            "-strict", "-2",   # <--- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен флаг -strict -2
            "-async", "1",     # <--- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен флаг -async 1
            "-map", "0:v:0",   # Мапим первый видеопоток из первого входа
            "-map", "1:a:0",   # Мапим первый аудиопоток из второго входа
            "-movflags", "+faststart",
            "-shortest", # <--- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен флаг -shortest
            "-y", final_output_path
        ]

        logger.debug(f"DEBUG: Путь к видео для финальной сборки: {video_path}")
        logger.debug(f"DEBUG: Путь к аудио для финальной сборки: {audio_path}")
        logger.debug(f"DEBUG: Ожидаемый финальный выходной файл: {final_output_path}")
        logger.debug(f"DEBUG: Финальная команда FFmpeg для сборки видео+аудио: {' '.join(cmd)}")

        run_ffmpeg_command(cmd, "Финальная сборка видео и аудио")

        logger.debug(f"DEBUG: FFmpeg завершил финальную сборку. Проверяем выходной файл...")
        if not Path(final_output_path).exists():
            logger.error(f"❌ Финальный видеофайл не создан: {final_output_path}")
            raise ProcessingError(f"Финальный видеофайл не создан: {final_output_path}")

        logger.info(f"✅ Финальное видео успешно собрано: {final_output_path}")

        # --- НОВАЯ ПРОВЕРКА: ffprobe для финального видео ---
        try:
            ffprobe_path = get_ffprobe_path()
            probe_cmd = [
                ffprobe_path,
                "-v", "error",
                "-select_streams", "a",  # Выбираем только аудиопотоки
                "-show_entries", "stream=codec_name,channels,sample_rate,duration",
                "-of", "json",
                final_output_path
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True, timeout=10)
            probe_data = json.loads(probe_result.stdout)

            if 'streams' in probe_data and probe_data['streams']:
                for stream in probe_data['streams']:
                    logger.info(f"🔍 FFprobe на {Path(final_output_path).name}: Аудиопоток найден: "
                                f"кодек={stream.get('codec_name')}, "
                                f"каналов={stream.get('channels')}, "
                                f"частота={stream.get('sample_rate')}, "
                                f"длительность={stream.get('duration')}")
            else:
                logger.warning(f"⚠️ FFprobe на {Path(final_output_path).name}: Аудиопотоки не найдены!")
        except Exception as e:
            logger.error(f"❌ Ошибка FFprobe для {Path(final_output_path).name}: {e}")
        # --- КОНЕЦ НОВОЙ ПРОВЕРКИ ---

        return final_output_path

    except Exception as e:
        logger.error(f"❌ Критическая ошибка при сборке финального видео: {e}")
        import traceback
        logger.error(f"Подробности ошибки финальной сборки: {traceback.format_exc()}")
        raise ProcessingError(f"Ошибка при сборке финального видео: {e}")


def final_assembly(temp_video_path, final_audio_path, output_file, temp_folder, frame_list_path, num_frames, logo_path,
                   subtitles_path, video_resolution, frame_rate, video_crf, video_preset, temp_audio_duration,
                   logo_width, logo_position_x, logo_position_y, logo_duration, subscribe_width, subscribe_position_x,
                   subscribe_position_y, subscribe_display_duration, subscribe_interval_gap, subtitles_enabled,
                   logo2_path=None, logo2_width=None, logo2_position_x=None, logo2_position_y=None, logo2_duration=None,
                   subscribe_duration="all", clips_info=None, audio_offset=0, 
                   folder_durations=None, audio_folder=None, overall_range_start=None, overall_range_end=None, silence_duration="1.0-2.5",
                   adjust_videos_to_audio=True, transitions_enabled=False, transition_duration=1.0, video_codec="libx264"):
    """
    Основная функция финальной сборки видео
    
    ВНИМАНИЕ: В новой попапочной логике temp_video_path уже содержит объединенное аудио.
    Функция теперь работает с видео, которое УЖЕ содержит нужный звуковой ряд.
    final_audio_path используется ТОЛЬКО для расчета длительности, не для добавления аудио.
    """
    
    # ЗАЩИТА ОТ TUPLE/LIST: Конвертируем все пути в строки ПЕРВЫМ ДЕЛОМ
    def safe_path_convert(path):
        if isinstance(path, (list, tuple)) and path:
            return str(path[0])
        elif isinstance(path, str) and path.startswith('[') and path.endswith(']'):
            # Обрабатываем строки вида "['path']" - строковое представление списка
            try:
                import ast
                parsed = ast.literal_eval(path)
                if isinstance(parsed, (list, tuple)) and parsed:
                    return str(parsed[0])
            except:
                pass
        
        if path:
            return str(path)
        return ""
    
    temp_video_path = safe_path_convert(temp_video_path)
    final_audio_path = safe_path_convert(final_audio_path)
    output_file = safe_path_convert(output_file)
    temp_folder = safe_path_convert(temp_folder)
    frame_list_path = safe_path_convert(frame_list_path) if frame_list_path else None
    logo_path = safe_path_convert(logo_path) if logo_path else None
    logo2_path = safe_path_convert(logo2_path) if logo2_path else None  
    subtitles_path = safe_path_convert(subtitles_path) if subtitles_path else None
    audio_folder = safe_path_convert(audio_folder) if audio_folder else None

    logger.info(f"🔍 ЧЕРНЫЙ ЭКРАН DEBUG: Начало финальной сборки: {output_file}")
    
    # ЧЕРНЫЙ ЭКРАН DEBUG: Проверяем входные файлы
    temp_video_duration = get_media_duration(temp_video_path) if os.path.exists(temp_video_path) else 0
    final_audio_file_duration = get_media_duration(final_audio_path) if os.path.exists(final_audio_path) else 0
    
    logger.info(f"🔍 ЧЕРНЫЙ ЭКРАН DEBUG: Входные файлы")
    logger.info(f"   temp_video_path: {temp_video_path} (длительность: {temp_video_duration:.3f}с)")
    logger.info(f"   final_audio_path: {final_audio_path} (длительность: {final_audio_file_duration:.3f}с)")
    logger.info(f"   🚨 КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: ИМУПРАВИЛЬНЫЙ АУДИОФАЙЛ? {final_audio_path}")
    logger.info(f"   🚨 ПРОВЕРКА: Содержит ли 'final_audio_with_music' в пути: {'final_audio_with_music' in final_audio_path}")
    logger.info(f"   temp_audio_duration (параметр): {temp_audio_duration:.3f}с")
    logger.info(f"   audio_offset: {audio_offset:.3f}с")
    logger.info(f"   adjust_videos_to_audio: {adjust_videos_to_audio}")
    
    # Дополнительная диагностика содержимого файла
    try:
        import subprocess
        import json
        probe_cmd = [
            get_ffprobe_path(),
            "-v", "error", 
            "-select_streams", "a",
            "-show_entries", "stream=codec_name,channels,duration,bit_rate",
            "-of", "json",
            final_audio_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True, timeout=10)
        probe_data = json.loads(probe_result.stdout)
        logger.info(f"   🔍 ДИАГНОСТИКА АУДИОФАЙЛА final_assembly: {probe_data}")
    except Exception as e:
        logger.error(f"   ❌ Ошибка диагностики аудиофайла: {e}")
    
    # ИСПРАВЛЕНИЕ ЛОГИКИ: При adjust_videos_to_audio=false видео НЕ растягивается, но аудио остается полным
    if adjust_videos_to_audio:
        target_video_duration = temp_audio_duration
        logger.info(f"✅ Режим подстройки видео под аудио: целевая длительность {target_video_duration:.2f}с")
    else:
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: При adjust_videos_to_audio=false финальное видео все равно должно иметь полную длительность аудио
        # Видео будет зациклено/повторено до полной длительности аудио
        target_video_duration = temp_audio_duration
        logger.info(f"⚠️ Режим без подстройки видео: видео ({temp_video_duration:.2f}с) будет адаптировано под аудио ({temp_audio_duration:.2f}с)")
        logger.info(f"   Финальное видео будет иметь длительность аудио: {target_video_duration:.2f}с")
        if temp_video_duration != temp_audio_duration:
            logger.warning(f"🔄 Видео короче аудио - может потребоваться зацикливание или заполнение")

    # Исправляем subscribe_width - принудительно делаем четным для libx264
    if subscribe_width % 2 != 0:
        subscribe_width = subscribe_width - 1
        logger.debug(f"Исправлен subscribe_width до четного числа: {subscribe_width}")

    # Проверка существования готового файла
    if os.path.exists(output_file):
        logger.info(f"Готовое видео уже существует: {output_file}")
        return output_file

    try:
        # Валидация входных данных (исключаем проверку subscribe_frames_folder так как frame_list уже создан)
        validation_errors = validate_inputs(
            None, temp_video_path, final_audio_path,
            logo_path, logo2_path, subtitles_path
        )

        if validation_errors:
            for error in validation_errors:
                logger.error(error)
            return None

        # Проверяем исходные файлы на наличие аудио
        logger.info("Проверка исходных файлов...")
        temp_video_has_audio, _ = check_audio_streams(temp_video_path)
        final_audio_has_audio, _ = check_audio_streams(final_audio_path)

        logger.info(f"Временное видео имеет аудио: {temp_video_has_audio}")
        logger.info(f"Финальное аудио имеет звук: {final_audio_has_audio}")

        # Создание отладочного файла кнопки
        subscribe_debug_path = os.path.join(temp_folder, "subscribe_debug.mp4")
        debug_cmd = [
            get_ffmpeg_path(),
            "-f", "concat", "-safe", "0", "-i", frame_list_path,
            "-vf",
            f"loop=loop=-1:size=1:start=0,trim=0:10,scale={subscribe_width}:-2:force_divisible_by=2,format=yuva420p",
            "-c:v", video_codec, "-t", "10", "-y", subscribe_debug_path
        ]
        run_ffmpeg_command(debug_cmd, "Создание отладочного файла кнопки")

        # ЗАЩИТА ОТ TUPLE/LIST: Обрабатываем clips_info
        if clips_info:
            # Конвертируем все пути в clips_info из tuple/list в строки
            for clip in clips_info:
                if 'path' in clip:
                    clip['path'] = safe_path_convert(clip['path'])
            
            logger.info(f"Обрабатываем {len(clips_info)} клипов")
            for i, clip in enumerate(clips_info):
                # КРИТИЧЕСКАЯ ПРОВЕРКА ОСТАНОВКИ!
                try:
                    import montage_control
                    if montage_control.check_stop_flag(f"final_assembly обработка клипа {i+1}"):
                        logger.error("🛑 ОСТАНОВКА МОНТАЖА при обработке клипов!")
                        return None
                except:
                    pass
                    
                logger.info(
                    f"Клип {i}: длительность={clip.get('duration', 0):.2f}с, аудио={clip.get('has_audio', False)}")
            audio_segments, last_audio_clip_end_time = extract_and_process_clip_audio(clips_info, temp_folder)
            logger.info(
                f"Получено {len(audio_segments)} аудиосегментов, последний клип заканчивается на {last_audio_clip_end_time:.2f}с")
        else:
            logger.info("Клипы отсутствуют")
            audio_segments, last_audio_clip_end_time = [], 0

        # ЧЕРНЫЙ ЭКРАН DEBUG: Диагностика перед созданием combined_audio
        logger.info(f"🔍 ЧЕРНЫЙ ЭКРАН DEBUG: Перед created_combined_audio")
        logger.info(f"   final_audio_path: {final_audio_path}")
        logger.info(f"   audio_segments: {len(audio_segments)}")
        logger.info(f"   last_audio_clip_end_time: {last_audio_clip_end_time:.3f}с")
        logger.info(f"   temp_audio_duration (входной): {temp_audio_duration:.3f}с")
        
        # Создание объединенного аудио с полной длительностью
        logger.info(f"🔍 ИСПРАВЛЕНИЕ: Создание combined_audio с длительностью {target_video_duration:.2f}с")
        result = create_combined_audio(
            final_audio_path, audio_segments, last_audio_clip_end_time,
            target_video_duration, temp_folder, folder_durations, audio_folder, 
            overall_range_start, overall_range_end, silence_duration
        )

        if result is None:
            logger.error("Не удалось создать объединенное аудио")
            return None
            
        combined_audio_path, updated_audio_duration = result
        
        # ЧЕРНЫЙ ЭКРАН DEBUG: Диагностика после create_combined_audio
        logger.info(f"🔍 ЧЕРНЫЙ ЭКРАН DEBUG: После create_combined_audio")
        logger.info(f"   combined_audio_path: {combined_audio_path}")
        logger.info(f"   updated_audio_duration: {updated_audio_duration:.3f}с")
        combined_actual_duration = get_media_duration(combined_audio_path) if os.path.exists(combined_audio_path) else 0
        logger.info(f"   combined_audio фактическая длительность: {combined_actual_duration:.3f}с")

        # Проверка качества аудио с обновленной длительностью
        if not verify_audio_quality(combined_audio_path, updated_audio_duration):
            logger.error("Проверка качества аудио не пройдена")
            return None
            
        # СОГЛАСНО EXCEL ЛОГИКЕ: Используем combined_audio с правильной длительностью
        final_audio_duration = get_media_duration(final_audio_path)
        logger.info(f"🎵 Длительности: combined_audio={updated_audio_duration:.2f}с, final_audio={final_audio_duration:.2f}с")
        
        # ИСПРАВЛЕНИЕ: Получаем длительность от правильного файла final_audio_path
        final_audio_duration_actual = get_media_duration(final_audio_path) if os.path.exists(final_audio_path) else temp_audio_duration
        temp_audio_duration = final_audio_duration_actual
        logger.info(f"🎯 ИСПРАВЛЕНИЕ: Используем длительность final_audio_path: {temp_audio_duration:.2f}с")
        logger.info(f"   (Игнорируем combined_audio длительность: {updated_audio_duration:.2f}с)")

        # Создание интервалов наложения кнопки подписки
        overlay_intervals = []
        
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение длительности для кнопки подписки
        try:
            video_duration = get_media_duration(temp_video_path)
            logger.info(f"📹 Длительность видео: {video_duration:.2f}с, аудио: {temp_audio_duration:.2f}с")
            
            # ЧЕРНЫЙ ЭКРАН DEBUG: Проверяем что temp_video_path существует и имеет правильную длительность
            if not os.path.exists(temp_video_path):
                logger.error(f"🚨 ЧЕРНЫЙ ЭКРАН: temp_video_path НЕ СУЩЕСТВУЕТ: {temp_video_path}")
            else:
                logger.info(f"🔍 ЧЕРНЫЙ ЭКРАН DEBUG: temp_video корректен")
                
        except Exception as e:
            logger.error(f"Ошибка получения длительности видео: {e}")
            video_duration = temp_audio_duration
        
        # ИСПРАВЛЕНО: Логика определения максимального времени показа кнопки
        # Кнопка может показываться на протяжении всего аудио,
        # но не должна появляться на чёрном экране после окончания видео
        if subscribe_duration == "all" or not subscribe_duration:
            # НОВОЕ: Используем полную длительность аудио, но только в пределах видео
            max_subscribe_time = temp_audio_duration
            # Кнопка может показываться даже после окончания видео,
            # так как final_assembly растянет видео на полную длительность аудио
        else:
            try:
                requested_duration = float(subscribe_duration)
                # DEBUG: About to call min() on requested_duration and temp_audio_duration
                logger.debug(f"DEBUG: About to call min() on requested_duration and temp_audio_duration")
                logger.debug(f"DEBUG: requested_duration: {requested_duration}, temp_audio_duration: {temp_audio_duration}")
                max_subscribe_time = min(requested_duration, temp_audio_duration)
            except (ValueError, TypeError):
                logger.warning(f"Некорректное значение subscribe_duration: {subscribe_duration}, используем полную длительность аудио")
                max_subscribe_time = temp_audio_duration
        
        logger.info(f"🔘 Кнопка подписки: отображение до {max_subscribe_time:.2f}с (видео: {video_duration:.2f}с, аудио: {temp_audio_duration:.2f}с)")
        
        # КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ о несоответствии длительностей
        if abs(video_duration - temp_audio_duration) > 5.0:
            if video_duration < temp_audio_duration * 0.5:
                logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Видео ({video_duration:.2f}с) намного короче аудио ({temp_audio_duration:.2f}с)!")
                logger.error("Это может привести к зависанию видео или чёрному экрану")
                logger.error("Проверьте конфигурацию эффектов и параметры обработки видео")
            else:
                logger.warning(f"⚠️ Предупреждение: Длительность видео ({video_duration:.2f}с) и аудио ({temp_audio_duration:.2f}с) различаются")
                logger.warning("Финальное видео будет иметь длительность аудио")
        interval_start = audio_offset

        while interval_start < max_subscribe_time:
            # DEBUG: About to call min() on interval_start + subscribe_display_duration and max_subscribe_time
            logger.debug(f"DEBUG: About to call min() on interval calculation")
            logger.debug(f"DEBUG: interval_start: {interval_start}, subscribe_display_duration: {subscribe_display_duration}, max_subscribe_time: {max_subscribe_time}")
            end_time = min(interval_start + subscribe_display_duration, max_subscribe_time)
            overlay_intervals.append((interval_start, end_time))
            # ИСПРАВЛЕНИЕ: правильный расчет следующего интервала - добавляем время показа + интервал
            interval_start += subscribe_display_duration + subscribe_interval_gap
            if interval_start >= max_subscribe_time:
                break

        # Построение FFmpeg команды для финальной сборки
        ffmpeg_cmd = [get_ffmpeg_path(), "-i", temp_video_path]

        # Определение индексов входов
        input_index = 1
        logo2_input_index = None
        logo_input_index = None

        if logo2_path:
            ffmpeg_cmd.extend(["-i", logo2_path])
            logo2_input_index = input_index
            input_index += 1

        if logo_path:
            ffmpeg_cmd.extend(["-i", logo_path])
            logo_input_index = input_index
            input_index += 1

        # ИСПРАВЛЕНИЕ: Используем переданный final_audio_path напрямую (он уже содержит фоновую музыку)
        logger.info(f"🎵 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем final_audio_path вместо combined_audio_path")
        logger.info(f"   final_audio_path: {final_audio_path}")
        logger.info(f"   combined_audio_path (ИГНОРИРУЕМ): {combined_audio_path}")
        ffmpeg_cmd.extend(["-i", final_audio_path])
        audio_input_index = input_index
        input_index += 1

        # Добавляем кнопку подписки
        subscribe_input_index = None
        if frame_list_path and os.path.exists(frame_list_path):
            ffmpeg_cmd.extend(["-f", "concat", "-safe", "0", "-i", frame_list_path])
            subscribe_input_index = input_index
            input_index += 1
            logger.info(f"🔘 Кнопка подписки добавлена как вход {subscribe_input_index}")
        else:
            logger.warning(f"⚠️ Frame list для кнопки подписки не найден: {frame_list_path}")

        # Построение фильтров
        filter_parts = []
        current_stream = "[0:v]"

        # НОВЫЙ ПОДХОД: С попапочным масштабированием такая компенсация не должна требоваться
        if video_duration < temp_audio_duration:
            duration_diff = temp_audio_duration - video_duration
            logger.warning(f"🚨 ПОТЕНЦИАЛЬНАЯ ПРОБЛЕМА: ТРЕБУЕТСЯ РАСШИРЕНИЕ ВИДЕО")
            logger.warning(f"   Исходное видео: {video_duration:.2f}с")
            logger.warning(f"   Целевая длительность: {temp_audio_duration:.2f}с")
            logger.warning(f"   Разница: {duration_diff:.2f}с")
            logger.warning(f"   ⚠️ ЭТО МОЖЕТ ВЫЗВАТЬ ФРИЗЫ! Попапочное масштабирование должно было исправить это.")
            
            # Если разница большая, это сигнал о проблеме в попапочной логике
            if duration_diff > 2.0:
                logger.error(f"❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: Разница {duration_diff:.2f}с слишком большая!")
                logger.error(f"   Это означает, что попапочное масштабирование работает неправильно")
                logger.error(f"   Следует проверить calculate_folder_durations_excel_based")
            
            logger.info(f"🔄 КОМПЕНСАЦИЯ (может вызвать фризы):")
            
            # Если разница небольшая (менее 5 секунд), используем простое расширение
            if duration_diff < 0.5:
                logger.info("   🚫 ИГНОРИРУЕМ: Разница меньше 0.5с - пропускаем расширение для избежания фризов")
                logger.info("   ✅ Небольшие расхождения FFmpeg обработает автоматически")
            elif duration_diff < 5.0:
                logger.info("   ⚠️ Небольшая разница - ОТКЛЮЧАЕМ tpad для избежания фризов")
                logger.warning("   🚫 ИСПРАВЛЕНИЕ: НЕ используем tpad=stop_mode=clone (причина фризов)")
                logger.info("   ✅ Позволяем FFmpeg автоматически обработать разницу в длительности")
                # ИСПРАВЛЕНИЕ: Убираем tpad фильтр который вызывает фризы
                # loop_filter = f"[0:v]tpad=stop_mode=clone:stop_duration={duration_diff:.2f}[v_extended]"
                # filter_parts.append(loop_filter)
                # current_stream = "[v_extended]"
                # logger.info(f"🔄 Фильтр расширения: {loop_filter}")
            else:
                # Для больших различий - создаем предварительно зацикленное видео
                logger.warning("   ⚠️ Большая разница в длительности - требуется предварительная обработка")
                logger.warning("   🚨 Создание зацикленного видео может потребовать дополнительного времени")
                
                # Используем более безопасный подход с ограниченным зацикливанием
                max_safe_loops = 3  # Ограничиваем количество повторений для безопасности
                # DEBUG: About to call min() on max_safe_loops and calculated loops
                logger.debug(f"DEBUG: About to call min() on loop calculation")
                logger.debug(f"DEBUG: max_safe_loops: {max_safe_loops}, calculated loops: {int(temp_audio_duration / video_duration) + 1}")
                total_loops_needed = min(max_safe_loops, int(temp_audio_duration / video_duration) + 1)
                additional_loops = total_loops_needed - 1
                
                logger.info(f"   📊 Безопасный расчет зацикливания:")
                logger.info(f"     Максимум безопасных повторений: {max_safe_loops}")
                logger.info(f"     Будет использовано повторений: {total_loops_needed}")
                logger.info(f"     Дополнительных циклов: {additional_loops}")
                
                # БЕЗОПАСНЫЙ ПОДХОД: Простое расширение последнего кадра
                logger.warning("   🔧 Используем безопасное расширение через tpad")
                
                # Рассчитываем сколько времени нужно добавить
                extension_duration = temp_audio_duration - video_duration
                
                # КОМПЕНСАЦИЯ ПЕРЕХОДОВ: если использовались переходы, видео уже укорочено
                if transitions_enabled:
                    # Определяем количество клипов из clips_info если доступно
                    num_clips = len(clips_info) if clips_info else 1
                    if num_clips > 1:
                        num_transitions = num_clips - 1
                        transition_time_loss = num_transitions * transition_duration
                        logger.warning(f"🔄 УЧЕТ ПЕРЕХОДОВ в расширении:")
                        logger.warning(f"   Количество переходов: {num_transitions}")
                        logger.warning(f"   Потеря времени на переходах: {transition_time_loss:.2f}с")
                        logger.warning(f"   Исходное расширение: {extension_duration:.2f}с")
                        
                        # НЕ добавляем время переходов к расширению, так как это должно быть 
                        # компенсировано в самих клипах (если компенсация не сработала)
                        logger.warning(f"   Финальное расширение: {extension_duration:.2f}с")
                        logger.warning("   ⚠️ Система переходов должна была компенсировать потерю времени")
                    else:
                        logger.info("   Переходы включены, но только 1 клип - компенсация не требуется")
                
                # ИСПРАВЛЕНИЕ: НЕ используем tpad для расширения видео - это вызывает фризы
                logger.warning("   🚫 ИСПРАВЛЕНИЕ: НЕ используем tpad=stop_mode=clone (причина фризов)")
                logger.info("   ✅ Позволяем FFmpeg автоматически обработать большую разницу в длительности")
                # loop_filter = f"[0:v]tpad=stop_mode=clone:stop_duration={extension_duration:.2f}[v_extended]"
                # filter_parts.append(loop_filter)
                # current_stream = "[v_extended]"
                # logger.info(f"🔄 Фильтр расширения: tpad=stop_duration={extension_duration:.2f}")
        else:
            logger.info(f"✅ Видео ({video_duration:.2f}с) достаточно длинное для аудио ({temp_audio_duration:.2f}с), зацикливание не требуется")

        # Субтитры
        if subtitles_enabled and subtitles_path:
            # Экранируем путь к субтитрам
            escaped_subtitles_path = subtitles_path.replace('\\', '\\\\').replace(':', '\\:')
            filter_parts.append(f"{current_stream}subtitles={escaped_subtitles_path}:force_style='Alignment=2'[v0]")
            current_stream = "[v0]"

        # Логотипы - ИСПРАВЛЕННАЯ ЛОГИКА с дополнительными проверками
        # DEBUG: About to call min() on logo durations
        logger.debug(f"DEBUG: About to call min() on logo_duration calculation")
        logger.debug(f"DEBUG: temp_audio_duration: {temp_audio_duration}, logo_duration: {logo_duration}")
        logo_duration_val = min(temp_audio_duration,
                                float(logo_duration)) if logo_duration and logo_duration != "all" else temp_audio_duration
        
        logger.debug(f"DEBUG: About to call min() on logo2_duration calculation")
        logger.debug(f"DEBUG: temp_audio_duration: {temp_audio_duration}, logo2_duration: {logo2_duration}")
        logo2_duration_val = min(temp_audio_duration,
                                 float(logo2_duration)) if logo2_duration and logo2_duration != "all" else temp_audio_duration

        # Начинаем счетчик потоков с учетом зацикливания
        stream_counter = 0
        if video_duration < temp_audio_duration:
            stream_counter += 1  # +1 за v_looped
        if subtitles_enabled and subtitles_path:
            stream_counter += 1  # +1 за v0 (субтитры)

        # ЛОГОТИП 2 (обычно это логотип канала)
        if logo2_path and logo2_input_index is not None and os.path.exists(logo2_path):
            logger.info(f"🏷️ Добавляем логотип 2: {logo2_path}")
            filter_parts.append(
                f"[{logo2_input_index}:v]scale={logo2_width}:-1:force_divisible_by=2,format=yuva420p[logo2]")
            stream_counter += 1
            filter_parts.append(
                f"{current_stream}[logo2]overlay={logo2_position_x}:{logo2_position_y}:enable='between(t,0,{logo2_duration_val})'[v{stream_counter}]")
            current_stream = f"[v{stream_counter}]"
        elif logo2_path:
            logger.warning(f"⚠️ ЛОГОТИП 2 НЕ НАЙДЕН: {logo2_path}")

        # ЛОГОТИП 1 (основной логотип)
        if logo_path and logo_input_index is not None and os.path.exists(logo_path):
            logger.info(f"🏷️ Добавляем логотип 1: {logo_path}")
            filter_parts.append(
                f"[{logo_input_index}:v]scale={logo_width}:-1:force_divisible_by=2,format=yuva420p[logo]")
            stream_counter += 1
            filter_parts.append(
                f"{current_stream}[logo]overlay={logo_position_x}:{logo_position_y}:enable='between(t,0,{logo_duration_val})'[v{stream_counter}]")
            current_stream = f"[v{stream_counter}]"
        elif logo_path:
            logger.warning(f"⚠️ ЛОГОТИП 1 НЕ НАЙДЕН: {logo_path}")

        # ВОССТАНОВЛЕНА КНОПКА ПОДПИСКИ с простой логикой без сложных фильтров
        if subscribe_input_index is not None and overlay_intervals:
            logger.info(f"🔘 Добавляем кнопку подписки: {len(overlay_intervals)} интервалов")
            logger.info(f"🔘 Позиция кнопки: {subscribe_position_x}x{subscribe_position_y}, размер: {subscribe_width}")
            
            # Простое масштабирование кнопки подписки без анимации
            filter_parts.append(
                f"[{subscribe_input_index}:v]scale={subscribe_width}:-2:force_divisible_by=2,format=yuva420p[subscribe]")
            
            stream_counter += 1
            
            # Строим условие включения для всех интервалов
            enable_conditions = []
            for start_time, end_time in overlay_intervals:
                enable_conditions.append(f"between(t,{start_time:.2f},{end_time:.2f})")
            
            enable_expression = "+".join(enable_conditions)
            
            filter_parts.append(
                f"{current_stream}[subscribe]overlay={subscribe_position_x}:{subscribe_position_y}:enable='{enable_expression}'[v{stream_counter}]")
            current_stream = f"[v{stream_counter}]"
            
            logger.info(f"🔘 Кнопка подписки настроена: интервалы {overlay_intervals}")
            logger.info(f"🔘 Enable expression: {enable_expression}")
        elif not subscribe_input_index:
            logger.warning(f"⚠️ КНОПКА ПОДПИСКИ НЕ ДОБАВЛЕНА: subscribe_input_index is None")
        elif not overlay_intervals:
            logger.warning(f"⚠️ КНОПКА ПОДПИСКИ НЕ ДОБАВЛЕНА: нет интервалов для отображения")

        # Финальная команда с улучшенными параметрами аудио и видео-аудио синхронизацией
        filter_complex = ";".join(filter_parts)
        
        # ИСПРАВЛЕНИЕ: Теперь temp_video.mp4 имеет правильную длительность, используем temp_audio_duration
        logger.info(f"🔍 ФИНАЛЬНАЯ СБОРКА:")
        logger.info(f"   temp_audio_duration: {temp_audio_duration:.3f}с")
        logger.info(f"   video_duration: {video_duration:.3f}с")
        logger.info(f"   target_video_duration: {target_video_duration:.3f}с")
        logger.info(f"   stream_counter: {stream_counter}")
        logger.info(f"   Финальный поток видео: [v{stream_counter}]")
        logger.info(f"🔍 FILTER COMPLEX: {filter_complex}")
        
        ffmpeg_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[v{stream_counter}]",
            "-map", f"{audio_input_index}:a:0",  # ИСПРАВЛЕНИЕ: Используем final_audio_path с фоновой музыкой
            "-c:v", video_codec, "-preset", video_preset, "-crf", str(video_crf),
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",  # Используем AAC вместо copy
            "-t", str(target_video_duration),  # ИСПРАВЛЕНИЕ ЧЕРНОГО ЭКРАНА: Используем целевую длительность в зависимости от adjust_videos_to_audio
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts+igndts",
            "-movflags", "+faststart",
            "-max_interleave_delta", "1000000",  # Улучшенная синхронизация видео-аудио
            "-fps_mode", "cfr",  # Постоянная частота кадров для предотвращения фризов (заменено -vsync)
            "-async", "1",  # Синхронизация аудио
            "-probesize", "50000000",
            "-analyzeduration", "50000000",
            "-map_metadata", "-1",
            "-y", output_file
        ])

        # ЧЕРНЫЙ ЭКРАН DEBUG: Детальная диагностика команды FFmpeg
        logger.info(f"🔍 ЧЕРНЫЙ ЭКРАН DEBUG: Финальная FFmpeg команда")
        logger.info(f"   temp_video_path: {temp_video_path}")
        logger.info(f"   🎵 ИСПОЛЬЗУЕМЫЙ АУДИОФАЙЛ: {final_audio_path}")
        logger.info(f"   🚫 ИГНОРИРУЕМЫЙ combined_audio_path: {combined_audio_path}")
        logger.info(f"   temp_audio_duration (для обрезки): {temp_audio_duration:.3f}с")
        logger.info(f"   video_duration (фактическая): {video_duration:.3f}с")
        logger.info(f"   filter_complex: {filter_complex}")
        
        # Логируем полную команду для отладки
        logger.info(f"Полная FFmpeg команда: {' '.join(ffmpeg_cmd)}")

        # Выполнение финальной сборки
        logger.info(f"🚀 ЗАПУСК финальной FFmpeg команды для {os.path.basename(output_file)}")
        run_ffmpeg_command(ffmpeg_cmd, "Финальная сборка видео")
        logger.info(f"✅ ЗАВЕРШЕНА финальная FFmpeg команда для {os.path.basename(output_file)}")

        # Проверка результата
        final_duration = get_media_duration(output_file)
        if final_duration is None:
            logger.error("Не удалось получить длительность финального видео")
            return None

        logger.info(f"Длительность финального видео: {final_duration:.2f}с")

        # Проверяем наличие аудио в финальном файле
        final_has_audio, final_streams = check_audio_streams(output_file)
        logger.info(f"Финальное видео содержит аудио: {final_has_audio}")

        if not final_has_audio:
            logger.error("КРИТИЧЕСКАЯ ОШИБКА: Финальное видео не содержит аудиопотоков!")
            return None

        if abs(final_duration - temp_audio_duration) > 2.0:  # Увеличили допуск
            logger.warning(
                f"Длительность видео не соответствует ожидаемой: {final_duration:.2f}с против {temp_audio_duration:.2f}с")

        # Финальная проверка звука
        logger.info(f"🔍 Проверяем качество финального видео против исходного аудио: {final_audio_path}")
        if not verify_audio_quality(output_file, temp_audio_duration):
            logger.warning("Финальная проверка звука не пройдена")

        logger.info(f"Финальная сборка завершена: {output_file}")
        return output_file

    except Exception as e:
        logger.error(f"Ошибка при финальной сборке: {e}")
        import traceback
        logger.error(f"Подробности ошибки: {traceback.format_exc()}")
        return None


def _add_global_background_music(video_path: str, total_duration: float, config: Any) -> str:
    """
    Добавляет фоновую музыку ко всему финальному видео
    ИСПРАВЛЕННАЯ ВЕРСИЯ с правильным синтаксисом фильтров
    """
    if not hasattr(config, 'background_music_path') or not config.background_music_path or not Path(config.background_music_path).exists():
        logger.info("🔇 Фоновая музыка не используется")
        return video_path

    if not hasattr(config, 'background_music_volume') or config.background_music_volume <= 0:
        logger.info("🔇 Громкость фоновой музыки = 0, пропускаем")
        return video_path

    logger.info("🎵 === ГЛОБАЛЬНОЕ НАЛОЖЕНИЕ ФОНОВОЙ МУЗЫКИ ===")

    output_path = Path(video_path).parent / "final_video_with_global_music.mp4"

    try:
        # Получаем длительность фоновой музыки
        music_duration = ffmpeg_get_media_duration(config.background_music_path)
        logger.info(f"🎵 Длительность фоновой музыки: {music_duration:.2f}с")
        logger.info(f"🎵 Длительность видео: {total_duration:.2f}с")
        logger.info(f"🎵 Громкость фоновой музыки: {config.background_music_volume:.3f}")

        # Строим команду FFmpeg для наложения музыки
        cmd = [get_ffmpeg_path(), "-y"]

        # Входы: видео и музыка
        cmd.extend(["-i", video_path])
        cmd.extend(["-i", config.background_music_path])

        # ИСПРАВЛЕННЫЙ filter_complex с правильным синтаксисом
        if music_duration < total_duration:
            # Зацикливаем музыку если она короче видео
            import math
            loops_needed = int(math.ceil(total_duration / music_duration))
            logger.info(f"🔄 Зацикливаем музыку {loops_needed} раз")

            # ИСПРАВЛЕНИЕ 1: Правильный синтаксис aloop
            music_filter = f"[1:a]aloop=loop={loops_needed-1}:size={int(music_duration * 44100)}[music_looped]"
            trim_filter = f"[music_looped]atrim=0:{total_duration:.3f}[music_trimmed]"
            volume_filter = f"[music_trimmed]volume={config.background_music_volume:.6f}[bg_music]"
            mix_filter = "[0:a][bg_music]amix=inputs=2:duration=first:dropout_transition=2[final_audio]"

            # Объединяем фильтры с правильными разделителями
            filter_complex = f"{music_filter};{trim_filter};{volume_filter};{mix_filter}"
        else:
            # Музыка длиннее видео - просто обрезаем и устанавливаем громкость
            trim_filter = f"[1:a]atrim=0:{total_duration:.3f}[music_trimmed]"
            volume_filter = f"[music_trimmed]volume={config.background_music_volume:.6f}[bg_music]"
            mix_filter = "[0:a][bg_music]amix=inputs=2:duration=first:dropout_transition=2[final_audio]"

            filter_complex = f"{trim_filter};{volume_filter};{mix_filter}"

        logger.info("🎵 ИСПРАВЛЕННЫЙ filter_complex:")
        logger.info(f"   {filter_complex}")

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "0:v",           # Берем видео из первого входа
            "-map", "[final_audio]", # Берем обработанное аудио
            "-c:v", "copy",          # Копируем видео без перекодировки
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-t", str(total_duration),
            str(output_path)
        ])

        logger.info("🎵 Применяем глобальную фоновую музыку...")
        logger.debug(f"ИСПРАВЛЕННАЯ команда: {' '.join(cmd)}")

        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)

        if output_path.exists() and output_path.stat().st_size > 0:
            actual_duration = ffmpeg_get_media_duration(str(output_path))
            logger.info(f"✅ Глобальная фоновая музыка добавлена: {output_path.name}")
            logger.info(f"   Длительность результата: {actual_duration:.2f}с")
            return str(output_path)
        else:
            raise ProcessingError("Файл с фоновой музыкой не создан")

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ FFmpeg ошибка: код {e.returncode}")
        logger.error(f"❌ stderr: {e.stderr}")
        logger.error(f"❌ stdout: {e.stdout}")
        logger.warning("⚠️ Используем видео без фоновой музыки")
        return video_path
    except Exception as e:
        logger.error(f"❌ Ошибка добавления глобальной фоновой музыки: {e}")
        logger.warning("⚠️ Используем видео без фоновой музыки")
        return video_path


def _add_global_background_music_simple(video_path: str, total_duration: float, config: Any) -> str:
    """
    Упрощенная версия добавления фоновой музыки
    """
    if not hasattr(config, 'background_music_path') or not config.background_music_path or not Path(config.background_music_path).exists():
        return video_path

    if not hasattr(config, 'background_music_volume') or config.background_music_volume <= 0:
        return video_path

    logger.info("🎵 === УПРОЩЕННОЕ НАЛОЖЕНИЕ ФОНОВОЙ МУЗЫКИ ===")

    output_path = Path(video_path).parent / "final_video_with_global_music.mp4"

    try:
        # Простая команда без сложных фильтров
        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", video_path,
            "-i", config.background_music_path,
            "-filter_complex",
            f"[1:a]volume={config.background_music_volume}[bg];[0:a][bg]amix=duration=first[audio]",
            "-map", "0:v",
            "-map", "[audio]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_duration),
            str(output_path)
        ]

        logger.info("🎵 Применяем упрощенную фоновую музыку...")
        logger.debug(f"Упрощенная команда: {' '.join(cmd)}")

        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)

        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info(f"✅ Упрощенная фоновая музыка добавлена: {output_path.name}")
            return str(output_path)
        else:
            raise ProcessingError("Файл с упрощенной фоновой музыкой не создан")

    except Exception as e:
        logger.error(f"❌ Ошибка упрощенной фоновой музыки: {e}")
        return video_path