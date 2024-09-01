# utils.py
from sqlalchemy.orm import Session
from datetime import datetime, timezone

import structlog
from llm import LLMWrapper
from models import User, UserActionLog
from sqlalchemy import func

logger = structlog.get_logger()

def get_translated_message(llm : LLMWrapper, text: str, language: str) -> str:
    """Translate a system message to the user's language."""
    return llm.translate(text, language)

async def send_message_to_user(bot, chat_id: int, text: str, llm : LLMWrapper, language: str = 'en'):
    translated_message = get_translated_message(llm, text, language)
    await bot.send_message(chat_id=chat_id, text=translated_message)

async def rate_limited(update, context, session: Session, llm) -> bool:
    user_telegram_id = update.effective_user.id
    user_language = update.message.from_user.language_code or 'en'
    current_time = datetime.now(timezone.utc)

    user = session.query(User).filter(User.telegram_id == user_telegram_id).first()
    if not user:
        translated_message = get_translated_message(llm, "Please start the bot first using /start.", 'en')
        await update.message.reply_text(translated_message)
        return True

    last_action_time = session.query(func.max(UserActionLog.timestamp)).filter(UserActionLog.user_id == user.id).scalar()
    
    # Ensure last_action_time is timezone-aware
    if last_action_time and last_action_time.tzinfo is None:
        last_action_time = last_action_time.replace(tzinfo=timezone.utc)
    
    if last_action_time and (current_time - last_action_time).seconds < 3:
        translated_message = get_translated_message(llm, "You're doing that too much. Please slow down.", user_language)
        await update.message.reply_text(translated_message)
        logger.info("Rate limit enforced", user_id=user.id, telegram_id=user_telegram_id)
        return True

    log_entry = UserActionLog(user_id=user.id, action=update.message.text)
    session.add(log_entry)
    return False