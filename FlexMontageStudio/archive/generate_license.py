import json
import datetime
import argparse
import string
import random
import hashlib
import hmac
from cryptography.fernet import Fernet
import os

# Ключ шифрования (храните в безопасном месте, в продакшене — отдельно)
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

def generate_license(duration=None, duration_minutes=None, user_id=None, hardware_id=None, output_db="licenses.json"):
    """Генерирует лицензионный ключ и сохраняет его в базу данных и отдельный файл."""
    start_date = datetime.datetime.now()
    if duration_minutes is not None:
        end_date = start_date + datetime.timedelta(minutes=duration_minutes)
    elif duration == "month":
        end_date = start_date + datetime.timedelta(days=30)
    elif duration == "3months":
        end_date = start_date + datetime.timedelta(days=90)
    elif duration == "year":
        end_date = start_date + datetime.timedelta(days=365)
    else:
        raise ValueError("Недопустимый срок действия. Используйте: month, 3months, year или duration_minutes")

    license_data = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "user_id": user_id or "anonymous",
        "hardware_id": hardware_id,
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
        "user_id": user_id or "anonymous",
        "created_at": start_date.isoformat()
    }

    # Сохранение в общую базу licenses.json
    licenses = []
    if os.path.exists(output_db):
        with open(output_db, "r", encoding="utf-8") as f:
            licenses = json.load(f)

    licenses.append(license_entry)

    with open(output_db, "w", encoding="utf-8") as f:
        json.dump(licenses, f, indent=4, ensure_ascii=False)

    # Создание отдельного файла для пользователя
    user_license_file = f"license_{license_key}.json"
    with open(user_license_file, "w", encoding="utf-8") as f:
        json.dump(license_entry, f, indent=4, ensure_ascii=False)

    print(f"Лицензионный ключ: {license_key}")
    print(f"Срок действия: до {end_date.strftime('%Y-%m-%d')}")
    print(f"Записано в базу данных: {output_db}")
    print(f"Создан файл для пользователя: {user_license_file}")
    return license_key, end_date, user_license_file

def revoke_license(license_key, output_db="licenses.json"):
    """Отзывает лицензию, помечая её как недействительную."""
    if not os.path.exists(output_db):
        print(f"База данных лицензий не найдена: {output_db}")
        return False, "База данных лицензий не найдена"

    with open(output_db, "r", encoding="utf-8") as f:
        licenses = json.load(f)

    for license in licenses:
        if license["key"] == license_key:
            license["status"] = "revoked"
            print(f"Лицензия {license_key} отозвана")
            with open(output_db, "w", encoding="utf-8") as f:
                json.dump(licenses, f, indent=4, ensure_ascii=False)
            return True, f"Лицензия {license_key} отозвана"
    print(f"Лицензия {license_key} не найдена")
    return False, f"Лицензия {license_key} не найдена"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Генератор и управление лицензиями")
    parser.add_argument("--action", type=str, default="generate", choices=["generate", "revoke"], help="Действие: generate или revoke")
    parser.add_argument("--duration", type=str, choices=["month", "3months", "year"], help="Срок действия лицензии (для generate)")
    parser.add_argument("--duration_minutes", type=int, help="Срок действия в минутах (для теста)")
    parser.add_argument("--user_id", type=str, help="Идентификатор пользователя (опционально)")
    parser.add_argument("--hardware_id", type=str, help="Идентификатор оборудования (опционально)")
    parser.add_argument("--key", type=str, help="Лицензионный ключ для отзыва (для revoke)")
    parser.add_argument("--output_db", type=str, default="licenses.json", help="Файл базы данных лицензий")
    args = parser.parse_args()

    if args.action == "generate":
        if not args.duration and not args.duration_minutes:
            parser.error("Требуется --duration или --duration_minutes для действия generate")
        license_key, end_date, user_license_file = generate_license(args.duration, args.duration_minutes, args.user_id, args.hardware_id, args.output_db)
    elif args.action == "revoke":
        if not args.key:
            parser.error("--key требуется для действия revoke")
        success, message = revoke_license(args.key, args.output_db)
        print(message)