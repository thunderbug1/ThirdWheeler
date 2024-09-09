import structlog
from sqlalchemy.orm import Session
from telegram.ext import ContextTypes
from models import ScheduledAction, User, UserActionLog
from datetime import datetime, timezone

logger = structlog.get_logger()

def get_translated_message(llm, text: str, target_language: str) -> str:
    """Translate a system message to the user's language."""
    return llm.translate(text, target_language)

async def send_message_to_user(bot, chat_id: int, message: str, llm, user_language: str):
    """Send a translated message to a user."""
    translated_message = get_translated_message(llm, message, user_language)
    await bot.send_message(chat_id=chat_id, text=translated_message)

def update_user_language(session: Session, user: User, telegram_language: str) -> None:
    """Update the user's language if it differs from the provided telegram language."""
    if user.language != telegram_language:
        user.language = telegram_language
        session.commit()
        logger.info(f"Updated language for user {user.telegram_id} to {telegram_language}")

async def rate_limited(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE, session: Session, llm) -> bool:
    """Check if the user is rate-limited and handle the response if they are."""
    user_telegram_id = update.effective_user.id
    user_language = update.message.from_user.language_code or 'en'
    current_time = datetime.now(timezone.utc)

    user = session.query(User).filter(User.telegram_id == user_telegram_id).first()
    if not user:
        translated_message = get_translated_message(llm, "Please start the bot first using /start.", 'en')
        await update.message.reply_text(translated_message)
        return True

    last_action_time = session.query(UserActionLog.timestamp).filter(UserActionLog.user_id == user.telegram_id).order_by(UserActionLog.timestamp.desc()).first()

    if last_action_time:
        # Convert last_action_time to an offset-aware datetime if it's offset-naive
        last_action_time_aware = last_action_time[0].replace(tzinfo=timezone.utc) if last_action_time[0].tzinfo is None else last_action_time[0]
        
        if (current_time - last_action_time_aware).total_seconds() < 3:
            translated_message = get_translated_message(llm, "You're doing that too much. Please slow down.", user_language)
            await update.message.reply_text(translated_message)
            logger.info("Rate limit enforced", telegram_id=user_telegram_id)
            return True
    
    log_entry = UserActionLog(user_id=user.telegram_id, action=update.message.text, timestamp=current_time)
    session.add(log_entry)
    session.commit()
    
    return False

from datetime import datetime, timezone

def format_scheduled_actions(actions : list[ScheduledAction]):
    if not actions:
        return "No scheduled actions."
    
    current_time = datetime.now(timezone.utc)
    formatted_list = "Here are the scheduled actions:\n"
    
    for action in actions:
        time_until_trigger = action.trigger_time - current_time
        days, seconds = time_until_trigger.days, time_until_trigger.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        # Format the time until trigger in a human-readable way
        time_str = f"{days} days, {hours} hours, and {minutes} minutes" if days > 0 else \
                   f"{hours} hours and {minutes} minutes" if hours > 0 else \
                   f"{minutes} minutes"

        formatted_list += (
            f"- Action ID {action.id}: {action.description} "
            f"(scheduled to trigger in {time_str}, at {action.trigger_time.isoformat()} UTC)\n"
        )
    
    return formatted_list
