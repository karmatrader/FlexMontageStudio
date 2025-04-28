# 4 Extend your life/2_auto_montage.py
import sys
import os

# Добавляем путь к common_scripts в sys.path
sys.path.append(os.path.abspath("../common_scripts"))

from auto_montage import process_auto_montage

# Имя канала
channel_name = "4 Extend your life"

# Вызываем общую функцию
process_auto_montage(channel_name, video_number="1")