import asyncio

from app.database import SessionLocal
from app.seed import seed_database


async def main() -> None:
    async with SessionLocal() as session:
        await seed_database(session)
    print("Seed complete: default roles and admin account are ready.")


if __name__ == "__main__":
    asyncio.run(main())
