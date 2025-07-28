from aiosqlite import Error, DatabaseError, OperationalError
from async_lru import alru_cache
from db_setup import SQL_LOG, Database
from typing import Tuple


class PCPPSQL:

    MAX_USER_MESSAGE_ID_COUNT: int = 1024
    pcpp_user_message_count: int

    @classmethod
    async def insert_bot_msg_ids(
        cls,
        pcpp_message_id: int,
        invalid_bot_message_id: int,
        user_message_id: int,
        channel_id: int,
    ) -> None:
        """
        Insert bot message IDs into the database, managing table size.
        """
        # Ensure table doesn't exceed maximum row count
        if (
            cls.pcpp_user_message_count >= cls.MAX_USER_MESSAGE_ID_COUNT
        ):  # Table cannot exceed 1000 rows
            try:
                await Database(
                    """
                    DELETE FROM pcpp_message_ids
                    WHERE user_msg_id = (SELECT user_msg_id FROM pcpp_message_ids LIMIT 1);
                    """
                ).run_query()
            except (OperationalError, DatabaseError) as db_error:
                SQL_LOG.exception("Cannot delete the row: %s", db_error)
            else:
                cls.pcpp_user_message_count -= 1

        # Insert new message IDs if table has space
        if cls.pcpp_user_message_count <= cls.MAX_USER_MESSAGE_ID_COUNT - 1:
            try:
                await Database(
                    """
                    INSERT INTO pcpp_message_ids(user_msg_id, pcpp_bot_msg_id, invalid_msg_id, channel_id)
                    VALUES(?, ?, ?, ?);
                    """,
                    (
                        user_message_id,
                        pcpp_message_id,
                        invalid_bot_message_id,
                        channel_id,
                    ),  # First ID - User, Second ID - Bot
                ).run_query(auto_commit=False)
            except (OperationalError, DatabaseError) as db_error:
                SQL_LOG.exception(
                    "Failed to insert the following data, rolling back.\n"
                    "User Message ID: %s\n"
                    "PCPP Preview Message ID: %s\n"
                    "Invalid Message ID: %s\n"
                    "Channel ID: %s\n"
                    "Error: %s",
                    user_message_id,
                    pcpp_message_id,
                    invalid_bot_message_id,
                    channel_id,
                    db_error,
                )
            else:
                cls.pcpp_user_message_count += 1
                await Database.conn.commit()

    @classmethod
    async def delete_msg_ids(
        cls, user_msg_id) -> None:
        """
        Delete database record and associated bot messages.
        """
        try:
            # Remove database entry for the user message
            await Database(
                """
                DELETE FROM pcpp_message_ids
                WHERE user_msg_id = ?;
                """,
                (user_msg_id,),
            ).run_query()

        except (OperationalError, DatabaseError) as db_error:
            SQL_LOG.exception(
                "Cannot delete the row containing user id: %s. Error: %s",
                user_msg_id,
                db_error,
            )
            raise

    @staticmethod
    @alru_cache(maxsize=1024)
    async def find_bot_msg_ids(user_msg_id: int) -> Tuple[Tuple[int, int], int]:
        """
        Retrieve bot message IDs and channel ID associated with a user message.
        """
        try:
            # Fetch bot message IDs and channel ID from database
            database_result = await Database(
                """
                SELECT pcpp_bot_msg_id, invalid_msg_id, channel_id FROM pcpp_message_ids
                WHERE user_msg_id = ?;
                """,
                (user_msg_id,),
            ).run_query()
            pcpp_bot_msg_id, invalid_msg_id, channel_id = database_result[0]
        except (OperationalError, DatabaseError) as db_error:
            SQL_LOG.exception(
                "Failed to search the corresponding bot message id, channel_id and booleans from the user message: %s\n Error: %s",
                user_msg_id,
                db_error,
            )
            raise Error from db_error
        return (pcpp_bot_msg_id, invalid_msg_id), channel_id
