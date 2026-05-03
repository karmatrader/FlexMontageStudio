"""
auth_service.py — двухфакторная аутентификация для nginx auth_request
Flow: пароль (bcrypt) → TOTP → финальный cookie (30 дней)

Переменные окружения:
  TOTP_SECRET        — base32 секрет (pyotp.random_base32())
  TOTP_COOKIE_SECRET — секрет для HMAC подписи cookie
  AUTH_PASSWORD_HASH — bcrypt хэш пароля (генерируется скриптом ниже)

Генерация хэша пароля:
  python3 -c "import bcrypt; print(bcrypt.hashpw(b'ВАШ_ПАРОЛЬ', bcrypt.gensalt()).decode())"
"""
import os
import hashlib
import hmac
import time
import io
import base64
import json
from flask import Flask, request, make_response, redirect, Response

import pyotp
import qrcode
import bcrypt

app = Flask(__name__)

TOTP_SECRET = os.environ.get("TOTP_SECRET", "")
COOKIE_SECRET = os.environ.get("TOTP_COOKIE_SECRET", "change_me")
PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH", "")
COOKIE_FINAL = "tghub_auth"
COOKIE_STEP1 = "tghub_step1"
COOKIE_DAYS = 30
STEP1_TTL = 300  # 5 минут
SERVICE_NAME = "TG Hub"


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def _hmac(value: str) -> str:
    return hmac.new(COOKIE_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_cookie(payload: dict, ttl: int) -> str:
    """Создаёт подписанный cookie: base64(json) + . + hmac."""
    data = json.dumps({**payload, "exp": int(time.time()) + ttl})
    b64 = base64.urlsafe_b64encode(data.encode()).decode()
    sig = _hmac(b64)
    return f"{b64}.{sig}"


def _verify_cookie(token: str) -> dict | None:
    """Проверяет подпись и срок действия. Возвращает payload или None."""
    try:
        b64, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _hmac(b64)):
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64).decode())
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _check_password(password: str) -> bool:
    if not PASSWORD_HASH:
        return False
    try:
        return bcrypt.checkpw(password.encode(), PASSWORD_HASH.encode())
    except Exception:
        return False


# ─── HTML шаблоны ─────────────────────────────────────────────────────────────

def _base_html(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TG Hub — {title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f0f13; color: #e0e0e0; font-family: system-ui, sans-serif;
       display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
.card {{ background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 12px;
        padding: 40px; width: 360px; }}
h1 {{ font-size: 20px; margin-bottom: 6px; color: #fff; }}
.subtitle {{ font-size: 12px; color: #444; margin-bottom: 24px; }}
label {{ display: block; font-size: 12px; color: #666; margin-bottom: 6px; }}
input[type=text], input[type=password] {{
    width: 100%; background: #0f0f13; border: 1px solid #2a2a3a; border-radius: 8px;
    padding: 12px 14px; color: #e0e0e0; font-size: 15px; outline: none; margin-bottom: 16px; }}
input[type=text]:focus, input[type=password]:focus {{ border-color: #7c6fe0; }}
.totp-input {{ font-size: 22px; letter-spacing: 6px; text-align: center; }}
button {{ width: 100%; background: #7c6fe0; border: none; border-radius: 8px;
         padding: 12px; color: #fff; font-size: 15px; cursor: pointer; transition: background 0.15s; }}
button:hover {{ background: #6a5ecc; }}
.error {{ color: #e06060; font-size: 13px; margin-top: 14px; text-align: center;
         background: #2a1010; border: 1px solid #4a2020; border-radius: 6px; padding: 8px; }}
.step {{ font-size: 11px; color: #444; text-align: right; margin-bottom: 20px; }}
</style></head>
<body><div class="card">{body}</div></body></html>"""


def _password_form(next_url: str, error: str = "") -> str:
    err = f'<div class="error">{error}</div>' if error else ""
    body = f"""
<h1>🔐 TG Hub</h1>
<p class="subtitle">Шаг 1 из 2 — Пароль</p>
<form method="post" action="/auth">
  <input type="hidden" name="next" value="{next_url}">
  <input type="hidden" name="step" value="password">
  <label>Пароль</label>
  <input type="password" name="password" autofocus autocomplete="current-password">
  <button type="submit">Продолжить →</button>
  {err}
</form>"""
    return _base_html("Вход", body)


def _totp_form(next_url: str, error: str = "") -> str:
    err = f'<div class="error">{error}</div>' if error else ""
    body = f"""
<h1>🔐 TG Hub</h1>
<p class="subtitle">Шаг 2 из 2 — Код аутентификатора</p>
<form method="post" action="/auth">
  <input type="hidden" name="next" value="{next_url}">
  <input type="hidden" name="step" value="totp">
  <label>6-значный код</label>
  <input type="text" name="code" class="totp-input" inputmode="numeric"
         maxlength="6" autocomplete="one-time-code" autofocus placeholder="000000">
  <button type="submit">Войти</button>
  {err}
</form>"""
    return _base_html("Код", body)


# ─── Маршруты ─────────────────────────────────────────────────────────────────

@app.route("/auth", methods=["GET"])
def auth_get():
    # Уже авторизован — пропускаем
    if _verify_cookie(request.cookies.get(COOKIE_FINAL, "")):
        return redirect(request.args.get("next", "/"))
    # Шаг 1 пройден — показываем TOTP
    if _verify_cookie(request.cookies.get(COOKIE_STEP1, "")):
        return _totp_form(request.args.get("next", "/"))
    return _password_form(request.args.get("next", "/"))


@app.route("/auth", methods=["POST"])
def auth_post():
    step = request.form.get("step", "password")
    next_url = request.form.get("next", "/")

    if step == "password":
        password = request.form.get("password", "")
        if not _check_password(password):
            # Небольшая задержка против брутфорса
            time.sleep(1)
            return _password_form(next_url, "Неверный пароль"), 401
        # Пароль верный — ставим step1 cookie и показываем TOTP
        resp = make_response(_totp_form(next_url))
        resp.set_cookie(
            COOKIE_STEP1,
            _make_cookie({"ok": True}, STEP1_TTL),
            max_age=STEP1_TTL,
            httponly=True, samesite="Lax", secure=True,
        )
        return resp

    elif step == "totp":
        # Проверяем что шаг 1 пройден
        if not _verify_cookie(request.cookies.get(COOKIE_STEP1, "")):
            return redirect(f"/auth?next={next_url}")
        if not TOTP_SECRET:
            return "TOTP_SECRET не настроен", 500
        code = request.form.get("code", "").strip()
        totp = pyotp.TOTP(TOTP_SECRET)
        if not totp.verify(code, valid_window=1):
            time.sleep(1)
            return _totp_form(next_url, "Неверный код. Попробуй ещё раз."), 401
        # Оба фактора пройдены — финальный cookie
        resp = make_response(redirect(next_url))
        resp.set_cookie(
            COOKIE_FINAL,
            _make_cookie({"auth": True}, COOKIE_DAYS * 86400),
            max_age=COOKIE_DAYS * 86400,
            httponly=True, samesite="Lax", secure=True,
        )
        # Удаляем step1 cookie
        resp.delete_cookie(COOKIE_STEP1)
        return resp

    return redirect(f"/auth?next={next_url}")


@app.route("/auth/verify", methods=["GET"])
def auth_verify():
    """Для nginx auth_request: 200 если авторизован, 401 иначе."""
    if _verify_cookie(request.cookies.get(COOKIE_FINAL, "")):
        return Response(status=200)
    return Response(status=401)


@app.route("/auth/setup", methods=["GET"])
def auth_setup():
    """QR-код для первичной настройки. Только с localhost."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return "Доступно только локально", 403
    if not TOTP_SECRET:
        return "Установи TOTP_SECRET", 500
    uri = pyotp.TOTP(TOTP_SECRET).provisioning_uri(name="admin", issuer_name=SERVICE_NAME)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Setup 2FA</title>
<style>body{{background:#0f0f13;color:#e0e0e0;font-family:system-ui;display:flex;
align-items:center;justify-content:center;min-height:100vh;flex-direction:column;gap:20px;}}
img{{border:8px solid #fff;border-radius:8px;}}
code{{background:#1a1a24;padding:8px 16px;border-radius:6px;font-size:14px;}}</style>
</head><body><h2>🔐 Настройка 2FA</h2>
<img src="data:image/png;base64,{b64}" width="260">
<p>Или введи секрет вручную:</p>
<code>{TOTP_SECRET}</code>
<p style="color:#444;font-size:12px;">Только с localhost</p>
</body></html>"""


if __name__ == "__main__":
    if not PASSWORD_HASH:
        print("\n⚠️  AUTH_PASSWORD_HASH не задан!")
        print("  Сгенерируй хэш пароля:")
        print("  python3 -c \"import bcrypt; print(bcrypt.hashpw(b'ВАШ_ПАРОЛЬ', bcrypt.gensalt()).decode())\"")
        print("  Добавь в systemd service: Environment=AUTH_PASSWORD_HASH=<хэш>\n")
    app.run(host="127.0.0.1", port=5002, debug=False)
