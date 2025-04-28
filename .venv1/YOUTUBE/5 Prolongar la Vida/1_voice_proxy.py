# 5 Prolongar la Vida/1_voice_proxy.py
import sys
import os

# Добавляем путь к common_scripts в sys.path
sys.path.append(os.path.abspath("../common_scripts"))

from voice_proxy import process_voice_and_proxy

# Имя канала
channel_name = "5 Prolongar la Vida"

# Вызываем общую функцию
process_voice_and_proxy(channel_name)