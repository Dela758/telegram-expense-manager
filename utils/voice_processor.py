import os
import json
import logging
import re
from groq import AsyncGroq

async def process_voice_note(audio_path):
    """
    Transcribes audio and extracts structured expense data.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logging.error("GROQ_API_KEY not found in environment.")
        return None

    client = AsyncGroq(api_key=api_key)

    # 1. Transcribe the audio
    transcription = await transcribe_audio(client, audio_path)
    if not transcription:
        return None

    logging.info(f"Voice Transcription: {transcription}")

    # 2. Parse the transcription into JSON using Llama 4
    parsed_data = await parse_transcription(client, transcription)
    return parsed_data

async def transcribe_audio(client, audio_path):
    try:
        with open(audio_path, "rb") as file:
            transcription = await client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), file.read()),
                model="whisper-large-v3",
                response_format="text"
            )
            return transcription
    except Exception as e:
        logging.error(f"Error during audio transcription: {e}")
        return None

async def parse_transcription(client, text):
    try:
        # Prompt for extraction
        prompt = (
            "Extract expense details from the following transcribed voice note. "
            "Return ONLY a JSON object with these fields: "
            "'amount' (float), 'category' (one of: food, transport, bills, entertainment, shopping, misc), "
            "'note' (short description). "
            "If the amount is not clear, try to infer it. If a field is missing, use null.\n\n"
            f"Transcription: \"{text}\""
        )

        completion = await client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )

        response_content = completion.choices[0].message.content
        logging.info(f"Raw Voice Parse Response: {response_content}")

        # Robust JSON extraction
        clean_json = re.sub(r"```json\s*|\s*```", "", response_content).strip()
        data = json.loads(clean_json)

        # Basic validation
        if 'amount' in data and data['amount'] is not None:
            try:
                data['amount'] = float(data['amount'])
                return data
            except (ValueError, TypeError):
                logging.warning(f"Invalid numeric amount in voice parse: {data['amount']}")

        return data
    except Exception as e:
        logging.error(f"Error parsing voice transcription: {e}")
        return None
