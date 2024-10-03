import sqlite3


async def setup_db():
    async with sqlite3.connect("discord_db.db") as conn:
        cursor = conn.cursor()
    cursor.execute(  # Creates a parent table of message ids
        """
        CREATE TABLE IF NOT EXISTS pcpp_msg_ids(
            user_msg_id INT PRIMARY KEY,
            bot_msg_id INT,
            link_id INT,
            PRIMARY KEY (user_msg_id, bot_msg_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS links(
            id
        )
        """
    )
