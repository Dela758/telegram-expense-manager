from .database import db

async def get_user_profile(user_id):
    """Fetch only the basic user settings (no expenses)."""
    user = await db.get_user(user_id)
    if not user: return None
    return {
        "user_id": user['user_id'],
        "pin": user['pin'],
        "currency": user['currency'],
        "budget": user['budget'],
        "email": user['email'],
        "subscription_tier": user['subscription_tier'],
        "premium_until": user['premium_until'],
        "ai_credits": user['ai_credits'],
        "category_limits": await db.get_limits(user_id),
        "custom_categories": await db.get_custom_categories(user_id),
        "recurring": await db.get_subscriptions(user_id)
    }

async def get_user_expenses(user_id, limit=None, offset=0):
    """Fetch expenses with optional pagination."""
    return await db.get_expenses(user_id, limit=limit, offset=offset)

async def get_user_data(user_id):
    """
    Backward compatibility wrapper. 
    WARNING: Avoid using for large datasets as it fetches ALL expenses.
    """
    profile = await get_user_profile(user_id)
    if not profile: return None
    profile["expenses"] = await get_user_expenses(user_id)
    return profile

async def save_user_data(user_id, data):
    """
    Simplified update. Real logic should use specific DB methods.
    Updated to be async.
    """
    # Create user if not exists
    if not await db.get_user(user_id):
        await db.create_user(user_id, pin=data.get("pin"))
    
    # Update core profile
    await db.update_user(user_id, 
                   currency=data.get("currency", "USD"),
                   budget=data.get("budget", 0),
                   email=data.get("email"),
                   pin=data.get("pin"))
    
    # For limits, we might need to sync
    if "category_limits" in data:
        for cat, amt in data["category_limits"].items():
            await db.set_limit(user_id, cat, amt)

async def set_user_pin(user_id, pin):
    if not await db.get_user(user_id):
        await db.create_user(user_id, pin=pin)
    else:
        await db.update_user(user_id, pin=pin)

async def validate_user_pin(user_id, pin):
    user = await db.get_user(user_id)
    if not user:
        return False
    return db.verify_pin(pin, user['pin'])
