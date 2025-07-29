from discord.ext import commands
from discord import app_commands
import discord


class SSDCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="ssdinfo",
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
        await ctx.send(f"You requested information about SSD: {ssd_name}")

    # Custom error handler for MissingRequiredArgument
    @ssdlookup.error
    async def ssdinfo_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "❌ **Error:** You must specify an SSD name!\n"
                "Example: `!ssdinfo Samsung_970` or `/ssdinfo ssd_name:Samsung_970`"
            )
        else:
            await ctx.send(f"⚠ An unexpected error occurred: `{error}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(SSDCog(bot))
