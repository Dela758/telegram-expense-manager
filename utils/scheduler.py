from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os
from datetime import datetime
from . import storage, mailer
from .database import db
from telegram import Bot
import logging

# Daily summary
async def send_daily_summary(bot: Bot, user_id, chat_id):
    data = await storage.get_user_data(user_id)
    if not data:
        return
    today = datetime.now().date().isoformat()
    summary = sum(e['amount'] for e in data.get('expenses', []) if e['date'].startswith(today))
    await bot.send_message(chat_id, f"📊 Today's total: {summary:.2f} {data.get('currency', 'USD')}")

# Category limit checks
def get_progress_bar(percent):
    length = 10
    filled = int(length * percent / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.0f}%"

async def check_limits(bot: Bot, user_id, chat_id):
    data = await storage.get_user_data(user_id)
    if not data:
        return
    limits = data.get("category_limits", {})
    if not limits:
        return
        
    total = {}
    for e in data.get("expenses", []):
        cat = e['category']
        total[cat] = total.get(cat, 0) + e['amount']
    
    warnings = []
    for cat, limit in limits.items():
        amt = total.get(cat, 0)
        percent = (amt / limit) * 100
        bar = get_progress_bar(percent)
        
        if amt > limit:
            warnings.append(f"🔴 *{cat.upper()} OVERSPENT*\n{bar}\nLimit: {limit:.2f} | Spent: {amt:.2f} (+{amt-limit:.2f})")
        elif percent >= 80:
            warnings.append(f"🟡 *{cat.upper()} WARNING*\n{bar}\nLimit: {limit:.2f} | Spent: {amt:.2f} ({(limit-amt):.2f} left)")
            
    if warnings:
        await bot.send_message(chat_id, "\n\n".join(warnings), parse_mode="Markdown")

# Monthly email report
async def send_monthly_report(bot: Bot, user_id, chat_id):
    data = await storage.get_user_data(user_id)
    if not data:
        return
    email = data.get("email")
    if email:
        try:
            path = mailer.export_csv(user_id, data.get("expenses", []))
            mailer.send_email(email, path)
            await bot.send_message(chat_id, f"📧 Monthly report sent to {email}")
        except Exception as e:
            logging.error(f"Failed to send report for {user_id}: {e}")

# Recurring expenses
async def process_recurring_expenses(bot: Bot, user_id, chat_id):
    data = await storage.get_user_data(user_id)
    if not data or not data.get("recurring"):
        return
        
    today = datetime.now()
    today_str = today.date().isoformat()
    recurring = data.get("recurring", [])
    
    for item in recurring:
        last_logged = item.get("last_logged")
        if last_logged:
            last_date = datetime.fromisoformat(last_logged)
            if last_date.month == today.month and last_date.year == today.year:
                continue
        
        # Log it
        await db.add_expense(
            user_id=user_id,
            amount=item['amount'],
            category=item['category'],
            date=today_str,
            note="Automated recurring expense"
        )
        await db.update_recurring_log(item['id'], today_str)
        
        await bot.send_message(chat_id, f"📅 *Automated Expense Logged*\n- {item['amount']} for {item['category']}", parse_mode="Markdown")

# Main scheduler logic
scheduler = AsyncIOScheduler()

async def scheduled_tasks(bot: Bot):
    users = await db.get_all_users()
    for user in users:
        user_id = user['user_id']
        chat_id = user_id # Assuming user_id is chat_id for direct messages
        
        await send_daily_summary(bot, user_id, chat_id)
        await check_limits(bot, user_id, chat_id)
        await process_recurring_expenses(bot, user_id, chat_id)
        
        if datetime.now().day == 1:
            await send_monthly_report(bot, user_id, chat_id)

def schedule_jobs(bot: Bot):
    # Run once a day at 20:00 (8 PM)
    scheduler.add_job(scheduled_tasks, CronTrigger(hour=20, minute=0), args=[bot])
    # Also run at 9 AM for recurring expenses check
    scheduler.add_job(scheduled_tasks, CronTrigger(hour=9, minute=0), args=[bot])
    
    scheduler.start()
    logging.info("Scheduler started.")
