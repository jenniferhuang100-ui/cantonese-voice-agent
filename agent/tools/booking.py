import csv
from pathlib import Path

BOOKINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "bookings.csv"
FIELDNAMES = ["name", "phone", "datetime"]


def book_fitting(name, phone, datetime_str):
    file_exists = BOOKINGS_PATH.exists()

    with open(BOOKINGS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({"name": name, "phone": phone, "datetime": datetime_str})

    return {"status": "confirmed", "name": name, "phone": phone, "datetime": datetime_str}
