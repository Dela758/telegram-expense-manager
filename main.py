import logging
import os
import re
from datetime import datetime
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler,
    PicklePersistence, ApplicationHandlerStop
)

from utils import storage, parser, currency, visualizer, forecaster, pdf_generator, ocr, voice_processor
from utils.database import db
from utils.scheduler import schedule_jobs

logging.basicConfig(level=logging.INFO)

# Conversation states
(
    ASK_PIN, VERIFY_PIN, ADD_EXPENSE, ADD_RECUR, 
    SET_LIMIT, SET_BUDGET, SET_EMAIL, ASK_CURRENCY, 
    ASK_EMAIL, EDIT_EXPENSE_AMT, EDIT_EXPENSE_CAT, 
    ADD_CATEGORY_NAME
) = range(12)

# -------------------- START / PIN --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Initialize new user or check authorization
    if context.user_data.get('authorized'):
        await show_main_menu(update, context)
        return ConversationHandler.END

    user_data = await storage.get_user_data(user_id)
    if not user_data:
        await storage.save_user_data(user_id, {
            "expenses": [],
            "budget": 0,
            "currency": "USD",
            "pin": None,
            "category_limits": {},
            "email": None,
        })

        welcome_msg = """🌟 *WELCOME TO EXPENSE TRACKER PRO* 🌟
━━━━━━━━━━━━━━━━━━━━
Your personal companion for smart financial management. 🧾💸

*What I can do for you:*
🛡️ *Secure tracking* with 4-digit PIN protection.
🎙️ *Voice Logging* – record expenses with AI transcription.
📸 *Receipt Scanning* – auto-extract data from photos.
📊 *Instant Summaries* & category breakdowns.
🔮 *AI Forecasts* to predict monthly spending.
📑 *Professional Reports* in PDF & CSV formats.
⏳ *Recurring bill* automation.

*Available Commands:*
🔹 `/menu` - Main dashboard (All buttons)
🔹 `/add` - Quick add (e.g., '50 food')
🔹 `/summary` - Today's spending report
🔹 `/upload` - Scan a receipt photo
🔹 `/recurring` - Manage repeat bills
🔹 `/limit` - Set category spending limits
🔹 `/setbudget` - Define monthly goals
🔹 `/settings` - Manage security & profile
━━━━━━━━━━━━━━━━━━━━
🔐 *Action Required:* Set a 4-digit PIN to secure your financial vault:"""

        await update.message.reply_text(welcome_msg, parse_mode="Markdown")
        return ASK_PIN

    await update.message.reply_text(
        """🔐 *WELCOME BACK*

Please enter your *4-digit PIN* to unlock your dashboard.""",
        parse_mode="Markdown"
    )
    return VERIFY_PIN

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("➕ Add Expense", callback_data='menu_add'),
         InlineKeyboardButton("📸 Upload Receipt", callback_data='menu_upload')],
        [InlineKeyboardButton("📊 Summary & Breakdown", callback_data='menu_summary')],
        [InlineKeyboardButton("📈 View Charts", callback_data='menu_charts'),
         InlineKeyboardButton("🔮 Forecast", callback_data='menu_forecast')],
        [InlineKeyboardButton("⏳ Recurring", callback_data='menu_recurring'),
         InlineKeyboardButton("🎯 Set Limit", callback_data='menu_limit')],
        [InlineKeyboardButton("💰 Set Budget", callback_data='menu_budget'),
         InlineKeyboardButton("📧 Export", callback_data='menu_export')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='menu_settings'),
         InlineKeyboardButton("📖 Help Guide", callback_data='menu_help')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "💰 *MAIN MENU* 💰\n\nWhat would you like to do?"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    return ConversationHandler.END

async def ask_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text("PIN must be 4 digits. Try again:")
        raise ApplicationHandlerStop()
        return ASK_PIN
    await storage.set_user_pin(update.effective_user.id, pin)
    context.user_data['authorized'] = True
    await update.message.reply_text("✅ PIN set!")
    await show_main_menu(update, context)
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def verify_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if await storage.validate_user_pin(update.effective_user.id, pin):
        context.user_data['authorized'] = True
        await update.message.reply_text("🔓 Access granted!")
        await show_main_menu(update, context)
        raise ApplicationHandlerStop()
        return ConversationHandler.END
    await update.message.reply_text("❌ Incorrect PIN. Try again:")
    raise ApplicationHandlerStop()
    return VERIFY_PIN

async def menu_add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text("Send an expense (e.g., 'Spent 50 on food' or '$10 lunch')")
    return ConversationHandler.END

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Security Guard: Only allow if authorized
    if not context.user_data.get('authorized'):
        return

    text = update.message.text
    parsed = parser.parse_expense_message(text)
    if not parsed:
        await update.message.reply_text("Couldn't understand. Try 'Spent 50 on food' or '$50 lunch'")
        raise ApplicationHandlerStop()
        
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    base_currency = user_data.get("currency", "USD")
    
    amount = parsed["amount"]
    symbol = parsed.get("symbol")
    if symbol:
        detected_curr = currency.get_currency_from_symbol(symbol)
        if detected_curr != base_currency:
            converted_amt = currency.convert(amount, detected_curr, base_currency)
            await update.message.reply_text(
                f"💱 Converted {symbol}{amount} ({detected_curr}) to `{converted_amt:.2f}` {base_currency}",
                parse_mode="Markdown"
            )
            amount = converted_amt

    # Direct DB Persistence
    await db.add_expense(
        user_id=user_id,
        amount=amount,
        category=parsed['category'],
        note=parsed.get('description')
    )
    
    await update.message.reply_text(f"💰 Added `{amount:.2f}` {base_currency} for {parsed['category']}", parse_mode="Markdown")

async def set_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("Send recurring expense like: 'Netflix 100'")
    return ADD_RECUR

async def save_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parser.parse_expense_message(update.message.text)
    if not parsed:
        await update.message.reply_text("Couldn’t parse. Try again.")
        raise ApplicationHandlerStop()
        return
    user_id = update.effective_user.id
    await db.add_recurring(user_id, parsed['amount'], parsed['category'])
    await update.message.reply_text("✅ Recurring expense saved.")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("Send category limit like 'food 500'")
    return SET_LIMIT

async def save_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cat, amt = update.message.text.split()
        amt = float(amt)
    except:
        await update.message.reply_text("Format: category amount (e.g., food 500)")
        raise ApplicationHandlerStop()
        return
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    limits = user_data.get("category_limits", {})
    limits[cat.lower()] = amt
    user_data["category_limits"] = limits
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text(f"✅ Limit set: {cat} → {amt} {user_data['currency']}")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("Enter your monthly budget (e.g., 2000):")
    return SET_BUDGET

async def save_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        budget = float(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid input. Please enter a number (e.g., 2000):")
        raise ApplicationHandlerStop()
        return SET_BUDGET
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    user_data["budget"] = budget
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text(f"✅ Monthly budget set to {budget} {user_data['currency']}")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    try:
        user_id = update.effective_user.id
        user_data = await storage.get_user_data(user_id)
        if not user_data:
            await update.effective_message.reply_text("❌ User data not found. Please /start.")
            return

        expenses = user_data.get("expenses", [])
        currency = user_data.get("currency", "USD")
        
        if not expenses:
            msg = "📭 No expenses recorded yet."
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]]))
            else:
                await update.message.reply_text(msg)
            return
            
        today = datetime.now().date()
        today_expenses = []
        for e in expenses:
            try:
                if 'date' in e and e['date'] and datetime.fromisoformat(e['date']).date() == today:
                    today_expenses.append(e)
            except (ValueError, TypeError):
                continue

        today_total = sum(e.get('amount', 0) for e in today_expenses)
        
        # Category breakdown for today
        breakdown = {}
        for e in today_expenses:
            cat = e.get('category', 'other')
            breakdown[cat] = breakdown.get(cat, 0) + e.get('amount', 0)
            
        res = f"📊 *TODAY'S SUMMARY* ({currency})\n"
        res += f"━━━━━━━━━━━━━━━\n"
        res += f"💰 *Total:* `{today_total:.2f}`\n\n"
        
        if breakdown:
            res += "*Breakdown:*\n"
            for cat, amt in breakdown.items():
                res += f"• {cat.capitalize()}: `{amt:.2f}`\n"
        
        # Budget info
        budget = user_data.get("budget", 0)
        if budget > 0:
            # Calculate monthly total
            this_month = today.replace(day=1)
            monthly_total = 0
            for e in expenses:
                try:
                    if 'date' in e and e['date'] and datetime.fromisoformat(e['date']).date() >= this_month:
                        monthly_total += e.get('amount', 0)
                except (ValueError, TypeError):
                    continue

            percent = (monthly_total / budget) * 100
            from utils.scheduler import get_progress_bar
            bar = get_progress_bar(percent)
            res += f"\n*Monthly Budget:*\n{bar}\nSpent: `{monthly_total:.2f}` / `{budget:.2f}`"

        keyboard = [
            [InlineKeyboardButton("📈 View Charts", callback_data='menu_charts'),
             InlineKeyboardButton("🔮 Forecast", callback_data='menu_forecast')],
            [InlineKeyboardButton("📜 History", callback_data='menu_history')],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(res, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(res, reply_markup=reply_markup, parse_mode="Markdown")
        return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error in summary: {e}", exc_info=True)
        return ConversationHandler.END
        if update.callback_query:
            await update.callback_query.answer("❌ Error generating summary.")
        else:
            await update.message.reply_text("❌ An error occurred while generating the summary.")

# -------------------- EMAIL / EXPORT --------------------

async def set_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("Enter your email for monthly reports:")
    return SET_EMAIL

async def save_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email:
        await update.message.reply_text("Invalid email. Try again:")
        raise ApplicationHandlerStop()
        return
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    user_data["email"] = email
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text("📩 Email saved.")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    import csv
    from io import StringIO
    try:
        user_id = update.effective_user.id
        expenses = await db.get_expenses(user_id)
        user_row = await db.get_user(user_id)
        limits = await db.get_limits(user_id)
        
        if not expenses:
            await update.effective_message.reply_text("📭 No expenses to export.")
            return

        currency = user_row['currency'] if user_row else "USD"
        budget = user_row['budget'] if user_row else 0

        output = StringIO()
        
        # Summary Section
        output.write(f"EXPENSE REPORT SUMMARY ({currency})\n")
        output.write(f"Total Budget,{budget:.2f}\n")
        total_spent = sum(e['amount'] for e in expenses)
        output.write(f"Total Spent,{total_spent:.2f}\n")
        output.write(f"Remaining,{(budget - total_spent):.2f}\n\n")

        if limits:
            output.write("CATEGORY LIMITS\n")
            output.write("Category,Limit,Spent,Status\n")
            cat_spend = {}
            for e in expenses:
                cat = e['category'].lower()
                cat_spend[cat] = cat_spend.get(cat, 0) + e['amount']
            for cat, limit in limits.items():
                spent = cat_spend.get(cat.lower(), 0)
                status = "OK" if spent <= limit else "OVER"
                output.write(f"{cat.capitalize()},{limit:.2f},{spent:.2f},{status}\n")
            output.write("\n")

        # Transaction List
        output.write("TRANSACTIONS\n")
        fieldnames = ["date", "amount", "category", "note"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for item in expenses:
            writer.writerow(item)

        output.seek(0)
        await update.effective_message.reply_document(
            document=output.getvalue().encode(), 
            filename=f"expenses_{datetime.now().strftime('%Y%m%d')}.csv"
        )
    except Exception as e:
        logging.error(f"Error in export_csv: {e}", exc_info=True)
        await update.effective_message.reply_text("❌ Failed to export CSV.")

# -------------------- PHOTOS --------------------

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("📸 Please send the receipt photo now.")
    return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message.photo:
        await update.message.reply_text("❗ No photo received.")
        return
    
    status_msg = await update.message.reply_text("🔍 *Scanning receipt with AI...*", parse_mode="Markdown")
    
    photo = update.message.photo[-1]
    os.makedirs("receipts", exist_ok=True)
    path = f"receipts/{user_id}_receipt.jpg"
    file = await photo.get_file()
    await file.download_to_drive(path)
    
    # AI Extraction
    data = await ocr.extract_receipt_data(path)
    
    if not data or 'amount' not in data:
        await status_msg.edit_text("❌ AI could not extract data. Receipt saved for manual entry.")
        return

    amount = data.get('amount', 0)
    category = data.get('category', 'misc')
    merchant = data.get('merchant', 'Unknown')
    date = data.get('date', 'Today')

    # Store data for confirmation
    context.user_data['temp_ocr'] = data
    
    res = (
        f"✅ *AI DETECTED EXPENSE*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏪 *Merchant:* `{merchant}`\n"
        f"💰 *Amount:* `{amount:.2f}`\n"
        f"📂 *Category:* `{category}`\n"
        f"📅 *Date:* `{date}`\n\n"
        f"Should I add this to your expenses?"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Add it", callback_data='ocr_confirm'),
         InlineKeyboardButton("❌ No, Ignore", callback_data='ocr_reject')]
    ]
    await status_msg.edit_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def ocr_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'ocr_confirm':
        data = context.user_data.get('temp_ocr')
        if not data:
            await query.edit_message_text("❌ Data expired. Please try again.")
            return
            
        user_id = update.effective_user.id
        await db.add_expense(
            user_id=user_id,
            amount=data['amount'],
            category=data['category'],
            note=f"Receipt from {data.get('merchant', 'Unknown')}"
        )
        await query.edit_message_text(f"✅ Added `{data['amount']:.2f}` to {data['category']}!")
        del context.user_data['temp_ocr']
    else:
        await query.edit_message_text("🗑️ Expense ignored.")
        if 'temp_ocr' in context.user_data:
            del context.user_data['temp_ocr']

# -------------------- VOICE --------------------

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message.voice:
        await update.message.reply_text("❗ No voice message received.")
        return
    
    status_msg = await update.message.reply_text("🎙️ *Transcribing & parsing voice note...*", parse_mode="Markdown")
    
    voice = update.message.voice
    os.makedirs("receipts", exist_ok=True)
    # Reuse receipts dir for audio files temporarily
    path = f"receipts/{user_id}_voice.ogg"
    file = await voice.get_file()
    await file.download_to_drive(path)
    
    # AI Extraction
    data = await voice_processor.process_voice_note(path)
    
    if not data or 'amount' not in data:
        await status_msg.edit_text("❌ AI could not understand the expense details in your voice note.")
        return

    amount = data.get('amount', 0)
    category = data.get('category', 'misc')
    note = data.get('note', 'Voice entry')

    # Store data for confirmation
    context.user_data['temp_voice'] = data
    
    res = (
        f"🎙️ *VOICE EXPENSE DETECTED*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 *Amount:* `{amount:.2f}`\n"
        f"📂 *Category:* `{category}`\n"
        f"📝 *Note:* `{note}`\n\n"
        f"Should I add this to your expenses?"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Add it", callback_data='voice_confirm'),
         InlineKeyboardButton("❌ No, Ignore", callback_data='voice_reject')]
    ]
    await status_msg.edit_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def voice_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'voice_confirm':
        data = context.user_data.get('temp_voice')
        if not data:
            await query.edit_message_text("❌ Data expired. Please try again.")
            return
            
        user_id = update.effective_user.id
        user_data = await storage.get_user_data(user_id)
        base_currency = user_data.get("currency", "USD")

        await db.add_expense(
            user_id=user_id,
            amount=data['amount'],
            category=data['category'],
            note=data.get('note', 'Voice entry')
        )
        await query.edit_message_text(f"✅ Added `{data['amount']:.2f}` {base_currency} to {data['category']}!")
        del context.user_data['temp_voice']
    else:
        await query.edit_message_text("🗑️ Voice expense ignored.")
        if 'temp_voice' in context.user_data:
            del context.user_data['temp_voice']

# -------------------- SETTINGS --------------------

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    current_currency = user_data.get("currency", "USD")

    keyboard = [
        [InlineKeyboardButton("🔐 Change PIN", callback_data='settings_pin')],
        [InlineKeyboardButton(f"💱 Change Currency ({current_currency})", callback_data='settings_currency')],
        [InlineKeyboardButton("📂 Manage Categories", callback_data='settings_categories')],
        [InlineKeyboardButton("📧 Set/Change Email", callback_data='settings_email')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "⚙️ *SETTINGS MENU*"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")

async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logging.info(f"Settings callback: {query.data}")

    if query.data == 'settings_pin':
        await query.edit_message_text("🔐 Send new 4-digit PIN:")
        return ASK_PIN
    elif query.data == 'settings_currency':
        await query.edit_message_text("💱 Enter 3-letter currency code (e.g., USD, EUR, GHS):")
        return ASK_CURRENCY
    elif query.data == 'settings_email':
        await query.edit_message_text("📧 Enter your email address:")
        return ASK_EMAIL
    elif query.data == 'settings_categories':
        await manage_categories(update, context)
        return ConversationHandler.END
    elif query.data == 'cat_add':
        await query.edit_message_text("📂 Enter name for new category:")
        return ADD_CATEGORY_NAME
    elif query.data.startswith('cat_del_'):
        cat_name = query.data.replace('cat_del_', '')
        await db.delete_custom_category(update.effective_user.id, cat_name)
        await query.answer(f"✅ Category '{cat_name}' deleted")
        await manage_categories(update, context)
        return ConversationHandler.END
    elif query.data == 'back_to_main':
        await show_main_menu(update, context)
        return ConversationHandler.END
    return ConversationHandler.END

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        logging.info(f"Main menu handler received: {query.data}")

        if query.data == 'menu_add':
            return await menu_add_handler(update, context)
        elif query.data == 'menu_upload':
            return await upload_command(update, context)
        elif query.data == 'menu_summary':
            return await summary(update, context)
        elif query.data == 'menu_export':
            return await export_menu(update, context)
        elif query.data == 'menu_help':
            return await help_command(update, context)
        elif query.data == 'export_pdf':
            return await export_pdf_handler(update, context)
        elif query.data == 'export_csv_action':
            return await export_csv_action_handler(update, context)
        elif query.data == 'menu_history':
            return await show_history(update, context)
        elif query.data.startswith('hist_page_'):
            page = int(query.data.split('_')[2])
            return await show_history(update, context, page=page)
        elif query.data == 'menu_forecast':
            return await show_forecast(update, context)
        elif query.data.startswith('del_'):
            await delete_expense_handler(update, context)
            return ConversationHandler.END
        elif query.data.startswith('editamt_'):
            expense_id = query.data.split('_')[1]
            context.user_data['edit_expense_id'] = expense_id
            await query.edit_message_text("✏️ Enter new amount:")
            return EDIT_EXPENSE_AMT
        elif query.data == 'menu_charts':
            return await send_charts(update, context)
        else:
            logging.warning(f"Unhandled callback in main_menu_handler: {query.data}")
            return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error in main_menu_handler: {e}", exc_info=True)
        await query.answer("❌ An error occurred.")
    return ConversationHandler.END

async def export_pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    query = update.callback_query
    user_id = update.effective_user.id
    user_row = await db.get_user(user_id)
    expenses = await db.get_expenses(user_id)
    limits = await db.get_limits(user_id)
    
    if not user_row:
        await query.answer("❌ User not found.")
        return
        
    if not expenses:
        await query.answer("📭 No data to export.")
        return
        
    await query.message.reply_text("📄 Generating detailed PDF report...")
    try:
        month_name = datetime.now().strftime("%B %Y")
        path = pdf_generator.generate_pdf_report(
            user_id=user_id, 
            expenses=expenses, 
            currency=user_row['currency'], 
            month_name=month_name,
            budget=user_row['budget'],
            limits=limits
        )
        
        with open(path, 'rb') as f:
            await update.effective_message.reply_document(document=f, filename=os.path.basename(path))
    except Exception as e:
        logging.error(f"Failed to generate PDF: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Failed to generate PDF report: {e}")

async def export_csv_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await export_csv(update, context)
    return ConversationHandler.END

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    query = update.callback_query
    user_id = update.effective_user.id
    limit = 5
    offset = page * limit
    expenses = await db.get_expenses(user_id, limit=limit, offset=offset)
    
    if not expenses and page == 0:
        msg = "📜 No recent expenses found."
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')]]
        if query: await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    elif not expenses and page > 0:
        await query.answer("No more history.")
        return
        
    res = f"📜 *RECENT HISTORY* (Page {page + 1})\n━━━━━━━━━━━━━━━\n"
    keyboard = []
    for ex in expenses:
        date_short = ex['date'][5:10]
        res += f"• `{date_short}`: {ex['category'].capitalize()} - `{ex['amount']:.2f}`\n"
        keyboard.append([
            InlineKeyboardButton(f"✏️ Edit Amount", callback_data=f"editamt_{ex['id']}"),
            InlineKeyboardButton(f"🗑️ Delete", callback_data=f"del_{ex['id']}")
        ])
    
    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"hist_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"hist_page_{page+1}"))
    keyboard.append(nav_buttons)
        
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')])
    
    if query: await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else: await update.message.reply_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def delete_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    expense_id = int(query.data.split('_')[1])
    await db.delete_expense(expense_id, update.effective_user.id)
    # Re-show history
    await show_history(update, context, page=0)

async def manage_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    custom_cats = await db.get_custom_categories(user_id)
    
    res = "📂 *MANAGE CATEGORIES*\n━━━━━━━━━━━━━━━\n"
    res += "*Standard:* food, transport, bills, entertainment, health, shopping, misc\n"
    if custom_cats:
        res += "\n*Custom:* " + ", ".join([f"`{c}`" for c in custom_cats])
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Custom Category", callback_data='cat_add')],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data='menu_settings')]
    ]
    
    for cat in custom_cats:
        keyboard.insert(-1, [InlineKeyboardButton(f"🗑️ Delete '{cat}'", callback_data=f"cat_del_{cat}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(res, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(res, reply_markup=reply_markup, parse_mode="Markdown")

async def show_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    res = forecaster.forecast_monthly_spend(user_data['expenses'], user_data['budget'])
    
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')]]
    await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("📄 Export PDF (Detailed)", callback_data='export_pdf')],
        [InlineKeyboardButton("📊 Export CSV (Raw)", callback_data='export_csv_action')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')]
    ]
    await query.edit_message_text("📧 *SELECT EXPORT FORMAT*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def send_charts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    expenses = user_data.get("expenses", [])
    
    if not expenses:
        await query.message.reply_text("📭 No data for charts yet.")
        return
        
    await query.message.reply_text("📊 Generating your charts...")
    pie, bar = visualizer.generate_spending_charts(user_id, expenses, user_data.get("currency", "USD"))
    
    from telegram import InputMediaPhoto
    media = []
    if pie and os.path.exists(pie):
        media.append(InputMediaPhoto(open(pie, 'rb')))
    if bar and os.path.exists(bar):
        media.append(InputMediaPhoto(open(bar, 'rb')))
        
    if media:
        await query.message.reply_media_group(media=media)
    else:
        await query.message.reply_text("❌ Failed to generate charts.")
    return ConversationHandler.END
    
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """📖 *EXPENSE TRACKER PRO - HELP GUIDE* 📖
━━━━━━━━━━━━━━━━━━━━
This bot helps you track your expenses using text, voice, and photos.

🛠️ *SLASH COMMANDS:*
🔹 `/start` - Initial setup & PIN login
🔹 `/menu` - Open the main interactive dashboard
🔹 `/add` <exp> - Quick add (e.g., `/add 50 coffee`)
🔹 `/summary` - View today's spending breakdown
🔹 `/upload` - Start receipt scanning photo mode
🔹 `/recurring` - Manage your automated bills
🔹 `/limit` - Set spending limits for categories
🔹 `/setbudget` - Define your total monthly budget
🔹 `/export` - Download data as CSV
🔹 `/settings` - Change PIN, Currency, or Email
🔹 `/help` - Show this guide

🎮 *DASHBOARD BUTTONS:*
➕ *Add Expense*: Manual entry with automatic parsing.
📸 *Upload Receipt*: AI extracts amount, merchant, and date.
📊 *Summary*: Dynamic spend bars & category lists.
📈 *View Charts*: Visual pie & bar chart generations.
🔮 *Forecast*: AI prediction of your month-end total.
⏳ *Recurring*: View and add repeating expenses.
🎯 *Set Limit*: Alerts when you overspend in a category.
💰 *Set Budget*: Track overall monthly progress.
📧 *Export*: Get professional PDF or CSV reports.
⚙️ *Settings*: Full profile and security management.

✨ *PRO TIPS:*
🎙️ *Voice Entry*: Just send a voice note like "I spent ten dollars on lunch" and I'll parse it!
💱 *Multi-Currency*: Tag expenses with symbols like `€50` or `100 GHS`. I'll convert them to your base currency automatically.
🔍 *Natural Language*: I understand phrases like "Spent 20 on gas" or "Coffee 5".

Need more help? Just start typing an expense!
━━━━━━━━━━━━━━━━━━━━"""
    
    keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")

async def received_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text("❌ Invalid PIN. Enter 4 digits:")
        raise ApplicationHandlerStop()
        return ASK_PIN
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    user_data["pin"] = pin
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text("✅ PIN updated.")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def received_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        await update.message.reply_text("❌ Invalid currency. Enter a 3-letter code:")
        raise ApplicationHandlerStop()
        return ASK_CURRENCY
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    user_data["currency"] = currency
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text(f"✅ Currency updated to {currency}.")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def received_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Invalid email. Enter again:")
        raise ApplicationHandlerStop()
        return ASK_EMAIL
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    user_data["email"] = email
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text(f"✅ Email updated to {email}.")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def edit_amt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_amt = float(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid amount. Enter a number:")
        raise ApplicationHandlerStop()
        return EDIT_EXPENSE_AMT
    
    expense_id = context.user_data.get('edit_expense_id')
    user_id = update.effective_user.id
    if expense_id:
        await db.update_expense(int(expense_id), user_id, amount=new_amt)
        await update.message.reply_text(f"✅ Expense updated to `{new_amt:.2f}`")
        del context.user_data['edit_expense_id']
    else:
        await update.message.reply_text("❌ Error: No expense selected for editing.")
    
    await show_main_menu(update, context)
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def add_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()
    if not name or len(name) > 20:
        await update.message.reply_text("❌ Invalid name. Keep it under 20 characters:")
        raise ApplicationHandlerStop()
        return ADD_CATEGORY_NAME
    
    success = await db.add_custom_category(update.effective_user.id, name)
    if success:
        await update.message.reply_text(f"✅ Category '{name}' added!")
    else:
        await update.message.reply_text(f"❌ Category '{name}' already exists.")
    
    await manage_categories(update, context)
    raise ApplicationHandlerStop()
    return ConversationHandler.END

# -------------------- MAIN --------------------

async def post_init(application):
    await db.init_db()

load_dotenv()
if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    persistence = PicklePersistence(filepath="data/persistence.pkl")
    
    app = ApplicationBuilder() \
        .token(os.getenv("BOT_TOKEN")) \
        .persistence(persistence) \
        .post_init(post_init) \
        .build()

    # Conversations
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_pin)],
            VERIFY_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_pin)]
        },
        fallbacks=[]
    )

    # Unified Dashboard Conversation
    dashboard_conv = ConversationHandler(
        entry_points=[
            CommandHandler("settings", settings),
            CommandHandler("recurring", set_recurring),
            CommandHandler("limit", set_limit),
            CommandHandler("setbudget", set_budget),
            CommandHandler("setemail", set_email),
            CallbackQueryHandler(settings, pattern="^menu_settings$"),
            CallbackQueryHandler(set_recurring, pattern="^menu_recurring$"),
            CallbackQueryHandler(set_limit, pattern="^menu_limit$"),
            CallbackQueryHandler(set_budget, pattern="^menu_budget$"),
            CallbackQueryHandler(upload_command, pattern="^menu_upload$"),
            CallbackQueryHandler(summary, pattern="^menu_summary$"),
            CallbackQueryHandler(show_history, pattern="^menu_history$"),
            CallbackQueryHandler(show_forecast, pattern="^menu_forecast$"),
            CallbackQueryHandler(export_menu, pattern="^menu_export$"),
            CallbackQueryHandler(send_charts, pattern="^menu_charts$"),
            CallbackQueryHandler(menu_add_handler, pattern="^menu_add$"), 
            CallbackQueryHandler(set_email, pattern="^settings_email$"), 
            CallbackQueryHandler(settings_callback_handler, pattern=re.compile(r"^(settings_|back_to_main|cat_add|cat_del_)")),
            CallbackQueryHandler(main_menu_handler, pattern=re.compile(r"^(menu_|del_|export_|editamt_|hist_page_)"))
        ],
        states={
            ADD_RECUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_recurring)],
            SET_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_limit)],
            SET_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_budget)],
            SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_email)],
            ASK_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_currency)],
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_email)],
            ASK_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_pin)],
            ADD_CATEGORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category_handler)],
            EDIT_EXPENSE_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_amt_handler)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        name="dashboard_conversation",
        persistent=True,
        allow_reentry=True,
    )

    # Register handlers
    app.add_handler(conv) # Startup & Auth (PIN)
    app.add_handler(dashboard_conv) # Main functionality
    
    # Callback queries for main menu (single actions)
    app.add_handler(CallbackQueryHandler(ocr_callback_handler, pattern=re.compile(r"^ocr_")))
    app.add_handler(CallbackQueryHandler(voice_callback_handler, pattern=re.compile(r"^voice_")))
    app.add_handler(CallbackQueryHandler(main_menu_handler, pattern=re.compile(r"^(menu_|del_|export_)")))
    app.add_handler(CallbackQueryHandler(settings_callback_handler, pattern=re.compile(r"^back_to_main$")))
    
    app.add_handler(CommandHandler("add", add_expense))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("export", export_csv))
    app.add_handler(CommandHandler("menu", show_main_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Group 1: Catch-all for expenses
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense), group=1)

    # Start background jobs
    schedule_jobs(app.bot)

    app.run_polling()
