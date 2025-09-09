from cryptography.fernet import Fernet

# Генерируем ключ
key = Fernet.generate_key()
print(f"Ваш ENCRYPTION_KEY: {key.decode('utf-8')}")