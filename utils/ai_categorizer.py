import os
import json
import logging
import re
from groq import AsyncGroq
from .database import db

async def get_smart_category(user_id, merchant_name, note=""):
    """
    Uses AI to determine the best category for a merchant/note based on available categories.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "misc"

    client = AsyncGroq(api_key=api_key)
    
    # 1. Get available categories for this user
    custom_cats = await db.get_custom_categories(user_id)
    standard_cats = ["food", "transport", "bills", "entertainment", "health", "shopping", "misc"]
    all_categories = list(set(standard_cats + custom_cats))

    # 2. Prompt Llama to pick the best one
    prompt = (
        f"A user spent money at '{merchant_name}' with note: '{note}'.\n"
        f"Available categories: {', '.join(all_categories)}.\n"
        "Which category fits best? Respond with ONLY the category name in lowercase."
    )

    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10
        )
        
        category = completion.choices[0].message.content.strip().lower()
        
        # Validation: Ensure it's in the list
        if category in all_categories:
            return category
        
        # Fallback to misc
        return "misc"
    except Exception as e:
        logging.error(f"Error in smart categorization: {e}")
        return "misc"
