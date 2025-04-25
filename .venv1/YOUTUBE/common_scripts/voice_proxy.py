import os
import sys
import csv
from datetime import datetime, timedelta
import shutil
import pandas as pd
import requests
import time
from config import get_channel_config, PROXY_CONFIG

def process_voice_and_proxy(channel_name):
    # Логируем начало функции
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начало обработки канала: {channel_name}")

    # Получаем настройки для канала
    config = get_channel_config(channel_name)
    if not config:
        raise ValueError(f"Канал {channel_name} не найден в конфигурации!")

    # Извлекаем параметры прокси из PROXY_CONFIG
    proxy_url = PROXY_CONFIG["proxy"]
    proxy_login = PROXY_CONFIG["proxy_login"]
    proxy_password = PROXY_CONFIG["proxy_password"]

    # Убираем префикс http:// или https:// из proxy_url, чтобы получить только хост и порт
    proxy_host_port = proxy_url.split("://")[-1]  # Извлекаем "65.109.79.15:25100"

    # Настройки прокси
    proxies = {
        "http": f"http://{proxy_login}:{proxy_password}@{proxy_host_port}",
        "https": f"http://{proxy_login}:{proxy_password}@{proxy_host_port}",
    }

    # URL для тестирования
    url = "http://httpbin.org/ip"
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Тестирование прокси-соединения")
        response = requests.get(url, proxies=proxies, timeout=10)
        print("Ответ сервера (HTTP-прокси):", response.json())
    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка при подключении через HTTP-прокси: {e}")

    # Извлекаем параметры из конфига
    CSV_FILE_PATH = config["csv_file_path"]
    OUTPUT_DIRECTORY = config["output_directory"]
    XLSX_FILE_PATH = config["xlsx_file_path"]
    STANDARD_VOICE_ID = config["standard_voice_id"]
    USE_LIBRARY_VOICE = config["use_library_voice"]
    original_voice_id = config["original_voice_id"]
    public_owner_id = config["public_owner_id"]
    default_lang = config["default_lang"]
    default_stability = config["default_stability"]
    default_similarity = config["default_similarity"]
    default_voice_speed = config["default_voice_speed"]
    default_voice_style = config["default_voice_style"]
    max_retries = config.get("max_retries", 10)  # Используем 10, если max_retries отсутствует

    # Функция parse_arguments с параметрами из конфига
    def parse_arguments():
        import argparse
        parser = argparse.ArgumentParser(description='Скрипт озвучки с параметрами речи.')
        parser.add_argument('--lang', type=str, default=default_lang, help='Код языка для выбора вкладки в Excel файле')
        parser.add_argument('--stability', type=float, default=default_stability, help='Параметр стабильности голоса (0.0 - 1.0)')
        parser.add_argument('--similarity', type=float, default=default_similarity, help='Параметр схожести с оригиналом (0.0 - 1.0)')
        parser.add_argument('--voice_speed', type=float, default=default_voice_speed, help='Скорость речи (зарезервировано)')
        parser.add_argument('--voice_style', type=str, default=default_voice_style, help='Стиль голоса (например: "excited", если доступно)')
        parser.add_argument('--max_retries', type=int, default=max_retries, help='Максимальное количество попыток для запросов')
        return parser.parse_args()

    def get_api_key_from_csv(csv_file_path):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Получение API-ключа из {csv_file_path}")
        api_key = None
        current_date = datetime.now().strftime('%d.%m.%Y')
        with open(csv_file_path, mode='r') as csv_file:
            reader = csv.DictReader(csv_file)
            rows = list(reader)
            for row in rows:
                if row.get('API') and not api_key:
                    row_date = datetime.strptime(row.get('Date'), '%d.%m.%Y').date()
                    one_month_ago = datetime.now().date() - timedelta(days=31)
                    if row_date <= one_month_ago:
                        api_key = row.get('API')
                        row['Date'] = current_date
        if api_key:
            temp_file_path = csv_file_path + '.tmp'
            with open(temp_file_path, mode='w', newline='') as temp_file:
                fieldnames = reader.fieldnames
                writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            shutil.move(temp_file_path, csv_file_path)
        return api_key

    def add_voice(api_key, voice_id, public_owner_id, new_name):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Добавление голоса: {new_name}")
        url = f"https://api.us.elevenlabs.io/v1/voices/add/{public_owner_id}/{voice_id}"
        headers = {"xi-api-key": api_key}
        data = {"new_name": new_name}
        try:
            response = requests.post(url, json=data, headers=headers, proxies=proxies)
            response.raise_for_status()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Голос из библиотеки успешно добавлен!")
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка при добавлении голоса: {e}")

    def get_voice_id(api_key, original_voice_id, public_owner_id):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Получение ID голоса")
        url = "https://api.us.elevenlabs.io/v1/voices"
        headers = {"xi-api-key": api_key}
        try:
            response = requests.get(url, headers=headers, proxies=proxies)
            response.raise_for_status()
            data = response.json()
            for item in data["voices"]:
                if item.get("sharing"):
                    if item["sharing"].get("original_voice_id") == original_voice_id and \
                       item["sharing"].get("public_owner_id") == public_owner_id:
                        return item["voice_id"]
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Новый ID голоса не найден.")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка при получении нового ID голоса: {e}")
            return None

    def cleanup_voices(api_key):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Очистка голосов из библиотеки")
        url = "https://api.us.elevenlabs.io/v1/voices"
        headers = {
            "xi-api-key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(url, headers=headers, proxies=proxies)
            response.raise_for_status()
            data = response.json()
            for voice in data.get("voices", []):
                if voice.get("category") != "premade":
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Удаление голоса из библиотеки: {voice['name']}")
                    delete_voice(api_key, voice["voice_id"])
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка при получении или удалении голосов: {e}")

    def delete_voice(api_key, voice_id):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Удаление голоса с ID: {voice_id}")
        url = f"https://api.us.elevenlabs.io/v1/voices/{voice_id}"
        headers = {"xi-api-key": api_key}
        try:
            response = requests.delete(url, headers=headers, proxies=proxies)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка при удалении голоса: {e}")

    def text_to_speech(api_key, text, output_file_path, voice_id, index, similarity, stability, voice_style, speed, max_retries):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Генерация аудио для строки {index + 1}")
        url = f"https://api.us.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        json_data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "similarity_boost": similarity,
                "stability": stability
            }
        }
        if voice_style:
            json_data["style"] = voice_style

        # Форматируем имя файла: числа от 1 до 99 с ведущими нулями (001-099), от 100 и выше — без (100, 101, ...)
        file_number = str(index + 1).zfill(3) if (index + 1) < 100 else str(index + 1)
        output_file_path = os.path.join(output_file_path, f"{file_number}.mp3")

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Попытка {attempt + 1} из {max_retries}...")
                response = requests.post(url, headers=headers, json=json_data, proxies=proxies, timeout=60)
                if response.status_code == 200:
                    with open(output_file_path, "wb") as audio_file:
                        audio_file.write(response.content)
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Успешно сохранено аудио: {output_file_path}")
                    return True
                else:
                    try:
                        response_data = response.json()
                        if response_data.get("detail", {}).get("status") == "detected_unusual_activity":
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Обнаружена необычная активность = BAN IP. Ожидание 2 минуты (ждем ротацию IP прокси) перед повторной попыткой...")
                            time.sleep(120)  # Ожидание 2 минуты
                            continue  # Повторяем попытку
                        elif response_data.get("detail", {}).get("status") == "quota_exceeded":
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Превышена квота: {response_data['detail']['message']}")
                            return "quota_exceeded"
                        else:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Не удалось сгенерировать аудио для файла {output_file_path}: {response.text}")
                            return False
                    except ValueError:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Не удалось распознать ответ сервера: {response.text}")
                        return False
            except requests.exceptions.Timeout:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Тайм-аут соединения. Повтор через 10 секунд (попытка {attempt + 1} из {max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(10)
                else:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Превышено количество попыток из-за тайм-аутов. Соединение не удалось.")
                    return False
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка соединения. Повтор через 10 секунд (попытка {attempt + 1} из {max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(10)
                else:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Превышено количество попыток. Соединение не удалось.")
                    return False
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Все попытки исчерпаны.")
        return False

    def get_starting_row(output_directory):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Проверка существующих файлов в {output_directory}")
        existing_files = os.listdir(output_directory)
        numbered_files = [int(f.split('.')[0]) for f in existing_files if f.split('.')[0].isdigit()]
        return max(numbered_files, default=0) + 1

    # Главная логика
    args = parse_arguments()
    LANGUAGE = args.lang.upper()
    stability = args.stability
    similarity = args.similarity
    voice_speed = args.voice_speed
    voice_style = args.voice_style
    max_retries = args.max_retries

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Загрузка Excel-файла: {XLSX_FILE_PATH}")
    excel_file = pd.ExcelFile(XLSX_FILE_PATH)
    sheet_names = excel_file.sheet_names
    if LANGUAGE not in sheet_names:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Вкладка '{LANGUAGE}' не найдена в Excel файле.")
        return

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Чтение данных из вкладки '{LANGUAGE}'")
    df = pd.read_excel(excel_file, sheet_name=LANGUAGE, header=None, usecols=[1])
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    starting_row = get_starting_row(OUTPUT_DIRECTORY)

    library_voice_id = None
    current_row = starting_row - 1
    result = None

    while True:
        api_key = get_api_key_from_csv(CSV_FILE_PATH)
        if not api_key:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API ключ не найден в CSV файле.")
            return

        cleanup_voices(api_key)

        if USE_LIBRARY_VOICE:
            new_voice_name = "Library_Copy"
            add_voice(api_key, original_voice_id, public_owner_id, new_voice_name)
            library_voice_id = get_voice_id(api_key, original_voice_id, public_owner_id)
            if not library_voice_id:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Не удалось получить ID нового голоса.")
                return

        try:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начало обработки строк Excel, начиная с {current_row + 1}")
            for index, row in df.iloc[current_row:].iterrows():
                text = str(row[1]).strip()
                if text and text.lower() != 'nan':
                    voice_id = library_voice_id if USE_LIBRARY_VOICE else STANDARD_VOICE_ID

                    result = text_to_speech(
                        api_key=api_key,
                        text=text,
                        output_file_path=OUTPUT_DIRECTORY,
                        voice_id=voice_id,
                        index=index,
                        similarity=similarity,
                        stability=stability,
                        voice_style=voice_style,
                        speed=voice_speed,
                        max_retries=max_retries
                    )

                    if result == "quota_exceeded":
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Превышение квоты, переключение на новый API-ключ.")
                        current_row = index
                        break
                    elif result is False:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка генерации речи. Прерывание работы.")
                        return
        finally:
            if USE_LIBRARY_VOICE and library_voice_id:
                delete_voice(api_key, library_voice_id)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Голос с ID {library_voice_id} удален из библиотеки.")

        if result is None:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Все строки обработаны или нет данных для обработки.")
            break
        elif result == "quota_exceeded":
            continue
        else:
            break

if __name__ == "__main__":
    test_channel = "1 ЗВЁЗДНЫЕ ТАЙНЫ TV"
    process_voice_and_proxy(test_channel)