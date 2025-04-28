import os
import subprocess
import json

# Цветовые коды ANSI для вывода в консоль
BLUE = "\033[94m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

def create_subscribe_frame_list(subscribe_frames_folder, temp_folder, frame_rate):
    """Создаёт список кадров для кнопки 'ПОДПИСЫВАЙТЕСЬ'."""
    frame_files = sorted([f for f in os.listdir(subscribe_frames_folder) if f.endswith('.png')])
    num_frames = len(frame_files)
    if num_frames == 0:
        print(f"{YELLOW}⚠️ Не найдено кадров в папке {subscribe_frames_folder}!{RESET}")
        return None, 0
    print(f"{GREEN}🎞️ Найдено кадров кнопки 'ПОДПИСЫВАЙТЕСЬ': {num_frames}{RESET}")

    frame_list_path = os.path.join(temp_folder, "frame_list.txt")
    with open(frame_list_path, "w") as f:
        for frame_file in frame_files:
            f.write(f"file '{os.path.join(subscribe_frames_folder, frame_file)}'\n")
            f.write(f"duration {1 / frame_rate}\n")
    return frame_list_path, num_frames

def final_assembly(temp_video_path, final_audio_path, output_file, temp_folder, frame_list_path, num_frames, logo_path, subtitles_path, video_resolution, frame_rate, video_crf, video_preset, temp_audio_duration, logo_width, logo_position_x, logo_position_y, logo_duration, subscribe_width, subscribe_position_x, subscribe_position_y, subscribe_display_duration, subscribe_interval_gap, subtitles_enabled, clips_info=None):
    """Выполняет финальную сборку видео с логотипом, кнопкой, субтитрами и аудио из первого клипа."""
    # Отладочный вывод пути к итоговому файлу
    print(f"{BLUE}📂 Проверяемый путь к итоговому видео: {output_file}{RESET}")

    # Проверяем, существует ли готовое видео
    if os.path.exists(output_file):
        print(f"{GREEN}✅ Готовое видео уже существует: {output_file}. Пропускаем монтаж.{RESET}")
        return output_file
    else:
        print(f"{BLUE}📂 Итоговое видео не найдено: {output_file}. Начинаем монтаж.{RESET}")

    subscribe_debug_path = os.path.join(temp_folder, "subscribe_debug.mp4")
    try:
        subprocess.run([
            "ffmpeg",
            "-f", "concat", "-safe", "0", "-i", frame_list_path,
            "-vf", f"loop=loop=-1:size={num_frames}:start=0,trim=0:10,scale={subscribe_width}:-1:force_divisible_by=2,format=yuva420p",
            "-c:v", "libx264", "-t", "10", "-y", subscribe_debug_path
        ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        print(f"{GREEN}✅ Отладочный файл кнопки создан: {subscribe_debug_path}{RESET}")
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при создании отладочного файла кнопки: {e.stderr.decode()}{RESET}")
        return None

    try:
        # Отладочный вывод для clips_info
        print(f"{BLUE}📹 Clips info: {json.dumps(clips_info)[:1000]}{RESET}")

        # Проверяем clips_info и определяем audio_offset динамически
        if not clips_info or not isinstance(clips_info, list):
            print(f"{YELLOW}⚠️ clips_info пуст или некорректен, основная аудиодорожка начнётся с 0 сек{RESET}")
            audio_offset = 0
            first_audio_clip = None
        else:
            # Динамически определяем audio_offset как длительность первого клипа с аудио
            audio_offset = 0
            first_audio_clip = None
            for idx, clip in enumerate(clips_info):
                if clip.get("has_audio", False):
                    first_audio_clip = clip
                    audio_offset = clip["duration"]
                    print(f"{BLUE}🎵 Первый клип с аудио (индекс {idx}): {clip['path']}, длительность: {clip['duration']:.2f} сек{RESET}")
                    print(f"{BLUE}🎵 Динамически определённый audio_offset: {audio_offset:.2f} сек{RESET}")
                    break
            if not first_audio_clip:
                print(f"{BLUE}🎵 Нет клипов с аудио, основная аудиодорожка начнётся с 0 сек{RESET}")
                audio_offset = 0

        # Проверяем длительность аудио в первом клипе
        if first_audio_clip:
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=duration", "-of", "json", first_audio_clip["path"]]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            try:
                probe_data = json.loads(probe_result.stdout)
                audio_duration = float(probe_data["streams"][1]["duration"])  # Предполагаем, что аудиопоток второй (индекс 1)
                print(f"{BLUE}🎵 Реальная длительность аудио в {first_audio_clip['path']}: {audio_duration:.2f} сек{RESET}")
                if abs(audio_duration - audio_offset) > 0.1:
                    print(f"{YELLOW}⚠️ Длительность аудио ({audio_duration:.2f} сек) отличается от audio_offset ({audio_offset:.2f} сек){RESET}")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"{YELLOW}⚠️ Ошибка при проверке длительности аудио в {first_audio_clip['path']}: {str(e)}{RESET}")

        # Проверяем final_audio.mp4
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", final_audio_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        try:
            probe_data = json.loads(probe_result.stdout)
            final_audio_duration = float(probe_data["format"]["duration"])
            print(f"{BLUE}🎵 Длительность final_audio.mp4: {final_audio_duration:.2f} сек{RESET}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"{YELLOW}⚠️ Ошибка при проверке длительности final_audio.mp4: {str(e)}{RESET}")

        # Создаём объединённый аудиофайл
        combined_audio_path = os.path.join(temp_folder, "combined_audio.mp3")
        ffmpeg_audio_cmd = ["ffmpeg"]
        if first_audio_clip:
            # Извлекаем аудио из первого клипа
            temp_audio_111 = os.path.join(temp_folder, "audio_111.mp3")
            ffmpeg_extract_cmd = [
                "ffmpeg", "-i", first_audio_clip["path"], "-map", "a", "-c:a", "mp3", "-t", str(audio_offset), "-y", temp_audio_111
            ]
            print(f"{BLUE}🎵 FFmpeg команда для извлечения аудио из первого клипа: {' '.join(ffmpeg_extract_cmd)}{RESET}")
            try:
                result = subprocess.run(ffmpeg_extract_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                print(f"{BLUE}🎵 FFmpeg stdout (extract): {result.stdout}{RESET}")
                print(f"{BLUE}🎵 FFmpeg stderr (extract): {result.stderr}{RESET}")
            except subprocess.CalledProcessError as e:
                print(f"{YELLOW}❌ Ошибка при извлечении аудио из первого клипа: {e.stderr}{RESET}")
                return None

            # Проверяем длительность извлечённого аудио
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", temp_audio_111]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            try:
                probe_data = json.loads(probe_result.stdout)
                temp_audio_111_duration = float(probe_data["format"]["duration"])
                print(f"{BLUE}🎵 Длительность audio_111.mp3: {temp_audio_111_duration:.2f} сек{RESET}")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"{YELLOW}⚠️ Ошибка при проверке длительности audio_111.mp3: {str(e)}{RESET}")

            # Перекодируем final_audio.mp4 в MP3
            reencoded_final_audio = os.path.join(temp_folder, "reencoded_final_audio.mp3")
            ffmpeg_reencode_cmd = [
                "ffmpeg", "-i", final_audio_path, "-c:a", "mp3", "-b:a", "128k", "-y", reencoded_final_audio
            ]
            print(f"{BLUE}🎵 FFmpeg команда для перекодирования final_audio.mp4: {' '.join(ffmpeg_reencode_cmd)}{RESET}")
            try:
                result = subprocess.run(ffmpeg_reencode_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                print(f"{BLUE}🎵 FFmpeg stdout (reencode): {result.stdout}{RESET}")
                print(f"{BLUE}🎵 FFmpeg stderr (reencode): {result.stderr}{RESET}")
            except subprocess.CalledProcessError as e:
                print(f"{YELLOW}❌ Ошибка при перекодировании final_audio.mp4: {e.stderr}{RESET}")
                return None

            # Проверяем длительность перекодированного аудио
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", reencoded_final_audio]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            try:
                probe_data = json.loads(probe_result.stdout)
                reencoded_final_audio_duration = float(probe_data["format"]["duration"])
                print(f"{BLUE}🎵 Длительность reencoded_final_audio.mp3: {reencoded_final_audio_duration:.2f} сек{RESET}")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"{YELLOW}⚠️ Ошибка при проверке длительности reencoded_final_audio.mp3: {str(e)}{RESET}")

            # Объединяем аудио с помощью amix
            ffmpeg_audio_cmd.extend([
                "-i", temp_audio_111, "-i", reencoded_final_audio,
                "-filter_complex", f"[0:a]atrim=0:{audio_offset},asetpts=PTS-STARTPTS[a0];[1:a]atrim=0:{temp_audio_duration-audio_offset},adelay={int(audio_offset*1000)}|0,asetpts=PTS-STARTPTS[a1];[a0][a1]amix=inputs=2:duration=longest[outa]",
                "-map", "[outa]", "-c:a", "mp3", "-b:a", "128k",
                "-t", str(temp_audio_duration),
                "-y", combined_audio_path
            ])
        else:
            ffmpeg_audio_cmd.extend(["-i", final_audio_path])
            ffmpeg_audio_cmd.extend([
                "-map", "a",
                "-c:a", "mp3", "-b:a", "128k",
                "-t", str(temp_audio_duration),
                "-y", combined_audio_path
            ])

        print(f"{BLUE}🎵 FFmpeg команда для объединённого аудио: {' '.join(ffmpeg_audio_cmd)}{RESET}")
        try:
            result = subprocess.run(ffmpeg_audio_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            print(f"{BLUE}🎵 FFmpeg stdout: {result.stdout}{RESET}")
            print(f"{BLUE}🎵 FFmpeg stderr: {result.stderr}{RESET}")
        except subprocess.CalledProcessError as e:
            print(f"{YELLOW}❌ Ошибка при создании объединённого аудиофайла: {e.stderr}{RESET}")
            return None

        # Проверяем длительность объединённого аудиофайла
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", combined_audio_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        try:
            probe_data = json.loads(probe_result.stdout)
            combined_audio_duration = float(probe_data["format"]["duration"])
            print(f"{BLUE}🎵 Длительность объединённого аудиофайла: {combined_audio_duration:.2f} сек{RESET}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"{YELLOW}⚠️ Ошибка при проверке длительности объединённого аудиофайла: {str(e)}{RESET}")

        overlay_intervals = []
        max_subscribe_time = min(300, temp_audio_duration)
        interval_start = audio_offset
        while interval_start < max_subscribe_time:
            end_time = min(interval_start + subscribe_display_duration, max_subscribe_time)
            overlay_intervals.append((interval_start, end_time))
            interval_start += subscribe_interval_gap
            if interval_start >= max_subscribe_time:
                break

        ffmpeg_cmd = ["ffmpeg"]
        ffmpeg_cmd.extend(["-i", temp_video_path])
        input_count = 1
        if logo_path:
            ffmpeg_cmd.extend(["-i", logo_path])
            input_count += 1
        ffmpeg_cmd.extend(["-f", "concat", "-safe", "0", "-i", frame_list_path])
        input_count += 1
        ffmpeg_cmd.extend(["-i", combined_audio_path])
        input_count += 1

        filter_complex_parts = []
        logo_duration_val = min(temp_audio_duration, float(logo_duration)) if logo_duration != "all" else temp_audio_duration

        if subtitles_enabled and subtitles_path and os.path.exists(subtitles_path):
            filter_complex_parts.append(f"[0:v]subtitles={subtitles_path}:force_style='Alignment=2'[v0]")
            current_stream = "[v0]"
        else:
            current_stream = "[0:v]"

        if logo_path:
            filter_complex_parts.append(f"[1:v]scale={logo_width}:-1[logo]")
            filter_complex_parts.append(
                f"{current_stream}[logo]overlay={logo_position_x}:{logo_position_y}:enable='between(t,0,{logo_duration_val})'[v1]")
            current_stream = "[v1]"
            subscribe_input_index = 2
        else:
            subscribe_input_index = 1

        filter_complex_parts.append(
            f"[{subscribe_input_index}:v]loop=loop=-1:size={num_frames}:start=0,trim=0:{temp_audio_duration},setpts=PTS-STARTPTS,scale={subscribe_width}:-1:force_divisible_by=2,format=yuva420p[subscribe]")
        overlay_conditions = [f"between(t,{start},{end})" for start, end in overlay_intervals if end <= temp_audio_duration]
        overlay_enable = " + ".join(overlay_conditions) if overlay_conditions else "0"
        filter_complex_parts.append(
            f"{current_stream}[subscribe]overlay={subscribe_position_x}:{subscribe_position_y}:enable='{overlay_enable}'[v2]")

        filter_complex = ";".join(filter_complex_parts)
        print(f"{MAGENTA}🔍 Интервалы наложения кнопки: {overlay_enable}{RESET}")

        ffmpeg_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[v2]", "-map", f"{input_count-1}:a",
            "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(temp_audio_duration),
            "-fflags", "+genpts+igndts", "-movflags", "+faststart",
            "-probesize", "50000000", "-analyzeduration", "50000000",
            "-async", "1",
            "-y", output_file
        ])
        try:
            result = subprocess.run(ffmpeg_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            print(f"{BLUE}🎥 FFmpeg stdout: {result.stdout}{RESET}")
            print(f"{BLUE}🎥 FFmpeg stderr: {result.stderr}{RESET}")
        except subprocess.CalledProcessError as e:
            print(f"{YELLOW}❌ Ошибка при финальной сборке: {e.stderr}{RESET}")
            return None

        # Проверяем длительность финального видео
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", output_file]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        try:
            probe_data = json.loads(probe_result.stdout)
            final_video_duration = float(probe_data["format"]["duration"])
            print(f"{BLUE}🎥 Длительность финального видео: {final_video_duration:.2f} сек{RESET}")
            if abs(final_video_duration - temp_audio_duration) > 1.0:
                print(f"{YELLOW}⚠️ Длительность видео не совпадает с ожидаемой: {final_video_duration:.2f} против {temp_audio_duration:.2f}!{RESET}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"{YELLOW}⚠️ Ошибка при проверке длительности финального видео: {str(e)}{RESET}")

        return output_file
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при финальной сборке: {e.stderr.decode()}{RESET}")
        return None