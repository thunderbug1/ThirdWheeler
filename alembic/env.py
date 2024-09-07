# alembic/env.py

from logging.config import fileConfig
import sys
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from settings import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
db_url = f"postgresql://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"

# Set the SQLAlchemy URL in Alembic config dynamically
config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# Since your entire directory is mounted as /app, 
# add /app to the sys.path to allow imports from the root directory
sys.path.insert(0, '/app')

# Import your models here
from models import Base

# Set the metadata object for autogenerate support
target_metadata = Base.metadata

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
