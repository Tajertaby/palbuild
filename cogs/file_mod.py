import datetime
import logging
import os
import re
from asyncio import sleep

import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
discord_log = logging.getLogger("discord.client")


class AutoMod(commands.Cog):
    SERVER_ID: int = 711236812416221324  # Test server, not main server
    REJECTED_FILETYPES_LOWER: set[str] = {
        "exe",
        "com",
        "dll",
        "bat",
        "vbs",
        "jar",
        "swf",
        "html",
        "js",
        "lnk",
        "ps1",
        "sh",
        "bin",
        "msi",
        "torrent",
        "zip",
        "rar",
        "7z",
    }
    SUPPORT_CHANNEL_IDS: set[int] = {
        1138822177999835176,  # ID: #pc-building
        1238376365917605941,  # ID: #hardware-troubleshoot
        1275248718618300416,  # ID: #software-troubleshoot
        1138459224691703919,  # ID: #peripherals
        1138821244876238878,  # ID: #prebuilts-laptops
    }

    GIF: set[str] = {"GIF", "gif"}
    REJECTED_FILETYPES_UPPER: set[str] = {
        ext.upper() for ext in REJECTED_FILETYPES_LOWER
    }
    keyword_block_list: set[str] = set()
    SEPARATOR_REGEX: str = r"_|:|;|/|\.|\-"
    AUTOMOD_ID: int = 1264219577123082280  # Rule from test server

    async def find_match(
        self, keyword_list, words, message: discord.Message, send_message_string: str
    ) -> None:
        if keyword_list.intersection(words):
            return await self.action(message, send_message_string)
        else:
            return True  # This tells the bot the function is ran and tells it to break the outer loop.

    @staticmethod
    async def action(
        message: discord.Message, send_message_string: str, gifs: bool = None
    ) -> None:

        try:
            await message.delete()  # Deletes offender's message
        except discord.errors.Forbidden:
            discord_log.exception("Cannot delete message, insufficient permissions.")
        if (
            not gifs
        ):  # Do not timeout the member if they sent a gif in support channels and not sent malicious messages/files.
            try:
                await message.author.timeout(
                    datetime.timedelta(minutes=1), reason="Triggered automod"
                )
            except discord.errors.Forbidden:
                discord_log.exception("Cannot timeout user: %s", message.author.name)
        reply_message = await message.channel.send(
            send_message_string
        )  # Bot replies with a temperory message
        await sleep(15)
        await reply_message.delete()
        return  # End the function

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:  # Checks files
        if message.author.bot:
            return

        message_words = set(re.split(self.SEPARATOR_REGEX, message.content))
        await self.find_match(
            self.keyword_block_list,
            message_words,
            message,
            f"{message.author.mention}, please keep to an appropriate language.",
        )  # Finds bad words separated by :, ;, /, _, - or .

        if len(message.attachments) > 0:
            for attachment in message.attachments:
                filename, ext = os.path.splitext(attachment.filename)
                ext_without_dot = ext[1:].lower()  # File name without extension.
                file_words = set(re.split(self.SEPARATOR_REGEX, attachment.filename))

                if ext_without_dot in (
                    self.REJECTED_FILETYPES_LOWER or self.REJECTED_FILETYPES_UPPER
                ):
                    await self.action(
                        message,
                        f"{message.author.mention}, your message containing the attachment named `{attachment.filename}` has been removed.\nYou cannot upload file types of: `{', '.join(self.REJECTED_FILETYPES_LOWER)}`",
                    )
                    break

                elif (
                    message.channel.id in self.SUPPORT_CHANNEL_IDS
                    and ext_without_dot in self.GIF
                ):  # Checks if GIFs are in support text channels.
                    await self.action(
                        message,
                        f"{message.author.mention} GIFs are not allowed in support channels.",
                        gifs=True,
                    )
                    break
                else:  # Checks for inappropriate file names
                    call_match = await self.find_match(
                        self.keyword_block_list,
                        file_words,
                        message,
                        f"{message.author.mention}, your message containing the attachment named `{attachment.filename}` has been removed.\nYour attachment might be deemed inappropriate.",
                    )
                    if call_match:
                        break

        # await bot.process_commands(message)

    @commands.Cog.listener()
    async def on_automod_rule_update(self, rule):
        if rule.id == self.AUTOMOD_ID:
            AutoMod.keyword_block_list = set(
                rule.trigger.keyword_filter
            )  # Updates set of custom blocked keywords
            print(AutoMod.keyword_block_list)
        else:
            return


async def setup(bot):
    cls = AutoMod
    my_guild = bot.get_guild(cls.SERVER_ID)  # Gets guild from cache
    if not my_guild:
        my_guild = await bot.fetch_guild(
            cls.SERVER_ID
        )  # If not found in cache, it will send an API request to get guild. If still not found, it is a invalid guild ID or a guild the bot is not in
    else:
        rule = await my_guild.fetch_automod_rule(cls.AUTOMOD_ID)
        cls.keyword_block_list = set(
            rule.trigger.keyword_filter
        )  # Gets a set of custom blocked keywords
        print(AutoMod.keyword_block_list)
    await bot.add_cog(cls(bot))
