from sqlalchemy import BigInteger, Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    telegram_id = Column(BigInteger, primary_key=True, unique=True, nullable=False)
    name = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    language = Column(String, nullable=True)

    conversations = relationship('Conversation', back_populates='user')
    scheduled_actions = relationship('ScheduledAction', back_populates='user')

class Couple(Base):
    __tablename__ = 'couples'
    
    id = Column(BigInteger, primary_key=True)
    user1_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    user2_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    
    user1 = relationship('User', foreign_keys=[user1_id])
    user2 = relationship('User', foreign_keys=[user2_id])
    conversations = relationship('Conversation', back_populates='couple')

class Conversation(Base):
    __tablename__ = 'conversations'
    
    id = Column(BigInteger, primary_key=True)
    couple_id = Column(BigInteger, ForeignKey('couples.id'))
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    couple = relationship('Couple', back_populates='conversations')
    user = relationship('User', back_populates='conversations')

class ScheduledAction(Base):
    __tablename__ = 'scheduled_actions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    description = Column(Text, nullable=False)  # Description of what will be done for the LLM
    trigger_time = Column(DateTime, nullable=False)  # When the action should be triggered
    is_active = Column(Boolean, default=True)  # Mark if the action is active

    user = relationship("User", back_populates="scheduled_actions")

class UserActionLog(Base):
    __tablename__ = 'user_action_logs'
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class PendingCouple(Base):
    __tablename__ = 'pending_couples'

    id = Column(BigInteger, primary_key=True)
    requester_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    requested_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=True)  # Make nullable
    token = Column(String, unique=True, nullable=False)

    requester = relationship('User', foreign_keys=[requester_id])
    requested = relationship('User', foreign_keys=[requested_id])

class Translation(Base):
    __tablename__ = 'translations'

    id = Column(BigInteger, primary_key=True)
    original_text = Column(Text, nullable=False)
    target_language = Column(String, nullable=False)
    translated_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Translation(original_text='{self.original_text}', target_language='{self.target_language}', translated_text='{self.translated_text}')>"
