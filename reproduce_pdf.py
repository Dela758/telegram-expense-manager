import os
import sys
from datetime import datetime

# Add current directory to path so we can import utils
sys.path.append(os.getcwd())

from utils import pdf_generator

def test_pdf_generation():
    user_id = 12345
    expenses = [
        {"amount": 50.0, "category": "food", "date": datetime.now().isoformat(), "note": "Lunch 🍔"},
        {"amount": 20.0, "category": "transport", "date": datetime.now().isoformat(), "note": "Bus 🚌"},
        {"amount": 100.0, "category": "entertainment", "date": datetime.now().isoformat(), "note": "Movie 🍿"},
    ]
    currency = "₦"  # Nigerian Naira (Unicode)
    month_name = "December 2025"
    budget = 500.0
    limits = {"food": 100.0, "transport": 50.0}

    print("Starting PDF generation...")
    try:
        path = pdf_generator.generate_pdf_report(
            user_id=user_id,
            expenses=expenses,
            currency=currency,
            month_name=month_name,
            budget=budget,
            limits=limits
        )
        print(f"PDF generated successfully at: {path}")
        if os.path.exists(path):
            print(f"File size: {os.path.getsize(path)} bytes")
        else:
            print("Error: File does not exist after generation!")
    except Exception as e:
        print(f"An error occurred during PDF generation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pdf_generation()
