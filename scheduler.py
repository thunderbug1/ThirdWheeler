# scheduler.py

from apscheduler.schedulers.background import BackgroundScheduler
import structlog
from database import SessionLocal
from models import ScheduledAction
from datetime import datetime

logger = structlog.get_logger()

def trigger_action(action_id):
    session = SessionLocal()
    action = session.query(ScheduledAction).filter(ScheduledAction.id == action_id, ScheduledAction.is_active == True).first()

    if action:
        # Here you can define what happens when an action is triggered
        logger.info("Triggering action", action_id=action_id, action=action.action)
        # After triggering, deactivate the action
        action.is_active = False
        session.commit()
    else:
        logger.warning("Scheduled action not found or already inactive", action_id=action_id)

    session.close()

def start_scheduler():
    scheduler = BackgroundScheduler()
    
    # Fetch scheduled actions from the database and schedule them
    session = SessionLocal()
    actions = session.query(ScheduledAction).filter(ScheduledAction.is_active == True, ScheduledAction.trigger_time > datetime.utcnow()).all()
    
    for action in actions:
        scheduler.add_job(trigger_action, 'date', run_date=action.trigger_time, args=[action.id])
        logger.info("Scheduled action", action_id=action.id, trigger_time=action.trigger_time)
    
    scheduler.start()

    logger.info("Scheduler started")
