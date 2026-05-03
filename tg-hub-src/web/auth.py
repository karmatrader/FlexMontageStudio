"""
web/auth.py — аутентификация и авторизация TG Hub
"""
import io
import base64
from functools import wraps

import bcrypt
import pyotp
import qrcode
from flask import session, redirect, request


def login_required(f):
    """Декоратор: требует авторизованного пользователя."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            next_url = request.path
            if request.query_string:
                next_url += "?" + request.query_string.decode()
            return redirect(f"/login?next={next_url}")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Декоратор: требует is_admin=1 в сессии."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(f"/login?next={request.path}")
        if not session.get("is_admin"):
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


def hash_password(password: str) -> str:
    """Хеширует пароль через bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str, hashed: str) -> bool:
    """Проверяет пароль против bcrypt-хеша."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def generate_totp_secret() -> str:
    """Генерирует случайный TOTP secret в base32."""
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    """Верифицирует TOTP-код (допускает ±1 период = 90 сек)."""
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def get_totp_uri(secret: str, username: str, issuer: str = "TG Hub") -> str:
    """Возвращает otpauth:// URI для QR-кода."""
    return pyotp.TOTP(secret).provisioning_uri(username, issuer_name=issuer)


def generate_qr_base64(uri: str) -> str:
    """Генерирует PNG QR-код для URI, возвращает base64-строку для <img src>."""
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
