import os
hmac_secret = os.urandom(24)  # 24 байта
print(f"Ваш HMAC_SECRET: {hmac_secret}")