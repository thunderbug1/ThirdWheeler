# db_utils.py
from sqlalchemy.orm import Session
from contextlib import contextmanager
from database import SessionLocal
from models import User, Couple
from sqlalchemy.exc import SQLAlchemyError
from models import ScheduledAction
from sqlalchemy.orm import Session
from datetime import datetime
from dateutil import parser

@contextmanager
def get_session() -> Session:
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        raise e
    finally:
        session.close()

def get_current_user(session: Session, telegram_id: int) -> User:
    return session.query(User).filter(User.telegram_id == telegram_id).first()

def check_user_linked(session: Session, user_id: int) -> Couple:
    return session.query(Couple).filter(
        (Couple.user1_id == user_id) | (Couple.user2_id == user_id)
    ).first()

def get_scheduled_actions_for_user(session: Session, user_id: int):
    return session.query(ScheduledAction).filter(
        ScheduledAction.user_id == user_id,
        ScheduledAction.is_active == True
    ).all()

def add_scheduled_action(session: Session, user_id: int, description: str, trigger_time: str):
    # Parse the trigger_time string into a datetime object
    trigger_time_dt = parser.parse(trigger_time)
    
    action = ScheduledAction(
        user_id=user_id,
        description=description,
        trigger_time=trigger_time_dt,
        is_active=True
    )
    session.add(action)
    session.commit()
    return action.id

def delete_scheduled_action(session: Session, action_id: int):
    action = session.query(ScheduledAction).filter(ScheduledAction.id == action_id).first()
    if action:
        session.delete(action)
        session.commit()
