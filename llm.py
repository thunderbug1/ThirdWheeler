# llm.py

import requests
import structlog
from sqlalchemy.orm import Session
from models import User
from models import Translation
from database import SessionLocal

# Create a cache for translations
translation_cache = {}

logger = structlog.get_logger()

async def overwrite_summary(user_id: int, new_summary: str):
    session = SessionLocal()
    user = session.query(User).filter(User.id == user_id).first()
    
    if user:
        user.summary = new_summary
        session.commit()
        session.close()
        logger.info("User summary updated", user_id=user_id)
        return "Summary updated successfully"
    
    session.close()
    logger.error("Failed to update user summary", user_id=user_id)
    return "Failed to update summary"

class LLMWrapper:
    def __init__(self, api_url="http://host.docker.internal:11434/v1", model_name="llama3.1"):
        self.api_url = api_url
        self.model_name = model_name

    async def get_response(self, context, summary=None, user_language='en', functions=None):
        messages = []

        # Define the assistant's system prompt
        system_prompt = (
            f"You are a helpful assistant Telegram bot called ThirdWheeler, designed to improve communication between couples. "
            f"Always respond in the user's preferred language: {user_language}. "
            "If the user's summary contains relevant details, incorporate that context into your responses. "
            "Help users communicate better by reminding them of things their partner might appreciate or want to see less often."
        )

        # Add the system prompt to the messages
        messages.append({"role": "system", "content": system_prompt})

        if summary:
            # Include the user's summary in the context
            messages.append({"role": "system", "content": f"User summary: {summary}"})

        # Append the conversation context
        messages.extend(context)

        # Log the request being sent to the LLM
        logger.info("Sending request to LLM", messages=messages)

        # Send the request to the locally hosted Llama 3.1 via Ollama API
        response = requests.post(
            f"{self.api_url}/chat/completions",
            json={
                "model": self.model_name,
                "messages": messages,
                "functions": functions if functions else [],
                "function_call": "auto"  # Automatically determine if a function call is needed
            }
        ,timeout=60)

        # Handle possible errors in the API response
        if response.status_code != 200:
            logger.error("LLM API call failed", status_code=response.status_code, response_text=response.text)
            return {"content": "Sorry, something went wrong while processing your request."}

        response_json = response.json()
        message_content = response_json['choices'][0]['message']
        
        if message_content.get("function_call"):
            function_name = message_content["function_call"]["name"]
            function_args = message_content["function_call"]["arguments"]

            if function_name == "overwrite_summary":
                await overwrite_summary(int(function_args['user_id']), function_args['new_summary'])
        
        # Log the response received from the LLM
        logger.info("Received response from LLM", response=message_content)

        return message_content

    def translate(self, text, target_language):
        if target_language == "en":
            return text # default strings are in english, no translation needed
        # Check local cache first
        if (text, target_language) in translation_cache:
            return translation_cache[(text, target_language)]

        # Check the database
        session = SessionLocal()
        translation = session.query(Translation).filter_by(
            original_text=text, target_language=target_language
        ).first()

        if translation:
            # Cache the translation locally
            translation_cache[(text, target_language)] = translation.translated_text
            session.close()
            return translation.translated_text

        # If translation is not found, use the locally hosted LLM via Ollama to translate
        logger.info("Translating text", text=text, target_language=target_language)
        response = requests.post(
            f"{self.api_url}/completions",
            json={
                "model": self.model_name,
                "prompt": f"Translate the following text to {target_language}: {text}",
                "max_tokens": 60
            }
        )

        if response.status_code != 200:
            logger.error("LLM API call failed during translation", status_code=response.status_code, response_text=response.text)
            return text  # Fallback to the original text if translation fails

        response_json = response.json()
        translated_text = response_json['choices'][0]['text'].strip()

        # Cache and store the translation in the database
        translation_cache[(text, target_language)] = translated_text
        new_translation = Translation(
            original_text=text,
            target_language=target_language,
            translated_text=translated_text
        )
        session.add(new_translation)
        session.commit()
        session.close()

        # Log the successful translation
        logger.info("Text translated successfully", original_text=text, translated_text=translated_text, target_language=target_language)

        return translated_text