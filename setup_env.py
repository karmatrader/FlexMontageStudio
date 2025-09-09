#!/usr/bin/env python3
"""
Скрипт быстрой настройки FlexMontage Studio
Использование:
    python setup_env.py                  # Создать .env файл
    python setup_env.py --new-keys      # Сгенерировать новые ключи
    python setup_env.py --production    # Подготовить для продакшена
"""

import sys
import os
from pathlib import Path


def main():
    # Проверяем структуру файлов
    current_dir = Path(__file__).parent
    config_dir = current_dir / "config"
    env_manager_file = config_dir / "env_manager.py"
    init_file = config_dir / "__init__.py"

    print("🔍 Проверка структуры файлов...")

    if not config_dir.exists():
        print("❌ Папка config/ не найдена!")
        print("Создайте папку config/ в корне проекта")
        return

    if not env_manager_file.exists():
        print("❌ Файл config/env_manager.py не найден!")
        print("Скопируйте файл env_manager.py в папку config/")
        return

    if not init_file.exists():
        print("🔧 Создаем файл config/__init__.py...")
        with open(init_file, 'w') as f:
            f.write("# Файл для превращения папки config в Python пакет\n")
        print("✅ Файл config/__init__.py создан")

    # Теперь пробуем импортировать
    try:
        from config.env_manager import EnvironmentManager
        print("✅ Модуль env_manager успешно импортирован")
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")

        # Альтернативный способ - прямой импорт
        print("🔄 Пробуем альтернативный способ импорта...")
        sys.path.insert(0, str(config_dir))
        try:
            import env_manager
            EnvironmentManager = env_manager.EnvironmentManager
            print("✅ Альтернативный импорт успешен")
        except ImportError as e2:
            print(f"❌ Альтернативный импорт тоже не удался: {e2}")
            return

    import argparse

    parser = argparse.ArgumentParser(
        description='Быстрая настройка окружения FlexMontage Studio',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python setup_env.py                    # Создать .env с дефолтными ключами
  python setup_env.py --new-keys        # Сгенерировать новые ключи
  python setup_env.py --production      # Подготовить для продакшена
  python setup_env.py --check           # Проверить текущие настройки
        """
    )

    parser.add_argument('--new-keys', action='store_true',
                        help='Сгенерировать новые ключи безопасности')
    parser.add_argument('--production', action='store_true',
                        help='Создать зашифрованный конфиг для продакшена')
    parser.add_argument('--check', action='store_true',
                        help='Проверить текущие настройки')
    parser.add_argument('--force', action='store_true',
                        help='Перезаписать существующие файлы')

    args = parser.parse_args()

    env_manager = EnvironmentManager()

    print("\n🚀 FlexMontage Studio - Настройка окружения")
    print("=" * 50)

    if args.check:
        check_environment(env_manager)
    elif args.production:
        setup_production(env_manager, args.force)
    elif args.new_keys:
        setup_with_new_keys(env_manager, args.force)
    else:
        setup_default(env_manager, args.force)


def check_environment(env_manager):
    """Проверка текущего окружения"""
    print("🔍 Проверка окружения...")

    env_vars = env_manager.load_environment()

    if env_vars:
        print("✅ Переменные окружения найдены")
        print(f"📊 Загружено ключей: {len(env_vars)}")

        # Проверка наличия файлов
        env_file = Path.cwd() / ".env"
        config_file = env_manager.config_dir / "app_config.enc"

        print("\n📁 Файлы конфигурации:")
        print(f"  .env файл: {'✅ Найден' if env_file.exists() else '❌ Не найден'}")
        print(f"  Зашифрованный конфиг: {'✅ Найден' if config_file.exists() else '❌ Не найден'}")

        # Проверка системных переменных
        sys_vars = ['FMS_ENCRYPTION_KEY', 'FMS_HMAC_SECRET']
        sys_found = [var for var in sys_vars if os.environ.get(var)]
        print(f"  Системные переменные: {len(sys_found)}/{len(sys_vars)} найдено")

    else:
        print("❌ Переменные окружения не найдены")
        print("💡 Запустите: python setup_env.py")


def setup_default(env_manager, force=False):
    """Настройка с дефолтными ключами"""
    print("🔧 Создание .env файла с дефолтными ключами...")

    env_file = Path.cwd() / ".env"
    if env_file.exists() and not force:
        print("⚠️  .env файл уже существует")
        response = input("Перезаписать? (y/N): ").lower()
        if response != 'y':
            print("❌ Отменено")
            return
        env_file.unlink()

    created_file = env_manager.create_env_template()
    print(f"✅ Создан файл: {created_file}")
    print("⚠️  ВНИМАНИЕ: Используются дефолтные ключи!")
    print("💡 Для продакшена используйте: python setup_env.py --new-keys")


def setup_with_new_keys(env_manager, force=False):
    """Настройка с новыми ключами"""
    print("🔑 Генерация новых ключей безопасности...")

    new_keys = env_manager.generate_new_keys()

    print("✅ Новые ключи сгенерированы:")
    for key, value in new_keys.items():
        print(f"  {key}={value}")

    # Создание .env файла с новыми ключами
    env_file = Path.cwd() / ".env"
    if env_file.exists() and not force:
        print(f"\n⚠️  .env файл уже существует: {env_file}")
        response = input("Перезаписать новыми ключами? (y/N): ").lower()
        if response != 'y':
            print("❌ Отменено")
            return

    # Создание содержимого .env файла
    env_content = f"""# FlexMontage Studio Environment Variables
# Сгенерировано автоматически

# Ключ шифрования для лицензий
FMS_ENCRYPTION_KEY={new_keys['FMS_ENCRYPTION_KEY']}

# Секрет для HMAC
FMS_HMAC_SECRET={new_keys['FMS_HMAC_SECRET']}

# Опциональные настройки
# FMS_DEBUG=true
# FMS_LOG_LEVEL=DEBUG
"""

    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(env_content)

    print(f"✅ Создан .env файл: {env_file}")
    print("🔒 Ключи уникальны для этой установки")


def setup_production(env_manager, force=False):
    """Настройка для продакшена"""
    print("🏭 Подготовка конфигурации для продакшена...")

    # Генерация новых ключей
    new_keys = env_manager.generate_new_keys()

    # Создание зашифрованного конфига
    config_file = env_manager.create_encrypted_config(new_keys)

    print("✅ Создан зашифрованный конфиг для продакшена")
    print(f"📁 Файл: {config_file}")

    # Показать инструкции для PyInstaller
    print("\n📝 Инструкции для PyInstaller:")
    print("1. Добавьте в .spec файл:")
    print("   datas=[")
    print(f"     ('{config_file.relative_to(Path.cwd())}', 'config/'),")
    print("     ...", )
    print("   ]")
    print("\n2. Соберите exe:")
    print("   pyinstaller your_app.spec")

    print("\n🔑 Ключи для продакшена:")
    for key, value in new_keys.items():
        print(f"  {key}={value}")

    print("\n⚠️  Сохраните эти ключи в безопасном месте!")


if __name__ == "__main__":
    main()