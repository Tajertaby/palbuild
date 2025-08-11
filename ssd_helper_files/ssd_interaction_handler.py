import discord
import re
from typing import List, Tuple, Match, Any
from ssd_helper_files.ssd_scraper import SSDScraper

# Template for custom select menu ID format
MENU_TEMPLATE: str = "ssdname:(?P<name>.{0,75})user:(?P<id>[0-9]+)"


class SSDMenu(discord.ui.DynamicItem[discord.ui.Select], template=MENU_TEMPLATE):
    """
    A dynamic select menu that displays SSD search results from PCPartPicker.
    Only the user who initiated the search can interact with the menu.
    """

    def __init__(
        self,
        options: List[discord.SelectOption],
        ssd_name: str,
        user_id: int,
        ssd_scraper: SSDScraper,
    ) -> None:
        """
        Initialize the SSD selection menu.

        Args:
            options: List of select options containing SSD information
            ssd_name: The name of the SSD being searched
            user_id: Discord ID of the user who initiated the search
            ssd_scraper: Instance of SSDScraper for getting SSD details
        """
        self.select_options: List[discord.SelectOption] = options
        self.search_ssd_name: str = ssd_name
        self.owner_user_id: int = user_id
        self.scraper_instance: SSDScraper = ssd_scraper

        # Initialize the parent Select menu with the formatted custom ID
        super().__init__(
            discord.ui.Select(
                placeholder="Searched SSD Results",
                custom_id=f"ssdname:{ssd_name}user:{user_id}",
                options=self.select_options,
            )
        )

    @staticmethod
    def generate_options(
        ssd_search_results: List[Tuple[str, str, str, str]],
    ) -> List[discord.SelectOption]:
        """
        Generate select menu options from SSD search results.

        Args:
            ssd_search_results: List of tuples containing:
                - model_name: str
                - release_date: str
                - storage_capacity: str
                - product_url: str

        Returns:
            List of formatted SelectOption objects for the menu
        """
        return [
            discord.SelectOption(
                label=f"{model_name}",
                description=f"Capacity: {storage_capacity}\nReleased: {release_date}",
                value=product_url,
            )
            for model_name, release_date, storage_capacity, product_url in ssd_search_results
        ]

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: Match[str],
        /,
    ) -> "SSDMenu":
        """
        Create an SSDMenu instance from a custom ID pattern match.

        Args:
            interaction: The Discord interaction that triggered the menu
            item: The Select menu item
            match: Regex match result from the custom ID

        Returns:
            An initialized SSDMenu instance
        """
        searched_ssd_name: str = match["name"]
        requesting_user_id: int = int(match["id"])
        scraper: SSDScraper = (
            SSDScraper()
        )  # Preserved original variable name from import
        search_results: List[Tuple[str, str, str, str]] = scraper.ssd_scraper_setup(
            searched_ssd_name
        )
        menu_options: List[discord.SelectOption] = cls.generate_options(search_results)
        return cls(menu_options, searched_ssd_name, requesting_user_id, scraper)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the original requesting user can interact with the menu."""
        return interaction.user.id == self.owner_user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle selection of an SSD from the menu.
        Fetches detailed information for the selected SSD.
        """
        selected_ssd_url: str = self.select_options.values[0]  # URL of the selected SSD
        await self.scraper_instance.specific_ssd_scraper(selected_ssd_url)
        await interaction.message.edit()  # Update the message with detailed info
