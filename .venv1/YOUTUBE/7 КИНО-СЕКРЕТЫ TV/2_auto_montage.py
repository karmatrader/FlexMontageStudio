# 7 КИНО-СЕКРЕТЫ TV/2_auto_montage.py

import sys
import os

# Добавляем путь к common_scripts в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common_scripts")))

from main import process_auto_montage

# Имя канала и номер видео
channel_name = "7 КИНО-СЕКРЕТЫ TV"
video_number = ""

# Вызываем основную функцию
process_auto_montage(channel_name, video_number=video_number)