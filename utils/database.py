import aiosqlite
import os
import bcrypt
from datetime import datetime
import logging

DB_PATH = os.environ.get("EXPENSE_DB_PATH", "data/expenses.db")

class ExpenseDB:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _get_conn(self):
        # Return the connection object (which is an async context manager)
        # We do NOT await here to avoid double-starting the thread.
        return aiosqlite.connect(self.db_path)

    async def init_db(self):
        async with self._get_conn() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    pin TEXT,
                    currency TEXT DEFAULT 'USD',
                    budget REAL DEFAULT 0,
                    email TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    category TEXT,
                    date TEXT,
                    note TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS category_limits (
                    user_id INTEGER,
                    category TEXT,
                    amount REAL,
                    PRIMARY KEY (user_id, category),
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recurring (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    category TEXT,
                    last_logged TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    name TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    UNIQUE(user_id, name)
                )
            """)
            await conn.commit()

    async def get_user(self, user_id):
        async with self._get_conn() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone()

    async def get_all_users(self):
        async with self._get_conn() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM users")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def create_user(self, user_id, pin=None, currency='USD', budget=0, email=None):
        hashed_pin = self._hash_pin(pin) if pin else None
        async with self._get_conn() as conn:
            await conn.execute("INSERT OR IGNORE INTO users (user_id, pin, currency, budget, email) VALUES (?, ?, ?, ?, ?)",
                         (user_id, hashed_pin, currency, budget, email))
            await conn.commit()

    async def update_user(self, user_id, **kwargs):
        if not kwargs: return
        if 'pin' in kwargs and kwargs['pin']:
            kwargs['pin'] = self._hash_pin(kwargs['pin'])
            
        keys = list(kwargs.keys())
        query = "UPDATE users SET " + ", ".join([f"{k} = ?" for k in keys]) + " WHERE user_id = ?"
        async with self._get_conn() as conn:
            await conn.execute(query, [kwargs[k] for k in keys] + [user_id])
            await conn.commit()

    def _hash_pin(self, pin: str) -> str:
        if not pin: return None
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pin.encode(), salt).decode()

    def verify_pin(self, plain_pin: str, hashed_pin: str) -> bool:
        if not plain_pin or not hashed_pin: return False
        try:
            # Handle legacy plain-text PINs (4 digits)
            if len(hashed_pin) == 4 and hashed_pin.isdigit():
                return plain_pin == hashed_pin
            return bcrypt.checkpw(plain_pin.encode(), hashed_pin.encode())
        except Exception as e:
            logging.error(f"PIN verification error: {e}")
            return False

    async def add_expense(self, user_id, amount, category, date=None, note=None):
        if not date: date = datetime.now().isoformat()
        async with self._get_conn() as conn:
            await conn.execute("INSERT INTO expenses (user_id, amount, category, date, note) VALUES (?, ?, ?, ?, ?)",
                         (user_id, amount, category, date, note))
            await conn.commit()

    async def get_expenses(self, user_id, limit=None, offset=0, category=None):
        query = "SELECT * FROM expenses WHERE user_id = ?"
        params = [user_id]
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY date DESC"
        
        if limit:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
        async with self._get_conn() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_expense(self, expense_id, user_id):
        async with self._get_conn() as conn:
            await conn.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id))
            await conn.commit()

    async def update_expense(self, expense_id, user_id, **kwargs):
        if not kwargs: return
        keys = list(kwargs.keys())
        query = f"UPDATE expenses SET {', '.join([f'{k} = ?' for k in keys])} WHERE id = ? AND user_id = ?"
        async with self._get_conn() as conn:
            await conn.execute(query, [kwargs[k] for k in keys] + [expense_id, user_id])
            await conn.commit()

    async def set_limit(self, user_id, category, amount):
        async with self._get_conn() as conn:
            await conn.execute("INSERT OR REPLACE INTO category_limits (user_id, category, amount) VALUES (?, ?, ?)",
                         (user_id, category.lower(), amount))
            await conn.commit()

    async def get_limits(self, user_id):
        async with self._get_conn() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT category, amount FROM category_limits WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            return {row['category']: row['amount'] for row in rows}

    async def add_recurring(self, user_id, amount, category):
        async with self._get_conn() as conn:
            await conn.execute("INSERT INTO recurring (user_id, amount, category) VALUES (?, ?, ?)",
                         (user_id, amount, category))
            await conn.commit()

    async def get_recurring(self, user_id):
        async with self._get_conn() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM recurring WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_recurring_log(self, recurring_id, last_logged):
        async with self._get_conn() as conn:
            await conn.execute("UPDATE recurring SET last_logged = ? WHERE id = ?", (last_logged, recurring_id))
            await conn.commit()

    # --- Custom Categories Methods ---
    async def add_custom_category(self, user_id, name):
        async with self._get_conn() as conn:
            try:
                await conn.execute("INSERT INTO custom_categories (user_id, name) VALUES (?, ?)", (user_id, name.lower()))
                await conn.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_custom_categories(self, user_id):
        async with self._get_conn() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT name FROM custom_categories WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            return [row['name'] for row in rows]

    async def delete_custom_category(self, user_id, name):
        async with self._get_conn() as conn:
            await conn.execute("DELETE FROM custom_categories WHERE user_id = ? AND name = ?", (user_id, name.lower()))
            await conn.commit()

db = ExpenseDB()
