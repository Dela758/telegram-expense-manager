import os
import base64
import json
import logging
import re
from groq import AsyncGroq

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

async def extract_receipt_data(image_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logging.error("GROQ_API_KEY not found in environment.")
        return None

    client = AsyncGroq(api_key=api_key)
    base64_image = encode_image(image_path)

    # Llama 4 Active Vision Models (verified Dec 2025)
    models = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct"
    ]
    
    for model in models:
        try:
            logging.info(f"Attempting OCR with model: {model}")
            completion = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Extract expense details from this receipt image. "
                                    "Return ONLY a JSON object with the following fields: "
                                    "'amount' (float), 'category' (best guess among: food, transport, bills, entertainment, shopping, misc), "
                                    "'merchant' (string), 'date' (ISO format if found, otherwise null). "
                                    "Do not include any other text."
                                )
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    }
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )

            response_content = completion.choices[0].message.content
            logging.info(f"Raw OCR response ({model}): {response_content}")
            
            # Robust JSON extraction
            try:
                # Remove Markdown code blocks if present
                clean_json = re.sub(r"```json\s*|\s*```", "", response_content).strip()
                data = json.loads(clean_json)
                
                # Basic validation
                if 'amount' in data and data['amount'] is not None:
                    # Ensure amount is a float
                    try:
                        data['amount'] = float(data['amount'])
                        return data
                    except (ValueError, TypeError):
                        logging.warning(f"Model {model} returned non-numeric amount: {data['amount']}")
                
                logging.warning(f"Model {model} returned invalid data structure: {data}")
            except Exception as parse_err:
                logging.error(f"Failed to parse JSON from {model}: {parse_err}")
                
        except Exception as e:
            logging.error(f"Error during OCR extraction with {model}: {e}")
            continue # Try next model
            
    return None
