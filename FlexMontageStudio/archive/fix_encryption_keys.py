#!/usr/bin/env python3
"""
Скрипт для синхронизации ключей шифрования между всеми компонентами системы
"""

import os
import base64
import json
import shutil
from pathlib import Path


def backup_files():
    """Создание бэкапов файлов перед изменением"""
    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"

    files_to_backup = [
        ".env",
        "lic/generate_license.py",
        "lic/license_manager.py",
        "licenses.json"
    ]

    backups_created = []

    for file_path in files_to_backup:
        full_path = os.path.join(app_dir, file_path)
        backup_path = full_path + ".backup"

        if os.path.exists(full_path) and not os.path.exists(backup_path):
            shutil.copy2(full_path, backup_path)
            backups_created.append(f"{file_path} -> {file_path}.backup")

    if backups_created:
        print("✅ Созданы бэкапы:")
        for backup in backups_created:
            print(f"   {backup}")

    return True


def get_license_system_keys():
    """Получение ключей из существующей системы лицензирования"""
    # Ключи из license_manager.py и generate_license.py
    encryption_key = b'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM='
    hmac_secret = b'\xc2\xcc\xac\x14\xea|6:[-\xb1\x8c\xdfb`)\xcb\xe8pQ\x9a\xbb\x93d'

    # Конвертируем в base64 для .env файла
    encryption_key_b64 = encryption_key.decode('utf-8')  # Уже в base64
    hmac_secret_b64 = base64.b64encode(hmac_secret).decode('utf-8')

    return {
        'encryption_key_bytes': encryption_key,
        'hmac_secret_bytes': hmac_secret,
        'encryption_key_b64': encryption_key_b64,
        'hmac_secret_b64': hmac_secret_b64
    }


def update_env_file(keys):
    """Обновление .env файла с правильными ключами"""
    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"
    env_file = os.path.join(app_dir, ".env")

    new_env_content = f"""# FlexMontage Studio Environment Variables
# Синхронизировано с системой лицензирования

# Ключ шифрования для лицензий
FMS_ENCRYPTION_KEY={keys['encryption_key_b64']}

# Секрет для HMAC
FMS_HMAC_SECRET={keys['hmac_secret_b64']}

# Опциональные настройки
# FMS_DEBUG=true
# FMS_LOG_LEVEL=DEBUG
"""

    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(new_env_content)

    print(f"✅ Обновлен .env файл с синхронизированными ключами")


def update_fallback_values_in_env_manager(keys):
    """Обновление fallback значений в env_manager.py"""
    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"
    env_manager_file = os.path.join(app_dir, "config", "env_manager.py")

    if not os.path.exists(env_manager_file):
        print(f"⚠️ Файл {env_manager_file} не найден")
        return

    with open(env_manager_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Заменяем fallback значения
    old_fallback = """    def _get_fallback_values(self) -> Dict[str, str]:
        \"\"\"Fallback значения для разработки\"\"\"
        return {
            'FMS_ENCRYPTION_KEY': 'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM=',
            'FMS_HMAC_SECRET': base64.b64encode(
                b'\\xc2\\xcc\\xac\\x14\\xea|6:[-\\xb1\\x8c\\xdfb`)\\xcb\\xe8pQ\\x9a\\xbb\\x93d').decode()
        }"""

    new_fallback = f"""    def _get_fallback_values(self) -> Dict[str, str]:
        \"\"\"Fallback значения для разработки\"\"\"
        return {{
            'FMS_ENCRYPTION_KEY': '{keys['encryption_key_b64']}',
            'FMS_HMAC_SECRET': '{keys['hmac_secret_b64']}'
        }}"""

    if old_fallback in content:
        content = content.replace(old_fallback, new_fallback)
        with open(env_manager_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ Обновлены fallback значения в env_manager.py")
    else:
        print("⚠️ Не найден блок fallback значений для замены")


def create_working_license():
    """Создание новой рабочей лицензии с правильными ключами"""
    import datetime
    import string
    import random
    import hashlib
    import hmac
    from cryptography.fernet import Fernet

    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"
    os.chdir(app_dir)

    keys = get_license_system_keys()

    # Используем правильные ключи
    cipher = Fernet(keys['encryption_key_bytes'])

    # Создаем лицензию на год
    start_date = datetime.datetime.now()
    end_date = start_date + datetime.timedelta(days=365)

    license_data = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "user_id": "mikman_fixed",
        "hardware_id": None,
        "license_id": str(random.randint(100000, 999999))
    }

    license_json = json.dumps(license_data)
    hmac_signature = hmac.new(keys['hmac_secret_bytes'], license_json.encode('utf-8'), hashlib.sha256).hexdigest()
    encrypted_data = cipher.encrypt(license_json.encode('utf-8')).decode('utf-8')

    # Генерируем ключ
    chars = string.ascii_letters + string.digits
    key = ''.join(random.choice(chars) for _ in range(16))
    license_key = f"{key[:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"

    license_entry = {
        "key": license_key,
        "data": encrypted_data,
        "hmac": hmac_signature,
        "status": "active",
        "user_id": "mikman_fixed",
        "created_at": start_date.isoformat()
    }

    # Сохраняем в общую базу
    licenses = []
    if os.path.exists("licenses.json"):
        with open("licenses.json", "r", encoding="utf-8") as f:
            licenses = json.load(f)

    licenses.append(license_entry)

    with open("licenses.json", "w", encoding="utf-8") as f:
        json.dump(licenses, f, indent=4, ensure_ascii=False)

    # Создаем индивидуальный файл
    individual_file = f"license_{license_key}.json"
    with open(individual_file, "w", encoding="utf-8") as f:
        json.dump(license_entry, f, indent=4, ensure_ascii=False)

    print(f"✅ Создана новая лицензия: {license_key}")
    print(f"   Действительна до: {end_date.strftime('%Y-%m-%d %H:%M:%S')}")

    return license_key


def set_license_in_settings(license_key):
    """Установка лицензии в настройки Qt"""
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("MyCompany", "AutoMontageApp")
        settings.setValue("license_key", license_key)
        print(f"✅ Лицензия {license_key} сохранена в настройки Qt")
    except Exception as e:
        print(f"⚠️ Не удалось сохранить в настройки Qt: {e}")


def main():
    print("=" * 70)
    print("🔧 СИНХРОНИЗАЦИЯ КЛЮЧЕЙ ШИФРОВАНИЯ FLEXMONTAGE STUDIO")
    print("=" * 70)

    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"
    if not os.path.exists(app_dir):
        print(f"❌ Директория приложения не найдена: {app_dir}")
        return

    print("1️⃣ Создание бэкапов...")
    backup_files()

    print("\n2️⃣ Получение ключей из системы лицензирования...")
    keys = get_license_system_keys()
    print(f"   Ключ шифрования: {keys['encryption_key_b64'][:20]}...")
    print(f"   HMAC секрет: {keys['hmac_secret_b64'][:20]}...")

    print("\n3️⃣ Обновление .env файла...")
    update_env_file(keys)

    print("\n4️⃣ Обновление fallback значений...")
    update_fallback_values_in_env_manager(keys)

    print("\n5️⃣ Создание новой рабочей лицензии...")
    try:
        license_key = create_working_license()
    except Exception as e:
        print(f"❌ Ошибка создания лицензии: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n6️⃣ Установка лицензии в настройки...")
    set_license_in_settings(license_key)

    print("\n" + "=" * 70)
    print("✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА!")
    print("=" * 70)
    print(f"🔑 Новая лицензия: {license_key}")
    print("🚀 Теперь запустите приложение:")
    print("   python startup.py")
    print("\n💡 Все ключи синхронизированы между компонентами системы!")
    print("🔒 Лицензия автоматически загрузится из настроек")


if __name__ == "__main__":
    main()