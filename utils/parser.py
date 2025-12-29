import re

def parse_expense_message(text):
    # Expanded regex to handle varied amount placement and currency symbols
    # Supports: "spent 50 on food", "$50 for lunch", "bought gas 12.50", "20.00 misc"
    pattern = re.compile(
        r"(?i)(?:spent|paid|bought)?\s*([$€£¥₹])?\s*(\d+(?:\.\d{1,2})?)\s*(?:\s+|on|for)?\s*([$€£¥₹])?\s*(\w+)?"
    )
    
    match = pattern.search(text)
    if not match:
        return None
        
    amount = float(match.group(2))
    category_raw = match.group(4) or "misc"
    
    # Simple aliasing
    aliases = {
        "lunch": "food",
        "dinner": "food",
        "breakfast": "food",
        "taxi": "transport",
        "bus": "transport",
        "uber": "transport",
        "gas": "transport",
        "petrol": "transport",
        "rent": "bills",
        "electricity": "bills",
        "water": "bills",
        "internet": "bills",
        "movie": "entertainment",
        "game": "entertainment"
    }
    
    category = category_raw.lower()
    category = aliases.get(category, category)
    
    # Detect currency symbol
    symbol = match.group(1) or match.group(3) or None
    
    return {"amount": amount, "category": category, "symbol": symbol}
