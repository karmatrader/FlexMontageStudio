#!/usr/bin/env python3
"""
Скрипт для исправления лицензии FlexMontage Studio
"""

import json
import datetime
import string
import random
import hashlib
import hmac
from cryptography.fernet import Fernet
import os

# Ключи из вашей системы
ENCRYPTION_KEY = b'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM='
HMAC_SECRET = b'\xc2\xcc\xac\x14\xea|6:[-\xb1\x8c\xdfb`)\xcb\xe8pQ\x9a\xbb\x93d'
cipher = Fernet(ENCRYPTION_KEY)


def generate_key_format():
    """Генерирует ключ в формате XXXX-XXXX-XXXX-XXXX."""
    chars = string.ascii_letters + string.digits
    key = ''.join(random.choice(chars) for _ in range(16))
    return f"{key[:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"


def create_hmac(data):
    """Создаёт HMAC для проверки целостности данных."""
    return hmac.new(HMAC_SECRET, data.encode('utf-8'), hashlib.sha256).hexdigest()


def create_new_license():
    """Создание новой рабочей лицензии"""
    print("🔧 Создание новой лицензии для FlexMontage Studio...")

    # Создаем лицензию на год
    start_date = datetime.datetime.now()
    end_date = start_date + datetime.timedelta(days=365)

    license_data = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "user_id": "mikman_main",
        "hardware_id": None,  # Без привязки к железу
        "license_id": str(random.randint(100000, 999999))
    }

    license_json = json.dumps(license_data)
    hmac_signature = create_hmac(license_json)
    encrypted_data = cipher.encrypt(license_json.encode('utf-8')).decode('utf-8')

    license_key = generate_key_format()

    license_entry = {
        "key": license_key,
        "data": encrypted_data,
        "hmac": hmac_signature,
        "status": "active",
        "user_id": "mikman_main",
        "created_at": start_date.isoformat()
    }

    return license_key, license_entry, end_date


def save_license(license_key, license_entry):
    """Сохранение лицензии в файлы"""
    # Загружаем существующие лицензии
    licenses = []
    if os.path.exists("licenses.json"):
        try:
            with open("licenses.json", "r", encoding="utf-8") as f:
                licenses = json.load(f)
        except:
            print("⚠️  Ошибка чтения licenses.json, создаем новый")
            licenses = []

    # Добавляем новую лицензию
    licenses.append(license_entry)

    # Сохраняем общую базу
    with open("licenses.json", "w", encoding="utf-8") as f:
        json.dump(licenses, f, indent=4, ensure_ascii=False)

    # Создаем индивидуальный файл
    individual_file = f"license_{license_key}.json"
    with open(individual_file, "w", encoding="utf-8") as f:
        json.dump(license_entry, f, indent=4, ensure_ascii=False)

    return individual_file


def clear_old_license_from_settings():
    """Очистка старого ключа из настроек Qt"""
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("MyCompany", "AutoMontageApp")
        settings.remove("license_key")
        print("🗑️  Старый лицензионный ключ удален из настроек")
    except Exception as e:
        print(f"⚠️  Не удалось очистить настройки: {e}")


def main():
    print("=" * 60)
    print("🔑 ИСПРАВЛЕНИЕ ЛИЦЕНЗИИ FLEXMONTAGE STUDIO")
    print("=" * 60)

    # Переходим в правильную директорию
    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"
    if os.path.exists(app_dir):
        os.chdir(app_dir)
        print(f"📁 Переход в директорию: {app_dir}")
    else:
        print(f"❌ Директория не найдена: {app_dir}")
        return

    try:
        # Создаем новую лицензию
        license_key, license_entry, end_date = create_new_license()

        # Сохраняем лицензию
        individual_file = save_license(license_key, license_entry)

        # Очищаем старые настройки
        clear_old_license_from_settings()

        print("\n✅ ЛИЦЕНЗИЯ УСПЕШНО СОЗДАНА!")
        print(f"🔑 Новый лицензионный ключ: {license_key}")
        print(f"📅 Действительна до: {end_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📄 Файл лицензии: {individual_file}")
        print(f"💾 Добавлена в общую базу: licenses.json")

        print("\n" + "=" * 60)
        print("🚀 ИНСТРУКЦИЯ ПО ЗАПУСКУ:")
        print("=" * 60)
        print("1. Скопируйте лицензионный ключ:")
        print(f"   {license_key}")
        print("2. Запустите приложение:")
        print("   python startup.py")
        print("3. Введите скопированный ключ в диалоговое окно")
        print("=" * 60)

        # Предлагаем автоматическое сохранение
        response = input("\n🔧 Сохранить ключ в настройки автоматически? (y/n): ")
        if response.lower() in ['y', 'yes', 'да']:
            try:
                from PySide6.QtCore import QSettings
                settings = QSettings("MyCompany", "AutoMontageApp")
                settings.setValue("license_key", license_key)
                print("✅ Лицензионный ключ сохранен! Приложение запустится автоматически.")
            except Exception as e:
                print(f"⚠️  Автосохранение не удалось: {e}")
                print("💡 Введите ключ вручную при запуске.")

    except Exception as e:
        print(f"❌ Ошибка создания лицензии: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()