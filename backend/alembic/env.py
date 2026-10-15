import os
from alembic import context
from sqlalchemy import create_engine, pool
from app.db import Base, DATABASE_URL
from app import models
config=context.config
target_metadata=Base.metadata
url=DATABASE_URL
def run_migrations_offline():
    context.configure(url=url,target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
def run_migrations_online():
    engine=create_engine(url,poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
if context.is_offline_mode():run_migrations_offline()
else:run_migrations_online()
