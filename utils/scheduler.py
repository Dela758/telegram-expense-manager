from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os
import asyncio
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
        path = None
        try:
            path = mailer.export_csv(user_id, data.get("expenses", []))
            mailer.send_email(email, path)
            await bot.send_message(chat_id, f"📧 Monthly report sent to {email}")
        except Exception as e:
            logging.error(f"Failed to send report for {user_id}: {e}")
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logging.error(f"Error removing temp CSV report {path}: {e}")

# Automated Subscription Logging
async def process_subscriptions(bot: Bot, user_id, chat_id):
    subs = await db.get_subscriptions(user_id)
    if not subs: return
    
    today = datetime.now()
    today_str = today.date().isoformat()
    
    for sub in subs:
        last_logged = sub.get("last_logged")
        should_log = False
        
        if not last_logged:
            should_log = True
        else:
            last_date = datetime.fromisoformat(last_logged)
            if sub['billing_cycle'] == 'monthly':
                # Log if it's a new month
                if last_date.month != today.month or last_date.year != today.year:
                    # Plus check if the day matches or has passed
                    start_day = datetime.fromisoformat(sub['start_date']).day
                    if today.day >= start_day:
                        should_log = True
            elif sub['billing_cycle'] == 'yearly':
                # Log if it's a new year
                if last_date.year != today.year:
                    start_date = datetime.fromisoformat(sub['start_date'])
                    if today.month > start_date.month or (today.month == start_date.month and today.day >= start_date.day):
                        should_log = True
        
        if should_log:
            await db.add_expense(
                user_id=user_id,
                amount=sub['amount'],
                category=sub['category'],
                date=today_str,
                note=f"Subscription: {sub['name']}"
            )
            await db.update_subscription_log(sub['id'], today_str)
            await bot.send_message(chat_id, f"💳 *Subscription Logged*\n• {sub['name']}: `{sub['amount']:.2f}`", parse_mode="Markdown")

# Main scheduler logic
scheduler = AsyncIOScheduler()

async def scheduled_tasks(bot: Bot):
    users = await db.get_all_users()
    for user in users:
        user_id = user['user_id']
        chat_id = user_id # Assuming user_id is chat_id for direct messages
        
        try:
            await send_daily_summary(bot, user_id, chat_id)
            await check_limits(bot, user_id, chat_id)
            await process_subscriptions(bot, user_id, chat_id)
            
            if datetime.now().day == 1:
                await send_monthly_report(bot, user_id, chat_id)
                
            # Rate limiting: wait 100ms between users to avoid hitting Telegram limits
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Error processing scheduled tasks for user {user_id}: {e}")

def schedule_jobs(bot: Bot):
    # Run once a day at 20:00 (8 PM)
    scheduler.add_job(scheduled_tasks, CronTrigger(hour=20, minute=0), args=[bot])
    # Also run at 9 AM for recurring expenses check
    scheduler.add_job(scheduled_tasks, CronTrigger(hour=9, minute=0), args=[bot])
    
    scheduler.start()
    logging.info("Scheduler started.")
