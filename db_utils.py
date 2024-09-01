# db_utils.py
from sqlalchemy.orm import Session
from contextlib import contextmanager
from database import SessionLocal
from models import User, Couple
from sqlalchemy.exc import SQLAlchemyError

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
