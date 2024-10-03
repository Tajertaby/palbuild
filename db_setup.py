import sqlite3

PCPP_MSG_IDS = {  # Used to reference in other files
    "table_name": "pcpp_message_ids",
    "user_msg_id": "user_msg_id",
    "bot_msg_id": "bot_msg_id",
    "content_id": "content_id",
}


async def setup_db():
    async with sqlite3.connect("discord_db.db") as conn:
        cursor = conn.cursor()
    cursor.execute(  # Creates a parent table of message ids
        """
        CREATE TABLE IF NOT EXISTS ?(
            ? INT,
            ? INT,
            ? INT UNIQUE,
            PRIMARY KEY (user_msg_id, bot_msg_id)
        )
        """,
        tuple(PCPP_MSG_IDS[key] for key in PCPP_MSG_IDS),
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pcpp_contents(
            id INT PRIMARY KEY,
            pcpp VARCHAR(4000)
            FOREIGN KEY id REFERENCES ?.
        )
        """
    )
