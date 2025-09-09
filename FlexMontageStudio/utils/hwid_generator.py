#!/usr/bin/env python3
"""
Генератор Hardware ID (HWID) для FlexMontage Studio
Использует несколько параметров системы (исключая MAC-адрес) для создания уникального идентификатора
"""
import hashlib
import platform
import os
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_cpu_info() -> str:
    """Получение информации о процессоре"""
    try:
        cpu_info = platform.processor() or "unknown_cpu"
        
        # Дополнительная информация для Windows
        if sys.platform == "win32":
            try:
                result = subprocess.run(['wmic', 'cpu', 'get', 'Name', '/value'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('Name='):
                            cpu_info = line.split('=', 1)[1].strip()
                            break
            except Exception:
                pass
        
        # Дополнительная информация для Linux
        elif sys.platform == "linux":
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.startswith('model name'):
                            cpu_info = line.split(':', 1)[1].strip()
                            break
            except Exception:
                pass
        
        return cpu_info[:100]  # Ограничиваем длину
        
    except Exception as e:
        logger.debug(f"Ошибка получения CPU info: {e}")
        return "unknown_cpu"


def get_motherboard_serial() -> str:
    """Получение серийного номера материнской платы"""
    try:
        if sys.platform == "win32":
            try:
                result = subprocess.run(['wmic', 'baseboard', 'get', 'SerialNumber', '/value'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('SerialNumber='):
                            serial = line.split('=', 1)[1].strip()
                            if serial and serial != "To be filled by O.E.M.":
                                return serial[:50]
            except Exception:
                pass
        
        elif sys.platform == "linux":
            try:
                result = subprocess.run(['sudo', 'dmidecode', '-s', 'baseboard-serial-number'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    serial = result.stdout.strip()
                    if serial and serial != "To Be Filled By O.E.M.":
                        return serial[:50]
            except Exception:
                pass
        
        elif sys.platform == "darwin":
            try:
                result = subprocess.run(['system_profiler', 'SPHardwareDataType'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Serial Number' in line:
                            serial = line.split(':', 1)[1].strip()
                            return serial[:50]
            except Exception:
                pass
        
        return "unknown_motherboard"
        
    except Exception as e:
        logger.debug(f"Ошибка получения motherboard serial: {e}")
        return "unknown_motherboard"


def get_disk_serial() -> str:
    """Получение серийного номера основного диска"""
    try:
        if sys.platform == "win32":
            try:
                # Получаем серийный номер диска C:
                result = subprocess.run(['wmic', 'logicaldisk', 'where', 'caption="C:"', 
                                       'get', 'VolumeSerialNumber', '/value'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('VolumeSerialNumber='):
                            serial = line.split('=', 1)[1].strip()
                            if serial:
                                return serial[:20]
            except Exception:
                pass
        
        elif sys.platform == "linux":
            try:
                # Пытаемся получить UUID root раздела
                result = subprocess.run(['blkid', '-s', 'UUID', '-o', 'value', '/'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    uuid = result.stdout.strip()
                    if uuid:
                        return uuid[:36]
            except Exception:
                pass
        
        elif sys.platform == "darwin":
            try:
                result = subprocess.run(['diskutil', 'info', '/'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Volume UUID' in line:
                            uuid = line.split(':', 1)[1].strip()
                            return uuid[:36]
            except Exception:
                pass
        
        return "unknown_disk"
        
    except Exception as e:
        logger.debug(f"Ошибка получения disk serial: {e}")
        return "unknown_disk"


def get_system_uuid() -> str:
    """Получение системного UUID"""
    try:
        if sys.platform == "win32":
            try:
                result = subprocess.run(['wmic', 'csproduct', 'get', 'UUID', '/value'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('UUID='):
                            uuid = line.split('=', 1)[1].strip()
                            if uuid and uuid != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
                                return uuid[:36]
            except Exception:
                pass
        
        elif sys.platform == "linux":
            try:
                if os.path.exists('/sys/class/dmi/id/product_uuid'):
                    with open('/sys/class/dmi/id/product_uuid', 'r') as f:
                        uuid = f.read().strip()
                        if uuid:
                            return uuid[:36]
            except Exception:
                pass
        
        elif sys.platform == "darwin":
            try:
                result = subprocess.run(['system_profiler', 'SPHardwareDataType'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Hardware UUID' in line:
                            uuid = line.split(':', 1)[1].strip()
                            return uuid[:36]
            except Exception:
                pass
        
        return "unknown_system_uuid"
        
    except Exception as e:
        logger.debug(f"Ошибка получения system UUID: {e}")
        return "unknown_system_uuid"


def get_username_info() -> str:
    """Получение информации о пользователе"""
    try:
        # Используем переменные окружения пользователя
        username = os.environ.get('USERNAME') or os.environ.get('USER') or "unknown_user"
        computername = os.environ.get('COMPUTERNAME') or platform.node() or "unknown_computer"
        
        return f"{username}@{computername}"[:50]
        
    except Exception as e:
        logger.debug(f"Ошибка получения user info: {e}")
        return "unknown_user@unknown_computer"


def get_install_path_hash() -> str:
    """Получение хэша от пути установки приложения"""
    try:
        if getattr(sys, 'frozen', False):
            # Скомпилированное приложение
            install_path = str(Path(sys.executable).parent)
        else:
            # Режим разработки
            install_path = str(Path(__file__).parent.parent)
        
        # Создаем хэш от пути установки
        path_hash = hashlib.md5(install_path.encode('utf-8')).hexdigest()
        return path_hash[:16]
        
    except Exception as e:
        logger.debug(f"Ошибка получения install path hash: {e}")
        return "unknown_install_path"


def generate_hwid() -> str:
    """
    Генерация Hardware ID на основе нескольких системных параметров
    
    Returns:
        str: Уникальный HWID в формате 32 символа (hex)
    """
    logger.info("🔧 Генерация Hardware ID...")
    
    try:
        # Собираем компоненты HWID
        components = {
            "cpu": get_cpu_info(),
            "motherboard": get_motherboard_serial(),
            "disk": get_disk_serial(),
            "system_uuid": get_system_uuid(),
            "user_info": get_username_info(),
            "install_path": get_install_path_hash(),
            "platform": f"{platform.system()}_{platform.release()}_{platform.architecture()[0]}"
        }
        
        logger.debug("HWID компоненты:")
        for key, value in components.items():
            logger.debug(f"  {key}: {value[:20]}...")
        
        # Объединяем все компоненты
        combined_string = "|".join([f"{k}:{v}" for k, v in components.items()])
        
        # Создаем финальный хэш
        hwid_hash = hashlib.sha256(combined_string.encode('utf-8')).hexdigest()
        
        # Берем первые 32 символа для удобства
        hwid = hwid_hash[:32].upper()
        
        logger.info(f"✅ HWID сгенерирован: {hwid[:8]}...{hwid[-4:]}")
        return hwid
        
    except Exception as e:
        logger.error(f"❌ Ошибка генерации HWID: {e}")
        # Fallback HWID на основе платформы и времени
        import time
        fallback_data = f"{platform.node()}_{platform.system()}_{int(time.time() / 86400)}"
        fallback_hwid = hashlib.md5(fallback_data.encode('utf-8')).hexdigest()[:32].upper()
        logger.warning(f"🔄 Используем fallback HWID: {fallback_hwid}")
        return fallback_hwid


def format_hwid_for_display(hwid: str) -> str:
    """
    Форматирование HWID для удобного отображения пользователю
    
    Args:
        hwid: Raw HWID (32 символа)
        
    Returns:
        str: Отформатированный HWID (XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX)
    """
    if len(hwid) != 32:
        return hwid
    
    return f"{hwid[0:8]}-{hwid[8:16]}-{hwid[16:24]}-{hwid[24:32]}"


def save_hwid_to_file(hwid: str, file_path: Optional[Path] = None) -> bool:
    """
    Сохранение HWID в файл для справки пользователя
    
    Args:
        hwid: HWID для сохранения
        file_path: Путь к файлу (по умолчанию hwid.txt рядом с приложением)
        
    Returns:
        bool: True если успешно сохранено
    """
    try:
        if not file_path:
            if getattr(sys, 'frozen', False):
                app_dir = Path(sys.executable).parent
            else:
                app_dir = Path(__file__).parent.parent
            file_path = app_dir / "hwid.txt"
        
        formatted_hwid = format_hwid_for_display(hwid)
        
        content = f"""FlexMontage Studio - Hardware ID (HWID)
==========================================

Ваш Hardware ID: {formatted_hwid}

📱 Отправьте этот HWID боту в Telegram: https://t.me/fms_license_bot
🔑 Бот пришлет вам лицензионный файл для активации программы
💾 Поместите полученный файл лицензии рядом с программой

⚠️  ВАЖНО: Этот HWID уникален для вашего компьютера.
   Лицензия будет работать только на этом ПК.
   
Дата создания: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Система: {platform.system()} {platform.release()}
"""
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"✅ HWID сохранен в файл: {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения HWID в файл: {e}")
        return False