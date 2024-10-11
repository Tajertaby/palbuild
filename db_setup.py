import aiosqlite
import asyncio
import logging

SQL_LOG = logging.getLogger("sql")


class Tables:
    def __init__(self, sql: str, *args) -> None:
        self.sql = sql
        self.args = args

    async def cursor_update_db(self) -> None:
        """
        Executes queries that updates the database.
        """
        for attempt in range(3, 0, -1):
            try:
                await self.cursor.execute(self.sql, self.args)
                await self.conn.commit()  # Commit changes after executing
                SQL_LOG.info("Successfully executed: %s", self.sql)
                break  # Stops the loop if successful
            except aiosqlite.Error as e:
                SQL_LOG.error(
                    "SQL execution error: %s | Attempts left: %s", e, attempt - 1
                )
                if attempt == 1:
                    raise e  # Re-raise the exception after the last attempt

    @classmethod
    def db_variables(
        cls, conn: aiosqlite.Connection, cursor: aiosqlite.Connection.cursor
    ) -> None:
        cls.conn = conn
        cls.cursor = cursor


class TableGroup:
    """
    Helper class to group tables
    """

    @staticmethod
    async def pcpp_tables():
        await Tables(
            """
            CREATE TABLE IF NOT EXISTS pcpp_message_ids(
                user_msg_id INT,
                bot_msg_id INT,
                content_id INT UNIQUE,
                PRIMARY KEY (user_msg_id, bot_msg_id)
            )
            """
        ).cursor_update_db()

        await Tables(
            """
            CREATE TABLE IF NOT EXISTS pcpp_contents(
                id INT PRIMARY KEY,
                        pcpp VARCHAR(4000),
                FOREIGN KEY (id) REFERENCES pcpp_message_ids(content_id)
            )
            """
        ).cursor_update_db()


async def setup_db() -> bool:
    """
    Sets up the database by creating necessary tables.
    If any table setup fails, it returns False.
    """
    SQL_LOG.info("Setting up the database")
    async with aiosqlite.connect("discord_db.db") as conn:
        async with conn.cursor() as cursor:
            Tables.db_variables(conn, cursor)  # Set these as class variables

            # Create tables
            try:
                await TableGroup.pcpp_tables()
            except aiosqlite.Error as e:
                SQL_LOG.error("Failed to set up the database: %s", e)
                return False  # This will be passed on the kill the bot if the tables are not setup
            SQL_LOG.info("Database setup completed successfully.")
            return True


if __name__ == "__main__":
    asyncio.run(setup_db())
