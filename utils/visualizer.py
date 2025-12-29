import matplotlib.pyplot as plt
import os
from datetime import datetime

# Set up a clean style
plt.style.use('ggplot')

def generate_spending_charts(user_id, expenses, currency="USD"):
    if not expenses:
        return None, None
        
    charts_dir = "charts"
    os.makedirs(charts_dir, exist_ok=True)
    
    # 1. Monthly Category Pie Chart
    today = datetime.now().date()
    this_month = today.replace(day=1)
    
    monthly_breakdown = {}
    for e in expenses:
        try:
            date = datetime.fromisoformat(e['date']).date()
            if date >= this_month:
                cat = e['category'].capitalize()
                monthly_breakdown[cat] = monthly_breakdown.get(cat, 0) + e['amount']
        except:
            continue
            
    pie_path = None
    if monthly_breakdown:
        plt.figure(figsize=(8, 6))
        plt.pie(monthly_breakdown.values(), labels=monthly_breakdown.keys(), autopct='%1.1f%%', startangle=140)
        plt.title(f"Monthly Spending Breakdown ({currency})")
        pie_path = os.path.join(charts_dir, f"{user_id}_pie.png")
        plt.savefig(pie_path)
        plt.close()
        
    # 2. Weekly Bar Chart (Last 7 days)
    import pandas as pd
    from datetime import timedelta
    
    last_7_days = today - timedelta(days=6)
    daily_data = { (today - timedelta(days=i)).isoformat(): 0 for i in range(7) }
    
    for e in expenses:
        try:
            date_str = datetime.fromisoformat(e['date']).date().isoformat()
            if date_str in daily_data:
                daily_data[date_str] += e['amount']
        except:
            continue
            
    plt.figure(figsize=(10, 5))
    dates = list(daily_data.keys())
    dates.reverse()
    values = [daily_data[d] for d in dates]
    
    plt.bar([d[-5:] for d in dates], values, color='skyblue')
    plt.title(f"Spending over last 7 days ({currency})")
    plt.ylabel("Amount")
    plt.xlabel("Date")
    
    bar_path = os.path.join(charts_dir, f"{user_id}_bar.png")
    plt.savefig(bar_path)
    plt.close()
    
    return pie_path, bar_path
