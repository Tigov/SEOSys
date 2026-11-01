"""Alembic environment: migrations run as the schema owner against DATABASE_OWNER_URL."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from seo_platform.config import settings
from seo_platform.schema import metadata

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline() -> None:
    context.configure(url=settings.database_owner_url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = context.config.attributes.get("url") or settings.database_owner_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_server_default=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
