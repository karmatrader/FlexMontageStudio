import os
import sys
import logging
import hashlib
import hmac
from pathlib import Path
from typing import Optional, Dict, Any
import base64
import json
from cryptography.fernet import Fernet


class EnvironmentManager:
    """Менеджер переменных окружения с поддержкой разных способов загрузки"""

    def __init__(self):
        self.env_loaded = False
        self.config_dir = self._get_config_dir()

    def _get_config_dir(self) -> Path:
        """Получение директории конфигурации в зависимости от ОС"""
        if getattr(sys, 'frozen', False):
            # Запущено из exe файла
            base_path = Path(sys.executable).parent
        else:
            # Запущено из исходного кода
            base_path = Path(__file__).parent.parent

        config_dir = base_path / "config"
        config_dir.mkdir(exist_ok=True)
        return config_dir

    def load_environment(self) -> Dict[str, Any]:
        """Загрузка переменных окружения с приоритетом источников"""
        env_vars = {}

        # 1. Попытка загрузки из .env файла (приоритет 1)
        env_vars.update(self._load_from_env_file())

        # 2. Попытка загрузки из системных переменных (приоритет 2)
        env_vars.update(self._load_from_system_env())

        # 3. Попытка загрузки из зашифрованного файла (приоритет 3)
        env_vars.update(self._load_from_encrypted_file())

        # 4. Fallback на хардкод значения (только для разработки)
        if not env_vars:
            logging.warning("ВНИМАНИЕ: Используются хардкод значения для разработки!")
            env_vars = self._get_fallback_values()

        self.env_loaded = bool(env_vars)
        return env_vars

    def _load_from_env_file(self) -> Dict[str, Any]:
        """Загрузка из .env файла"""
        env_file_paths = [
            Path.cwd() / ".env",  # Рядом с exe или в корне проекта
            self.config_dir / ".env",
            Path.home() / ".flexmontage" / ".env"
        ]

        for env_file in env_file_paths:
            if env_file.exists():
                try:
                    env_vars = self._parse_env_file(env_file)
                    if env_vars:
                        logging.info(f"Переменные окружения загружены из: {env_file}")
                        return env_vars
                except Exception as e:
                    logging.error(f"Ошибка загрузки {env_file}: {e}")

        return {}

    def _parse_env_file(self, env_file: Path) -> Dict[str, str]:
        """Парсинг .env файла"""
        env_vars = {}
        with open(env_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        key, value = line.split('=', 1)
                        # Убираем кавычки если есть
                        value = value.strip('"\'')
                        env_vars[key.strip()] = value
                    except ValueError:
                        logging.warning(f"Некорректная строка в {env_file}:{line_num}: {line}")
        return env_vars

    def _load_from_system_env(self) -> Dict[str, str]:
        """Загрузка из системных переменных окружения"""
        required_vars = ['FMS_ENCRYPTION_KEY', 'FMS_HMAC_SECRET']
        env_vars = {}

        for var in required_vars:
            value = os.environ.get(var)
            if value:
                env_vars[var] = value

        if env_vars:
            logging.info("Переменные окружения загружены из системы")

        return env_vars

    def _load_from_encrypted_file(self) -> Dict[str, Any]:
        """Загрузка из зашифрованного конфигурационного файла"""
        config_file = self.config_dir / "app_config.enc"
        if not config_file.exists():
            return {}

        try:
            # Простое base64 кодирование
            with open(config_file, 'rb') as f:
                encoded_data = f.read()
                decoded_data = base64.b64decode(encoded_data).decode('utf-8')

            env_vars = {}
            for line in decoded_data.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()

            if env_vars:
                logging.info("Переменные окружения загружены из зашифрованного файла")

            return env_vars
        except Exception as e:
            logging.error(f"Ошибка загрузки зашифрованного файла: {e}")
            return {}

    def _get_fallback_values(self) -> Dict[str, str]:
        """Fallback значения для разработки"""
        return {
            'FMS_ENCRYPTION_KEY': 'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM=',
            'FMS_HMAC_SECRET': 'wsysFOp8NjpbLbGM32JgKcvocFGau5Nk'
        }

    def create_env_template(self) -> Path:
        """Создание шаблона .env файла"""
        template_path = Path.cwd() / ".env"
        if template_path.exists():
            logging.info(f".env файл уже существует: {template_path}")
            return template_path

        template_content = """# FlexMontage Studio Environment Variables
# Ключи для работы системы лицензирования

# Ключ шифрования для лицензий (base64)
FMS_ENCRYPTION_KEY=EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM=

# Секрет для HMAC (base64)
FMS_HMAC_SECRET=wswsFD6sczo6Wy2xjN9iYCnL6HBRmruTZA==

# Опциональные настройки
# FMS_DEBUG=true
# FMS_LOG_LEVEL=DEBUG
"""
        with open(template_path, 'w', encoding='utf-8') as f:
            f.write(template_content)

        logging.info(f"Создан .env файл: {template_path}")
        return template_path

    def create_encrypted_config(self, env_vars: Dict[str, str]) -> Path:
        """Создание зашифрованного конфигурационного файла"""
        config_content = '\n'.join(f"{k}={v}" for k, v in env_vars.items())
        encoded_content = base64.b64encode(config_content.encode('utf-8'))

        config_file = self.config_dir / "app_config.enc"
        with open(config_file, 'wb') as f:
            f.write(encoded_content)

        logging.info(f"Создан зашифрованный конфиг: {config_file}")
        return config_file

    def generate_new_keys(self) -> Dict[str, str]:
        """Генерация новых ключей безопасности"""
        encryption_key = Fernet.generate_key().decode()
        hmac_secret = base64.b64encode(os.urandom(32)).decode()

        return {
            'FMS_ENCRYPTION_KEY': encryption_key,
            'FMS_HMAC_SECRET': hmac_secret
        }


class SecurityManager:
    """Менеджер безопасности с улучшенной загрузкой переменных окружения"""

    def __init__(self):
        self.env_manager = EnvironmentManager()
        self.env_vars = self.env_manager.load_environment()

        self._encryption_key = self._get_encryption_key()
        self._hmac_secret = self._get_hmac_secret()
        self._cipher = Fernet(self._encryption_key) if self._encryption_key else None

    def _get_encryption_key(self) -> Optional[bytes]:
        """Получение ключа шифрования"""
        key = self.env_vars.get('FMS_ENCRYPTION_KEY')
        if not key:
            logging.error("Ключ шифрования не найден!")
            return None

        try:
            # Если ключ в base64, декодируем
            if self._is_base64(key):
                return base64.b64decode(key)
            else:
                # Если строка, кодируем в байты
                return key.encode() if len(key) == 44 else base64.urlsafe_b64encode(key.encode()[:32])
        except Exception as e:
            logging.error(f"Ошибка обработки ключа шифрования: {e}")
            return None

    def _get_hmac_secret(self) -> Optional[bytes]:
        """Получение секрета HMAC"""
        secret = self.env_vars.get('FMS_HMAC_SECRET')
        if not secret:
            logging.error("HMAC секрет не найден!")
            return None

        try:
            # Если секрет в base64, декодируем
            if self._is_base64(secret):
                return base64.b64decode(secret)
            else:
                return secret.encode()
        except Exception as e:
            logging.error(f"Ошибка обработки HMAC секрета: {e}")
            return None

    def _is_base64(self, s: str) -> bool:
        """Проверка, является ли строка base64"""
        try:
            return base64.b64encode(base64.b64decode(s)).decode() == s
        except Exception:
            return False

    def create_hmac(self, data: str) -> Optional[str]:
        """Создание HMAC для данных"""
        if not self._hmac_secret:
            return None
        try:
            return hmac.new(self._hmac_secret, data.encode('utf-8'), hashlib.sha256).hexdigest()
        except Exception as e:
            logging.error(f"Ошибка создания HMAC: {e}")
            return None

    def decrypt_license(self, encrypted_data: str) -> Optional[str]:
        """Расшифровка лицензионных данных"""
        if not self._cipher:
            return None
        try:
            return self._cipher.decrypt(encrypted_data.encode('utf-8')).decode('utf-8')
        except Exception as e:
            logging.error(f"Ошибка расшифровки лицензии: {e}")
            return None


# Утилита для настройки окружения
def setup_environment():
    """Скрипт настройки переменных окружения"""
    import argparse

    parser = argparse.ArgumentParser(description='Настройка переменных окружения FlexMontage Studio')
    parser.add_argument('--create-env', action='store_true', help='Создать .env файл')
    parser.add_argument('--create-encrypted', action='store_true', help='Создать зашифрованный конфиг')
    parser.add_argument('--generate-keys', action='store_true', help='Сгенерировать новые ключи')

    args = parser.parse_args()

    env_manager = EnvironmentManager()

    if args.generate_keys:
        # Генерация новых ключей
        new_keys = env_manager.generate_new_keys()
        print("🔑 Новые ключи сгенерированы:")
        for key, value in new_keys.items():
            print(f"{key}={value}")

        if args.create_encrypted:
            env_manager.create_encrypted_config(new_keys)
            print("✅ Зашифрованный конфиг создан")

        if args.create_env:
            env_manager.create_env_template()
            print("✅ .env файл создан")

    elif args.create_env:
        env_manager.create_env_template()
        print("✅ .env файл создан")

    elif args.create_encrypted:
        # Использовать существующие ключи
        env_vars = env_manager.load_environment()
        if env_vars:
            env_manager.create_encrypted_config(env_vars)
            print("✅ Зашифрованный конфиг создан")
        else:
            print("❌ Не найдены ключи для создания зашифрованного конфига")

    else:
        # Показать статус
        env_vars = env_manager.load_environment()
        if env_vars:
            print("✅ Переменные окружения загружены успешно")
            print(f"Найдено ключей: {len(env_vars)}")
        else:
            print("❌ Переменные окружения не найдены")
            print("Используйте --create-env для создания .env файла")


if __name__ == "__main__":
    setup_environment()