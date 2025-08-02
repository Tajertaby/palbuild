import discord
import re
from typing import List
from ssd_helper_files.ssd_scraper import SSDScraper

MENU_TEMPLATE = "ssdname:(?P<name>.{0,75})user:(?P<id>[0-9]+)"


class SSDMenu(discord.ui.DynamicItem[discord.ui.Select], template=MENU_TEMPLATE):
    """
    A custom select menu for multiple PCPartPicker list previews.
    """

    def __init__(
        self,
        options: list[discord.SelectOption],
        ssd_name,
        user_id: int,
    ) -> None:
        self.options = options
        self.ssd_name = ssd_name
        self.user_id: int = user_id
        super().__init__(
            discord.ui.Select(
                placeholder="Searched SSD Results",
                custom_id=f"ssdname:{ssd_name}user:{user_id}",
                options=self.options,
            )
        )

    @staticmethod
    def generate_options(ssd_partial_info: list[tuple]) -> list[discord.SelectOption]:
        """
        Generate select options for SSDs based on searched name.
        """
        return [
            discord.SelectOption(
                label=f"{ssd_name}",
                description=f"Capacity: {ssd_capacity}\nReleased: {ssd_released}",
                value=url,
            )
            for ssd_name, ssd_released, ssd_capacity, url in ssd_partial_info
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
        ssd_name = match["name"]
        user_id = int(match["id"])
        ssd_scraper = SSDScraper()
        ssd_partial_info = ssd_scraper.ssd_scraper_setup(ssd_name)
        options = cls.generate_options(ssd_partial_info)
        return cls(options, user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the user who created the menu to interact with it.
        return interaction.user.id == self.user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle the select menu option selection.
        """
        await PCPPInteractionHandler.send_preview(interaction, self.item.values[0])
        await interaction.message.edit()
