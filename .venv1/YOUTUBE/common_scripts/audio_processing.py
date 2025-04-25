import os
import subprocess
import json
from tqdm import tqdm
import pandas as pd

# Цветовые коды ANSI для вывода в консоль
BLUE = "\033[94m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"

def get_audio_files_for_video(xlsx_file_path, output_directory, video_number, language="ru"):
    """Читает Excel-файл и возвращает список аудиофайлов для заданного номера видео."""
    try:
        df = pd.read_excel(xlsx_file_path, sheet_name=language.upper(), header=None, usecols=[0, 1])
    except FileNotFoundError:
        print(f"{YELLOW}❌ Файл Excel не найден: {xlsx_file_path}{RESET}")
        return []
    except ValueError:
        print(f"{YELLOW}❌ Вкладка '{language.upper()}' не найдена в Excel-файле{RESET}")
        return []

    video_markers = []
    target_marker = f"ВИДЕО {video_number}"
    for idx, row in df.iterrows():
        marker = str(row[0]).strip() if pd.notna(row[0]) else ""
        if marker.startswith("ВИДЕО"):
            video_markers.append((idx + 1, marker))

    start_row = None
    end_row = None
    for i, (row_idx, marker) in enumerate(video_markers):
        if marker == target_marker:
            start_row = row_idx
            end_row = video_markers[i + 1][0] if i + 1 < len(video_markers) else len(df) + 1
            break

    if start_row is None:
        print(f"{YELLOW}❌ Метка '{target_marker}' не найдена в столбце A{RESET}")
        return []

    print(f"{BLUE}📑 Найден диапазон для {target_marker}: строки {start_row}–{end_row - 1}{RESET}")

    audio_files = []
    for row_idx in range(start_row, end_row):
        file_number = str(row_idx).zfill(3) if row_idx < 100 else str(row_idx)
        audio_path = os.path.join(output_directory, f"{file_number}.mp3")
        if os.path.exists(audio_path):
            audio_files.append(f"{file_number}.mp3")
        else:
            print(f"{YELLOW}⚠️ Аудиофайл не найден: {audio_path}{RESET}")

    return audio_files

def process_audio_files(audio_files, temp_audio_folder, temp_folder, audio_channels, audio_sample_rate, audio_bitrate):
    """Обрабатывает и склеивает аудиофайлы."""
    processed_audio_files = []
    total_audio_duration = 0
    for audio in tqdm(audio_files, desc="🎵 Обрабатываем аудио"):
        input_path = os.path.join(temp_audio_folder, audio)
        output_path = os.path.join(temp_folder, f"processed_{os.path.splitext(audio)[0]}.wav")
        try:
            subprocess.run([
                "ffmpeg", "-i", input_path,
                "-c:a", "pcm_s16le", "-ac", str(audio_channels), "-ar", str(audio_sample_rate),
                "-y", output_path
            ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", output_path]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            try:
                probe_data = json.loads(probe_result.stdout)
                duration = float(probe_data["format"]["duration"])
            except (json.JSONDecodeError, KeyError) as e:
                print(f"{YELLOW}❌ Ошибка при разборе длительности аудио {output_path}: {str(e)}. Пропускаем файл.{RESET}")
                continue
            total_audio_duration += duration
            processed_audio_files.append(output_path)
        except subprocess.CalledProcessError as e:
            print(f"{YELLOW}❌ Ошибка при обработке аудио {input_path}: {e.stderr.decode()}{RESET}")
            continue

    if not processed_audio_files:
        print(f"{YELLOW}⚠️ Не удалось обработать ни одного аудиофайла!{RESET}")
        return None, None

    audio_concat_list_path = os.path.join(temp_folder, "audio_concat_list.txt")
    with open(audio_concat_list_path, "w") as f:
        for audio in processed_audio_files:
            f.write(f"file '{audio}'\n")

    temp_audio_path = os.path.join(temp_folder, "temp_audio.wav")
    try:
        subprocess.run([
            "ffmpeg", "-f", "concat", "-safe", "0", "-i", audio_concat_list_path,
            "-c:a", "pcm_s16le", "-y", temp_audio_path
        ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при склейке аудио: {e.stderr.decode()}{RESET}")
        return None, None

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", temp_audio_path]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        probe_data = json.loads(probe_result.stdout)
        temp_audio_duration = float(probe_data["format"]["duration"])
    except (json.JSONDecodeError, KeyError) as e:
        print(f"{YELLOW}❌ Ошибка при разборе длительности temp_audio.wav: {str(e)}{RESET}")
        return None, None

    final_audio_path = os.path.join(temp_folder, "final_audio.mp3")
    try:
        subprocess.run([
            "ffmpeg", "-i", temp_audio_path,
            "-c:a", "mp3", "-b:a", audio_bitrate,
            "-map", "0:a", "-t", str(temp_audio_duration),
            "-y", final_audio_path
        ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при конверсии в MP3: {e.stderr.decode()}{RESET}")
        return None, None

    return final_audio_path, temp_audio_duration

def add_background_music(final_audio_path, background_music_path, temp_folder, temp_audio_duration, audio_bitrate, audio_sample_rate, background_music_volume):
    """Добавляет фоновую музыку к аудиодорожке."""
    if not background_music_path or not os.path.isfile(background_music_path):
        print(f"{YELLOW}⚠️ Фоновая музыка не найдена: {background_music_path}. Используется исходное аудио.{RESET}")
        return final_audio_path

    print(f"{BLUE}=== 🎵 Добавляем фоновую музыку ==={RESET}")
    temp_music_path = os.path.join(temp_folder, "temp_music.mp3")
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", background_music_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        music_duration = float(json.loads(probe_result.stdout)["format"]["duration"])
        print(f"{BLUE}🎵 Длительность фоновой музыки: {int(music_duration // 60)}:{int(music_duration % 60):02d}{RESET}")

        if music_duration < temp_audio_duration:
            print(f"{YELLOW}⚠️ Фоновая музыка короче видео ({music_duration:.2f} сек против {temp_audio_duration:.2f} сек). Будет зациклена.{RESET}")
            subprocess.run([
                "ffmpeg", "-i", background_music_path,
                "-filter_complex", f"aloop=loop=-1:size={int(temp_audio_duration * audio_sample_rate)}",
                "-c:a", "mp3", "-b:a", audio_bitrate,
                "-t", str(temp_audio_duration),
                "-y", temp_music_path
            ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        else:
            subprocess.run([
                "ffmpeg", "-i", background_music_path,
                "-c:a", "mp3", "-b:a", audio_bitrate,
                "-t", str(temp_audio_duration),
                "-y", temp_music_path
            ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

        final_audio_with_music_path = os.path.join(temp_folder, "final_audio_with_music.mp3")
        subprocess.run([
            "ffmpeg",
            "-i", final_audio_path,
            "-i", temp_music_path,
            "-filter_complex", f"[0:a]volume=1.0[a];[1:a]volume={background_music_volume}[b];[a][b]amix=inputs=2:duration=longest",
            "-c:a", "mp3", "-b:a", audio_bitrate,
            "-t", str(temp_audio_duration),
            "-y", final_audio_with_music_path
        ], check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        print(f"{BLUE}🎵 Фоновая музыка добавлена с громкостью {background_music_volume}{RESET}")
        return final_audio_with_music_path
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при добавлении фоновой музыки: {e.stderr.decode()}{RESET}")
        return final_audio_path
    except (json.JSONDecodeError, KeyError) as e:
        print(f"{YELLOW}❌ Ошибка при разборе длительности фоновой музыки: {str(e)}{RESET}")
        return final_audio_path