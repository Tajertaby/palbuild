import datetime
import textwrap
from typing import List, Tuple, Optional, Union

import discord
from discord.ext import commands
from aiosqlite import OperationalError, DatabaseError

from db_setup import SQL_LOG, Database
from .pcpp_utility import PCPPUtility, ILOVEPCS_BLUE
from .pcpp_interaction_handler import PCPPInteractionHandler
from .pcpp_ui_components import PCPPButton, PCPPMenu


class HandleLinks:
    @staticmethod
    def handle_valid_links(
        channel_id: int, message_id: int, timestamp: int, pcpp_urls: list[str]
    ) -> Tuple[discord.Embed, discord.ui.View]:
        """
        Handle valid PCPartPicker links by creating appropriate UI components.
        """
        timestamp = str(timestamp.timestamp()).replace(".", "")
        preview_embed = PCPPMessage.create_preview_embed(pcpp_urls)
        view = discord.ui.View(timeout=None)

        if len(pcpp_urls) == 1:
            button = PCPPButton(channel_id, message_id, timestamp, pcpp_urls[0])
            view.add_item(button)
        else:
            options = PCPPMenu.generate_options(pcpp_urls)
            menu = PCPPMenu(channel_id, message_id, timestamp, options)
            view.add_item(menu)

        return preview_embed, view

    @staticmethod
    @lru_cache(maxsize=1)
    def handle_invalid_links() -> discord.Embed:
        """
        Handle invalid PCPartPicker links by sending an error message.
        """
        error_embed = discord.Embed(
            title=(
                "**One or more of your PCPartPicker link(s) is invalid. "
                "These links only make the associated list viewable to you. "
                "Please refer to the image below for guidance.**"
            ),
            color=ILOVEPCS_BLUE,
        )
        error_embed.set_image(url="https://i.imgur.com/O0TFvRc.jpeg")
        return error_embed


class PCPPMessage:
    """
    Handles message-related operations for PCPartPicker link previews.
    """

    @staticmethod
    @alru_cache(maxsize=1024)
    async def extract_bot_msg_using_user_id(
        bot: commands.Bot, bot_message_ids: Tuple[int, ...], channel_id: int
    ) -> Tuple[discord.Message, ...]:
        """
        Fetch bot messages from a specific channel using their message IDs.
        """
        channel = bot.get_channel(channel_id)
        bot_messages = [
            await channel.fetch_message(message_id) for message_id in bot_message_ids
        ]
        return tuple(bot_messages)

    @staticmethod
    async def insert_bot_msg_ids(
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
            PCPPCog.pcpp_user_message_count >= PCPPCog.MAX_USER_MESSAGE_ID_COUNT
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
                PCPPCog.pcpp_user_message_count -= 1

        # Insert new message IDs if table has space
        if PCPPCog.pcpp_user_message_count <= PCPPCog.MAX_USER_MESSAGE_ID_COUNT - 1:
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
                PCPPCog.pcpp_user_message_count += 1
                await Database.conn.commit()

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

    @staticmethod
    async def edit_pcpp_preview(
        bot_message: discord.Message,
        channel_id: int,
        user_msg_id: int,
        timestamp: datetime.datetime,
        pcpp_urls: List[str],
    ) -> None:
        """
        Edit an existing PCPP preview message with new embed and view.
        """
        preview_embed, view = HandleLinks.handle_valid_links(
            channel_id, user_msg_id, timestamp, pcpp_urls
        )
        await bot_message.edit(embed=preview_embed, view=view)

    @staticmethod
    async def edit_invalid_link(bot_message: discord.Message) -> None:
        """
        Edit a message to show an invalid link error.
        """
        error_embed = HandleLinks.handle_invalid_links()
        await bot_message.edit(embed=error_embed)

    @staticmethod
    async def placeholder_message(
        bot_message: discord.Message,
        no_pcpp_preview: bool = False,
        no_invalid_links: bool = False,
        edit: bool = False,
    ) -> Optional[discord.Message]:
        """
        Create or edit a placeholder message for various scenarios.
        """
        if no_pcpp_preview:
            embed = discord.Embed(
                title="No PCPP previews available.", color=ILOVEPCS_BLUE
            )
        elif no_invalid_links:
            embed = discord.Embed(
                title="No invalid PCPP links detected.", color=ILOVEPCS_BLUE
            )
        else:
            DISCORD_LOG.error("Failed to get a placeholder message.")
            return None

        if not edit:
            return await bot_message.reply(embed=embed)
        else:
            return await bot_message.edit(embed=embed, view=None)

    @staticmethod
    async def delete_message(
        user_msg_id: int, bot_messages: Tuple[discord.Message, ...]
    ) -> None:
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

            # Delete all associated bot messages
            for bot_message in bot_messages:
                await bot_message.delete()
        except (OperationalError, DatabaseError) as db_error:
            SQL_LOG.exception(
                "Cannot delete the row containing user id or delete the message: %s. Error: %s",
                user_msg_id,
                db_error,
            )
        else:
            PCPPCog.pcpp_user_message_count -= 1

    @staticmethod
    async def edit_pcpp_message(
        bot_messages: Tuple[discord.Message, discord.Message],
        message: discord.Message,
        pcpp_bools: Tuple[List[str], Union[str, bool]],
        before_pcpp_bools: Tuple[List[str], Union[str, bool]],
    ) -> Optional[discord.Message]:
        """
        Edit PCPP preview messages based on changes in message content.
        """
        pcpp_urls, invalid_link = pcpp_bools
        pcpp_message, invalid_link_message = bot_messages

        # No URLs or invalid links, no action needed
        if not any((pcpp_urls, invalid_link)):
            return None

        before_pcpp_urls, before_invalid_link = before_pcpp_bools

        # Various conditions for editing messages
        if (all([pcpp_urls, not invalid_link]) and all(before_pcpp_bools)) or (
            all([pcpp_urls, not invalid_link, before_invalid_link])
        ):
            await PCPPMessage.edit_pcpp_preview(
                pcpp_message,
                message.channel.id,
                message.id,
                message.edited_at,
                pcpp_urls,
            )
            await PCPPMessage.placeholder_message(
                invalid_link_message, no_invalid_links=True, edit=True
            )

        elif all([not pcpp_urls, invalid_link]) and all(before_pcpp_bools):
            await PCPPMessage.placeholder_message(
                pcpp_message, no_pcpp_preview=True, edit=True
            )

        elif (
            (all([pcpp_urls, invalid_link]) and all(before_pcpp_bools))
            or (all([pcpp_urls, not invalid_link, before_pcpp_urls]))
            or (all([pcpp_urls, invalid_link, before_invalid_link]))
        ):
            await PCPPMessage.edit_pcpp_preview(
                pcpp_message,
                message.channel.id,
                message.id,
                message.edited_at,
                pcpp_urls,
            )

        elif all([pcpp_urls, invalid_link, before_pcpp_urls]):
            await PCPPMessage.edit_pcpp_preview(
                pcpp_message,
                message.channel.id,
                message.id,
                message.edited_at,
                pcpp_urls,
            )
            await PCPPMessage.edit_invalid_link(invalid_link_message)

        elif all([not pcpp_urls, invalid_link, before_pcpp_urls]):
            await PCPPMessage.placeholder_message(
                pcpp_message, no_pcpp_preview=True, edit=True
            )
            await PCPPMessage.edit_invalid_link(invalid_link_message)

        elif all([not pcpp_urls, invalid_link, before_invalid_link]):
            return None

    @staticmethod
    async def prepare_new_message(
        message: discord.Message,
        pcpp_bools: Tuple[List[str], Union[str, bool]],
    ) -> None:
        """
        Prepare and send bot messages for a new user message with PCPP links.
        """
        pcpp_message: Optional[discord.Message] = None
        invalid_bot_message: Optional[discord.Message] = None
        pcpp_urls, invalid_link = pcpp_bools

        # No URLs or invalid links, no action needed
        if not any((pcpp_urls, invalid_link)):
            return
        else:
            await message.edit(suppress=True)

        # Handle PCPP URLs preview
        if pcpp_urls:
            preview_embed, view = HandleLinks.handle_valid_links(
                message.channel.id, message.id, message.created_at, pcpp_urls
            )
            pcpp_message = await message.reply(embed=preview_embed, view=view)
        elif not pcpp_urls:
            pcpp_message = await PCPPMessage.placeholder_message(
                message, no_pcpp_preview=True
            )

        # Handle invalid links
        if invalid_link:
            error_embed = HandleLinks.handle_invalid_links()
            invalid_bot_message = await message.reply(embed=error_embed)
        elif not invalid_link:
            invalid_bot_message = await PCPPMessage.placeholder_message(
                message, no_invalid_links=True
            )

        # Insert message IDs into database
        await PCPPMessage.insert_bot_msg_ids(
            pcpp_message.id,
            invalid_bot_message.id,
            message.id,
            message.channel.id,
        )

    @staticmethod
    def create_preview_embed(urls: List[str]) -> discord.Embed:
        """
        Create an embed for PCPartPicker list previews.
        """
        url_list = "\n".join(urls)
        return discord.Embed(
            description=textwrap.dedent(
                f"These are the previews for the following links:\n{url_list}"
            ),
            color=ILOVEPCS_BLUE,
        )
