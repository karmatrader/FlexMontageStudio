import subprocess
import os
import tempfile
from pathlib import Path

def run_ffmpeg_command_test(cmd, description="FFmpeg command"):
    print(f"Executing FFmpeg: {description} -> {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        print(f"✅ {description} stdout:\n{result.stdout}")
        if result.stderr:
            print(f"⚠️ {description} stderr:\n{result.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при выполнении {description}: FFmpeg вернул ненулевой код {e.returncode}")
        print(f"FFmpeg stdout:\n{e.stdout}")
        print(f"FFmpeg stderr:\n{e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        print(f"❌ Таймаут при выполнении {description}.")
        return False
    except FileNotFoundError:
        print(f"❌ FFmpeg не найден. Проверьте путь.")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка при выполнении {description}: {e}")
        return False

def get_ffmpeg_path_test():
    # Замените на ваш актуальный путь к ffmpeg
    return "/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/ffmpeg/ffmpeg"

def create_solid_color_video(output_path, duration=2.0, color="red", width=1920, height=1080, fps=30):
    cmd = [
        get_ffmpeg_path_test(),
        "-f", "lavfi",
        "-i", f"color={color}:s={width}x{height}:r={fps}:d={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-y", output_path
    ]
    return run_ffmpeg_command_test(cmd, f"Создание видео {color}")

def test_xfade_transition():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        video1_path = tmp_path / "red.mp4"
        video2_path = tmp_path / "blue.mp4"
        output_path = tmp_path / "xfade_test_output.mp4"

        print("--- Создание первого видео (красный) ---")
        if not create_solid_color_video(str(video1_path), duration=2.0, color="red"):
            print("Не удалось создать красное видео.")
            return

        print("--- Создание второго видео (синий) ---")
        if not create_solid_color_video(str(video2_path), duration=2.0, color="blue"):
            print("Не удалось создать синее видео.")
            return

        print("--- Попытка создания перехода xfade ---")
        # xfade: transition=fade, duration=1.0, offset=1.0 (т.е. переход начинается на 1.0с красного видео)
        cmd_xfade = [
            get_ffmpeg_path_test(),
            "-i", str(video1_path),
            "-i", str(video2_path),
            "-filter_complex",
            "[0:v][1:v]xfade=transition=fade:duration=1.0:offset=1.0[v_out]",
            "-map", "[v_out]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-y", str(output_path)
        ]

        if run_ffmpeg_command_test(cmd_xfade, "Тест xfade"):
            print(f"✅ Тест xfade завершен. Проверьте файл: {output_path}")
            # Если тест успешен, вы можете открыть файл и посмотреть
            # os.startfile(str(output_path)) # Для Windows
            # subprocess.run(['open', str(output_path)]) # Для macOS
        else:
            print("❌ Тест xfade провален.")

if __name__ == "__main__":
    test_xfade_transition()