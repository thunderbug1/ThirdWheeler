from telegram import Update
from telegram.ext import ContextTypes
from db_utils import add_scheduled_action, delete_scheduled_action
from models import Conversation, User, Translation
from database import SessionLocal
from utils import format_scheduled_actions, send_message_to_user
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import ClassVar
import openai
import structlog

logger = structlog.get_logger()

# Base class for actions with shared execution logic
class BaseAction(BaseModel):
    function_name: ClassVar[str]  # Class-level variable, not part of Pydantic's schema

    class Config:
        # Extra fields like class variables are ignored in the schema
        extra = "forbid"

    @classmethod
    async def execute(cls, context, session, llm, user, user_language, arguments: dict):
        raise NotImplementedError("Execute method must be implemented in subclasses.")

    # @staticmethod
    # def with_db_session(func):
    #     """Decorator to handle database session management."""
    #     async def wrapper(*args, **kwargs):
    #         session = SessionLocal()
    #         try:
    #             return await func(*args, session=session, **kwargs)  # Pass session through kwargs
    #         except Exception as e:
    #             logger.error(f"Database error: {e}")
    #             return "An error occurred"
    #         finally:
    #             session.close()
    #     return wrapper

# Models for specific actions
class OverwriteSummary(BaseAction):
    """Overwrite the user's summary with new information."""
    function_name: ClassVar[str] = "overwrite_summary"  # Class-level variable

    user_id: int = Field(..., description="The ID of the user.")
    new_summary: str = Field(..., description="The new summary of the user.")

    @classmethod
    # @BaseAction.with_db_session
    async def execute(cls, context, session, llm, user, user_language, arguments: dict):
        user = session.query(User).filter(User.id == arguments['user_id']).first()
        if user:
            user.summary = arguments['new_summary']
            session.commit()
            logger.info("User summary updated", user_id=user.id)
            return "Summary updated successfully"
        logger.error("User not found", user_id=arguments['user_id'])
        return "Failed to update summary"

class AddScheduledAction(BaseAction):
    """Schedule an action in the future. Use this tool whenever you plan to do something in the future."""
    function_name: ClassVar[str] = "add_scheduled_action"

    user_id: int = Field(..., description="The ID of the user.")
    description: str = Field(..., description="Description of the action, including recurrence.")
    trigger_time: str = Field(..., description="The trigger time in ISO 8601 format.")

    @classmethod
    # @BaseAction.with_db_session
    async def execute(cls, context, session, llm, user, user_language, arguments: dict):
        trigger_time = datetime.fromisoformat(arguments['trigger_time'])
        action_id = add_scheduled_action(session, user.id, arguments['description'], trigger_time)
        await send_message_to_user(context.bot, user.telegram_id, f"Scheduled action {action_id} added!", llm, user_language)

class DeleteScheduledAction(BaseAction):
    """Delete an existing scheduled action."""
    function_name: ClassVar[str] = "delete_scheduled_action"

    action_id: int = Field(..., description="The ID of the action to delete.")

    @classmethod
    # @BaseAction.with_db_session
    async def execute(cls, context, session, llm, user, user_language, arguments: dict) -> str:
        delete_scheduled_action(session, int(arguments['action_id']))
        await send_message_to_user(context.bot, user.telegram_id, f"Scheduled action {arguments['action_id']} deleted!", llm, user_language)
        return "tool call succesfully deleted scheduled action"

# Function to retrieve LLM tools
def get_llm_functions():
    return [
        openai.pydantic_function_tool(OverwriteSummary),
        openai.pydantic_function_tool(AddScheduledAction),
        openai.pydantic_function_tool(DeleteScheduledAction),
    ]

# Helper function to dynamically find the correct class by function_name
def get_action_class_by_function_name(function_name: str):
    for subclass in BaseAction.__subclasses__():
        if subclass.__name__ == function_name:
            return subclass
    return None

# Unified execution handler using dynamic class method calling
async def execute_tool(context, session, llm, user, user_language, function_name: str, arguments: dict) -> str:
    """Handle execution of different tool functions by dynamically calling the respective class methods.

        returns a feedback string for the llm """
    try:
        action_class = get_action_class_by_function_name(function_name)
        if action_class:
            await action_class.execute(context, session, llm, user, user_language, arguments)
            return f"successfully executed tool {function_name}"
        else:
            logger.warning(f"Unknown function call: {function_name}")
            return f"Unknown function call: {function_name}"
    except Exception as e:
        logger.error(f"Error executing tool {function_name}: {e}")
        return f"Error executing tool {function_name}: {e}"

# Factory to build tool function handler
def build_call_tool_function(context, session, llm, user, user_language):
    return lambda function_name, arguments: execute_tool(context, session, llm, user, user_language, function_name, arguments)
