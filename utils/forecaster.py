from datetime import datetime, timedelta
import pandas as pd

def forecast_monthly_spend(expenses, budget):
    if not expenses:
        return "No data for forecast."
    
    df = pd.DataFrame(expenses)
    df['date'] = pd.to_datetime(df['date'])
    
    # Get current month data
    today = datetime.now()
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    this_month_df = df[df['date'] >= month_start]
    
    if this_month_df.empty:
        return "No spending recorded this month yet."
        
    # Calculate daily average
    days_passed = (today - month_start).days + 1
    total_spent = this_month_df['amount'].sum()
    daily_avg = total_spent / days_passed
    
    # Project to end of month
    import calendar
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    projected_total = daily_avg * days_in_month
    
    diff = projected_total - budget if budget > 0 else 0
    
    res = f"🔮 *MONTHLY FORECAST*\n"
    res += f"━━━━━━━━━━━━━━━\n"
    res += f"📅 Days passed: `{days_passed}` / `{days_in_month}`\n"
    res += f"💰 Current spend: `{total_spent:.2f}`\n"
    res += f"📈 Projected total: `{projected_total:.2f}`\n"
    
    if budget > 0:
        if projected_total > budget:
            res += f"\n⚠️ *Over budget by:* `{diff:.2f}`"
        else:
            res += f"\n✅ *Under budget by:* `{abs(diff):.2f}`"
            
    return res
