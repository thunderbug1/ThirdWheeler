import time
import structlog
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from telegram import Bot
from models import ScheduledAction, Conversation
from db_utils import get_session, get_current_user
from utils import send_message_to_user
from llm import setup_llm, LLMWrapper

logger = structlog.get_logger()

def start_scheduler(bot_token: str):
    bot = Bot(token=bot_token)
    llm = setup_llm()
    logger.info("Scheduler started")

    while True:
        with get_session() as session:
            now = datetime.now(timezone.utc)
            actions_to_trigger = session.query(ScheduledAction).filter(
                ScheduledAction.trigger_time <= now,
                ScheduledAction.is_active == True
            ).all()

            for action in actions_to_trigger:
                try:
                    trigger_action(session, bot, llm, action)
                    # Mark the action as inactive after triggering
                    action.is_active = False
                    session.commit()
                except Exception as e:
                    logger.error("Failed to trigger scheduled action", action_id=action.id, error=str(e))
                    session.rollback()

        time.sleep(60)  # Check every minute

def format_time_since(timestamp):
    now = datetime.now(timezone.utc)
    time_diff = now - timestamp

    days = time_diff.days
    seconds = time_diff.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if days > 0:
        return f"{days} days ago"
    elif hours > 0:
        return f"{hours} hours ago"
    elif minutes > 0:
        return f"{minutes} minutes ago"
    else:
        return "just now"

def trigger_action(session: Session, bot: Bot, llm: LLMWrapper, action: ScheduledAction):
    user = get_current_user(session, action.user_id)

    if user:
        # Retrieve the last few messages between the bot and the user
        recent_conversations = session.query(Conversation).filter(
            Conversation.user_id == user.id
        ).order_by(Conversation.timestamp.desc()).limit(5).all()

        # Prepare the conversation history for the LLM context
        recent_messages = []
        for conversation in reversed(recent_conversations):  # Reverse to maintain chronological order
            time_since = format_time_since(conversation.timestamp)
            recent_messages.append({
                "role": "user" if conversation.user_id == user.id else "assistant",
                "content": f"{conversation.message} (sent {time_since})"
            })

        # Prepare the LLM context with the recent messages and action description
        context_messages = recent_messages + [
            {"role": "system", "content": "Generate a message for the following action based on the recent conversation context."},
            {"role": "user", "content": f"Action description: {action.description}"}
        ]

        try:
            llm_response = llm.get_response(context_messages)
            message = llm_response.content
        except Exception as e:
            logger.error("Failed to generate message with LLM", action_id=action.id, error=str(e))
            message = f"Reminder: {action.description}"  # Fallback to the description

        send_message_to_user(bot, user.telegram_id, message, llm=None, user_language=user.language)
        logger.info("Triggered scheduled action", action_id=action.id, user_id=action.user_id)
    else:
        logger.warning("User not found for scheduled action", action_id=action.id, user_id=action.user_id)
