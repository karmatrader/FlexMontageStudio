import os
import subprocess
import json
import logging
from ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_media_duration as ffmpeg_get_media_duration

# Настройка логгера для модуля
logger = logging.getLogger(__name__)

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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
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


def run_ffmpeg_command(cmd, description="FFmpeg команда"):
    """Безопасное выполнение FFmpeg команды с логированием"""
    logger.info(f"Выполнение: {description}")
    logger.debug(f"Команда: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug(f"stdout: {result.stdout}")
        if result.stderr:
            logger.debug(f"stderr: {result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при выполнении {description}: {e.stderr}")
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

        if not clip.get("has_audio", False):
            continue

        temp_clip_audio = os.path.join(temp_folder, f"clip_audio_{idx}.mp3")
        temp_clip_audio_mono = os.path.join(temp_folder, f"clip_audio_{idx}_mono.mp3")

        # Извлечение аудио
        extract_cmd = [
            get_ffmpeg_path(), "-i", clip["path"],
            "-map", "0:a:0", "-c:a", "mp3", "-b:a", "128k",
            "-t", str(clip["duration"]),
            "-y", temp_clip_audio
        ]
        run_ffmpeg_command(extract_cmd, f"Извлечение аудио из клипа {idx}")

        # Конвертация в моно
        mono_cmd = [
            get_ffmpeg_path(), "-i", temp_clip_audio,
            "-ac", "1", "-c:a", "mp3", "-b:a", "128k",
            "-y", temp_clip_audio_mono
        ]
        run_ffmpeg_command(mono_cmd, f"Конвертация аудио в моно для клипа {idx}")

        audio_segments.append((temp_clip_audio_mono, clip_start_time, clip["duration"]))
        last_audio_clip_end_time = current_time

    return audio_segments, last_audio_clip_end_time


def create_combined_audio(final_audio_path, audio_segments, last_audio_clip_end_time, temp_audio_duration, temp_folder):
    """Создание объединенного аудиофайла с правильным смещением озвучки"""
    logger.info("Создание объединенного аудио...")
    logger.info(
        f"Параметры: last_audio_clip_end_time={last_audio_clip_end_time:.2f}с, temp_audio_duration={temp_audio_duration:.2f}с")

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
        return combined_audio_path, temp_audio_duration

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

    # Возвращаем кортеж: (путь_к_аудио, новая_длительность)
    return combined_audio_path, temp_audio_duration


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

    if abs(audio_duration - expected_duration) > 2.0:  # Увеличили допуск
        logger.warning(f"Длительность аудио не соответствует ожидаемой")
        return False

    # Проверка наличия звука в указанные моменты времени
    for test_time in test_times:
        if test_time >= audio_duration:
            continue

        test_segment_path = f"/tmp/test_segment_{test_time}.mp3"
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


def final_assembly(temp_video_path, final_audio_path, output_file, temp_folder, frame_list_path, num_frames, logo_path,
                   subtitles_path, video_resolution, frame_rate, video_crf, video_preset, temp_audio_duration,
                   logo_width, logo_position_x, logo_position_y, logo_duration, subscribe_width, subscribe_position_x,
                   subscribe_position_y, subscribe_display_duration, subscribe_interval_gap, subtitles_enabled,
                   logo2_path=None, logo2_width=None, logo2_position_x=None, logo2_position_y=None, logo2_duration=None,
                   subscribe_duration="all", clips_info=None, audio_offset=0):
    """Основная функция финальной сборки видео"""

    logger.info(f"Начало финальной сборки: {output_file}")

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
            "-c:v", "libx264", "-t", "10", "-y", subscribe_debug_path
        ]
        run_ffmpeg_command(debug_cmd, "Создание отладочного файла кнопки")

        # Проверка и обработка аудио
        if clips_info:
            logger.info(f"Обрабатываем {len(clips_info)} клипов")
            for i, clip in enumerate(clips_info):
                logger.info(
                    f"Клип {i}: длительность={clip.get('duration', 0):.2f}с, аудио={clip.get('has_audio', False)}")
            audio_segments, last_audio_clip_end_time = extract_and_process_clip_audio(clips_info, temp_folder)
            logger.info(
                f"Получено {len(audio_segments)} аудиосегментов, последний клип заканчивается на {last_audio_clip_end_time:.2f}с")
        else:
            logger.info("Клипы отсутствуют")
            audio_segments, last_audio_clip_end_time = [], 0

        # Создание объединенного аудио
        result = create_combined_audio(
            final_audio_path, audio_segments, last_audio_clip_end_time,
            temp_audio_duration, temp_folder
        )

        if result is None:
            logger.error("Не удалось создать объединенное аудио")
            return None
            
        combined_audio_path, updated_audio_duration = result

        # Проверка качества аудио с обновленной длительностью
        if not verify_audio_quality(combined_audio_path, updated_audio_duration):
            logger.error("Проверка качества аудио не пройдена")
            return None
            
        # Обновляем temp_audio_duration для остальной логики
        temp_audio_duration = updated_audio_duration

        # Создание интервалов наложения кнопки подписки
        overlay_intervals = []
        
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение длительности для кнопки подписки
        try:
            video_duration = get_media_duration(temp_video_path)
            logger.info(f"📹 Длительность видео: {video_duration:.2f}с, аудио: {temp_audio_duration:.2f}с")
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

        # Добавляем аудио файл
        ffmpeg_cmd.extend(["-i", combined_audio_path])
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

        # Субтитры
        if subtitles_enabled and subtitles_path:
            # Экранируем путь к субтитрам
            escaped_subtitles_path = subtitles_path.replace('\\', '\\\\').replace(':', '\\:')
            filter_parts.append(f"[0:v]subtitles={escaped_subtitles_path}:force_style='Alignment=2'[v0]")
            current_stream = "[v0]"

        # Логотипы
        logo_duration_val = min(temp_audio_duration,
                                float(logo_duration)) if logo_duration and logo_duration != "all" else temp_audio_duration
        logo2_duration_val = min(temp_audio_duration,
                                 float(logo2_duration)) if logo2_duration and logo2_duration != "all" else temp_audio_duration

        stream_counter = 1 if subtitles_enabled and subtitles_path else 0

        if logo2_path and logo2_input_index is not None:
            filter_parts.append(
                f"[{logo2_input_index}:v]scale={logo2_width}:-1:force_divisible_by=2,format=yuva420p[logo2]")
            stream_counter += 1
            filter_parts.append(
                f"{current_stream}[logo2]overlay={logo2_position_x}:{logo2_position_y}:enable='between(t,0,{logo2_duration_val})'[v{stream_counter}]")
            current_stream = f"[v{stream_counter}]"

        if logo_path and logo_input_index is not None:
            filter_parts.append(
                f"[{logo_input_index}:v]scale={logo_width}:-1:force_divisible_by=2,format=yuva420p[logo]")
            stream_counter += 1
            filter_parts.append(
                f"{current_stream}[logo]overlay={logo_position_x}:{logo_position_y}:enable='between(t,0,{logo_duration_val})'[v{stream_counter}]")
            current_stream = f"[v{stream_counter}]"

        # ВОССТАНОВЛЕНА КНОПКА ПОДПИСКИ с простой логикой без сложных фильтров
        if subscribe_input_index is not None and overlay_intervals:
            logger.info(f"🔘 Добавляем кнопку подписки: {len(overlay_intervals)} интервалов")
            
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

        # Финальная команда с улучшенными параметрами аудио и видео-аудио синхронизацией
        filter_complex = ";".join(filter_parts)
        
        # ИСПРАВЛЕНИЕ: Добавляем дополнительные параметры для предотвращения фризов
        ffmpeg_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[v{stream_counter}]",
            "-map", f"{audio_input_index}:a:0",  # Явно указываем первый аудиопоток
            "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",  # Используем AAC вместо copy
            "-t", str(temp_audio_duration),  # Ограничиваем длительность для корректной синхронизации с аудио
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts+igndts",
            "-movflags", "+faststart",
            "-max_interleave_delta", "1000000",  # Улучшенная синхронизация видео-аудио
            "-vsync", "cfr",  # Постоянная частота кадров для предотвращения фризов
            "-async", "1",  # Синхронизация аудио
            "-probesize", "50000000",
            "-analyzeduration", "50000000",
            "-map_metadata", "-1",
            "-y", output_file
        ])

        # Логируем полную команду для отладки
        logger.info(f"Полная FFmpeg команда: {' '.join(ffmpeg_cmd)}")

        # Выполнение финальной сборки
        run_ffmpeg_command(ffmpeg_cmd, "Финальная сборка видео")

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
        if not verify_audio_quality(output_file, temp_audio_duration):
            logger.warning("Финальная проверка звука не пройдена")

        logger.info(f"Финальная сборка завершена: {output_file}")
        return output_file

    except Exception as e:
        logger.error(f"Ошибка при финальной сборке: {e}")
        import traceback
        logger.error(f"Подробности ошибки: {traceback.format_exc()}")
        return None