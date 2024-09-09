import asyncio
import time
import structlog
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from telegram import Bot
from models import ScheduledAction, Conversation
from db_utils import get_session, get_current_user
from tools import build_call_tool_function, get_llm_functions
from utils import send_message_to_user
from llm import get_user_summary, setup_llm, LLMWrapper

logger = structlog.get_logger()


async def start_scheduler(bot_token: str):
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
                    await trigger_action(session, bot, llm, action)  # Use 'await' for async trigger
                    # Mark the action as inactive after triggering
                    action.is_active = False
                    session.commit()
                except Exception as e:
                    logger.error("Failed to trigger scheduled action", action_id=action.id, error=str(e))
                    session.rollback()

        await asyncio.sleep(60)  # Use asyncio.sleep to avoid blocking the event loop


def format_time_since(timestamp):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
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

async def trigger_action(session: Session, bot: Bot, llm: LLMWrapper, action: ScheduledAction):
    user = get_current_user(session, action.user_id)

    if user:
        # Retrieve the last few messages between the bot and the user
        recent_conversations = session.query(Conversation).filter(
            Conversation.user_id == user.telegram_id
        ).order_by(Conversation.timestamp.desc()).limit(5).all()

        # Prepare the conversation history for the LLM context
        recent_messages = []
        for conversation in reversed(recent_conversations):  # Reverse to maintain chronological order
            time_since = format_time_since(conversation.timestamp)
            recent_messages.append({
                "role": "user" if conversation.user_id == user.telegram_id else "assistant",
                "content": f"{conversation.message} (sent {time_since})"
            })

        # Prepare the LLM context with the recent messages and action description
        context_messages = recent_messages + [
            {"role": "system", "content": "Generate a message for the following action based on the recent conversation context. Do not re-execute the commands from the recent conversation. If it is supposed to be a recurring action, schedule the next action trigger and make sure to add the description of the desired action frequency to the action description for future rescheduling since only one action is scheduled at a time and after triggering it, the next action is scheduled."},
            {"role": "user", "content": f"Action description: {action.description}"}
        ]

        user_summary = get_user_summary(user)

        # try:
        llm_response = await llm.get_response(context_messages,  
                                              summary=user_summary,           
                                              user_language=user.language, 
                                                tools=get_llm_functions(),
                                                call_tool=build_call_tool_function(bot, session, llm, user, user.language))
        message = llm_response.content
        # except Exception as e:
        #     logger.error("Failed to generate message with LLM", action_id=action.id, error=str(e))
        #     message = f"Reminder: {action.description}"  # Fallback to the description

        await send_message_to_user(bot, user.telegram_id, message, llm=llm, user_language=user.language)
        logger.info("Triggered scheduled action", action_id=action.id, user_id=action.user_id)
    else:
        logger.warning("User not found for scheduled action", action_id=action.id, user_id=action.user_id)
