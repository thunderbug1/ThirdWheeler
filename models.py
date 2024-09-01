from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    summary = Column(Text, nullable=True)

    conversations = relationship('Conversation', back_populates='user')

class Couple(Base):
    __tablename__ = 'couples'
    
    id = Column(Integer, primary_key=True)
    user1_id = Column(Integer, ForeignKey('users.id'))
    user2_id = Column(Integer, ForeignKey('users.id'))
    
    user1 = relationship('User', foreign_keys=[user1_id])
    user2 = relationship('User', foreign_keys=[user2_id])
    conversations = relationship('Conversation', back_populates='couple')

class Conversation(Base):
    __tablename__ = 'conversations'
    
    id = Column(Integer, primary_key=True)
    couple_id = Column(Integer, ForeignKey('couples.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    couple = relationship('Couple', back_populates='conversations')
    user = relationship('User')

class ScheduledAction(Base):
    __tablename__ = 'scheduled_actions'
    
    id = Column(Integer, primary_key=True)
    couple_id = Column(Integer, ForeignKey('couples.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    action = Column(String, nullable=False)
    trigger_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)

    couple = relationship('Couple')
    user = relationship('User')

class UserActionLog(Base):
    __tablename__ = 'user_action_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class PendingCouple(Base):
    __tablename__ = 'pending_couples'

    id = Column(Integer, primary_key=True)
    requester_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    requested_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # Make nullable
    token = Column(String, unique=True, nullable=False)

    requester = relationship('User', foreign_keys=[requester_id])
    requested = relationship('User', foreign_keys=[requested_id])

class Translation(Base):
    __tablename__ = 'translations'

    id = Column(Integer, primary_key=True)
    original_text = Column(Text, nullable=False)
    target_language = Column(String, nullable=False)
    translated_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Translation(original_text='{self.original_text}', target_language='{self.target_language}', translated_text='{self.translated_text}')>"
