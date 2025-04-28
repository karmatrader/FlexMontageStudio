import os
import random
import subprocess
import json
import numpy as np
from PIL import Image, ImageFile
import cv2
from tqdm import tqdm
import shutil
from utils import filter_hidden_files
import re

ImageFile.LOAD_TRUNCATED_IMAGES = True

# Цветовые коды ANSI для вывода в консоль
BLUE = "\033[94m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"

# Функция для натуральной сортировки
def natural_sort_key(s):
    # Разбиваем строку на части: числа и не-числа
    parts = re.split(r'(\d+)', s)
    # Преобразуем числовые части в int для правильного сравнения
    return [int(part) if part.isdigit() else part.lower() for part in parts]

def get_video_duration(input_path):
    """Получить длительность видео с помощью ffprobe."""
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", input_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_result.stdout)
        duration = float(probe_data["format"]["duration"])
        if duration <= 0:
            print(f"{YELLOW}⚠️ Длительность {input_path} недопустима: {duration} сек{RESET}")
            return 0
        return duration
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"{YELLOW}⚠️ Ошибка при получении длительности {input_path}: {e}{RESET}")
        return 0

def has_audio_stream(input_path):
    """Проверяет наличие аудиодорожки в видеофайле."""
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-show_streams", "-select_streams", "a", "-of", "json", input_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_result.stdout)
        return len(probe_data.get("streams", [])) > 0
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"{YELLOW}⚠️ Ошибка при проверке аудиодорожки {input_path}: {e}{RESET}")
        return False

def check_video_params(input_path, target_resolution, target_fps, target_codec="h264", target_pix_fmt="yuv420p"):
    """Проверяет, соответствует ли видеофайл целевым параметрам, возвращает статус и причины несоответствия."""
    try:
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,pixel_format",
            "-of", "json", input_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_result.stdout)

        stream = probe_data.get("streams", [{}])[0]
        codec = stream.get("codec_name", "")
        width = stream.get("width", 0)
        height = stream.get("height", 0)
        pix_fmt = stream.get("pixel_format", "")

        # Проверяем частоту кадров
        fps_fraction = stream.get("r_frame_rate", "0/1")
        try:
            num, den = map(int, fps_fraction.split("/"))
            fps = num / den if den != 0 else 0
        except (ValueError, ZeroDivisionError):
            fps = 0

        # Проверяем разрешение
        target_width, target_height = map(int, target_resolution.split(":"))

        # Проверяем соответствие
        reasons = []
        if codec != target_codec:
            reasons.append(f"codec={codec} (expected {target_codec})")
        if pix_fmt == "":
            reasons.append(f"pixel_format=unknown (expected {target_pix_fmt})")
        elif pix_fmt != target_pix_fmt:
            reasons.append(f"pixel_format={pix_fmt} (expected {target_pix_fmt})")
        if width != target_width or height != target_height:
            reasons.append(f"resolution={width}x{height} (expected {target_width}x{target_height})")
        if abs(fps - target_fps) >= 0.1:
            reasons.append(f"fps={fps:.2f} (expected {target_fps})")

        is_match = (
            codec == target_codec and
            (pix_fmt == target_pix_fmt or pix_fmt == "") and
            width == target_width and
            height == target_height and
            abs(fps - target_fps) < 0.1
        )
        if not is_match:
            print(f"{YELLOW}⚠️ Видео {input_path} не соответствует параметрам: {', '.join(reasons)}{RESET}")
        return is_match, reasons
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"{YELLOW}⚠️ Ошибка при проверке параметров {input_path}: {str(e)}. Файл будет пропущен.{RESET}")
        return False, [f"error={str(e)}"]

def reencode_video(input_path, output_path, video_resolution, frame_rate, video_crf, video_preset, preserve_audio=False):
    """Перекодирует видео в целевой формат (libx264, yuv420p, указанное разрешение и fps)."""
    cmd = [
        "ffmpeg", "-reinit_filter", "0", "-i", input_path,
        "-vf", f"fps={frame_rate},format=yuv420p,scale={video_resolution}:force_original_aspect_ratio=decrease,pad={video_resolution}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
    ]
    if preserve_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.append("-an")
    cmd.extend(["-fps_mode", "passthrough", "-fflags", "+genpts", "-y", output_path])
    print(f"{BLUE}📹 Перекодируем видео: {' '.join(cmd)}{RESET}")
    try:
        result = subprocess.run(
            cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
        )
        print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
        # Проверяем перекодированный файл
        is_valid, reasons = check_video_params(output_path, video_resolution, frame_rate)
        if not is_valid:
            print(f"{YELLOW}⚠️ Перекодированный файл {output_path} не соответствует параметрам: {', '.join(reasons)}{RESET}")
            return False
        duration = get_video_duration(output_path)
        if duration <= 0:
            print(f"{YELLOW}⚠️ Перекодированный файл {output_path} имеет недопустимую длительность{RESET}")
            return False
        return True
    except subprocess.CalledProcessError as e:
        print(f"{YELLOW}❌ Ошибка при перекодировании {input_path}: {e.stderr}{RESET}")
        return False

def resize_and_blur(img, image_size, bokeh_blur_kernel, bokeh_blur_sigma):
    """Создает размытую версию изображения для фона."""
    img_resized = img.resize(image_size, Image.LANCZOS)
    img_np = np.array(img_resized)
    blurred = cv2.GaussianBlur(img_np, bokeh_blur_kernel, bokeh_blur_sigma)
    img_blurred = Image.fromarray(blurred)
    return img_blurred

def process_image_fixed_height(img_path, desired_size, bokeh_blur_kernel, bokeh_blur_sigma):
    """Обрабатывает изображение, масштабируя с фиксированной высотой и добавляя боке, если нужно."""
    img = Image.open(img_path)
    img_aspect = img.width / img.height
    new_width = int(desired_size[1] * img_aspect)
    new_height = desired_size[1]
    img_resized = img.resize((new_width, new_height), Image.LANCZOS)
    if new_width < desired_size[0]:
        blurred_img = resize_and_blur(img, (desired_size[0], new_height), bokeh_blur_kernel, bokeh_blur_sigma)
        x_offset = (desired_size[0] - new_width) // 2
        blurred_img.paste(img_resized, (x_offset, 0))
        return blurred_img
    else:
        return img_resized

def concat_photos_random(processed_photo_files, temp_folder, temp_audio_duration):
    """Создаёт список для случайной склейки фото/видео."""
    random.shuffle(processed_photo_files)
    concat_list_path = os.path.join(temp_folder, "concat_list.txt")
    with open(concat_list_path, "w") as f:
        for photo in processed_photo_files:
            f.write(f"file '{photo}'\n")
    return concat_list_path

def concat_photos_in_order(processed_photo_files, temp_folder, temp_audio_duration):
    """Создаёт список для склейки фото/видео по порядку."""
    concat_list_path = os.path.join(temp_folder, "concat_list.txt")
    with open(concat_list_path, "w") as f:
        for photo in processed_photo_files:
            f.write(f"file '{photo}'\n")
    return concat_list_path

def process_photos_and_videos(
    photo_files, preprocessed_photo_folder, temp_folder, video_resolution, frame_rate, video_crf, video_preset, temp_audio_duration, adjust_videos_to_audio, preserve_clip_audio=False
):
    """Обрабатывает фото и видео, поддерживая два режима: масштабирование (True) или исходная длительность с обрезкой (False)."""
    processed_photo_files = []
    skipped_files = []
    total_duration = 0
    clips_info = []

    if not photo_files:
        print(f"{YELLOW}⚠️ Нет доступных файлов для обработки!{RESET}")
        return processed_photo_files, skipped_files, clips_info

    # Сортируем photo_files: сначала по наличию аудио, затем по имени с натуральной сортировкой
    def has_audio_priority(file):
        path = os.path.join(preprocessed_photo_folder, file)
        ext = os.path.splitext(file)[1].lower()
        return not (preserve_clip_audio and ext in ('.mp4', '.mov') and has_audio_stream(path))

    # Сначала сортируем по имени с натуральной сортировкой
    photo_files_sorted_by_name = sorted(photo_files, key=lambda x: natural_sort_key(os.path.splitext(x)[0]))
    # Затем сортируем по приоритету аудио (файлы с аудио в начале)
    sorted_photo_files = sorted(photo_files_sorted_by_name, key=has_audio_priority)
    print(f"{BLUE}📹 Отсортированные файлы: {sorted_photo_files}{RESET}")

    if adjust_videos_to_audio:
        # Режим True: масштабировать все клипы под аудио
        photo_duration = temp_audio_duration / len(sorted_photo_files) if sorted_photo_files else 0
        print(f"{BLUE}📹 Режим масштабирования: длительность каждого клипа {photo_duration:.2f} сек (всего {len(sorted_photo_files)} клипов){RESET}")

        for idx, photo in enumerate(tqdm(sorted_photo_files, desc="🔧 Обрабатываем фото и видео")):
            input_path = os.path.join(preprocessed_photo_folder, photo)
            output_path = os.path.join(temp_folder, f"processed_{os.path.splitext(photo)[0]}.mp4")
            ext = os.path.splitext(photo)[1].lower()
            has_audio = preserve_clip_audio and ext in ('.mp4', '.mov') and has_audio_stream(input_path)
            print(f"{BLUE}📹 Клип {idx+1}: {photo}, has_audio={has_audio}, путь: {input_path}{RESET}")

            if ext in ('.mp4', '.mov'):
                print(f"{BLUE}📹 Проверяем видео: {input_path}{RESET}")
                is_match, reasons = check_video_params(
                    input_path,
                    target_resolution=video_resolution,
                    target_fps=frame_rate,
                    target_codec="h264",
                    target_pix_fmt="yuv420p"
                )
                temp_input_path = input_path

                if is_match and not has_audio:
                    print(f"{GREEN}✅ Видео {photo} уже соответствует параметрам, перекодирование не требуется{RESET}")
                    video_duration = get_video_duration(input_path)
                    print(f"{BLUE}📹 Исходная длительность видео {photo}: {video_duration:.2f} сек{RESET}")
                    if video_duration < photo_duration:
                        print(f"{YELLOW}⚠️ Видео {photo} короче требуемой длительности ({video_duration:.2f} < {photo_duration:.2f}), будет использовано как есть{RESET}")
                        shutil.copy(input_path, output_path)
                    else:
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
                            "-c:v", "copy", "-an", "-t", str(photo_duration),
                            "-y", output_path
                        ]
                        print(f"{BLUE}📹 Выполняем команду FFmpeg (обрезка): {' '.join(cmd)}{RESET}")
                        try:
                            result = subprocess.run(
                                cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                            )
                            print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
                            print(f"{BLUE}📹 FFmpeg stderr: {result.stderr}{RESET}")
                        except subprocess.CalledProcessError as e:
                            print(f"{YELLOW}❌ Ошибка при обрезке {input_path}: {e.stderr}{RESET}")
                            skipped_files.append(photo)
                            continue
                else:
                    temp_reencode_path = os.path.join(temp_folder, f"reencoded_{os.path.splitext(photo)[0]}.mp4")
                    if reencode_video(input_path, temp_reencode_path, video_resolution, frame_rate, video_crf, video_preset, preserve_audio=has_audio):
                        temp_input_path = temp_reencode_path
                        print(f"{GREEN}✅ Видео {photo} перекодировано: {', '.join(reasons)} → libx264, yuv420p, {video_resolution}, {frame_rate} fps{' с аудио' if has_audio else ''}{RESET}")
                    else:
                        print(f"{YELLOW}⚠️ Видео {photo} не удалось перекодировать и будет пропущено.{RESET}")
                        skipped_files.append(photo)
                        continue

                    video_duration = get_video_duration(temp_input_path)
                    print(f"{BLUE}📹 Исходная длительность видео {photo}: {video_duration:.2f} сек{RESET}")

                    if has_audio:
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", temp_input_path,
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                            "-y", output_path
                        ]
                    else:
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", temp_input_path,
                            "-vf", f"fps={frame_rate},format=yuv420p,scale={video_resolution}:force_original_aspect_ratio=decrease,pad={video_resolution}:(ow-iw)/2:(oh-ih)/2",
                            "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
                            "-an", "-t", str(photo_duration), "-fps_mode", "passthrough",
                            "-fflags", "+genpts", "-y", output_path
                        ]
                    print(f"{BLUE}📹 Выполняем команду FFmpeg: {' '.join(cmd)}{RESET}")
                    try:
                        result = subprocess.run(
                            cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                        )
                        print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
                        print(f"{BLUE}📹 FFmpeg stderr: {result.stderr}{RESET}")
                    except subprocess.CalledProcessError as e:
                        print(f"{YELLOW}❌ Ошибка при обработке {input_path}: {e.stderr}{RESET}")
                        skipped_files.append(photo)
                        continue

                processed_duration = get_video_duration(output_path)
                if processed_duration <= 0:
                    print(f"{YELLOW}⚠️ Обработанный файл {output_path} имеет недопустимую длительность{RESET}")
                    skipped_files.append(photo)
                    continue
                print(f"{GREEN}✅ Видео {photo} обработано: длительность {processed_duration:.2f} сек {'(с аудио)' if has_audio else '(масштабировано до ' + str(photo_duration) + ' сек)'}{RESET}")
                processed_photo_files.append(output_path)
                clips_info.append({"path": output_path, "duration": processed_duration, "has_audio": has_audio})
                total_duration += processed_duration
            else:
                cmd = [
                    "ffmpeg", "-loop", "1", "-i", input_path,
                    "-vf",
                    f"scale={video_resolution}:force_original_aspect_ratio=decrease,pad={video_resolution}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                    "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
                    "-an", "-t", str(photo_duration), "-r", str(frame_rate),
                    "-map", "0:v:0", "-map", "-0:s", "-map", "-0:d",
                    "-fflags", "+genpts", "-y", output_path
                ]
                print(f"{BLUE}📹 Выполняем команду FFmpeg: {' '.join(cmd)}{RESET}")
                try:
                    result = subprocess.run(
                        cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                    )
                    print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
                    print(f"{BLUE}📹 FFmpeg stderr: {result.stderr}{RESET}")
                    processed_duration = get_video_duration(output_path)
                    if processed_duration <= 0:
                        print(f"{YELLOW}⚠️ Обработанный файл {output_path} имеет недопустимую длительность{RESET}")
                        skipped_files.append(photo)
                        continue
                    print(f"{GREEN}✅ Изображение {photo} обработано: длительность {processed_duration:.2f} сек{RESET}")
                    processed_photo_files.append(output_path)
                    clips_info.append({"path": output_path, "duration": processed_duration, "has_audio": False})
                    total_duration += processed_duration
                except subprocess.CalledProcessError as e:
                    print(f"{YELLOW}❌ Ошибка при обработке {input_path}: {e.stderr}{RESET}")
                    skipped_files.append(photo)
                    continue
    else:
        # Режим False: исходная длительность, обрезать последний клип
        available_files = sorted_photo_files.copy()
        random.shuffle(available_files)
        print(f"{BLUE}📹 Режим исходной длительности: обрезка последнего клипа под {temp_audio_duration:.2f} сек{RESET}")

        for idx, photo in enumerate(tqdm(available_files, desc="🔧 Обрабатываем фото и видео")):
            input_path = os.path.join(preprocessed_photo_folder, photo)
            output_path = os.path.join(temp_folder, f"processed_{len(processed_photo_files)}_{os.path.splitext(photo)[0]}.mp4")
            ext = os.path.splitext(photo)[1].lower()
            has_audio = preserve_clip_audio and ext in ('.mp4', '.mov') and has_audio_stream(input_path)
            print(f"{BLUE}📹 Клип {idx+1}: {photo}, has_audio={has_audio}, путь: {input_path}{RESET}")

            if ext in ('.mp4', '.mov'):
                print(f"{BLUE}📹 Проверяем видео: {input_path}{RESET}")
                is_match, reasons = check_video_params(
                    input_path,
                    target_resolution=video_resolution,
                    target_fps=frame_rate,
                    target_codec="h264",
                    target_pix_fmt="yuv420p"
                )

                if is_match and not has_audio:
                    print(f"{GREEN}✅ Видео {photo} уже соответствует параметрам, перекодирование не требуется{RESET}")
                    video_duration = get_video_duration(input_path)
                    print(f"{BLUE}📹 Исходная длительность видео {photo}: {video_duration:.2f} сек{RESET}")
                    is_last_clip = total_duration + video_duration >= temp_audio_duration

                    if is_last_clip:
                        remaining_duration = temp_audio_duration - total_duration
                        if remaining_duration <= 0:
                            break
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
                            "-c:v", "copy", "-an", "-t", str(remaining_duration),
                            "-y", output_path
                        ]
                    else:
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
                            "-c:v", "copy", "-an", "-y", output_path
                        ]

                    print(f"{BLUE}📹 Выполняем команду FFmpeg (копирование/обрезка): {' '.join(cmd)}{RESET}")
                    try:
                        result = subprocess.run(
                            cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                        )
                        print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
                        print(f"{BLUE}📹 FFmpeg stderr: {result.stderr}{RESET}")
                        processed_duration = get_video_duration(output_path)
                        if processed_duration <= 0:
                            print(f"{YELLOW}⚠️ Обработанный файл {output_path} имеет недопустимую длительность{RESET}")
                            skipped_files.append(photo)
                            available_files.remove(photo)
                            continue
                        print(f"{GREEN}✅ Видео {photo} обработано: длительность {processed_duration:.2f} сек {'(обрезано до ' + str(remaining_duration) + ' сек)' if is_last_clip else '(исходная)'}{RESET}")
                        processed_photo_files.append(output_path)
                        clips_info.append({"path": output_path, "duration": processed_duration, "has_audio": False})
                        total_duration += processed_duration
                        if is_last_clip:
                            break
                    except subprocess.CalledProcessError as e:
                        print(f"{YELLOW}❌ Ошибка при обработке {input_path}: {e.stderr}{RESET}")
                        skipped_files.append(photo)
                        available_files.remove(photo)
                        continue
                else:
                    temp_reencode_path = os.path.join(temp_folder, f"reencoded_{os.path.splitext(photo)[0]}.mp4")
                    if reencode_video(input_path, temp_reencode_path, video_resolution, frame_rate, video_crf, video_preset, preserve_audio=has_audio):
                        input_path = temp_reencode_path
                        print(f"{GREEN}✅ Видео {photo} перекодировано: {', '.join(reasons)} → libx264, yuv420p, {video_resolution}, {frame_rate} fps{' с аудио' if has_audio else ''}{RESET}")
                    else:
                        print(f"{YELLOW}⚠️ Видео {photo} не удалось перекодировать и будет пропущено{RESET}")
                        skipped_files.append(photo)
                        available_files.remove(photo)
                        continue

                    video_duration = get_video_duration(input_path)
                    print(f"{BLUE}📹 Исходная длительность видео {photo}: {video_duration:.2f} сек{RESET}")

                    is_last_clip = total_duration + video_duration >= temp_audio_duration

                    if has_audio:
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                            "-y", output_path
                        ]
                    elif is_last_clip:
                        remaining_duration = temp_audio_duration - total_duration
                        if remaining_duration <= 0:
                            break
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
                            "-vf", f"fps={frame_rate},format=yuv420p,scale={video_resolution}:force_original_aspect_ratio=decrease,pad={video_resolution}:(ow-iw)/2:(oh-ih)/2",
                            "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
                            "-an", "-t", str(remaining_duration),
                            "-fps_mode", "passthrough", "-fflags", "+genpts", "-y", output_path
                        ]
                    else:
                        cmd = [
                            "ffmpeg", "-reinit_filter", "0", "-i", input_path,
                            "-vf", f"fps={frame_rate},format=yuv420p,scale={video_resolution}:force_original_aspect_ratio=decrease,pad={video_resolution}:(ow-iw)/2:(oh-ih)/2",
                            "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
                            "-an", "-fps_mode", "passthrough", "-fflags", "+genpts", "-y", output_path
                        ]

                    print(f"{BLUE}📹 Выполняем команду FFmpeg: {' '.join(cmd)}{RESET}")
                    try:
                        result = subprocess.run(
                            cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                        )
                        print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
                        print(f"{BLUE}📹 FFmpeg stderr: {result.stderr}{RESET}")
                        processed_duration = get_video_duration(output_path)
                        if processed_duration <= 0:
                            print(f"{YELLOW}⚠️ Обработанный файл {output_path} имеет недопустимую длительность{RESET}")
                            skipped_files.append(photo)
                            available_files.remove(photo)
                            continue
                        print(f"{GREEN}✅ Видео {photo} обработано: длительность {processed_duration:.2f} сек {'(с аудио)' if has_audio else '(обрезано до ' + str(remaining_duration) + ' сек)' if is_last_clip else '(исходная)'}{RESET}")
                        processed_photo_files.append(output_path)
                        clips_info.append({"path": output_path, "duration": processed_duration, "has_audio": has_audio})
                        total_duration += processed_duration
                        if is_last_clip:
                            break
                    except subprocess.CalledProcessError as e:
                        print(f"{YELLOW}❌ Ошибка при обработке {input_path}: {e.stderr}{RESET}")
                        skipped_files.append(photo)
                        available_files.remove(photo)
                        continue
            else:
                is_last_clip = total_duration + temp_audio_duration >= temp_audio_duration
                duration = remaining_duration if is_last_clip else temp_audio_duration / len(sorted_photo_files)
                cmd = [
                    "ffmpeg", "-loop", "1", "-i", input_path,
                    "-vf",
                    f"scale={video_resolution}:force_original_aspect_ratio=decrease,pad={video_resolution}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                    "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf),
                    "-an", "-t", str(duration), "-r", str(frame_rate),
                    "-map", "0:v:0", "-map", "-0:s", "-map", "-0:d",
                    "-fflags", "+genpts", "-y", output_path
                ]
                print(f"{BLUE}📹 Выполняем команду FFmpeg: {' '.join(cmd)}{RESET}")
                try:
                    result = subprocess.run(
                        cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace'
                    )
                    print(f"{BLUE}📹 FFmpeg stdout: {result.stdout}{RESET}")
                    print(f"{BLUE}📹 FFmpeg stderr: {result.stderr}{RESET}")
                    processed_duration = get_video_duration(output_path)
                    if processed_duration <= 0:
                        print(f"{YELLOW}⚠️ Обработанный файл {output_path} имеет недопустимую длительность{RESET}")
                        skipped_files.append(photo)
                        available_files.remove(photo)
                        continue
                    print(f"{GREEN}✅ Изображение {photo} обработано: длительность {processed_duration:.2f} сек{RESET}")
                    processed_photo_files.append(output_path)
                    clips_info.append({"path": output_path, "duration": processed_duration, "has_audio": False})
                    total_duration += processed_duration
                    if is_last_clip:
                        break
                except subprocess.CalledProcessError as e:
                    print(f"{YELLOW}❌ Ошибка при обработке {input_path}: {e.stderr}{RESET}")
                    skipped_files.append(photo)
                    available_files.remove(photo)
                    continue

            if total_duration < temp_audio_duration and available_files:
                print(f"{BLUE}📹 Недостаточно длительности ({total_duration:.2f}/{temp_audio_duration:.2f} сек), повторное использование клипов{RESET}")
                available_files = sorted_photo_files.copy()
                random.shuffle(available_files)

    print(f"{GREEN}📹 Общая длительность видео: {total_duration:.2f} сек, аудио: {temp_audio_duration:.2f} сек{RESET}")
    print(f"{BLUE}📹 Итоговое clips_info: {clips_info}{RESET}")
    return processed_photo_files, skipped_files, clips_info

def preprocess_images(photo_folder_vid, preprocessed_photo_folder, bokeh_enabled, bokeh_image_size, bokeh_blur_kernel, bokeh_blur_sigma, video_resolution=None, frame_rate=None):
    """Предобработка изображений с эффектом боке, копирование видео только при необходимости."""
    image_files = filter_hidden_files(os.listdir(photo_folder_vid))
    total_files = len([f for f in image_files if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    with tqdm(total=total_files, desc="Processing images with bokeh", ncols=80) as pbar:
        for image_filename in image_files:
            if image_filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                image_path = os.path.join(photo_folder_vid, image_filename)
                try:
                    processed_image = process_image_fixed_height(image_path, bokeh_image_size, bokeh_blur_kernel, bokeh_blur_sigma)
                    processed_image.save(os.path.join(preprocessed_photo_folder, image_filename))
                    pbar.update()
                except OSError:
                    print(f"{YELLOW}⚠️ Пропуск поврежденного файла: {image_path}{RESET}")
                    continue
            elif image_filename.lower().endswith(('.mp4', '.mov')):
                video_path = os.path.join(photo_folder_vid, image_filename)
                if video_resolution is not None and frame_rate is not None:
                    is_match, _ = check_video_params(
                        video_path,
                        target_resolution=video_resolution,
                        target_fps=frame_rate,
                        target_codec="h264",
                        target_pix_fmt="yuv420p"
                    )
                    if is_match:
                        print(f"{GREEN}✅ Видео {image_filename} уже соответствует параметрам, копирование в preprocessed_photos не требуется{RESET}")
                    else:
                        print(f"{YELLOW}⚠️ Видео {image_filename} требует перекодирования, копируем в preprocessed_photos{RESET}")
                else:
                    print(f"{YELLOW}⚠️ Параметры video_resolution или frame_rate не указаны, копируем видео {image_filename} в preprocessed_photos{RESET}")
                shutil.copy(video_path, os.path.join(preprocessed_photo_folder, image_filename))