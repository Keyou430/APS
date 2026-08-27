from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.database import Base
from app.models import *  # noqa: F403

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """Ignore only dialect/legacy representations with an equivalent ORM object."""
    if type_ == "unique_constraint" and reflected and compare_to is None:
        table = getattr(object_, "table", None)
        metadata_table = target_metadata.tables.get(getattr(table, "name", ""))
        columns = tuple(column.name for column in getattr(object_, "columns", ()))
        if metadata_table is not None and any(
            index.unique and tuple(column.name for column in index.columns) == columns
            for index in metadata_table.indexes
        ):
            return False
    if (
        type_ == "index"
        and not reflected
        and context.get_context().dialect.name == "sqlite"
        and object_.info.get("skip_autogenerate_sqlite")
    ):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_async_migrations())
