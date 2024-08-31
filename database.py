# database.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/thirdwheeler")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    # Create all tables
    Base.metadata.create_all(bind=engine)
