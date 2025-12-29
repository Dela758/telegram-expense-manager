import os
import asyncio
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

async def list_models():
    api_key = os.getenv("GROQ_API_KEY")
    client = AsyncGroq(api_key=api_key)
    try:
        models = await client.models.list()
        vision_models = [m.id for m in models.data if "vision" in m.id.lower() or "scout" in m.id.lower() or "maverick" in m.id.lower()]
        print("Available Vision/Multimodal Models:")
        for m_id in vision_models:
            print(f"- {m_id}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())
