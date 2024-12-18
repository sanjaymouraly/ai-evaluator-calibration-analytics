"""Alembic environment configuration."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import engine_from_config, pool

# Import all models so autogenerate can see them
import app.models  # noqa: F401
from alembic import context
from app.config import settings
from app.db import Base

config = context.config
if settings.database_url:
    config.set_main_option("sqlalchemy.url", settings.database_url)

logger = logging.getLogger("alembic")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Any) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
