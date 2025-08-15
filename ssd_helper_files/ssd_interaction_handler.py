import discord
import embed_creator
import re
from typing import List, Tuple, Match, Optional
from ssd_helper_files.ssd_scraper import SSDScraper

# Constants
MENU_TEMPLATE: str = "ssdname:(?P<name>.{0,75})user:(?P<id>[0-9]+)"
TECH_POWERUP_BASE_URL: str = "https://www.techpowerup.com"


class SSDMenu(discord.ui.DynamicItem[discord.ui.Select], template=MENU_TEMPLATE):
    """
    Dynamic select menu for displaying and interacting with SSD search results.
    Ensures only the initiating user can interact with the menu.
    """

    def __init__(
        self,
        options: List[discord.SelectOption],
        ssd_name: str,
        user_id: int,
    ) -> None:
        """
        Initialize the SSD selection menu.

        Args:
            options: Select options containing SSD information
            ssd_name: Original search query for SSDs
            user_id: Discord ID of the command invoker
        """
        self.select_options = options
        self.search_ssd_name = ssd_name
        self.owner_user_id = user_id

        super().__init__(
            discord.ui.Select(
                placeholder="Select an SSD for detailed information",
                custom_id=self._generate_custom_id(ssd_name, user_id),
                options=options,
                min_values=1,
                max_values=1,
            )
        )

    @staticmethod
    def _generate_custom_id(ssd_name: str, user_id: int) -> str:
        """Generate a custom ID for the select menu."""
        return f"ssdname:{ssd_name}user:{user_id}"

    @staticmethod
    def _format_option_description(release_date: str, capacity: str) -> str:
        """Format the description text for a menu option."""
        return f"Capacity: {capacity} | Released: {release_date}"

    @classmethod
    def generate_options(
        cls,
        ssd_search_results: List[Tuple[str, str, str, str]],
    ) -> List[discord.SelectOption]:
        """
        Create SelectOption objects from SSD search results.

        Args:
            ssd_search_results: List of (model, release_date, capacity, url) tuples

        Returns:
            List of formatted SelectOption objects
        """
        return [
            discord.SelectOption(
                label=model_name,
                description=cls._format_option_description(
                    release_date, storage_capacity
                ),
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
    ) -> "SSDMenu":
        """
        Reconstruct the menu from a custom ID during interaction.

        Args:
            interaction: The triggering Discord interaction
            item: The Select menu item
            match: Regex match of the custom ID

        Returns:
            Reconstructed SSDMenu instance
        """
        searched_ssd_name = match["name"]
        user_id = int(match["id"])

        search_results = await SSDScraper.ssd_scraper_setup(searched_ssd_name)
        menu_options = cls.generate_options(search_results)

        return cls(menu_options, searched_ssd_name, user_id)

    async def _handle_unauthorized_interaction(
        self, interaction: discord.Interaction
    ) -> None:
        """Respond to interactions from non-authorized users."""
        embed = embed_creator.create_embed(
            description="⚠️ Only the original command user can interact with this menu."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _process_selected_ssd(self, interaction: discord.Interaction) -> None:
        """Fetch and display details for the selected SSD."""
        selected_url = f"{TECH_POWERUP_BASE_URL}{self.item.values[0]}"
        ssd_name, ssd_details = await SSDScraper.specific_ssd_scraper(selected_url)

        embed = embed_creator.create_embed(title=ssd_name, description=ssd_details, title_url=selected_url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await interaction.message.edit()  # Reset user choice after selection

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle menu selection events.

        Args:
            interaction: The triggering Discord interaction
        """
        if interaction.user.id != self.owner_user_id:
            await self._handle_unauthorized_interaction(interaction)
            return

        await self._process_selected_ssd(interaction)
