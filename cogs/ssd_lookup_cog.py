from discord.ext import commands
from discord import app_commands
from ssd_helper_files.ssd_scraper import SSDScraper
from ssd_interaction_handler.py import SSDMenu
import discord

ILOVEPCS_BLUE = 9806321

class SSDCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="ssdlookup",
        description="Look up SSD information from the TechPowerUp database.",
    )
    @app_commands.describe(ssd_name="The name of the SSD to look up")
    async def ssdlookup(self, ctx: commands.Context, ssd_name: str):
        """
        Get information about an SSD

        Parameters
        ----------
        ssd_name: str
            The name of the SSD you want information about
        """
        ssd_scraper = SSDScraper()
        ssd_partial_info = await ssd_scraper.ssd_scraper_setup(ssd_name)
        options = SSDMenu.generate_options(ssd_partial_info)
        ssd_menu = SSDMenu(options, ssd_name, ctx.author.id)
        embed = discord.Embed(
            description = f"Here are the search results for {ssd_name} on the TechPowerUp SSD database; choose an option from the menu to view information about a specific SSD."
            color = ILOVEPCS_BLUE
        )
        await ctx.reply(embed=embed, view=ssd_menu)

    # Custom error handler for MissingRequiredArgument
    @ssdlookup.error
    async def ssdinfo_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title = "⚠️ You must specify an SSD name"
                color = ILOVEPCS_BLUE
            )
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(
                title = f"❌ An unexpected error occurred: `{error}`"
                color = ILOVEPCS_BLUE
            )
            await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SSDCog(bot))
