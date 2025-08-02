from discord.ext import commands
from discord import app_commands
from ssd_helper_files.ssd_scraper import SSDScraper, NOT_UNIQUE
from ssd_helper_files.ssd_interaction_handler import SSDMenu
import discord
import logging
import re

ILOVEPCS_BLUE = 9806321
DISCORD_LOG = logging.getLogger("discord")


class SSDCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="ssdlookup",
        description="Look up SSD information from the TechPowerUp database.",
    )
    @app_commands.describe(ssd_name="The name of the SSD to look up.")
    async def ssdlookup(self, ctx: commands.Context, *, ssd_name: str):
        """
        Get information about an SSD

        Parameters
        ----------
        ssd_name: str
            The name of the SSD you want information about
        """

        ssd_name_length = len(ssd_name)
        if ssd_name_length > 30:
            embed = self.embed_maker(
                f"Your search term is {ssd_name_length} charactors long, cannot be over 30 charactors long"
            )
            await ctx.reply(embed=embed)
            return

        ssd_scraper = SSDScraper()
        ssd_partial_info = await ssd_scraper.ssd_scraper_setup(ssd_name)
        if ssd_partial_info != NOT_UNIQUE:
            options = SSDMenu.generate_options(ssd_partial_info)
            ssd_menu = SSDMenu(options, ssd_name, ctx.author.id)
            view = discord.ui.View(timeout=None)
            view.add_item(ssd_menu)
            embed = self.embed_maker(
                f"Here are the search results for `{ssd_name}` on the TechPowerUp SSD database.\nChoose an option from the menu to view information about a specific SSD."
            )
            await ctx.reply(embed=embed, view=view)
        else:
            embed = self.embed_maker(
                "Cannot generate a menu due to not unique menu options."
            )
            await ctx.reply(embed=embed)

    def embed_maker(self, description) -> discord.Embed:
        return discord.Embed(description=description, color=ILOVEPCS_BLUE)

    # Custom error handler for MissingRequiredArgument
    @ssdlookup.error
    async def ssdinfo_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            embed = self.embed_maker("⚠️ You must specify an SSD name")
            await ctx.reply(embed=embed)
            DISCORD_LOG.exception(error)
        else:
            embed = self.embed_maker(f"❌ An unexpected error occurred: `{error}`")
            await ctx.reply(embed=embed)
            DISCORD_LOG.exception(error)


async def setup(bot: commands.Bot):
    await bot.add_cog(SSDCog(bot))
