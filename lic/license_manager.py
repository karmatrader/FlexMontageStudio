# license_manager.py - этот файл добавьте в ваше приложение
import os
import json
import hashlib
import platform
import subprocess
import requests
from datetime import datetime
from typing import Tuple, Optional, Dict
import hmac


class LicenseManager:
    def __init__(self):
        self.api_url = "http://5.61.39.42"  # Ваш IP сервера
        self.secret_key = "5590eb3b26db68a9d85f9349ce4b591b"  # Из .env файла
        self.license_file = "license.json"
        self.hwid_cache = None

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
            print(f"Ошибка чтения лицензии: {e}")
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

    def check_license(self) -> Tuple[bool, str, Optional[str]]:
        """
        Основной метод проверки лицензии
        Возвращает: (успех, сообщение, hwid)
        """
        hwid = self.get_hwid()

        # Загружаем лицензию
        license_data = self.load_license()

        if not license_data:
            return False, "Лицензия не найдена", hwid

        # Проверяем онлайн или офлайн
        valid, message = self.verify_license_online(license_data)

        return valid, message, hwid

    def display_hwid_dialog(self) -> Tuple[str, str]:
        """Показать диалог с HWID для пользователя"""
        hwid = self.get_hwid()

        message = f"""
╔══════════════════════════════════════════════════════╗
║                  АКТИВАЦИЯ ЛИЦЕНЗИИ                  ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  Для активации программы:                            ║
║                                                      ║
║  1. Скопируйте ваш HWID:                             ║
║     {hwid}                                           ║
║                                                      ║
║  2. Откройте Telegram бот: @fms_license_bot          ║
║                                                      ║
║  3. Отправьте команду /start                         ║
║                                                      ║
║  4. Следуйте инструкциям бота                        ║
║                                                      ║
║  5. Сохраните полученный файл license.json           ║
║     в папку с программой                             ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
        """

        return hwid, message


# Пример использования в вашем приложении
def main():
    """Пример интеграции в основное приложение"""

    # Инициализация менеджера лицензий
    license_mgr = LicenseManager()

    # Проверяем лицензию
    is_valid, message, hwid = license_mgr.check_license()

    if is_valid:
        print(f"✅ {message}")
        # Запускаем основную программу
        # start_main_application()
    else:
        print(f"❌ {message}")

        if "не найдена" in message.lower():
            # Показываем инструкцию для получения лицензии
            hwid, instruction = license_mgr.display_hwid_dialog()
            print(instruction)
            # Замените @YourLicenseBot на имя вашего бота!
        else:
            print(f"Ошибка: {message}")

        # Завершаем программу
        exit(1)


if __name__ == "__main__":
    main()