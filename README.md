# 💰 Telegram Expense Tracker Bot

A professional, feature-rich **Telegram bot** built in Python to track daily expenses, manage budgets, scan receipts with AI, and generate visual reports — all directly from your chat.

---

## 🚀 Key Features

### 📥 Effortless Entry
- **Natural Language Parsing**: Add expenses by typing simple sentences (e.g., "Spent 50 on dinner").
- **AI OCR Scanning**: Upload a photo of your receipt, and the bot automatically extracts the amount, category, merchant, and date using **Groq-powered Vision AI**.
- **Recurring Expenses**: Set up automated logging for monthly bills or subscriptions.

### 📊 Powerful Insights
- **Monthly Forecasts**: Predict your end-of-month spending based on current habits.
- **Spending Charts**: Generate pie and bar charts to visualize where your money goes.
- **Budget Alerts**: Set monthly limits and get notified when you reach 80% or exceed your budget.

### 📄 Professional Reporting
- **PDF Export**: Receive a detailed, formatted monthly report with category breakdowns and limit status.
- **CSV Export**: Get a spreadsheet-ready file sent directly to your email.
- **Interactive History**: View and delete recent transactions via inline buttons.

### 🔒 Security & Customization
- **PIN Protected**: Secure your data with a `bcrypt`-hashed PIN.
- **Multi-Currency Support**: Dynamically switch your default currency.
- **Custom Categories**: Define your own expense categories to match your lifestyle.

---

## 🧠 Tech Stack

- **Python 3.10+**
- **python-telegram-bot v20+**: Asynchronous wrapper for the Telegram API.
- **SQLite3 / aiosqlite**: Local, persistent, and non-blocking database storage.
- **Groq AI (Llama-4 Vision)**: Cutting-edge OCR for receipt parsing.
- **FPDF2**: Clean, customizable PDF report generation.
- **Pandas & Matplotlib**: Data analysis and visual chart generation.

---

## ⚙️ Setup & Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/telegram-expense-tracker.git
   cd telegram-expense-tracker
   ```

2. **Configure Environment Variables**
   Create a `.env` file in the root directory:
   ```env
   BOT_TOKEN=your_telegram_bot_token
   GROQ_API_KEY=your_groq_api_key
   EMAIL_ADDRESS=your_gmail@gmail.com
   EMAIL_PASSWORD=your_app_specific_password
   EXCHANGE_API_KEY=your_exchange_rate_api_key
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Bot**
   ```bash
   python main.py
   ```
