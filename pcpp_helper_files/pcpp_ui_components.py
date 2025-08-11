import discord
import re
from typing import List

from .pcpp_interaction_handler import (
    PCPPInteractionHandler,
    BUTTON_TEMPLATE,
    MENU_TEMPLATE,
)


class PCPPButton(discord.ui.DynamicItem[discord.ui.Button], template=BUTTON_TEMPLATE):
    """
    A custom button for PCPartPicker list previews.
    """

    def __init__(self, channel_id: int, message_id: int, timestamp: int, url: str):
        self.channel_id = channel_id
        self.message_id = message_id
        self.timestamp = timestamp
        self.url = url
        super().__init__(
            discord.ui.Button(
                label="View Preview",
                style=discord.ButtonStyle.blurple,
                custom_id=f"button:channel:{self.channel_id}message:{self.message_id}timestamp:{self.timestamp}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        """
        Create a PCPPButton instance from a custom ID.
        """
        channel_id, message_id, timestamp = (
            PCPPInteractionHandler.parse_interaction_ids(match)
        )
        pcpp_urls = await PCPPInteractionHandler.get_msg_object_for_url(
            interaction.client, channel_id, message_id, timestamp
        )
        url = pcpp_urls[0]
        return cls(channel_id, message_id, timestamp, url)

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle the button press event.
        """
        await PCPPInteractionHandler.send_preview(interaction, self.url)


class PCPPMenu(discord.ui.DynamicItem[discord.ui.Select], template=MENU_TEMPLATE):
    """
    A custom select menu for multiple PCPartPicker list previews.
    """

    def __init__(
        self,
        channel_id: int,
        message_id: int,
        timestamp: int,
        options: list[discord.SelectOption],
    ) -> None:
        self.channel_id = channel_id
        self.message_id = message_id
        self.timestamp = timestamp
        self.options = options
        super().__init__(
            discord.ui.Select(
                placeholder="View Previews",
                custom_id=f"menu:channel:{self.channel_id}message:{self.message_id}timestamp:{self.timestamp}",
                options=self.options,
            )
        )

    @staticmethod
    def generate_options(pcpp_urls: list[str]) -> list[discord.SelectOption]:
        """
        Generate select options for PCPartPicker URLs.
        """
        return [
            discord.SelectOption(label=f"List Preview {i}", value=url)
            for i, url in enumerate(pcpp_urls[:25], start=1)
        ]

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: re.Match[str],
        /,
    ):
        """
        Create a PCPPMenu instance from a custom ID.
        """
        channel_id, message_id, timestamp = (
            PCPPInteractionHandler.parse_interaction_ids(match)
        )
        pcpp_urls = await PCPPInteractionHandler.get_msg_object_for_url(
            interaction.client, channel_id, message_id, timestamp
        )
        options = cls.generate_options(pcpp_urls)
        return cls(channel_id, message_id, timestamp, options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle the select menu option selection.
        """
        await PCPPInteractionHandler.send_preview(interaction, self.item.values[0], view=None)
        await interaction.message.edit()  # Reset user choice after selection
