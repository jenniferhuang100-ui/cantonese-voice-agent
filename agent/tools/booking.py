import csv
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CSV_PATH = os.path.join(DATA_DIR, "bookings.csv")


def book_fitting(name, phone, datetime_str):
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(CSV_PATH)

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Name", "Phone", "DateTime"])
        writer.writerow([name, phone, datetime_str])

    return {"status": "success", "message": f"Successfully booked for {name}."}
