import requests
import time
import os

# Using ExchangeRate-API (exchangerate-api.com) as it's more reliable
# Fallback to a free tier if no key is provided
API_KEY = os.getenv("EXCHANGE_API_KEY")
BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/" if API_KEY else "https://open.er-api.com/v6/latest/"

# Cache structure: {"timestamp": 0, "rates": {}}
_cache = {"timestamp": 0, "rates": {}, "base": "USD"}
CACHE_DURATION = 86400  # 24 hours

def _get_rates(base="USD"):
    global _cache
    now = time.time()
    
    if _cache["rates"] and (now - _cache["timestamp"] < CACHE_DURATION) and _cache["base"] == base:
        return _cache["rates"]
        
    try:
        url = BASE_URL + base
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if data.get("result") == "success" or data.get("result") == "error": # er-api uses 'result'
            rates = data.get("conversion_rates") or data.get("rates")
            if rates:
                _cache = {"timestamp": now, "rates": rates, "base": base}
                return rates
    except Exception as e:
        print(f"[ERROR] Currency API failed: {e}")
        
    return _cache.get("rates", {"USD": 1.0})

def convert(amount, from_currency, to_currency):
    if from_currency == to_currency:
        return amount
        
    rates = _get_rates(from_currency)
    if to_currency in rates:
        return amount * rates[to_currency]
    
    # If direct rate not found, try via USD
    usd_rates = _get_rates("USD")
    if from_currency in usd_rates and to_currency in usd_rates:
        amount_in_usd = amount / usd_rates[from_currency]
        return amount_in_usd * usd_rates[to_currency]
        
    return amount

def get_currency_from_symbol(symbol):
    symbols = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "₽": "RUB",
        "₩": "KRW",
        "₦": "NGN"
    }
    return symbols.get(symbol, "USD")
