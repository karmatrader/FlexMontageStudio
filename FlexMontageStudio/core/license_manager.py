"""
Менеджер лицензий FlexMontage Studio
"""
import json
import logging
import datetime
import hashlib
import hmac
import uuid
import os
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import QMessageBox
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Константы для лицензирования
ENCRYPTION_KEY = b'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM='
HMAC_SECRET = b'\xc2\xcc\xac\x14\xea|6:[-\xb1\x8c\xdfb`)\xcb\xe8pQ\x9a\xbb\x93d'


class LicenseManager:
    """Менеджер лицензий"""

    def __init__(self, licenses_db: str = "licenses.json"):
        self.licenses_db = Path(licenses_db)
        self.cipher = Fernet(ENCRYPTION_KEY)
        # Определяем базовую директорию для поиска файлов лицензий
        self.base_dir = self.licenses_db.parent

    def create_hmac(self, data: str) -> str:
        """Создание HMAC для данных"""
        return hmac.new(HMAC_SECRET, data.encode('utf-8'), hashlib.sha256).hexdigest()

    def load_license_from_db(self, license_key: str) -> Optional[dict]:
        """Загрузка лицензии из базы данных"""
        if not self.licenses_db.exists():
            return None

        try:
            with open(self.licenses_db, "r", encoding="utf-8") as f:
                licenses = json.load(f)

            for license_data in licenses:
                if license_data["key"] == license_key:
                    logger.info(f"Лицензия найдена в базе данных: {license_key}")
                    return license_data

        except Exception as e:
            logger.error(f"Ошибка чтения licenses.json: {e}")

        return None

    def load_individual_license(self, license_key: str) -> Optional[dict]:
        """Загрузка индивидуальной лицензии"""
        individual_license_file = self.base_dir / f"license_{license_key}.json"

        if not individual_license_file.exists():
            return None

        try:
            with open(individual_license_file, "r", encoding="utf-8") as f:
                license_entry = json.load(f)

            # Добавляем в общую базу
            self.add_license_to_db(license_entry)
            logger.info(f"Индивидуальная лицензия загружена: {license_key}")
            return license_entry

        except Exception as e:
            logger.error(f"Ошибка чтения {individual_license_file}: {e}")

        return None

    def add_license_to_db(self, license_entry: dict) -> None:
        """Добавление лицензии в базу данных"""
        try:
            licenses = []
            if self.licenses_db.exists():
                with open(self.licenses_db, "r", encoding="utf-8") as f:
                    licenses = json.load(f)

            # Проверяем, нет ли уже такой лицензии
            license_key = license_entry["key"]
            if not any(license["key"] == license_key for license in licenses):
                licenses.append(license_entry)

                with open(self.licenses_db, "w", encoding="utf-8") as f:
                    json.dump(licenses, f, indent=4, ensure_ascii=False)

                logger.info(f"Лицензия добавлена в базу данных: {license_key}")

        except Exception as e:
            logger.error(f"Ошибка добавления лицензии в базу: {e}")

    def get_hardware_id(self) -> str:
        """Получение ID оборудования"""
        try:
            import getmac
            import platform

            mac = getmac.get_mac_address() or "unknown_mac_" + str(uuid.uuid4())[:8]
            system_info = platform.node() + platform.system() + platform.processor()
            combined = (mac + system_info).encode('utf-8')
            hardware_id = hashlib.sha256(combined).hexdigest()

            logger.debug(f"Hardware ID сгенерирован: {hardware_id[:8]}...")
            return hardware_id

        except Exception as e:
            logger.error(f"Ошибка генерации hardware_id: {e}")
            raise

    def validate_license_data(self, license_entry: dict) -> bool:
        """Валидация данных лицензии"""
        # Проверка статуса
        if license_entry["status"] != "active":
            QMessageBox.critical(None, "Ошибка лицензии",
                                 "Лицензия отозвана или недействительна!")
            return False

        try:
            # Расшифровка и проверка HMAC
            license_json = self.cipher.decrypt(license_entry["data"].encode('utf-8')).decode('utf-8')
            expected_hmac = self.create_hmac(license_json)

            if not hmac.compare_digest(expected_hmac, license_entry["hmac"]):
                QMessageBox.critical(None, "Ошибка лицензии",
                                     "Лицензионный ключ повреждён или подделан!")
                return False

            # Парсинг данных лицензии
            license_data = json.loads(license_json)

            # Проверка срока действия
            end_date = datetime.datetime.fromisoformat(license_data["end_date"])
            if datetime.datetime.now() > end_date:
                QMessageBox.critical(None, "Ошибка лицензии",
                                     "Срок действия лицензии истёк!")
                return False

            # Проверка оборудования
            if license_data.get("hardware_id"):
                current_hardware_id = self.get_hardware_id()
                if current_hardware_id != license_data["hardware_id"]:
                    QMessageBox.critical(None, "Ошибка лицензии",
                                         "Лицензия не соответствует оборудованию!")
                    return False

            logger.info(f"Лицензия действительна до {end_date.strftime('%Y-%m-%d')}")
            return True

        except Exception as e:
            logger.error(f"Ошибка валидации лицензии: {e}")
            QMessageBox.critical(None, "Ошибка лицензии",
                                 f"Ошибка проверки лицензии: {str(e)}")
            return False

    def check_license(self, license_key: str) -> bool:
        """
        Проверка лицензии

        Args:
            license_key: Лицензионный ключ

        Returns:
            bool: True если лицензия действительна
        """
        logger.info(f"Проверка лицензии: {license_key}")

        # Поиск лицензии в базе данных
        license_entry = self.load_license_from_db(license_key)

        # Если не найдена, ищем индивидуальную лицензию
        if not license_entry:
            license_entry = self.load_individual_license(license_key)

        # Если лицензия не найдена
        if not license_entry:
            QMessageBox.critical(None, "Ошибка лицензии",
                                 "Недействительный лицензионный ключ!")
            return False

        # Валидация лицензии
        return self.validate_license_data(license_entry)

    def get_license_info(self, license_key: str) -> Optional[dict]:
        """
        Получение информации о лицензии

        Args:
            license_key: Лицензионный ключ

        Returns:
            dict: Информация о лицензии или None
        """
        license_entry = self.load_license_from_db(license_key)
        if not license_entry:
            license_entry = self.load_individual_license(license_key)

        if not license_entry:
            return None

        try:
            license_json = self.cipher.decrypt(license_entry["data"].encode('utf-8')).decode('utf-8')
            license_data = json.loads(license_json)

            return {
                "key": license_key,
                "status": license_entry["status"],
                "end_date": license_data["end_date"],
                "hardware_id": license_data.get("hardware_id"),
                "created_date": license_data.get("created_date")
            }

        except Exception as e:
            logger.error(f"Ошибка получения информации о лицензии: {e}")
            return None


# Глобальный экземпляр менеджера лицензий
_license_manager = LicenseManager()


def check_license(license_key: str, licenses_db: str = "licenses.json") -> bool:
    """Функция для обратной совместимости"""
    return _license_manager.check_license(license_key)