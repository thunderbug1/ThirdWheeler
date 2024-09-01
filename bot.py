import secrets
import structlog
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from database import SessionLocal
from models import User, Couple, Conversation, UserActionLog, PendingCouple
import os
from scheduler import start_scheduler
from database import init_db
from datetime import datetime
from llm import LLMWrapper
import re
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
import dotenv

dotenv.load_dotenv()

# Configure structured logging with structlog
structlog.configure(
    processors=[
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

BOT_TOKEN = os.getenv('BOT_TOKEN')
llm = LLMWrapper(api_url="http://host.docker.internal:11434/v1")

RATE_LIMIT_SECONDS = 10
CONFIRM_UNLINK, CONFIRM_DELETE = range(2)

def validate_username(username):
    return re.match(r'^[a-zA-Z0-9_]{5,32}$', username)

def translate_message(llm, text, target_language):
    """Translate a system message to the user's language."""
    return llm.translate(text, target_language)

async def rate_limited(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    user_telegram_id = update.effective_user.id
    user_language = update.message.from_user.language_code or 'en'
    current_time = datetime.utcnow()

    user = session.query(User).filter(User.telegram_id == user_telegram_id).first()
    if not user:
        translated_message = translate_message(llm, "Please start the bot first using /start.", 'en')
        await update.message.reply_text(translated_message)
        session.close()
        return True

    last_action_time = session.query(func.max(UserActionLog.timestamp)).filter(UserActionLog.user_id == user.id).scalar()
    if last_action_time and (current_time - last_action_time).seconds < RATE_LIMIT_SECONDS:
        translated_message = translate_message(llm, "You're doing that too much. Please slow down.", user_language)
        await update.message.reply_text(translated_message)
        session.close()
        logger.info("Rate limit enforced", user_id=user.id, telegram_id=user_telegram_id)
        return True
    
    log_entry = UserActionLog(user_id=user.id, action=update.message.text)
    session.add(log_entry)
    session.commit()
    session.close()
    return False
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    token = context.args[0] if context.args else None
    user_language = update.message.from_user.language_code or 'en'

    logger.info("User started bot", telegram_id=update.effective_user.id)

    # Ensure the current user exists in the users table
    current_user = session.query(User).filter(User.telegram_id == update.effective_user.id).first()
    if not current_user:
        current_user = User(telegram_id=update.effective_user.id, name=update.effective_user.full_name)
        session.add(current_user)
        session.commit()
        logger.info("New user registered", telegram_id=update.effective_user.id)

    if token:
        pending_couple = session.query(PendingCouple).filter(PendingCouple.token == token).first()

        if pending_couple:
            if pending_couple.requested_id is None:
                # Assign the current user as the requested_id
                pending_couple.requested_id = current_user.id

                # Ensure the requester exists in the users table
                requester = session.query(User).filter(User.id == pending_couple.requester_id).first()
                if not requester:
                    translated_message = translate_message(llm, "Error: Requester not found.", user_language)
                    await update.message.reply_text(translated_message)
                    session.close()
                    logger.error("Requester not found", requester_id=pending_couple.requester_id)
                    return

                # Create a Couple entry
                couple = Couple(
                    user1_id=pending_couple.requester_id,
                    user2_id=pending_couple.requested_id
                )
                session.add(couple)

                # Remove the pending request
                session.delete(pending_couple)
                session.commit()

                # Notify both users that they are now linked
                requester_message = translate_message(
                    llm,
                    f"You are now linked with {current_user.name}!",
                    requester.language or 'en'
                )
                await context.bot.send_message(chat_id=requester.telegram_id, text=requester_message)

                requested_message = translate_message(
                    llm,
                    f"You are now linked with {requester.name}!",
                    user_language
                )
                await context.bot.send_message(chat_id=current_user.telegram_id, text=requested_message)

                logger.info("Couple linked successfully", couple_id=couple.id)
            elif pending_couple.requested_id == current_user.id:
                # The user is already the requested_id, link again (this might happen on a retry)
                couple = Couple(
                    user1_id=pending_couple.requester_id,
                    user2_id=pending_couple.requested_id
                )
                session.add(couple)

                # Remove the pending request
                session.delete(pending_couple)
                session.commit()

                # Notify both users that they are now linked
                requester_message = translate_message(
                    llm,
                    f"You are now linked with {current_user.name}!",
                    requester.language or 'en'
                )
                await context.bot.send_message(chat_id=requester.telegram_id, text=requester_message)

                requested_message = translate_message(
                    llm,
                    f"You are now linked with {requester.name}!",
                    user_language
                )
                await context.bot.send_message(chat_id=current_user.telegram_id, text=requested_message)

                logger.info("Couple linked successfully", couple_id=couple.id)
            else:
                # The link is valid but it's not meant for this user
                translated_message = translate_message(llm, "This link is not meant for you.", user_language)
                await update.message.reply_text(translated_message)
                logger.warning("Invalid link attempt", telegram_id=update.effective_user.id)
        else:
            translated_message = translate_message(llm, "Invalid or expired link.", user_language)
            await update.message.reply_text(translated_message)
            logger.warning("Expired or invalid link used", telegram_id=update.effective_user.id)
    else:
        translated_message = translate_message(llm, f"Hello {update.effective_user.full_name}! Welcome to ThirdWheeler.", user_language)
        await update.message.reply_text(translated_message)
    
    session.close()

async def add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await rate_limited(update, context):
        return
    
    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == update.effective_user.id).first()
    user_language = update.message.from_user.language_code or 'en'

    if not user:
        translated_message = translate_message(llm, "Please start the bot first using /start.", user_language)
        await update.message.reply_text(translated_message)
        session.close()
        logger.warning("Attempted to get invite link without starting", telegram_id=update.effective_user.id)
        return

    # Check if the user is already part of a couple
    existing_couple = session.query(Couple).filter(
        (Couple.user1_id == user.id) | (Couple.user2_id == user.id)
    ).first()

    if existing_couple:
        translated_message = translate_message(llm, "You are already linked with a partner. Remove that link first with /remove_partner", user_language)
        await update.message.reply_text(translated_message)
        session.close()
        logger.warning("Attempted to get invite link while already linked.", telegram_id=update.effective_user.id)
        return

    # Generate a unique token for the invite link
    token = secrets.token_urlsafe(16)
    pending_couple = PendingCouple(
        requester_id=user.id,
        requested_id=None,
        token=token
    )
    session.add(pending_couple)
    session.commit()

    invite_link = f"https://t.me/{context.bot.username}?start={token}"
    translated_message = translate_message(llm, f"Here is your invite link: {invite_link}\nShare this with your partner to link your chats.", user_language)
    await update.message.reply_text(translated_message)
    logger.info("Invite link generated", user_id=user.id, invite_link=invite_link)
    
    session.close()

async def remove_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await rate_limited(update, context):
        return
    
    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == update.effective_user.id).first()
    user_language = update.message.from_user.language_code or 'en'

    # Check if the user is part of a couple
    couple = session.query(Couple).filter(
        (Couple.user1_id == user.id) | (Couple.user2_id == user.id)
    ).first()

    if not couple:
        translated_message = translate_message(llm, "You are not linked with any partner.", user_language)
        await update.message.reply_text(translated_message)
        session.close()
        logger.warning("Unlink attempt with no partner linked", telegram_id=update.effective_user.id)
        return ConversationHandler.END

    # Ask for confirmation
    translated_message = translate_message(llm, "Are you sure you want to unlink from your partner? Type 'yes' to confirm or 'no' to cancel.", user_language)
    await update.message.reply_text(translated_message)
    session.close()
    return CONFIRM_UNLINK

async def confirm_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == update.effective_user.id).first()
    user_language = update.message.from_user.language_code or 'en'

    try:
        if update.message.text.lower() == 'yes':
            # Start a transaction
            session.begin()

            # Check again within the transaction to prevent race conditions
            couple = session.query(Couple).filter(
                (Couple.user1_id == user.id) | (Couple.user2_id == user.id)
            ).with_for_update().first()

            if couple:
                session.delete(couple)
                session.commit()  # Commit the transaction
                translated_message = translate_message(llm, "You have been unlinked from your partner.", user_language)
                await update.message.reply_text(translated_message)
                logger.info("Partner unlinked successfully", user_id=user.id, partner_id=(couple.user1_id if couple.user2_id == user.id else couple.user2_id))
            else:
                session.rollback()
                translated_message = translate_message(llm, "You are no longer linked with a partner.", user_language)
                await update.message.reply_text(translated_message)
                logger.warning("Unlink attempt failed, no active link found", telegram_id=update.effective_user.id)
        else:
            translated_message = translate_message(llm, "Unlinking process has been cancelled.", user_language)
            await update.message.reply_text(translated_message)
            logger.info("Unlinking process cancelled by user", telegram_id=update.effective_user.id)
    except SQLAlchemyError as e:
        session.rollback()
        translated_message = translate_message(llm, "An error occurred during the unlinking process.", user_language)
        await update.message.reply_text(translated_message)
        logger.error("SQLAlchemy error during unlinking", error=str(e), telegram_id=update.effective_user.id)
    finally:
        session.close()

    return ConversationHandler.END

async def delete_all_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await rate_limited(update, context):
        return
    
    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == update.effective_user.id).first()
    user_language = update.message.from_user.language_code or 'en'

    # Check if the user is part of a couple
    couple = session.query(Couple).filter(
        (Couple.user1_id == user.id) | (Couple.user2_id == user.id)
    ).first()

    if not couple:
        translated_message = translate_message(llm, "You are not linked with any partner. Your data will be deleted.", user_language)
        await update.message.reply_text(translated_message)
        session.delete(user)
        session.commit()
        session.close()
        translated_message = translate_message(llm, "All your data has been deleted.", user_language)
        await update.message.reply_text(translated_message)
        logger.info("User data deleted (no partner linked)", telegram_id=update.effective_user.id)
        return ConversationHandler.END

    # Ask for confirmation
    translated_message = translate_message(llm, "This will delete all your data and your partner's data, and cannot be undone. Type 'yes' to confirm or 'no' to cancel.", user_language)
    await update.message.reply_text(translated_message)
    session.close()
    return CONFIRM_DELETE

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == update.effective_user.id).first()
    user_language = update.message.from_user.language_code or 'en'

    try:
        if update.message.text.lower() == 'yes':
            # Start a transaction
            session.begin()

            # Find and delete the couple entry
            couple = session.query(Couple).filter(
                (Couple.user1_id == user.id) | (Couple.user2_id == user.id)
            ).with_for_update().first()

            if couple:
                partner_id = couple.user1_id if couple.user2_id == user.id else couple.user2_id
                partner = session.query(User).filter(User.id == partner_id).first()

                # Delete all related data
                session.query(Conversation).filter(Conversation.couple_id == couple.id).delete()
                session.query(ScheduledAction).filter(ScheduledAction.couple_id == couple.id).delete()

                session.delete(couple)
                session.delete(user)
                if partner:
                    session.delete(partner)

                session.commit()  # Commit the transaction
                translated_message = translate_message(llm, "All your data and your partner's data have been deleted.", user_language)
                await update.message.reply_text(translated_message)
                logger.info("User and partner data deleted successfully", user_id=user.id, partner_id=partner_id)
            else:
                session.rollback()
                translated_message = translate_message(llm, "You are no longer linked with a partner.", user_language)
                await update.message.reply_text(translated_message)
                logger.warning("Delete data attempt failed, no active link found", telegram_id=update.effective_user.id)
        else:
            translated_message = translate_message(llm, "Data deletion process has been cancelled.", user_language)
            await update.message.reply_text(translated_message)
            logger.info("Data deletion process cancelled by user", telegram_id=update.effective_user.id)
    except SQLAlchemyError as e:
        session.rollback()
        translated_message = translate_message(llm, "An error occurred during the data deletion process.", user_language)
        await update.message.reply_text(translated_message)
        logger.error("SQLAlchemy error during data deletion", error=str(e), telegram_id=update.effective_user.id)
    finally:
        session.close()

    return ConversationHandler.END

async def cancel_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_language = update.message.from_user.language_code or 'en'
    translated_message = translate_message(llm, "Unlinking process has been cancelled.", user_language)
    await update.message.reply_text(translated_message)
    logger.info("Unlinking process cancelled", telegram_id=update.effective_user.id)
    return ConversationHandler.END

async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_language = update.message.from_user.language_code or 'en'
    translated_message = translate_message(llm, "Data deletion process has been cancelled.", user_language)
    await update.message.reply_text(translated_message)
    logger.info("Data deletion process cancelled", telegram_id=update.effective_user.id)
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await rate_limited(update, context):
        return

    user_telegram_id = update.effective_user.id
    message = update.message.text

    session = SessionLocal()
    user = session.query(User).filter(User.telegram_id == user_telegram_id).first()

    if not user:
        user_language = update.message.from_user.language_code or 'en'
        translated_message = translate_message(llm, "Please start the bot first using /start.", user_language)
        await update.message.reply_text(translated_message)
        session.close()
        logger.warning("User attempted to send a message without starting the bot", telegram_id=update.effective_user.id)
        return

    # Fetch the user's history and summary
    user_summary = user.summary if user.summary else ""
    user_history = session.query(Conversation).filter(Conversation.user_id == user.id).count()

    # If the user has no history and no summary, add a hidden introductory message
    if user_history == 0 and not user_summary:
        hidden_intro_message = (
            "This is the user's first interaction. "
            "Introduce yourself as the ThirdWheeler bot, a helpful assistant designed to help couples communicate better. "
            "Explain that you can remind them of things their partner would like to see more or less often, "
            "and help them improve their relationship through better communication. "
            "Explain that they can add their partner by using the /add_partner command followed by their partner's username or via an invite link. "
            "Once they are linked with their partner, you will keep track of their conversations and provide helpful reminders. "
            "To get started, ask the user for some basic information such as their name, birthday, and anything else they would like you to know. "
            "Once this information is gathered, store it in the user's summary so that you don't need to ask again."
        )
        # Add the hidden introductory message to the context
        context_messages = [
            {"role": "system", "content": hidden_intro_message},
            {"role": "user", "content": message}
        ]
    else:
        context_messages = [{"role": "user", "content": message}]

    # Detect user's language from the incoming message (using Telegram API or other methods)
    user_language = update.message.from_user.language_code or 'en'

    # Log the user message
    logger.info("Handling user message", telegram_id=user_telegram_id, message=message)

    # Continue with the regular LLM response
    response = await llm.get_response(context_messages, summary=user_summary, user_language=user_language, functions=[
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
        }
    ])

    # Store the user's conversation history
    conversation = Conversation(
        couple_id=None,  # This is a user-specific interaction, not a couple interaction
        user_id=user.id,
        message=message
    )
    session.add(conversation)
    session.commit()

    # Translate the response to the user's language
    translated_response = llm.translate(response['content'], user_language)

    await update.message.reply_text(translated_response)
    session.close()

    # Log the completion of the message handling
    logger.info("User message handled successfully", telegram_id=user_telegram_id)

def main():
    init_db()
    start_scheduler()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_partner", add_partner))
    application.add_handler(CommandHandler("delete_all_my_data", delete_all_my_data))

    unlink_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('remove_partner', remove_partner)],
        states={
            CONFIRM_UNLINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_unlink)]
        },
        fallbacks=[CommandHandler('cancel', cancel_unlink)]
    )

    delete_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('delete_all_my_data', delete_all_my_data)],
        states={
            CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)]
        },
        fallbacks=[CommandHandler('cancel', cancel_delete)]
    )

    application.add_handler(unlink_conv_handler)
    application.add_handler(delete_conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting bot")
    application.run_polling()
    logger.info("Bot stopped")

if __name__ == "__main__":
    main()
