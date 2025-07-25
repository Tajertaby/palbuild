import re
from typing import Tuple

import discord
from async_lru import alru_cache

from .pcpp_utility import PCPPUtility

BUTTON_TEMPLATE: str = (
    "button:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)timestamp:(?P<timestamp>[0-9]+)"
)
MENU_TEMPLATE: str = (
    "menu:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)timestamp:(?P<timestamp>[0-9]+)"
)


class PCPPInteractionHandler:
    """
    Handler for PCPartPicker-related Discord interactions.
    """

    @staticmethod
    def parse_interaction_ids(match: re.Match[str]) -> Tuple[int, int, int]:
        """
        Parse channel and message IDs from a regex match.
        """
        channel_id = int(match["channel_id"])
        message_id = int(match["message_id"])
        timestamp = int(match["timestamp"])
        return channel_id, message_id, timestamp

    @staticmethod
    @alru_cache(maxsize=1024)
    async def get_msg_object_for_url(
        bot, channel_id: int, message_id: int, timestamp: int
    ) -> list[str]:
        """
        Retrieve PCPartPicker URLs from a specific Discord message.
        """
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        return PCPPUtility.extract_unique_pcpp_urls(message.content)

    @staticmethod
    @alru_cache(maxsize=1024)
    async def send_preview(interaction: discord.Interaction, url: str) -> None:
        """
        Send a preview of a PCPartPicker list as an ephemeral message.
        """
        preview_embed = await PCPPUtility.generate_list_preview(url)
        await interaction.response.send_message(embed=preview_embed, ephemeral=True)
