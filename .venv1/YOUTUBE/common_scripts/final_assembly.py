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

def final_assembly(temp_video_path, final_audio_path, output_file, temp_folder, frame_list_path, num_frames, logo_path, subtitles_path, video_resolution, frame_rate, video_crf, video_preset, temp_audio_duration, logo_width, logo_position_x, logo_position_y, logo_duration, subscribe_width, subscribe_position_x, subscribe_position_y, subscribe_display_duration, subscribe_interval_gap, subtitles_enabled):
    """Выполняет финальную сборку видео с логотипом, кнопкой и субтитрами."""
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
        overlay_intervals = []
        max_subscribe_time = min(300, temp_audio_duration)
        interval_start = 0
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
        ffmpeg_cmd.extend(["-i", final_audio_path])
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
            "-shortest",
            "-fflags", "+genpts+igndts", "-movflags", "+faststart",
            "-probesize", "50000000", "-analyzeduration", "50000000",
            "-async", "1",
            "-y", output_file
        ])
        subprocess.run(ffmpeg_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при финальной сборке: {e.stderr.decode()}{RESET}")
        return None