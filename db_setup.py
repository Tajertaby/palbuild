import aiosqlite

class Tables:
    def __init__(self, sql: str, *args) -> None:
        self.sql = sql
        self.args = args

    async def cursor_execute(self) -> None:
        self.cursor.execute(self.sql, self.args)

    @classmethod
    def set_cursor(cls, cursor):
        cls.cursor = cursor
        
async def setup_db() -> None:
    async with aiosqlite.connect("discord_db.db") as conn:
        Tables.set_cursor(conn.cursor())

    Tables(
        """
        CREATE TABLE IF NOT EXISTS pcpp_message_ids(
            user_msg_id INT,
            bot_msg_id INT,
            content_id INT UNIQUE,
            PRIMARY KEY (user_msg_id, bot_msg_id)
        )
        """
    ).cursor_execute()

    Tables(
        """
        CREATE TABLE IF NOT EXISTS pcpp_contents(
            id INT PRIMARY KEY,
            pcpp VARCHAR(4000),
            FOREIGN KEY id REFERENCES pcpp_message_ids(content_id)
        )
        """
    ).cursor_execute()
