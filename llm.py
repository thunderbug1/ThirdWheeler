import os
import openai
import requests
import structlog
from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import ContextTypes
from db_utils import add_scheduled_action, delete_scheduled_action, get_scheduled_actions_for_user
from models import Conversation, User, Translation
from database import SessionLocal
from utils import format_scheduled_actions, send_message_to_user
from datetime import datetime, timezone
import json

# Create a cache for translations
translation_cache = {}

logger = structlog.get_logger()

def overwrite_summary(user_id: int, new_summary: str):
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
    def __init__(self, api_url="http://host.docker.internal:11434/v1", model_name="llama3.1", use_openai=False):
        self.api_url = api_url
        self.model_name = model_name
        self.use_openai = use_openai  # Switch between using OpenAI and the locally hosted model

    async def get_response(self, context, summary=None, user_language='en', functions=None) -> dict:
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

        if self.use_openai:
            # Use OpenAI's API
            response = openai.ChatCompletion.create(
                model=self.model_name,
                messages=messages,
                functions=functions if functions else [],
                function_call="auto",  # Automatically determine if a function call is needed
                timeout=60
            )

            message_content = response.choices[0].message
        else:
            # Use the locally hosted model via API
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
                overwrite_summary(int(function_args['user_id']), function_args['new_summary'])

        # Log the response received from the LLM
        logger.info("Received response from LLM", response=message_content)

        return message_content

    def translate(self, text, target_language):
        if target_language == "en":
            return text  # default strings are in English, no translation needed
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

        # If translation is not found, use the locally hosted LLM or OpenAI API to translate
        if self.use_openai:
            response = openai.Completion.create(
                model=self.model_name,
                prompt=f"Translate the following text to {target_language}: {text}",
                max_tokens=60
            )
            translated_text = response.choices[0].text.strip()
        else:
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


def setup_llm() -> LLMWrapper:
    llm = LLMWrapper(api_url=os.getenv("LLM_URL", ""), 
                     model_name=os.getenv("LLM_MODEL"), 
                     use_openai=os.getenv("USE_OPENAI_LLM").lower() == "true")
    return llm

def get_user_summary(user: User) -> str:
    return user.summary if user.summary else ""

def prepare_context_messages(session: Session, user: User, user_summary: str, message: str) -> list:
    user_history = session.query(Conversation).filter(Conversation.user_id == user.id).count()
    scheduled_actions = get_scheduled_actions_for_user(session, user.id)
    formatted_actions = format_scheduled_actions(scheduled_actions)

    context_messages = []

    if user_history == 0 and not user_summary:
        context_messages.append({"role": "system", "content": get_hidden_intro_message()})

    current_time = datetime.now(timezone.utc).isoformat()
    context_messages.append({"role": "system", "content": f"The current system time is {current_time} UTC."})
    context_messages.append({"role": "system", "content": formatted_actions})
    context_messages.append({"role": "user", "content": message})

    return context_messages

def get_hidden_intro_message() -> str:
    return (
        "This is the user's first interaction. "
        "Introduce yourself as the ThirdWheeler bot, a helpful assistant designed to help couples communicate better. "
        "Explain that you can remind them of things their partner would like to see more or less often, "
        "and help them improve their relationship through better communication. "
        "Explain that they can add their partner by using the /add_partner command followed by their partner's username or via an invite link. "
        "Once they are linked with their partner, you will keep track of their conversations and provide helpful reminders. "
        "To get started, ask the user for some basic information such as their name, birthday, and anything else they would like you to know. "
        "Once this information is gathered, store it in the user's summary so that you don't need to ask again."
    )

def get_llm_functions() -> list:
    return [
        {
            "name": "overwrite_summary",
            "description": "Overwrite the user's summary with new information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "The ID of the user."},
                    "new_summary": {"type": "string", "description": "The new summary of the user."},
                },
                "required": ["user_id", "new_summary"],
            },
        },
        {
            "name": "add_scheduled_action",
            "description": "Add a new scheduled action for when you want to become active to send a message to the user. Avoid redundant scheduled actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "The ID of the user."},
                    "description": {"type": "string", "description": "The description of the action. Also mention the frequency if it is a recurring action."},
                    "trigger_time": {"type": "string", "description": "The time to trigger the action, in ISO 8601 format."}
                },
                "required": ["user_id", "description", "trigger_time"]
            }
        },
        {
            "name": "delete_scheduled_action",
            "description": "Delete an existing scheduled action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {"type": "integer", "description": "The ID of the action to delete."}
                },
                "required": ["action_id"]
            }
        }
    ]

async def save_conversation(session: Session, user_id: int, message: str):
    conversation = Conversation(
        couple_id=None,  # This is a user-specific interaction, not a couple interaction
        user_id=user_id,
        message=message
    )
    session.add(conversation)



async def process_llm_response(response: dict, update: Update, context: ContextTypes.DEFAULT_TYPE, session: Session, user: User, user_language: str):
    response_content = response['content']
    await update.message.reply_text(response_content)

    if 'function_call' in response:
        function_name = response['function_call']['name']
        arguments = json.loads(response['function_call']['arguments'])  # Parse arguments as JSON

        if function_name == "add_scheduled_action":
            trigger_time = datetime.fromisoformat(arguments['trigger_time'])
            action_id = add_scheduled_action(session, user.id, arguments['description'], trigger_time)
            await send_message_to_user(context.bot, user.telegram_id, f"Scheduled action {action_id} added!", llm, user_language)
        
        elif function_name == "delete_scheduled_action":
            delete_scheduled_action(session, int(arguments['action_id']))
            action_id = arguments['action_id']
            await send_message_to_user(context.bot, user.telegram_id, f"Scheduled action {action_id} deleted!", llm, user_language)
        else:
            logger.warning(f"Unknown function call: {function_name}")

        logger.info("Function call processing completed", function_name=function_name)
    else:
        logger.info("no function calls were made")

