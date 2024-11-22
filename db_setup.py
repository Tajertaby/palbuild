import logging
import os
from textwrap import dedent
from typing import Union, List, Tuple

import aiosqlite

SQL_LOG = logging.getLogger("sql")


class Database:
    def __init__(self, sql: str, params: tuple = None) -> None:
        self.sql = dedent(sql)  # Used to easily check which type of SQL query
        self.params = params

    async def run_query(self, auto_commit=True) -> Union[int, List[Tuple]]:
        """
        Executes queries that updates the database.
        """
        for attempt in range(3, 0, -1):
            try:
                await self.cursor.execute(self.sql, self.params)
                if not self.sql.startswith("SELECT") and auto_commit:
                    await self.conn.commit()
                    SQL_LOG.info("Successfully executed and commited: %s", self.sql)
                    return self.cursor.rowcount # Returns no of rows affected
                elif self.sql.startswith("SELECT"):
                    rows = await self.cursor.fetchall()
                    SQL_LOG.info("Successfully executed: %s", self.sql)
                    return rows
                else: # This happens when auto commit is false
                    SQL_LOG.info("Successfully executed: %s", self.sql)
                    return self.cursor.rowcount
            except aiosqlite.Error as e:
                await self.conn.rollback()
                SQL_LOG.exception(
                    "SQL execution error: %s | Attempts left: %s", e, attempt - 1
                )
                if attempt == 1:
                    raise e # Re-raise the exception after the last attempt
            else:
                break # Stops the loop if successful

    @classmethod
    async def count_rows(cls, table_name) -> int:
        try:
            count_rows = await cls(f"SELECT DISTINCT Count(*) FROM {table_name};").run_query()
            return int(count_rows[0][0]) # Convert from list of tuples to int
        except (aiosqlite.OperationalError, aiosqlite.DatabaseError) as e:
            SQL_LOG.exception("Failed to count rows: %s", e)

    @classmethod
    async def setup_db(cls) -> bool:
        """
        Sets up the database by creating necessary tables.
        If any table setup fails, it returns False.
        """
        SQL_LOG.info("Setting up the database")
        try:
            cls.conn: aiosqlite.Connection = await aiosqlite.connect("discord_db.db")
            cls.cursor: aiosqlite.Connection.cursor = await cls.conn.cursor()
            await TableGroup.pcpp_tables()  # Create tables
        except (aiosqlite.OperationalError, aiosqlite.DatabaseError) as e:
            SQL_LOG.error("Failed to set up the database: %s", e)
            await Database.conn.rollback()
            return False  # This will be passed on the kill the bot if the tables are not setup
        else:
            SQL_LOG.info("Database setup completed successfully.")
            return True

    @classmethod
    async def close_db(cls) -> None:
        """
        Ensure the cursor and connection are closed
        """
        if cls.cursor:
            await cls.cursor.close()  # Close cursor if it was opened
        if cls.conn:
            await cls.conn.close()  # Close connection if it was opened


class TableGroup:
    """
    Helper class to group tables
    """

    @staticmethod
    async def pcpp_tables():
        await Database(
            """
            CREATE TABLE IF NOT EXISTS pcpp_message_ids(
                user_msg_id INT,
                pcpp_bot_msg_id INT,
                invalid_msg_id INT,
                channel_id INT,
                pcpp_preview BOOLEAN,
                invalid_link BOOLEAN,
                PRIMARY KEY (user_msg_id)
            );
            """
        ).run_query()
