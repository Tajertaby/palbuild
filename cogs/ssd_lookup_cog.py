from discord.ext import commands
from discord import app_commands
from ssd_helper_files.ssd_scraper import SSDScraper, NOT_UNIQUE
from ssd_helper_files.ssd_interaction_handler import SSDMenu
import discord

import embed_creator
import logging
import re

# Constants
MAX_SSD_SEARCH_LENGTH: int = 30
DISCORD_LOG: logging.Logger = logging.getLogger("discord")


class SSDCog(commands.Cog):
    """Discord cog for handling SSD lookup commands using TechPowerUp database."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the SSD cog with the bot instance."""
        self.bot: commands.Bot = bot

    @commands.hybrid_command(
        name="ssdlookup",
        description="Look up SSD information from the TechPowerUp database.",
    )
    @app_commands.describe(ssd_name="The name of the SSD to look up.")
    async def ssdlookup(self, ctx: commands.Context, *, ssd_name: str) -> None:
        """
        Get information about an SSD from TechPowerUp database.

        Parameters
        ----------
        ctx : commands.Context
            The invocation context
        ssd_name : str
            The name of the SSD to search for (max 30 characters)
        """
        # Validate input length
        ssd_name_length: int = len(ssd_name)
        if ssd_name_length > MAX_SSD_SEARCH_LENGTH:
            embed: discord.Embed = embed_creator._create_embed(
                description=f"Your search term is {ssd_name_length} characters long, "
                f"cannot be over {MAX_SSD_SEARCH_LENGTH} characters long"
            )
            await ctx.reply(embed=embed)
            return

        # Initialize scraper and fetch data
        ssd_results: list[tuple] | str = await SSDScraper.ssd_scraper_setup(ssd_name)

        # Handle search results
        if ssd_results != NOT_UNIQUE:
            menu_options: list[discord.SelectOption] = SSDMenu.generate_options(
                ssd_results
            )
            ssd_menu: SSDMenu = SSDMenu(menu_options, ssd_name, ctx.author.id)

            view: discord.ui.View = discord.ui.View(timeout=None)
            view.add_item(ssd_menu)

            response_embed: discord.Embed = embed_creator._create_embed(
                description=f"Here are the search results for `{ssd_name}` on the TechPowerUp SSD database.\n"
                "Choose an option from the menu to view information about a specific SSD."
            )
            await ctx.reply(embed=response_embed, view=view)
        else:
            error_embed: discord.Embed = embed_creator._create_embed(
                description="Cannot generate a menu due to not unique menu options."
            )
            await ctx.reply(embed=error_embed)

    @ssdlookup.error
    async def ssdinfo_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        Handle errors for the ssdlookup command.

        Args:
            ctx: The invocation context
            error: The exception that was raised
        """
        if isinstance(error, commands.MissingRequiredArgument):
            error_embed: discord.Embed = embed_creator._create_embed(
                description="⚠️ You must specify an SSD name"
            )
            await ctx.reply(embed=error_embed)
            DISCORD_LOG.exception(error)
        else:
            error_embed: discord.Embed = embed_creator._create_embed(
                description=f"❌ An unexpected error occurred: `{error}`"
            )
            await ctx.reply(embed=error_embed)
            DISCORD_LOG.exception(error)


async def setup(bot: commands.Bot) -> None:
    """Add the SSDCog to the bot."""
    bot.add_dynamic_items(SSDMenu)
    await bot.add_cog(SSDCog(bot))
