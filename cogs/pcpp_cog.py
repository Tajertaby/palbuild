import re
from functools import lru_cache
from typing import List, Optional, Tuple

import discord
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from discord.ext import commands
from aiosqlite import OperationalError, DatabaseError
from db_setup import Database
from pcpp_message_handler import PCPPMessage, HandleLinks
from pcpp_utility import PCPPUtility, INVALID_URL_PATTERN, ILOVEPCS_BLUE
from pcpp_ui_components import PCPPButton, PCPPMenu


class PCPPCog(commands.Cog):
    """
    Cog for handling PCPartPicker list previews in Discord.
    """

    MAX_USER_MESSAGE_ID_COUNT: int = 1024
    pcpp_user_message_count: int

    def __init__(self, bot: commands.Bot):
        """
        Initialize the PCPPCog with the Discord bot instance.
        """
        self.bot: commands.Bot = bot

    @classmethod
    async def find_row_count(cls) -> None:
        """
        Asynchronously count the rows in the PCPP message IDs database table.
        """
        cls.pcpp_user_message_count = await Database.count_rows("pcpp_message_ids")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Listen for messages containing PCPartPicker URLs and handle them.
        """
        if message.author == self.bot.user:
            return

        # This list can contain the PCPP list or the link invalid response.
        pcpp_urls: List[str]
        invalid_link: Optional[str]
        pcpp_urls, invalid_link = self.pcpp_regex_search(message.content)
        await PCPPMessage.prepare_new_message(
            message, pcpp_bools=(pcpp_urls, invalid_link)
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """
        Handle message edit events for PCPartPicker URLs.
        """
        if before.content == after.content:
            return

        pcpp_urls: List[str]
        invalid_link: Optional[str]
        pcpp_urls, invalid_link = self.pcpp_regex_search(after.content)

        before_pcpp_urls: List[str]
        before_invalid_link: Optional[str]
        before_pcpp_urls, before_invalid_link = self.pcpp_regex_search(before.content)

        bot_msg_ids: List[int]
        channel_id_to_fetch: Optional[int]
        bot_msg_ids, channel_id_to_fetch = await PCPPMessage.find_bot_msg_ids(after.id)

        if not all([all(bot_msg_ids), channel_id_to_fetch]):
            return  # Cannot edit message without a valid bot/channel id

        if any([before_pcpp_urls, before_invalid_link]) and any(
            [pcpp_urls, invalid_link]
        ):
            # This list can contain the PCPP list or the link invalid response.
            if (before_pcpp_urls, before_invalid_link) == (pcpp_urls, invalid_link):
                # This checks if the lists found in dict are all still in new message
                return
            else:
                bot_messages = await PCPPMessage.extract_bot_msg_using_user_id(
                    self.bot, bot_msg_ids, channel_id_to_fetch
                )
                await PCPPMessage.edit_pcpp_message(
                    bot_messages,
                    after,
                    pcpp_bools=(pcpp_urls, invalid_link),
                    before_pcpp_bools=(before_pcpp_urls, before_invalid_link),
                )
        elif any([before_pcpp_urls, before_invalid_link]) and not any(
            [pcpp_urls, invalid_link]
        ):
            bot_messages = await PCPPMessage.extract_bot_msg_using_user_id(
                self.bot, bot_msg_ids, channel_id_to_fetch
            )
            await PCPPMessage.delete_message(after.id, bot_messages)
        else:
            return

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """
        Handle message deletion events for PCPartPicker URLs.
        """
        pcpp_urls: List[str]
        invalid_link: Optional[str]
        pcpp_urls, invalid_link = self.pcpp_regex_search(message.content)

        if any([pcpp_urls, invalid_link]):
            bot_msg_ids: List[int]
            channel_id_to_fetch: Optional[int]
            bot_msg_ids, channel_id_to_fetch = await PCPPMessage.find_bot_msg_ids(
                message.id
            )
            bot_messages = await PCPPMessage.extract_bot_msg_using_user_id(
                self.bot, bot_msg_ids, channel_id_to_fetch
            )
            await PCPPMessage.delete_message(message.id, bot_messages)

    @lru_cache(maxsize=1024)
    def pcpp_regex_search(
        self, message_content: str
    ) -> Tuple[List[str], Optional[str]]:
        """
        Search for PCPartPicker URLs and invalid links in a message.
        """
        pcpp_urls = PCPPUtility.extract_unique_pcpp_urls(message_content)
        invalid_link = INVALID_URL_PATTERN.search(message_content)
        if invalid_link:
            invalid_link = invalid_link.group()
        return pcpp_urls, invalid_link


async def setup(bot: commands.Bot) -> None:
    """
    Setup function to add the cog to the bot.
    """
    bot.add_dynamic_items(PCPPButton, PCPPMenu)
    cog_instance = PCPPCog(bot)
    await bot.add_cog(cog_instance)
    await PCPPCog.find_row_count()
