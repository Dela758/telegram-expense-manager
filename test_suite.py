import os
import unittest
import asyncio
import uuid
from datetime import datetime, timedelta
from utils.database import ExpenseDB
from utils import parser, currency, forecaster, pdf_generator

class TestExpenseTracker(unittest.TestCase):
    def setUp(self):
        self.test_db = f"data/test_{uuid.uuid4().hex}.db"
        self.user_id = 999999

    def tearDown(self):
        if hasattr(self, 'test_db') and os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except:
                pass

    def test_01_database_user_and_expense_and_hashing(self):
        """Test user creation, PIN hashing, and expense CRUD"""
        async def run():
            db = ExpenseDB(self.test_db)
            await db.init_db()
            await db.create_user(self.user_id, pin="1234", currency="USD", budget=1000)
            user = await db.get_user(self.user_id)
            
            # Verify PIN is hashed and not "1234"
            self.assertNotEqual(user['pin'], "1234")
            self.assertTrue(db.verify_pin("1234", user['pin']))
            
            await db.add_expense(self.user_id, 50.0, "food", note="Test expense")
            expenses = await db.get_expenses(self.user_id)
            self.assertEqual(len(expenses), 1)
            
            expense_id = expenses[0]['id']
            await db.update_expense(expense_id, self.user_id, amount=75.0)
            expenses_after = await db.get_expenses(self.user_id)
            self.assertEqual(expenses_after[0]['amount'], 75.0)
            
            await db.delete_expense(expense_id, self.user_id)
            expenses_final = await db.get_expenses(self.user_id)
            self.assertEqual(len(expenses_final), 0)
            
        asyncio.run(run())

    def test_02_parsing(self):
        """Test natural language parsing (Synchronous)"""
        cases = [
            ("Spent 50 on food", 50.0, "food", None),
            ("$10 lunch", 10.0, "food", "$"),
        ]
        for msg, amt, cat, sym in cases:
            res = parser.parse_expense_message(msg)
            self.assertIsNotNone(res)
            self.assertEqual(res['amount'], amt)

    def test_03_forecaster(self):
        """Test spending forecast logic (Synchronous)"""
        today = datetime.now()
        expenses = [
            {"amount": 100, "date": (today - timedelta(days=1)).isoformat(), "category": "food"},
        ]
        res = forecaster.forecast_monthly_spend(expenses, 5000)
        self.assertIn("🔮", res)

    def test_04_pdf_generation(self):
        """Test PDF report generation"""
        expenses = [
            {"amount": 50, "date": datetime.now().isoformat(), "category": "food"},
        ]
        path = pdf_generator.generate_pdf_report(self.user_id, expenses, "USD", "Test Month")
        self.assertTrue(os.path.exists(path))

    def test_05_custom_categories(self):
        """Test custom categories logic"""
        async def run():
            db_inst = ExpenseDB(self.test_db)
            await db_inst.init_db()
            await db_inst.add_custom_category(self.user_id, "gym")
            categories = await db_inst.get_custom_categories(self.user_id)
            self.assertIn("gym", categories)
            await db_inst.delete_custom_category(self.user_id, "gym")
            
        asyncio.run(run())

    def test_06_storage_get_user_data(self):
        """Test storage.get_user_data and verify it fetches subscriptions (recurring) successfully"""
        from utils import storage
        from utils.database import db
        async def run():
            # Point singleton db to test db path
            db.db_path = self.test_db
            await db.init_db()
            
            # Create user & subscription
            await db.create_user(self.user_id, pin="1234")
            await db.add_subscription(self.user_id, "Spotify", 9.99, "entertainment", "monthly")
            
            # Fetch user data via storage wrapper
            data = await storage.get_user_data(self.user_id)
            
            # Verify data
            self.assertIsNotNone(data)
            self.assertTrue(db.verify_pin("1234", data["pin"]))
            self.assertEqual(len(data["recurring"]), 1)
            self.assertEqual(data["recurring"][0]["name"], "Spotify")
            
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
