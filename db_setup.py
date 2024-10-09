import aiosqlite
import asyncio
import threading


class Tables:
    def __init__(self, sql: str, *args) -> None:
        self.sql = sql
        self.args = args

    async def cursor_update_db(self) -> None:
        for attempt in range (3,0,-1):
            try:
                await self.cursor.execute(self.sql, self.args)
                await self.conn.commit()  # Commit changes after executing
                break # Stops the loop if successful
            except aiosqlite.Error as e:
                print(f"An error occurred: {e} \n {attempt-1} attempts left")  # Handle errors appropriately
    
    @classmethod
    def db_variables(cls, conn, cursor):
        cls.conn = conn
        cls.cursor = cursor

class TableGroup: # Helper class to group tables for organisation
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



async def setup_db() -> None:
    print(f"Setting up database in thread: {threading.get_ident()}")
    async with aiosqlite.connect("discord_db.db") as conn:
        async with conn.cursor() as cursor:
            Tables.db_variables(conn, cursor) # Set these as class variables

            # Create tables
            try:
                await TableGroup.pcpp_tables()
            except aiosqlite.Error:
                return False # This will be passed on the kill the bot if the tables are not setup
            return True
                    

if __name__ == "__main__":
    print(f"Main thread: {threading.get_ident()}")
    asyncio.run(setup_db())
