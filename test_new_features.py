import os
import asyncio
import uuid
import unittest
from utils.database import ExpenseDB
from utils.ai_categorizer import get_smart_category

class TestNewFeatures(unittest.TestCase):
    def setUp(self):
        self.test_db = f"data/test_new_{uuid.uuid4().hex}.db"
        self.user_id = 888888

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except:
                pass

    def test_01_subscriptions(self):
        """Test subscription CRUD operations"""
        async def run():
            db = ExpenseDB(self.test_db)
            await db.init_db()
            
            # Add subscription
            await db.add_subscription(self.user_id, "Netflix", 15.99, "entertainment", "monthly")
            subs = await db.get_subscriptions(self.user_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]['name'], "Netflix")
            self.assertEqual(subs[0]['billing_cycle'], "monthly")
            
            # Update log
            sub_id = subs[0]['id']
            await db.update_subscription_log(sub_id, "2026-01-01")
            subs_after = await db.get_subscriptions(self.user_id)
            self.assertEqual(subs_after[0]['last_logged'], "2026-01-01")
            
            # Delete
            await db.delete_subscription(sub_id, self.user_id)
            subs_final = await db.get_subscriptions(self.user_id)
            self.assertEqual(len(subs_final), 0)
            
        asyncio.run(run())

    def test_02_ai_categorizer_logic(self):
        """
        Test AI categorizer. 
        Note: This requires GROQ_API_KEY. Tests will skip if not present.
        """
        if not os.getenv("GROQ_API_KEY"):
            print("Skipping AI Categorizer test (no API key).")
            return

        async def run():
            db = ExpenseDB(self.test_db)
            await db.init_db()
            
            # Case: Standard merchant
            cat = await get_smart_category(self.user_id, "Starbucks")
            self.assertEqual(cat, "food")
            
            # Case: Clear description
            cat = await get_smart_category(self.user_id, "Monthly Gas", "Paid for car fuel")
            self.assertEqual(cat, "transport")
            
            # Case: Custom category awareness
            await db.add_custom_category(self.user_id, "crypto")
            cat = await get_smart_category(self.user_id, "Coinbase purchase", "buying bitcoin")
            self.assertEqual(cat, "crypto")
            
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
