import sys
import json
import datetime
import string
import random
import hashlib
import hmac
from cryptography.fernet import Fernet
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QDialog, QFormLayout,
                             QLineEdit, QComboBox, QMessageBox, QLabel)
from PySide6.QtCore import Qt

# Ключ шифрования и HMAC-секрет (совпадают с startup.py)
ENCRYPTION_KEY = b'EJ_NOoG-CdNJa6o-yySTs5Ibp_JC2tJpeROQPpvmPPM='
HMAC_SECRET = b'\xc2\xcc\xac\x14\xea|6:[-\xb1\x8c\xdfb`)\xcb\xe8pQ\x9a\xbb\x93d'
cipher = Fernet(ENCRYPTION_KEY)

def generate_key_format():
    """Генерирует ключ в формате XXXX-XXXX-XXXX-XXXX."""
    chars = string.ascii_letters + string.digits
    key = ''.join(random.choice(chars) for _ in range(16))
    return f"{key[:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"

def create_hmac(data):
    """Создаёт HMAC для проверки целостности данных."""
    return hmac.new(HMAC_SECRET, data.encode('utf-8'), hashlib.sha256).hexdigest()

def generate_license(duration=None, duration_minutes=None, user_id=None, hardware_id=None, output_db="licenses.json"):
    """Генерирует лицензионный ключ и сохраняет его в базу данных и отдельный файл."""
    start_date = datetime.datetime.now()
    if duration_minutes is not None:
        end_date = start_date + datetime.timedelta(minutes=duration_minutes)
    elif duration == "month":
        end_date = start_date + datetime.timedelta(days=30)
    elif duration == "3months":
        end_date = start_date + datetime.timedelta(days=90)
    elif duration == "year":
        end_date = start_date + datetime.timedelta(days=365)
    else:
        raise ValueError("Недопустимый срок действия. Используйте: month, 3months, year или duration_minutes")

    license_data = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "user_id": user_id or "anonymous",
        "hardware_id": hardware_id,
        "license_id": str(random.randint(100000, 999999))
    }

    license_json = json.dumps(license_data)
    hmac_signature = create_hmac(license_json)
    encrypted_data = cipher.encrypt(license_json.encode('utf-8')).decode('utf-8')

    license_key = generate_key_format()

    license_entry = {
        "key": license_key,
        "data": encrypted_data,
        "hmac": hmac_signature,
        "status": "active",
        "user_id": user_id or "anonymous",
        "created_at": start_date.isoformat()
    }

    # Сохранение в общую базу licenses.json
    licenses = []
    if os.path.exists(output_db):
        with open(output_db, "r", encoding="utf-8") as f:
            licenses = json.load(f)

    licenses.append(license_entry)

    with open(output_db, "w", encoding="utf-8") as f:
        json.dump(licenses, f, indent=4, ensure_ascii=False)

    # Создание отдельного файла для пользователя
    user_license_file = f"license_{license_key}.json"
    with open(user_license_file, "w", encoding="utf-8") as f:
        json.dump(license_entry, f, indent=4, ensure_ascii=False)

    return license_key, end_date, user_license_file

def revoke_license(license_key, output_db="licenses.json"):
    """Отзывает лицензию, помечая её как недействительную."""
    if not os.path.exists(output_db):
        return False, "База данных лицензий не найдена"

    with open(output_db, "r", encoding="utf-8") as f:
        licenses = json.load(f)

    for license in licenses:
        if license["key"] == license_key:
            license["status"] = "revoked"
            with open(output_db, "w", encoding="utf-8") as f:
                json.dump(licenses, f, indent=4, ensure_ascii=False)
            return True, f"Лицензия {license_key} отозвана"
    return False, f"Лицензия {license_key} не найдена"

class AddLicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать новую лицензию")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        self.layout.addLayout(self.form_layout)

        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText("Например: user123")
        self.form_layout.addRow("Идентификатор пользователя:", self.user_id_input)

        self.hardware_id_input = QLineEdit()
        self.hardware_id_input.setPlaceholderText("Оставьте пустым, если не требуется")
        self.form_layout.addRow("Идентификатор оборудования:", self.hardware_id_input)

        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["1 месяц", "3 месяца", "1 год", "Произвольный (минуты)"])
        self.form_layout.addRow("Срок действия:", self.duration_combo)

        self.minutes_input = QLineEdit()
        self.minutes_input.setPlaceholderText("Введите минуты (например, 5)")
        self.minutes_input.setEnabled(False)  # Активно только при выборе "Произвольный"
        self.form_layout.addRow("Минуты:", self.minutes_input)

        self.duration_combo.currentTextChanged.connect(self.toggle_minutes_input)

        self.button_layout = QHBoxLayout()
        self.create_button = QPushButton("Создать")
        self.create_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.reject)
        self.button_layout.addWidget(self.create_button)
        self.button_layout.addWidget(self.cancel_button)
        self.layout.addLayout(self.button_layout)

    def toggle_minutes_input(self, text):
        self.minutes_input.setEnabled(text == "Произвольный (минуты)")

    def get_license_data(self):
        duration_map = {
            "1 месяц": "month",
            "3 месяца": "3months",
            "1 год": "year"
        }
        duration = duration_map.get(self.duration_combo.currentText())
        duration_minutes = None
        if self.duration_combo.currentText() == "Произвольный (минуты)":
            try:
                duration_minutes = int(self.minutes_input.text())
                if duration_minutes <= 0:
                    raise ValueError
            except ValueError:
                raise ValueError("Укажите положительное количество минут")
        return {
            "user_id": self.user_id_input.text().strip() or None,
            "hardware_id": self.hardware_id_input.text().strip() or None,
            "duration": duration,
            "duration_minutes": duration_minutes
        }

class LicenseManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Менеджер лицензий")
        self.setGeometry(100, 100, 800, 600)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Ключ", "Статус", "Пользователь", "Срок действия", "Создано", "Действия"])
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.table)

        self.button_layout = QHBoxLayout()
        self.add_button = QPushButton("Добавить лицензию")
        self.add_button.clicked.connect(self.add_license)
        self.revoke_button = QPushButton("Отозвать лицензию")
        self.revoke_button.clicked.connect(self.revoke_license)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.load_licenses)
        self.button_layout.addWidget(self.add_button)
        self.button_layout.addWidget(self.revoke_button)
        self.button_layout.addWidget(self.refresh_button)
        self.layout.addLayout(self.button_layout)

        self.status_label = QLabel("Готово")
        self.layout.addWidget(self.status_label)

        self.load_licenses()

    def load_licenses(self):
        licenses_db = "licenses.json"
        self.table.setRowCount(0)

        if not os.path.exists(licenses_db):
            self.status_label.setText("База данных лицензий не найдена")
            return

        try:
            with open(licenses_db, "r", encoding="utf-8") as f:
                licenses = json.load(f)

            self.table.setRowCount(len(licenses))
            for row, license in enumerate(licenses):
                try:
                    license_json = cipher.decrypt(license["data"].encode('utf-8')).decode('utf-8')
                    license_data = json.loads(license_json)
                    end_date = datetime.datetime.fromisoformat(license_data["end_date"]).strftime('%Y-%m-%d %H:%M:%S')
                except Exception as e:
                    end_date = "Ошибка"

                self.table.setItem(row, 0, QTableWidgetItem(license["key"]))
                self.table.setItem(row, 1, QTableWidgetItem(license["status"]))
                self.table.setItem(row, 2, QTableWidgetItem(license["user_id"]))
                self.table.setItem(row, 3, QTableWidgetItem(end_date))
                self.table.setItem(row, 4, QTableWidgetItem(license["created_at"][:10]))

                revoke_button = QPushButton("Отозвать")
                revoke_button.clicked.connect(lambda checked, key=license["key"]: self.revoke_license(key))
                self.table.setCellWidget(row, 5, revoke_button)

            self.table.resizeColumnsToContents()
            self.status_label.setText("Лицензии загружены")
        except Exception as e:
            self.status_label.setText(f"Ошибка загрузки лицензий: {str(e)}")

    def add_license(self):
        dialog = AddLicenseDialog(self)
        if dialog.exec():
            license_data = dialog.get_license_data()
            try:
                license_key, end_date, user_license_file = generate_license(
                    duration=license_data["duration"],
                    duration_minutes=license_data["duration_minutes"],
                    user_id=license_data["user_id"],
                    hardware_id=license_data["hardware_id"]
                )
                QMessageBox.information(
                    self,
                    "Успех",
                    f"Лицензия создана: {license_key}\n"
                    f"Действительна до: {end_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Файл лицензии: {user_license_file}"
                )
                self.load_licenses()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось создать лицензию: {str(e)}")

    def revoke_license(self, license_key=None):
        if not license_key:
            selected = self.table.selectedItems()
            if not selected:
                QMessageBox.warning(self, "Ошибка", "Выберите лицензию для отзыва!")
                return
            license_key = selected[0].text()

        success, message = revoke_license(license_key)
        if success:
            QMessageBox.information(self, "Успех", message)
            self.load_licenses()
        else:
            QMessageBox.critical(self, "Ошибка", message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Указываем полный путь к styles.qss
    with open("/Users/mikman/PycharmProjects/PythonProject/.venv2/FlexMontage Studio/styles.qss", "r") as f:
        app.setStyleSheet(f.read())
    window = LicenseManager()
    window.show()
    sys.exit(app.exec())