import logging
import os
import re
import warnings
from datetime import datetime
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler,
    PicklePersistence, ApplicationHandlerStop, PreCheckoutQueryHandler
)

from utils import storage, parser, currency, visualizer, forecaster, pdf_generator, ocr, voice_processor
from utils.database import db
from utils.scheduler import schedule_jobs

async def send_menu(query, text, reply_markup=None, parse_mode="Markdown"):
    """Delete the old menu message and send a fresh one at the bottom of the chat."""
    try:
        await query.message.delete()
    except Exception:
        pass  # If delete fails (e.g. already gone), just continue
    await query.message.chat.send_message(text, reply_markup=reply_markup, parse_mode=parse_mode)

def is_premium_active(user_data):
    if not user_data:
        return False
    if user_data.get("subscription_tier") != "premium":
        return False
    premium_until = user_data.get("premium_until")
    if not premium_until:
        return False
    try:
        until_date = datetime.fromisoformat(premium_until)
        return until_date > datetime.now()
    except ValueError:
        return False

def get_premium_upgrade_keyboard():
    keyboard = [
        [InlineKeyboardButton("⭐ Buy Premium (1 Month) - 150 Stars", callback_data='buy_premium_1m')],
        [InlineKeyboardButton("📸 Buy 50 AI Credits - 50 Stars", callback_data='buy_credits_50')],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

logging.basicConfig(level=logging.INFO)

# Suppress PTB warning about CallbackQueryHandler with per_message=False.
# This is intentional: the dashboard ConversationHandler tracks state per-user,
# not per-message, which is the correct behaviour for this bot.
warnings.filterwarnings(
    "ignore",
    message=".*per_message=False.*CallbackQueryHandler.*",
    category=UserWarning,
)

# Conversation states
(
    ASK_PIN, VERIFY_PIN, ADD_EXPENSE,  
    SET_LIMIT, SET_BUDGET, SET_EMAIL, ASK_CURRENCY, 
    ASK_EMAIL, EDIT_EXPENSE_AMT, EDIT_EXPENSE_CAT, 
    ADD_CATEGORY_NAME, ADD_SUB_NAME, ADD_SUB_AMT, 
    ADD_SUB_CAT, ADD_SUB_CYCLE
) = range(15)

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
        [InlineKeyboardButton("💳 Subscriptions", callback_data='menu_subs')],
        [InlineKeyboardButton("🎯 Set Limit", callback_data='menu_limit'),
         InlineKeyboardButton("💰 Set Budget", callback_data='menu_budget')],
        [InlineKeyboardButton("📧 Export", callback_data='menu_export'),
         InlineKeyboardButton("⚙️ Settings", callback_data='menu_settings')],
        [InlineKeyboardButton("⭐ Premium Hub", callback_data='menu_premium')],
        [InlineKeyboardButton("📖 Help Guide", callback_data='menu_help')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "💰 *MAIN MENU* 💰\n\nWhat would you like to do?"
    if update.callback_query:
        await update.callback_query.answer()
        await send_menu(update.callback_query, msg, reply_markup=reply_markup)
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

    # --- Free Tier Quota Check ---
    if not is_premium_active(user_data):
        monthly_count = await db.get_monthly_expense_count(user_id)
        FREE_MONTHLY_LIMIT = 30
        if monthly_count >= FREE_MONTHLY_LIMIT:
            await update.message.reply_text(
                f"🚫 *Free Tier Limit Reached!*\n\n"
                f"You've logged *{monthly_count}/{FREE_MONTHLY_LIMIT}* expenses this month.\n\n"
                f"Upgrade to *⭐ Premium* for unlimited tracking!",
                parse_mode="Markdown",
                reply_markup=get_premium_upgrade_keyboard()
            )
            raise ApplicationHandlerStop()
    
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

    # Smart Categorization Fallback
    category = parsed['category']
    if category == 'misc' or not category:
        from utils.ai_categorizer import get_smart_category
        category = await get_smart_category(user_id, parsed.get('description', ''), text)

    # Direct DB Persistence
    await db.add_expense(
        user_id=user_id,
        amount=amount,
        category=category,
        note=parsed.get('description')
    )
    
    await update.message.reply_text(f"💰 Added `{amount:.2f}` {base_currency} for {category}", parse_mode="Markdown")

async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("🎯 Enter category and limit (e.g., 'food 500'):")
    return SET_LIMIT

async def save_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) < 2: raise ValueError()
        cat, amt = parts[0], float(parts[1])
    except:
        await update.message.reply_text("❌ Format: category amount (e.g., food 500)")
        raise ApplicationHandlerStop()
        return
    
    user_id = update.effective_user.id
    user_row = await db.get_user(user_id)
    currency = user_row['currency'] if user_row else "USD"
    
    await db.set_limit(user_id, cat, amt)
    await update.message.reply_text(f"✅ Limit set: {cat.capitalize()} → {amt:.2f} {currency}")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    await update.effective_message.reply_text("💰 Enter your total monthly budget amount:")
    return SET_BUDGET

async def save_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        budget = float(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid input. Please enter a number (e.g., 2000):")
        raise ApplicationHandlerStop()
        return SET_BUDGET
    user_id = update.effective_user.id
    user_row = await db.get_user(user_id)
    currency = user_row['currency'] if user_row else "USD"
    
    await db.update_user(user_id, budget=budget)
    await update.message.reply_text(f"✅ Monthly budget set to {budget:.2f} {currency}")
    raise ApplicationHandlerStop()
    return ConversationHandler.END

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    try:
        user_id = update.effective_user.id
        expenses = await db.get_expenses(user_id)
        user_row = await db.get_user(user_id)
        
        if not user_row:
            await update.effective_message.reply_text("❌ User data not found. Please /start.")
            return

        currency = user_row['currency']
        
        if not expenses:
            msg = "📭 No expenses recorded yet."
            if update.callback_query:
                await send_menu(update.callback_query, msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]]), parse_mode=None)
            else:
                await update.effective_message.reply_text(msg)
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
        budget = user_row['budget']
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
            await send_menu(update.callback_query, res, reply_markup=reply_markup)
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

        # Add Active Subscriptions Summary
        subs = await db.get_subscriptions(user_id)
        if subs:
            output.write("\n--- ACTIVE SUBSCRIPTIONS ---\n")
            output.write("Name,Amount,Category,Cycle,Start Date\n")
            for s in subs:
                output.write(f"{s['name']},{s['amount']},{s['category']},{s['billing_cycle']},{s['start_date']}\n")

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

    # --- Premium Gate ---
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    if not is_premium_active(user_data):
        await update.effective_message.reply_text(
            "📸 *AI Receipt Scanning is a Premium Feature*\n\n"
            "Upgrade to *⭐ Premium* to unlock unlimited AI receipt scanning!",
            parse_mode="Markdown",
            reply_markup=get_premium_upgrade_keyboard()
        )
        return ConversationHandler.END

    await update.effective_message.reply_text("📸 Please send the receipt photo now.")
    return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message.photo:
        await update.message.reply_text("❗ No photo received.")
        return

    # --- Premium Gate ---
    user_data = await storage.get_user_data(user_id)
    if not is_premium_active(user_data):
        await update.message.reply_text(
            "📸 *AI Receipt Scanning is a Premium Feature*\n\n"
            "Upgrade to *⭐ Premium* to unlock unlimited AI receipt scanning!",
            parse_mode="Markdown",
            reply_markup=get_premium_upgrade_keyboard()
        )
        return

    status_msg = await update.message.reply_text("🔍 *Scanning receipt with AI...*", parse_mode="Markdown")
    
    photo = update.message.photo[-1]
    os.makedirs("receipts", exist_ok=True)
    path = f"receipts/{user_id}_receipt.jpg"
    file = await photo.get_file()
    await file.download_to_drive(path)
    
    # AI Extraction
    try:
        data = await ocr.extract_receipt_data(path)
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logging.error(f"Error removing temp receipt file {path}: {e}")
    
    if not data or 'amount' not in data:
        await status_msg.edit_text("❌ AI could not extract data. Receipt photo has been cleaned up.")
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

    # --- AI Credit Check ---
    user_data = await storage.get_user_data(user_id)
    if not is_premium_active(user_data):
        credits = user_data.get("ai_credits", 0) if user_data else 0
        if credits <= 0:
            await update.message.reply_text(
                "🎙️ *AI Voice Logging Unavailable*\n\n"
                "You've used all your free AI voice credits.\n"
                "Buy more credits or upgrade to *⭐ Premium* for unlimited voice logging!",
                parse_mode="Markdown",
                reply_markup=get_premium_upgrade_keyboard()
            )
            return
    
    status_msg = await update.message.reply_text("🎙️ *Transcribing & parsing voice note...*", parse_mode="Markdown")
    
    voice = update.message.voice
    os.makedirs("receipts", exist_ok=True)
    # Reuse receipts dir for audio files temporarily
    path = f"receipts/{user_id}_voice.ogg"
    file = await voice.get_file()
    await file.download_to_drive(path)
    
    # AI Extraction
    try:
        data = await voice_processor.process_voice_note(path)
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logging.error(f"Error removing temp voice file {path}: {e}")
    
    if not data or 'amount' not in data:
        await status_msg.edit_text("❌ AI could not understand the expense details in your voice note. Audio has been cleaned up.")
        return

    # Deduct credit for successful transcription
    if not is_premium_active(user_data):
        await db.use_ai_credit(user_id)

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
        await send_menu(update.callback_query, msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")

async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logging.error(f"Error in settings_callback_handler: {e}", exc_info=True)
        if query: await query.answer("❌ Error in settings.")
        return ConversationHandler.END

# -------------------- SUBSCRIPTIONS --------------------

async def subscriptions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    user_id = update.effective_user.id
    subs = await db.get_subscriptions(user_id)
    
    msg = "💳 *SUBSCRIPTION MANAGEMENT*\n━━━━━━━━━━━━━━━\n"
    if not subs:
        msg += "No active subscriptions found."
    else:
        total_monthly = 0
        for s in subs:
            amount = s['amount']
            if s['billing_cycle'] == 'yearly':
                amount /= 12
            total_monthly += amount
            msg += f"• *{s['name']}*: `{s['amount']:.2f}` ({s['billing_cycle']})\n"
        
        msg += f"\n💰 *Est. Monthly Cost:* `{total_monthly:.2f}`"

    keyboard = [
        [InlineKeyboardButton("➕ Add Subscription", callback_data='sub_add')],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]
    ]
    
    for s in subs:
        keyboard.insert(-1, [InlineKeyboardButton(f"🗑️ Delete '{s['name']}'", callback_data=f"sub_del_{s['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        await send_menu(query, msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    return ConversationHandler.END

async def sub_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("📝 Enter the name of the subscription (e.g., Netflix):")
    return ADD_SUB_NAME

async def sub_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_sub'] = {'name': update.message.text.strip()}
    await update.message.reply_text("💰 Enter the amount:")
    return ADD_SUB_AMT

async def sub_add_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        context.user_data['temp_sub']['amount'] = amt
    except:
        await update.message.reply_text("❌ Invalid amount. Try again:")
        return ADD_SUB_AMT
    
    # Use AI to guess category based on name
    from utils.ai_categorizer import get_smart_category
    guessed_cat = await get_smart_category(update.effective_user.id, context.user_data['temp_sub']['name'])
    context.user_data['temp_sub']['category'] = guessed_cat
    
    keyboard = [
        [InlineKeyboardButton("📅 Monthly", callback_data='cycle_monthly'),
         InlineKeyboardButton("📆 Yearly", callback_data='cycle_yearly')]
    ]
    await update.message.reply_text(
        f"🔄 Select billing cycle (AI guessed category: *{guessed_cat}*):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ADD_SUB_CYCLE

async def sub_add_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cycle = 'monthly' if query.data == 'cycle_monthly' else 'yearly'
    sub_data = context.user_data.get('temp_sub')
    
    await db.add_subscription(
        user_id=update.effective_user.id,
        name=sub_data['name'],
        amount=sub_data['amount'],
        category=sub_data['category'],
        billing_cycle=cycle
    )
    
    await query.edit_message_text(f"✅ Subscription '{sub_data['name']}' added!")
    del context.user_data['temp_sub']
    await subscriptions_menu(update, context)
    return ConversationHandler.END

async def sub_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sub_id = int(query.data.replace('sub_del_', ''))
    await db.delete_subscription(sub_id, update.effective_user.id)
    await query.answer("✅ Subscription deleted")
    await subscriptions_menu(update, context)
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
        elif query.data == 'menu_settings':
            return await settings(update, context)
        elif query.data == 'menu_limit':
            return await set_limit(update, context)
        elif query.data == 'menu_budget':
            return await set_budget(update, context)
        elif query.data == 'menu_charts':
            return await send_charts(update, context)
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
        elif query.data == 'menu_subs':
            return await subscriptions_menu(update, context)
        elif query.data == 'sub_add':
            return await sub_add_start(update, context)
        elif query.data == 'back_to_main':
            return await show_main_menu(update, context)
        elif query.data == 'menu_premium':
            return await show_premium_hub(update, context)
        elif query.data.startswith('sub_del_'):
            return await sub_delete_handler(update, context)
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
    pdf_path = None
    try:
        month_name = datetime.now().strftime("%B %Y")
        # Fetch active subscriptions to include in the report
        subscriptions = await db.get_subscriptions(user_id)
        
        pdf_path = pdf_generator.generate_pdf_report(
            user_id=user_id,
            expenses=expenses,
            currency=user_row['currency'],
            month_name=month_name,
            budget=user_row['budget'],
            limits=limits,
            subscriptions=subscriptions
        )
        
        with open(pdf_path, 'rb') as f:
            await update.effective_message.reply_document(document=f, filename=os.path.basename(pdf_path))
    except Exception as e:
        logging.error(f"Failed to generate PDF: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Failed to generate PDF report: {e}")
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception as e:
                logging.error(f"Error removing generated PDF report {pdf_path}: {e}")

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
        await send_menu(update.callback_query, res, reply_markup=reply_markup)
    else:
        await update.message.reply_text(res, reply_markup=reply_markup, parse_mode="Markdown")

async def show_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return ConversationHandler.END
    
    query = update.callback_query
    user_id = update.effective_user.id
    expenses = await db.get_expenses(user_id)
    user_row = await db.get_user(user_id)
    budget = user_row['budget'] if user_row else 0
    
    res = forecaster.forecast_monthly_spend(expenses, budget)
    
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')]]
    if query:
        await send_menu(query, res, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.effective_message.reply_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("📄 Export PDF (Detailed)", callback_data='export_pdf')],
        [InlineKeyboardButton("📊 Export CSV (Raw)", callback_data='export_csv_action')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_to_main')]
    ]
    if query:
        await send_menu(query, "📧 *SELECT EXPORT FORMAT*", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.effective_message.reply_text("📧 *SELECT EXPORT FORMAT*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def send_charts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    query = update.callback_query
    user_id = update.effective_user.id
    expenses = await db.get_expenses(user_id)
    user_row = await db.get_user(user_id)
    currency = user_row['currency'] if user_row else "USD"
    
    if not expenses:
        msg = "📭 No data for charts yet."
        if query:
            await query.message.reply_text(msg)
        else:
            await update.effective_message.reply_text(msg)
        return
        
    status_msg = await update.effective_message.reply_text("📊 Generating your charts...")
    pie, bar = visualizer.generate_spending_charts(user_id, expenses, currency)
    
    from telegram import InputMediaPhoto
    media = []
    files_to_close = []
    try:
        if pie and os.path.exists(pie):
            f_pie = open(pie, 'rb')
            files_to_close.append(f_pie)
            media.append(InputMediaPhoto(f_pie))
        if bar and os.path.exists(bar):
            f_bar = open(bar, 'rb')
            files_to_close.append(f_bar)
            media.append(InputMediaPhoto(f_bar))
            
        if media:
            await query.message.reply_media_group(media=media)
        else:
            await query.message.reply_text("❌ Failed to generate charts.")
    except Exception as e:
        logging.error(f"Failed to send charts: {e}", exc_info=True)
        await query.message.reply_text("❌ Failed to generate charts.")
    finally:
        for f in files_to_close:
            try:
                f.close()
            except:
                pass
        for path in [pie, bar]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logging.error(f"Error removing chart file {path}: {e}")
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
        await send_menu(update.callback_query, help_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")

async def received_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text("❌ Invalid PIN. Enter 4 digits:")
        return ASK_PIN
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    user_data["pin"] = pin
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text("✅ PIN updated.")
    return ConversationHandler.END

async def received_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        await update.message.reply_text("❌ Invalid currency. Enter a 3-letter code:")
        return ASK_CURRENCY
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    user_data["currency"] = currency
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text(f"✅ Currency updated to {currency}.")
    return ConversationHandler.END

async def received_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Invalid email. Enter again:")
        return ASK_EMAIL
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id) or {}
    user_data["email"] = email
    await storage.save_user_data(user_id, user_data)
    await update.message.reply_text(f"✅ Email updated to {email}.")
    return ConversationHandler.END

async def edit_amt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_amt = float(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid amount. Enter a number:")
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
    return ConversationHandler.END

async def add_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()
    if not name or len(name) > 20:
        await update.message.reply_text("❌ Invalid name. Keep it under 20 characters:")
        return ADD_CATEGORY_NAME
    
    success = await db.add_custom_category(update.effective_user.id, name)
    if success:
        await update.message.reply_text(f"✅ Category '{name}' added!")
    else:
        await update.message.reply_text(f"❌ Category '{name}' already exists.")
    
    await manage_categories(update, context)
    return ConversationHandler.END

# -------------------- PREMIUM HUB --------------------

async def show_premium_hub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display Premium Hub with current tier status and purchase options."""
    if not context.user_data.get('authorized'):
        await update.effective_message.reply_text("🔐 Please /start and enter your PIN first.")
        return
    
    user_id = update.effective_user.id
    user_data = await storage.get_user_data(user_id)
    query = update.callback_query

    if is_premium_active(user_data):
        until_str = user_data.get("premium_until", "")
        try:
            until_date = datetime.fromisoformat(until_str).strftime("%d %b %Y")
        except:
            until_date = "Unknown"
        tier_badge = f"⭐ *PREMIUM*\nActive until: `{until_date}`"
    else:
        monthly_count = await db.get_monthly_expense_count(user_id)
        credits = user_data.get("ai_credits", 0) if user_data else 0
        tier_badge = (
            f"🆓 *FREE TIER*\n"
            f"• Transactions this month: `{monthly_count}/30`\n"
            f"• AI Voice Credits remaining: `{credits}`"
        )

    msg = (
        f"⭐ *PREMIUM HUB*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{tier_badge}\n\n"
        f"*Unlock with Premium:*\n"
        f"✅ Unlimited expense logging\n"
        f"✅ Unlimited AI receipt scanning (OCR)\n"
        f"✅ Unlimited AI voice logging\n"
        f"✅ Professional PDF reports\n"
        f"✅ Unlimited category limits"
    )

    keyboard = [
        [InlineKeyboardButton("⭐ Premium — 1 Month (150 Stars)", callback_data='buy_premium_1m')],
        [InlineKeyboardButton("⭐ Premium — 3 Months (400 Stars)", callback_data='buy_premium_3m')],
        [InlineKeyboardButton("🎙️ AI Voice Credits Pack — 50 credits (50 Stars)", callback_data='buy_credits_50')],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.answer()
        await send_menu(query, msg, reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")


async def send_invoice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle purchase button taps by sending a Telegram Stars invoice."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    PRODUCTS = {
        'buy_premium_1m': {
            "title": "⭐ Premium — 1 Month",
            "description": "Unlimited expense logging, AI scans, voice notes and reports for 30 days.",
            "payload": "premium_30_days",
            "price": 150,
        },
        'buy_premium_3m': {
            "title": "⭐ Premium — 3 Months",
            "description": "Unlimited expense logging, AI scans, voice notes and reports for 90 days.",
            "payload": "premium_90_days",
            "price": 400,
        },
        'buy_credits_50': {
            "title": "🎙️ AI Voice Credits Pack — 50 Credits",
            "description": "50 AI credits for voice logging transcription.",
            "payload": "credits_50",
            "price": 50,
        },
    }

    product = PRODUCTS.get(query.data)
    if not product:
        await query.answer("❌ Unknown product.", show_alert=True)
        return

    try:
        from telegram import LabeledPrice
        await context.bot.send_invoice(
            chat_id=user_id,
            title=product["title"],
            description=product["description"],
            payload=product["payload"],
            provider_token="",  # Required parameter, must be empty string for Telegram Stars (XTR)
            currency="XTR",  # Telegram Stars currency code
            prices=[LabeledPrice(label=product["title"], amount=product["price"])],
        )
    except Exception as e:
        logging.error(f"Error sending invoice: {e}", exc_info=True)
        await query.message.reply_text("❌ Failed to create invoice. Please try again later.")


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve all pre-checkout queries (validate server-side if needed)."""
    query = update.pre_checkout_query
    valid_payloads = {"premium_30_days", "premium_90_days", "credits_50"}
    if query.invoice_payload in valid_payloads:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Unknown product. Please try again.")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle completed Telegram Stars payments and grant the purchased product."""
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    user_id = update.effective_user.id

    logging.info(f"Successful payment from user {user_id}: payload={payload}, stars={payment.total_amount}")

    if payload == "premium_30_days":
        await db.upgrade_user_to_premium(user_id, days=30)
        await update.message.reply_text(
            "🎉 *Welcome to Premium!* ⭐\n\n"
            "Your account has been upgraded for *30 days*.\n"
            "Enjoy unlimited expense logging, AI scanning, and professional reports!",
            parse_mode="Markdown"
        )
    elif payload == "premium_90_days":
        await db.upgrade_user_to_premium(user_id, days=90)
        await update.message.reply_text(
            "🎉 *Welcome to Premium!* ⭐\n\n"
            "Your account has been upgraded for *90 days*.\n"
            "Enjoy unlimited expense logging, AI scanning, and professional reports!",
            parse_mode="Markdown"
        )
    elif payload == "credits_50":
        await db.add_ai_credits(user_id, 50)
        await update.message.reply_text(
            "✅ *50 AI Voice Credits Added!* 🎙️\n\n"
            "You can now log 50 more voice notes using AI transcription.",
            parse_mode="Markdown"
        )
    else:
        logging.warning(f"Unknown payment payload received: {payload}")
        await update.message.reply_text("✅ Payment received. If you have issues, contact support.")

# -------------------- MAIN --------------------

async def post_init(application):
    await db.init_db()

if __name__ == "__main__":
    load_dotenv()
    
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        import sys
        logging.critical("BOT_TOKEN is not set in the environment or .env file. Exiting.")
        sys.exit(1)
        
    if not os.getenv("GROQ_API_KEY"):
        logging.warning("GROQ_API_KEY is not set. Vision OCR scanning and Voice processing features will not work.")
        
    if not os.getenv("EMAIL_ADDRESS") or not os.getenv("EMAIL_PASSWORD"):
        logging.warning("EMAIL_ADDRESS or EMAIL_PASSWORD is not set. Scheduled monthly email reports will fail.")

    os.makedirs("data", exist_ok=True)
    persistence = PicklePersistence(filepath="data/persistence.pkl")
    
    app = ApplicationBuilder() \
        .token(bot_token) \
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
            CommandHandler("limit", set_limit),
            CommandHandler("setbudget", set_budget),
            CommandHandler("setemail", set_email),
            CallbackQueryHandler(settings, pattern="^menu_settings$"),
            CallbackQueryHandler(set_limit, pattern="^menu_limit$"),
            CallbackQueryHandler(set_budget, pattern="^menu_budget$"),
            CallbackQueryHandler(upload_command, pattern="^menu_upload$"),
            CallbackQueryHandler(subscriptions_menu, pattern="^menu_subs$"),
            CallbackQueryHandler(summary, pattern="^menu_summary$"),
            CallbackQueryHandler(sub_delete_handler, pattern="^sub_del_"),
            CallbackQueryHandler(main_menu_handler, pattern=re.compile(r"^(menu_|del_|export_|editamt_|hist_page_|sub_|back_)"))
        ],
        states={
            SET_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_limit)],
            SET_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_budget)],
            SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_email)],
            ASK_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_currency)],
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_email)],
            ASK_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_pin)],
            ADD_CATEGORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category_handler)],
            EDIT_EXPENSE_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_amt_handler)],
            ADD_SUB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub_add_name)],
            ADD_SUB_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub_add_amt)],
            ADD_SUB_CYCLE: [CallbackQueryHandler(sub_add_cycle, pattern="^cycle_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        name="dashboard_conversation",
        persistent=True,
        allow_reentry=True,
        per_message=False,
    )

    # Register handlers
    app.add_handler(conv) # Startup & Auth (PIN)
    app.add_handler(dashboard_conv) # Main functionality
    
    # Callback queries for main menu (single actions)
    app.add_handler(CallbackQueryHandler(ocr_callback_handler, pattern=re.compile(r"^ocr_")))
    app.add_handler(CallbackQueryHandler(voice_callback_handler, pattern=re.compile(r"^voice_")))
    app.add_handler(CallbackQueryHandler(send_invoice_handler, pattern=re.compile(r"^buy_")))
    app.add_handler(CallbackQueryHandler(main_menu_handler, pattern=re.compile(r"^(menu_|del_|export_|editamt_|hist_page_|sub_|back_)")))
    app.add_handler(CallbackQueryHandler(settings_callback_handler, pattern=re.compile(r"^(settings_|cat_add|cat_del_)")))
    
    app.add_handler(CommandHandler("add", add_expense))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("export", export_csv))
    app.add_handler(CommandHandler("menu", show_main_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("premium", show_premium_hub))

    # Telegram Stars payment handlers
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Catch-all for expenses (Run last in Group 0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense))

    # Start background jobs
    schedule_jobs(app.bot)

    app.run_polling()
