from discord.ext import commands
from discord import app_commands
from ssd_helper_files.ssd_scraper import SSDScraper, NOT_UNIQUE
from ssd_helper_files.ssd_interaction_handler import SSDMenu
import discord
import embed_creator
import logging
from typing import Optional

# Constants
MAX_SSD_SEARCH_LENGTH: int = 30
DISCORD_LOG: logging.Logger = logging.getLogger("discord")


class SSDCog(commands.Cog):
    """Discord cog for handling SSD lookup commands using TechPowerUp database."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the SSD cog with the bot instance."""
        self.bot: commands.Bot = bot

    async def _validate_search_term(self, ctx: commands.Context, ssd_name: str) -> bool:
        """Validate the SSD search term length."""
        if len(ssd_name) > MAX_SSD_SEARCH_LENGTH:
            embed = embed_creator.create_embed(
                description=f"Search term cannot exceed {MAX_SSD_SEARCH_LENGTH} characters."
            )
            await ctx.reply(embed=embed)
            return False
        return True

    async def _handle_ssd_results(
        self, 
        ctx: commands.Context, 
        ssd_results: list[tuple] | str, 
        ssd_name: str
    ) -> None:
        """Handle the SSD search results and send appropriate response."""
        if ssd_results == NOT_UNIQUE:
            await self._send_error_response(ctx, "Cannot generate menu due to non-unique options.")
            return

        menu_options = SSDMenu.generate_options(ssd_results)
        ssd_menu = SSDMenu(menu_options, ssd_name, ctx.author.id)

        view = discord.ui.View(timeout=None)
        view.add_item(ssd_menu)

        response_embed = embed_creator.create_embed(
            description=(
                f"Here are the search results for `{ssd_name}` on the TechPowerUp SSD database.\n"
                "Choose an option from the menu to view information about a specific SSD."
            )
        )
        await ctx.reply(embed=response_embed, view=view)

    async def _send_error_response(self, ctx: commands.Context, message: str) -> None:
        """Send an error response embed."""
        embed = embed_creator.create_embed(description=message)
        await ctx.reply(embed=embed)

    @commands.hybrid_command(
        name="ssdlookup",
        description="Look up SSD information from the TechPowerUp database.",
    )
    @app_commands.describe(ssd_name="The name of the SSD to look up.")
    async def ssdlookup(self, ctx: commands.Context, *, ssd_name: str) -> None:
        """
        Get information about an SSD from TechPowerUp database.

        Args:
            ctx: The invocation context
            ssd_name: The name of the SSD to search for (max 30 characters)
        """
        if not await self._validate_search_term(ctx, ssd_name):
            return

        try:
            ssd_results = await SSDScraper.ssd_scraper_setup(ssd_name)
            await self._handle_ssd_results(ctx, ssd_results, ssd_name)
        except Exception as e:
            await self._handle_ssd_lookup_error(ctx, e)
            DISCORD_LOG.exception(f"Error in ssdlookup command: {e}")

    async def _handle_ssd_lookup_error(self, ctx: commands.Context, error: Exception) -> None:
        """Handle errors specific to SSD lookup."""
        if isinstance(error, commands.MissingRequiredArgument):
            message = "⚠️ You must specify an SSD name"
        else:
            message = f"❌ An unexpected error occurred: `{error}`"
        
        await self._send_error_response(ctx, message)

    @ssdlookup.error
    async def ssdinfo_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        Handle errors for the ssdlookup command.

        Args:
            ctx: The invocation context
            error: The exception that was raised
        """
        await self._handle_ssd_lookup_error(ctx, error)


async def setup(bot: commands.Bot) -> None:
    """Add the SSDCog to the bot."""
    bot.add_dynamic_items(SSDMenu)
    await bot.add_cog(SSDCog(bot))