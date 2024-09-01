import structlog
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from db_utils import get_session, get_current_user, check_user_linked
from utils import get_translated_message, send_message_to_user, rate_limited
from models import User, Couple, PendingCouple, Conversation, ScheduledAction
import os
from scheduler import start_scheduler
from database import init_db
from llm import LLMWrapper
import secrets
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

CONFIRM_UNLINK, CONFIRM_DELETE = range(2)

async def link_users_and_notify(session, context, couple, current_user, requester, user_language):
    session.add(couple)
    session.commit()

    requester_message = get_translated_message(
        llm,
        f"You are now linked with {current_user.name}!",
        requester.language or 'en'
    )
    await context.bot.send_message(chat_id=requester.telegram_id, text=requester_message)

    requested_message = get_translated_message(
        llm,
        f"You are now linked with {requester.name}!",
        user_language
    )
    await context.bot.send_message(chat_id=current_user.telegram_id, text=requested_message)

    logger.info("Couple linked successfully", couple_id=couple.id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        token = context.args[0] if context.args else None
        user_language = update.message.from_user.language_code or 'en'

        logger.info("User started bot", telegram_id=update.effective_user.id)

        current_user = get_current_user(session, update.effective_user.id)
        if not current_user:
            current_user = User(telegram_id=update.effective_user.id, name=update.effective_user.full_name)
            session.add(current_user)
            session.commit()
            logger.info("New user registered", telegram_id=update.effective_user.id)

        if token:
            pending_couple = session.query(PendingCouple).filter(PendingCouple.token == token).first()

            if pending_couple:
                if pending_couple.requested_id is None:
                    pending_couple.requested_id = current_user.id

                    requester = session.query(User).filter(User.id == pending_couple.requester_id).first()
                    if not requester:
                        translated_message = get_translated_message(llm, "Error: Requester not found.", user_language)
                        await update.message.reply_text(translated_message)
                        logger.error("Requester not found", requester_id=pending_couple.requester_id)
                        return

                    couple = Couple(
                        user1_id=pending_couple.requester_id,
                        user2_id=pending_couple.requested_id
                    )

                    session.delete(pending_couple)

                    await link_users_and_notify(session, context, couple, current_user, requester, user_language)
                elif pending_couple.requested_id == current_user.id:
                    couple = Couple(
                        user1_id=pending_couple.requester_id,
                        user2_id=pending_couple.requested_id
                    )
                    session.add(couple)

                    session.delete(pending_couple)

                    await link_users_and_notify(session, context, couple, current_user, requester, user_language)
                else:
                    translated_message = get_translated_message(llm, "This link is not meant for you.", user_language)
                    await update.message.reply_text(translated_message)
                    logger.warning("Invalid link attempt", telegram_id=update.effective_user.id)
            else:
                translated_message = get_translated_message(llm, "Invalid or expired link.", user_language)
                await update.message.reply_text(translated_message)
                logger.warning("Expired or invalid link used", telegram_id=update.effective_user.id)
        else:
            translated_message = get_translated_message(llm, f"Hello {update.effective_user.full_name}! Welcome to ThirdWheeler.", user_language)
            await update.message.reply_text(translated_message)

async def add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        if await rate_limited(update, context, session, llm):
            return
        
        user = get_current_user(session, update.effective_user.id)
        user_language = update.message.from_user.language_code or 'en'

        if not user:
            await send_message_to_user(context.bot, update.effective_user.id, "Please start the bot first using /start.", llm, user_language)
            logger.warning("Attempted to get invite link without starting", telegram_id=update.effective_user.id)
            return

        existing_couple = check_user_linked(session, user.id)

        if existing_couple:
            await send_message_to_user(context.bot, update.effective_user.id, "You are already linked with a partner. Remove that link first with /remove_partner", llm, user_language)
            logger.warning("Attempted to get invite link while already linked.", telegram_id=update.effective_user.id)
            return

        token = secrets.token_urlsafe(16)
        pending_couple = PendingCouple(
            requester_id=user.id,
            requested_id=None,
            token=token
        )
        session.add(pending_couple)

        invite_link = f"https://t.me/{context.bot.username}?start={token}"
        await send_message_to_user(context.bot, update.effective_user.id, f"Here is your invite link: {invite_link}\nShare this with your partner to link your chats.", llm, user_language)
        logger.info("Invite link generated", user_id=user.id, invite_link=invite_link)

async def remove_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        if await rate_limited(update, context, session, llm):
            return
        
        user = get_current_user(session, update.effective_user.id)
        user_language = update.message.from_user.language_code or 'en'

        couple = check_user_linked(session, user.id)

        if not couple:
            await send_message_to_user(context.bot, update.effective_user.id, "You are not linked with any partner.", llm, user_language)
            logger.warning("Unlink attempt with no partner linked", telegram_id=update.effective_user.id)
            return ConversationHandler.END

        await send_message_to_user(context.bot, update.effective_user.id, "Are you sure you want to unlink from your partner? Type 'yes' to confirm or 'no' to cancel.", llm, user_language)
        return CONFIRM_UNLINK

async def confirm_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        user = get_current_user(session, update.effective_user.id)
        user_language = update.message.from_user.language_code or 'en'

        try:
            if update.message.text.lower() == 'yes':
                couple = check_user_linked(session, user.id)

                if couple:
                    session.delete(couple)
                    await send_message_to_user(context.bot, update.effective_user.id, "You have been unlinked from your partner.", llm, user_language)
                    logger.info("Partner unlinked successfully", user_id=user.id, partner_id=(couple.user1_id if couple.user2_id == user.id else couple.user2_id))
                else:
                    await send_message_to_user(context.bot, update.effective_user.id, "You are no longer linked with a partner.", llm, user_language)
                    logger.warning("Unlink attempt failed, no active link found", telegram_id=update.effective_user.id)
            else:
                await send_message_to_user(context.bot, update.effective_user.id, "Unlinking process has been cancelled.", llm, user_language)
                logger.info("Unlinking process cancelled by user", telegram_id=update.effective_user.id)
        except SQLAlchemyError as e:
            await send_message_to_user(context.bot, update.effective_user.id, "An error occurred during the unlinking process.", llm, user_language)
            logger.error("SQLAlchemy error during unlinking", error=str(e), telegram_id=update.effective_user.id)

    return ConversationHandler.END

async def delete_all_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        if await rate_limited(update, context, session, llm):
            return
        
        user = get_current_user(session, update.effective_user.id)
        user_language = update.message.from_user.language_code or 'en'

        couple = check_user_linked(session, user.id)

        if not couple:
            await send_message_to_user(context.bot, update.effective_user.id, "You are not linked with any partner. Your data will be deleted.", llm, user_language)
            session.delete(user)
            logger.info("User data deleted (no partner linked)", telegram_id=update.effective_user.id)
            return ConversationHandler.END

        await send_message_to_user(context.bot, update.effective_user.id, "This will delete all your data and your partner's data, and cannot be undone. Type 'yes' to confirm or 'no' to cancel.", llm, user_language)
        return CONFIRM_DELETE

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        user = get_current_user(session, update.effective_user.id)
        user_language = update.message.from_user.language_code or 'en'

        try:
            if update.message.text.lower() == 'yes':
                couple = check_user_linked(session, user.id)

                if couple:
                    partner_id = couple.user1_id if couple.user2_id == user.id else couple.user2_id
                    partner = get_current_user(session, partner_id)

                    session.query(Conversation).filter(Conversation.couple_id == couple.id).delete()
                    session.query(ScheduledAction).filter(ScheduledAction.couple_id == couple.id).delete()

                    session.delete(couple)
                    session.delete(user)
                    if partner:
                        session.delete(partner)

                    await send_message_to_user(context.bot, update.effective_user.id, "All your data and your partner's data have been deleted.", llm, user_language)
                    logger.info("User and partner data deleted successfully", user_id=user.id, partner_id=partner_id)
                else:
                    await send_message_to_user(context.bot, update.effective_user.id, "You are no longer linked with a partner.", llm, user_language)
                    logger.warning("Delete data attempt failed, no active link found", telegram_id=update.effective_user.id)
            else:
                await send_message_to_user(context.bot, update.effective_user.id, "Data deletion process has been cancelled.", llm, user_language)
                logger.info("Data deletion process cancelled by user", telegram_id=update.effective_user.id)
        except SQLAlchemyError as e:
            await send_message_to_user(context.bot, update.effective_user.id, "An error occurred during the data deletion process.", llm, user_language)
            logger.error("SQLAlchemy error during data deletion", error=str(e), telegram_id=update.effective_user.id)

    return ConversationHandler.END

async def cancel_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_language = update.message.from_user.language_code or 'en'
    translated_message = get_translated_message(llm, "Unlinking process has been cancelled.", user_language)
    await update.message.reply_text(translated_message)
    logger.info("Unlinking process cancelled", telegram_id=update.effective_user.id)
    return ConversationHandler.END

async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_language = update.message.from_user.language_code or 'en'
    translated_message = get_translated_message(llm, "Data deletion process has been cancelled.", user_language)
    await update.message.reply_text(translated_message)
    logger.info("Data deletion process cancelled", telegram_id=update.effective_user.id)
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_session() as session:
        if await rate_limited(update, context, session, llm):
            return

        user_telegram_id = update.effective_user.id
        message = update.message.text

        user = get_current_user(session, user_telegram_id)

        if not user:
            user_language = update.message.from_user.language_code or 'en'
            await send_message_to_user(context.bot, user_telegram_id, "Please start the bot first using /start.", llm, user_language)
            logger.warning("User attempted to send a message without starting the bot", telegram_id=update.effective_user.id)
            return

        user_summary = user.summary if user.summary else ""
        user_history = session.query(Conversation).filter(Conversation.user_id == user.id).count()

        context_messages = []
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
            context_messages.append({"role": "system", "content": hidden_intro_message})

        context_messages.append({"role": "user", "content": message})

        user_language = update.message.from_user.language_code or 'en'

        logger.info("Handling user message", telegram_id=user_telegram_id, message=message)

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

        conversation = Conversation(
            couple_id=None,  # This is a user-specific interaction, not a couple interaction
            user_id=user.id,
            message=message
        )
        session.add(conversation)

        translated_response = llm.translate(response['content'], user_language)

        await update.message.reply_text(translated_response)

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
