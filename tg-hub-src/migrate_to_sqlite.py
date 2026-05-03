"""
migrate_to_sqlite.py — однократная миграция данных из JSON в SQLite
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from modules.db import migrate_from_json

digests_json = os.path.join(BASE_DIR, "data", "digests_history.json")
posts_json = os.path.join(BASE_DIR, "data", "posts_history.json")

print("Миграция данных JSON → SQLite...")
migrate_from_json(digests_json, posts_json)
print("Готово! База данных: data/tghub.db")
