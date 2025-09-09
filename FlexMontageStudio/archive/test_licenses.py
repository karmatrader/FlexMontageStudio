#!/usr/bin/env python3
"""
Скрипт для тестирования лицензий FlexMontage Studio
"""

import json
import datetime
import hashlib
import hmac
from cryptography.fernet import Fernet
import os

# Ключи из вашей системы (точно такие же как в startup.py)
ENCRYPTION_KEY = b'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM='
HMAC_SECRET = b'\xc2\xcc\xac\x14\xea|6:[-\xb1\x8c\xdfb`)\xcb\xe8pQ\x9a\xbb\x93d'
cipher = Fernet(ENCRYPTION_KEY)


def create_hmac(data):
    """Создаёт HMAC для проверки целостности данных."""
    return hmac.new(HMAC_SECRET, data.encode('utf-8'), hashlib.sha256).hexdigest()


def test_license(license_key):
    """Тестирование конкретной лицензии"""
    print(f"\n🔍 Тестирование лицензии: {license_key}")

    # Поиск лицензии в общей базе
    license_entry = None
    if os.path.exists("licenses.json"):
        try:
            with open("licenses.json", "r", encoding="utf-8") as f:
                licenses = json.load(f)
            for license_item in licenses:
                if license_item["key"] == license_key:
                    license_entry = license_item
                    break
        except Exception as e:
            print(f"❌ Ошибка чтения licenses.json: {e}")
            return False

    # Поиск в индивидуальном файле
    if not license_entry:
        individual_file = f"license_{license_key}.json"
        if os.path.exists(individual_file):
            try:
                with open(individual_file, "r", encoding="utf-8") as f:
                    license_entry = json.load(f)
            except Exception as e:
                print(f"❌ Ошибка чтения {individual_file}: {e}")
                return False

    if not license_entry:
        print(f"❌ Лицензия {license_key} не найдена!")
        return False

    print(f"✅ Лицензия найдена в базе")
    print(f"   Статус: {license_entry['status']}")
    print(f"   Пользователь: {license_entry['user_id']}")
    print(f"   Создана: {license_entry['created_at'][:10]}")

    # Проверка статуса
    if license_entry["status"] != "active":
        print(f"❌ Лицензия не активна: {license_entry['status']}")
        return False

    # Проверка целостности
    try:
        license_json = cipher.decrypt(license_entry["data"].encode('utf-8')).decode('utf-8')
        print(f"✅ Расшифровка успешна")

        expected_hmac = create_hmac(license_json)
        if not hmac.compare_digest(expected_hmac, license_entry["hmac"]):
            print(f"❌ HMAC не совпадает!")
            return False
        print(f"✅ HMAC проверка пройдена")

        license_data = json.loads(license_json)
        end_date = datetime.datetime.fromisoformat(license_data["end_date"])
        current_date = datetime.datetime.now()

        print(f"✅ Данные лицензии расшифрованы")
        print(f"   Действительна до: {end_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Текущее время: {current_date.strftime('%Y-%m-%d %H:%M:%S')}")

        if current_date > end_date:
            print(f"❌ Срок действия лицензии истёк!")
            return False

        days_left = (end_date - current_date).days
        print(f"✅ Лицензия действительна! Осталось дней: {days_left}")

        return True

    except Exception as e:
        print(f"❌ Ошибка проверки лицензии: {e}")
        import traceback
        traceback.print_exc()
        return False


def clear_old_settings():
    """Очистка старых настроек Qt"""
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("MyCompany", "AutoMontageApp")
        old_key = settings.value("license_key", "")
        if old_key:
            print(f"🗑️  Найден старый ключ в настройках: {old_key}")
            settings.remove("license_key")
            print(f"🗑️  Старый ключ удален из настроек")
        else:
            print(f"ℹ️  В настройках нет сохраненного ключа")
    except Exception as e:
        print(f"⚠️  Не удалось проверить настройки: {e}")


def set_working_license(license_key):
    """Установка рабочей лицензии в настройки"""
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("MyCompany", "AutoMontageApp")
        settings.setValue("license_key", license_key)
        print(f"✅ Лицензия {license_key} сохранена в настройки!")
    except Exception as e:
        print(f"⚠️  Не удалось сохранить в настройки: {e}")


def main():
    print("=" * 70)
    print("🔑 ТЕСТИРОВАНИЕ ЛИЦЕНЗИЙ FLEXMONTAGE STUDIO")
    print("=" * 70)

    # Переходим в правильную директорию
    app_dir = "/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio"
    if os.path.exists(app_dir):
        os.chdir(app_dir)
        print(f"📁 Переход в директорию: {app_dir}")
    else:
        print(f"❌ Директория не найдена: {app_dir}")
        return

    # Очищаем старые настройки
    clear_old_settings()

    # Список активных лицензий из вашей базы
    active_licenses = [
        "ix5x-x1en-aK6Z-QlX1",  # костя1
        "qozn-J2wc-kB5t-7QEP",  # Мик6
        "fkF8-HXAT-LEjW-s2To",  # кость7
        "e0PA-L1aX-tnri-amzv",  # иван1
        "1d0u-jMj5-eCNn-nala",  # кость777
        "cNzZ-a9pQ-0X4z-aaiT"  # мик777 (самый новый)
    ]

    print(f"\n🔍 Тестирование {len(active_licenses)} активных лицензий...")

    working_licenses = []

    for license_key in active_licenses:
        if test_license(license_key):
            working_licenses.append(license_key)
            print(f"✅ Лицензия {license_key} работает!")
        else:
            print(f"❌ Лицензия {license_key} не работает!")

    print("\n" + "=" * 70)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 70)

    if working_licenses:
        print(f"✅ Рабочих лицензий найдено: {len(working_licenses)}")
        for i, key in enumerate(working_licenses, 1):
            print(f"   {i}. {key}")

        # Используем самую новую рабочую лицензию
        recommended_key = working_licenses[-1]  # Последняя = самая новая
        print(f"\n🎯 Рекомендуемая лицензия: {recommended_key}")

        response = input(f"\n🔧 Установить {recommended_key} как активную лицензию? (y/n): ")
        if response.lower() in ['y', 'yes', 'да']:
            set_working_license(recommended_key)
            print(f"\n🚀 Теперь можете запускать приложение:")
            print(f"   python startup.py")
            print(f"\n💡 Лицензия будет загружена автоматически!")
        else:
            print(f"\n💡 Для ручного ввода используйте один из рабочих ключей выше")
    else:
        print(f"❌ Ни одна лицензия не работает!")
        print(f"\n🔧 Нужно создать новую лицензию:")
        print(f"   python lic/generate_license.py --action generate --duration year --user_id mikman_new")


if __name__ == "__main__":
    main()