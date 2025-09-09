# license_manager.py - этот файл добавьте в ваше приложение
import os
import json
import hashlib
import platform
import subprocess
import requests
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, Dict
import hmac
import logging
from cryptography.fernet import Fernet
from core.file_api import file_api

logger = logging.getLogger(__name__)

# Константы для лицензирования
ENCRYPTION_KEY = b'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM='
HMAC_SECRET = b'\xc2\xcc\xac\x14\xea|6:[-\xb1\x8c\xdfb`)\xcb\xe8pQ\x9a\xbb\x93d'


class LicenseManager:
    def __init__(self, licenses_db: str = "license.json"):
        # ЗАМЕНИТЕ НА ВАШИ ДАННЫЕ!
        self.api_url = "http://5.61.39.42"  # Ваш IP сервера
        self.secret_key = "5590eb3b26db68a9d85f9349ce4b591b"  # Из .env файла
        self.license_file = "license.json"
        self.hwid_cache = None
        self.licenses_db = Path(licenses_db)
        self.cipher = Fernet(ENCRYPTION_KEY)
        # Определяем базовую директорию для поиска файлов лицензий
        self.base_dir = self.licenses_db.parent

    def get_hwid(self) -> str:
        """Генерация уникального HWID на основе железа"""
        if self.hwid_cache:
            return self.hwid_cache

        system = platform.system()

        try:
            if system == "Windows":
                # Получаем UUID материнской платы
                cmd = 'wmic csproduct get UUID'
                result = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL)
                uuid_str = result.decode().split('\n')[1].strip()
            elif system == "Darwin":  # macOS
                cmd = "ioreg -rd1 -c IOPlatformExpertDevice | grep IOPlatformUUID"
                result = subprocess.check_output(cmd, shell=True)
                uuid_str = result.decode().split('"')[3]
            else:  # Linux
                # Читаем machine-id
                with open('/etc/machine-id', 'r') as f:
                    uuid_str = f.read().strip()
        except Exception as e:
            # Fallback - используем MAC адрес
            import uuid
            uuid_str = str(uuid.getnode())

        # Хешируем для безопасности и унификации длины
        hwid = hashlib.sha256(uuid_str.encode()).hexdigest()[:32]
        self.hwid_cache = hwid
        return hwid

    def generate_signature(self, license_key: str, email: str, hwid: str) -> str:
        """Генерация подписи для проверки"""
        sign_string = f"{license_key}{email}{hwid}"
        signature = hmac.new(
            self.secret_key.encode(),
            sign_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    def load_license(self) -> Optional[Dict]:
        """Загрузка лицензии из файла"""
        if not os.path.exists(self.license_file):
            return None

        try:
            with open(self.license_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения лицензии: {e}")
            return None

    def verify_license_online(self, license_data: Dict) -> Tuple[bool, str]:
        """Онлайн проверка лицензии"""
        try:
            hwid = self.get_hwid()

            # Проверяем соответствие HWID
            if license_data.get('hwid') != hwid:
                return False, "Лицензия привязана к другому компьютеру"

            # Подготавливаем данные для проверки
            verification_data = {
                'license_key': license_data.get('license_id'),  # В вашей лицензии это license_id
                'email': license_data.get('email'),
                'hwid': hwid,
                'signature': self.generate_signature(
                    license_data.get('license_id'),
                    license_data.get('email'),
                    hwid
                )
            }

            # Отправляем запрос на сервер
            response = requests.post(
                f"{self.api_url}/verify",
                json=verification_data,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('valid'):
                    return True, "Лицензия действительна"
                else:
                    return False, result.get('message', 'Лицензия недействительна')
            else:
                return False, "Ошибка проверки лицензии"

        except requests.exceptions.RequestException as e:
            # При проблемах с сетью проверяем офлайн
            return self.verify_license_offline(license_data)
        except Exception as e:
            return False, f"Ошибка: {str(e)}"

    def verify_license_offline(self, license_data: Dict) -> Tuple[bool, str]:
        """Офлайн проверка лицензии (базовая)"""
        try:
            hwid = self.get_hwid()

            # Проверяем HWID
            if license_data.get('hwid') != hwid:
                return False, "Лицензия привязана к другому компьютеру"

            # Проверяем подпись
            expected_signature = license_data.get('signature')
            if not expected_signature:
                return False, "Лицензия повреждена (отсутствует подпись)"

            # Для офлайн режима просто проверяем наличие основных полей
            required_fields = ['license_id', 'email', 'hwid', 'signature']
            for field in required_fields:
                if field not in license_data:
                    return False, f"Лицензия повреждена (отсутствует {field})"

            return True, "Лицензия проверена (офлайн режим)"

        except Exception as e:
            return False, f"Ошибка офлайн проверки: {str(e)}"

    def check_license(self, license_key: str = None) -> bool:
        """
        Совместимость со старым API - проверка лицензии по ключу
        """
        # Если передан ключ, проверяем его (старая логика для демо-лицензии)
        if license_key:
            # Проверяем демо-лицензию
            if license_key == "ybjL-nS2S-dTim-Xwf4":
                return True  # Демо-лицензия всегда валидна
            return False
        
        # Новая логика - проверяем файл license.json
        hwid = self.get_hwid()
        license_data = self.load_license()

        if not license_data:
            return False

        # Проверяем онлайн или офлайн
        valid, message = self.verify_license_online(license_data)
        return valid

    def get_hwid_for_display(self) -> str:
        """Возвращает HWID для показа пользователю в новом формате"""
        return self.get_hwid()

    def display_hwid_dialog(self) -> Tuple[str, str]:
        """Показать диалог с HWID для пользователя"""
        hwid = self.get_hwid()

        message = f"""
╔══════════════════════════════════════════════════════╗
║                  АКТИВАЦИЯ ЛИЦЕНЗИИ                   ║
╠══════════════════════════════════════════════════════╣
║                                                        ║
║  Для активации программы:                             ║
║                                                        ║
║  1. Скопируйте ваш HWID:                             ║
║     {hwid}                 ║
║                                                        ║
║  2. Откройте Telegram бот: @fms_license_bot           ║
║                                                        ║
║  3. Отправьте команду /start                         ║
║                                                        ║
║  4. Следуйте инструкциям бота                        ║
║                                                        ║
║  5. Сохраните полученный файл license.json           ║
║     в папку с программой                             ║
║                                                        ║
╚══════════════════════════════════════════════════════╝
        """

        return hwid, message

    def create_hmac(self, data: str) -> str:
        """Создание HMAC для данных"""
        return hmac.new(HMAC_SECRET, data.encode('utf-8'), hashlib.sha256).hexdigest()

    def load_license_from_db(self, license_key: str) -> Optional[dict]:
        """Загрузка лицензии из базы данных через File API"""
        if not file_api.exists(self.licenses_db):
            return None

        try:
            # Используем File API для кэшированного чтения
            licenses = file_api.read_json(self.licenses_db, default=[])

            for license_data in licenses:
                if license_data["key"] == license_key:
                    logger.info(f"Лицензия найдена в базе данных через File API: {license_key}")
                    return license_data

            return None
        except Exception as e:
            logger.error(f"Ошибка загрузки лицензий из базы данных: {e}")
            return None


# Пример использования в вашем приложении
def main():
    """Пример интеграции в основное приложение"""

    # Инициализация менеджера лицензий
    license_mgr = LicenseManager()

    # Проверяем лицензию
    hwid = license_mgr.get_hwid()
    valid = license_mgr.check_license()

    if valid:
        print(f"✅ Лицензия действительна")
        # Запускаем основную программу
        # start_main_application()
    else:
        print(f"❌ Лицензия не найдена или недействительна")

        # Показываем инструкцию для получения лицензии
        hwid_display, instruction = license_mgr.display_hwid_dialog()
        print(instruction)
        print(f"HWID: {hwid_display}")
        print("Получите лицензию у бота в Telegram")

        # Завершаем программу
        exit(1)


if __name__ == "__main__":
    main()