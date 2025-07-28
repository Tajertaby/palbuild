import asyncio
import os
import logging
import sys
from typing import Tuple

import discord
from discord.ext import commands
from dotenv import load_dotenv

from db_setup import Database
from sessions import SessionManager

# Load environment variables
CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))
load_dotenv(f"{CURRENT_PATH}\\secrets.env")
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")
COGS_PATH: str = f"{CURRENT_PATH}\\cogs"

# Retrieve a tuple of cog names and paths
# Each tuple contains (cog_name, cog_path)
COGS: Tuple[Tuple[str, str], ...] = tuple(
    (cog.replace(".py", ""), f"{COGS_PATH}\\{cog}")
    for cog in os.listdir(COGS_PATH)
    if cog.endswith(".py")
)


class FileManager:
    @classmethod
    def check_file_exists(cls, files: list[str]) -> dict[str, bool]:
        """Check if the specified files exist in the COGS_PATH directory."""
        file_bools = {}
        for file in files:
            file_path = os.path.join(COGS_PATH, file)
            if os.path.isfile(file_path):
                file_bools[file] = True
            else:
                logging.error(
                    "The file '%s' does not exist in the directory '%s'.", file, COGS_PATH
                )
                file_bools[file] = False
        return file_bools

    @classmethod
    async def load_cog(cls, cog: str) -> None:
        """Loads a cog after validating its syntax."""
        try:
            await bot.load_extension(f"cogs.{cog}")
            logging.info("Loaded cog: %s", cog)
        except discord.ext.commands.errors.ExtensionNotFound as not_found:
            logging.exception("Did not find cog %s: %s", cog, not_found)
        except discord.ext.commands.ExtensionAlreadyLoaded as already_loaded:
            logging.exception(
                "Cog %s is already loaded, reloading cog: %s", cog, already_loaded
            )
            await cls.reload_cog(cog)
        except discord.ext.commands.NoEntryPointError as no_entry_point:
            logging.exception("Cog %s has no setup function: %s", cog, no_entry_point)
        except discord.ext.commands.ExtensionFailed as failed_load:
            logging.exception(
                "Cog %s has failed to load during its execution: %s",
                cog,
                failed_load,
            )

    @classmethod
    async def reload_cog(cls, cog) -> None:
        """Reloads a cog after validating its syntax."""
        try:
            await bot.reload_extension(f"cogs.{cog}")
            logging.info("Reloaded cog: %s", cog)
        except discord.ext.commands.errors.ExtensionNotFound as not_found:
            logging.exception("Did not find cog %s: %s", cog, not_found)
        except discord.ext.commands.errors.ExtensionNotLoaded as not_loaded:
            logging.exception("Did not load cog %s, loading cog: %s", cog, not_loaded)
            await cls.load_cog(cog)
        except discord.ext.commands.NoEntryPointError as no_entry_point:
            logging.exception("Cog %s has no setup function: %s", cog, no_entry_point)
        except discord.ext.commands.ExtensionFailed as failed_load:
            logging.exception(
                "Cog %s has failed to load during its execution: %s",
                cog,
                failed_load,
            )

    @staticmethod
    async def unload_cog(cog: str) -> None:
        """Unloads a cog."""
        try:
            await bot.unload_extension(f"cogs.{cog}")
            logging.info("Unloaded cog: %s", cog)
        except discord.ext.commands.errors.ExtensionNotFound as not_found:
            logging.exception("Did not find cog %s: %s", cog, not_found)
        except discord.ext.commands.errors.ExtensionNotLoaded as not_loaded:
            logging.exception(
                "Cog %s was not loaded, no action needed: %s", cog, not_loaded
            )


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        """Sets up initial cogs and starts the file watcher."""
        logging.debug("Starting setup hook")
        setup_check = (
            await Database.setup_db()
        )  # Creates the necessary databases if needed
        if not setup_check:  # Stops the bot from running if the database setup fails
            logging.critical(
                "Database setup failed, terminating connection to Discord and shutting down the program."
            )
            await self.close()
            sys.exit(1)
        SessionManager.create_session()  # Start a session for network requests
        for cog_name, cog_path in COGS:  # cog_path is a placeholder variable
            await FileManager.load_cog(cog_name)

    async def on_ready(self) -> None:
        """Logs when the bot is ready."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def close(self) -> None:
        """Closes database and network session when bot shuts down."""
        await Database.close_db()
        await SessionManager.close_session()
        await super().close()


bot = DiscordBot()


@bot.command(name="reload")
async def reload(ctx, *cog_names: str):
    """Reloads one or more specific cogs or all cogs if no cog names are provided."""
    if cog_names:
        # Reload specific cogs
        for cog_name in cog_names:
            cog_name = cog_name.strip(", ")  # Remove any extra whitespace
            cog_path = os.path.join(COGS_PATH, f"{cog_name}.py")
            if os.path.isfile(cog_path):
                await FileManager.reload_cog(cog_name)
            else:
                logging.error("Cog file %s not found.", cog_name)
    else:
        # Reload all cogs
        for cog_name in COGS:
            await FileManager.reload_cog(cog_name)


@bot.command(name="load")
@commands.is_owner()
async def load(ctx, *cog_names: str):
    """Loads one or more specific cogs"""
    if cog_names:
        # Reload specific cogs
        for cog_name in cog_names:
            cog_name = cog_name.strip(", ")  # Remove any extra whitespace
            cog_path = os.path.join(COGS_PATH, f"{cog_name}.py")
            if os.path.isfile(cog_path):
                await FileManager.load_cog(cog_name)
            else:
                logging.error("Cog file %s.py not found.", cog_name)
    else:
        logging.error("No cog files were provided.")


@bot.command(name="unload")
@commands.is_owner()
async def unload(ctx, *cog_names: str):
    """Unloads one or more specific cogs"""
    if cog_names:
        # Reload specific cogs
        for cog_name in cog_names:
            cog_name = cog_name.strip(", ")  # Remove any extra whitespace
            cog_path = os.path.join(COGS_PATH, f"{cog_name}.py")
            if os.path.isfile(cog_path):
                await FileManager.unload_cog(cog_name)
            else:
                logging.error("Cog file %s.py not found.", cog_name)
    else:
        logging.error("No cog files were provided.")


@bot.command(name="stop")
@commands.is_owner()
async def stop(ctx):
    """Command to stop the bot"""
    await ctx.send("Shutting down...")
    await bot.close()


@bot.command(name="restart")
@commands.is_owner()
async def restart(ctx):
    """Command to restart the bot"""
    await ctx.send("Restarting...")
    os.execv(sys.executable, ["python"] + sys.argv)


@bot.event
async def on_message(message: discord.Message) -> None:
    """Ensures commands will trigger."""
    await bot.process_commands(message)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN, root_logger=True)  # Run the bot
