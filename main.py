import asyncio
import os
import logging
import sys
from typing import Tuple, Set, Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
from watchfiles import awatch, Change

from db_setup import Database
from sessions import SessionManager

# Load environment variables
load_dotenv(r"E:\Discord Bot Files\secrets.env")
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")
COGS_PATH: str = r"E:\Discord Bot Files\cogs"

# Retrieve a tuple of cog names and paths
# Each tuple contains (cog_name, cog_path)
COGS: Tuple[Tuple[str, str], ...] = tuple(
    (cog.replace(".py", ""), f"{COGS_PATH}\\{cog}")
    for cog in os.listdir(COGS_PATH)
    if cog.endswith(".py")
)


class FileManager:
    """Manages loading, unloading, and reloading of cogs based on file events and bot startup."""

    debounce_timer: Optional[asyncio.Task] = None
    accumulated_changes: Set[Tuple[Change, str]] = set()

    @classmethod
    async def start_debounce(cls) -> None:
        """Starts the debounce process and monitors file changes."""
        async for changes in awatch(COGS_PATH):
            added_changes: Set[Tuple[Change, str]] = {
                (change, file_path)
                for change, file_path in changes
                if change == Change.added
            }
            if added_changes:
                await cls.set_debounce_timer(added_changes)
            else:
                await cls.set_debounce_timer(changes)

    @classmethod
    async def set_debounce_timer(cls, changes: Set[Tuple[Change, str]]) -> None:
        """Sets a debounce timer to group events within a time frame."""
        for change in changes:
            cls.accumulated_changes.add(change)
        if cls.debounce_timer:
            cls.debounce_timer.cancel()
        accumulated_changes_copy = cls.accumulated_changes.copy()
        cls.debounce_timer = bot.loop.create_task(
            cls.debounce_wait(accumulated_changes_copy)
        )

    @classmethod
    async def debounce_wait(cls, changes: Set[Tuple[Change, str]]) -> None:
        """Waits for the debounce period and then processes accumulated changes."""
        logging.info("Debounce period started.")
        try:
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            logging.info("Debounce period reset.")
            return
        finally:
            cls.debounce_timer = None
            logging.info("Debounce period ended.")
            await cls.observer(changes)

    @classmethod
    async def load_cog(cls, cog: str, file_path: str) -> None:
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
            await cls.reload_cog(cog, file_path)
        except discord.ext.commands.NoEntryPointError as no_entry_point:
            logging.exception("Cog %s has no setup function: %s", cog, no_entry_point)
        except discord.ext.commands.ExtensionFailed as failed_load:
            logging.exception(
                "Cog %s has failed to load during its execution: %s",
                cog,
                failed_load,
            )

    @classmethod
    async def reload_cog(cls, cog: str, file_path: str) -> None:
        """Reloads a cog after validating its syntax."""
        try:
            await bot.reload_extension(f"cogs.{cog}")
            logging.info("Reloaded cog: %s", cog)
        except discord.ext.commands.errors.ExtensionNotFound as not_found:
            logging.exception("Did not find cog %s: %s", cog, not_found)
        except discord.ext.commands.errors.ExtensionNotLoaded as not_loaded:
            logging.exception("Did not load cog %s, loading cog: %s", cog, not_loaded)
            await cls.load_cog(cog, file_path)
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

    @staticmethod
    async def validate_cog(file_path: str) -> bool:
        """Validates cog syntax without executing it."""
        try:
            with open(file_path, encoding="utf-8") as cog_open:
                cog_code = cog_open.read()
            compile(cog_code, file_path, mode="exec")
            return True
        except FileNotFoundError as f:
            logging.exception("Cog file not found: %s", f)
        except SyntaxError as syntax_error:
            logging.exception("A syntax error occurred: %s", syntax_error)
        except Exception as e:
            logging.exception("An exception occurred: %s", e)
        return False

    @classmethod
    async def observer(cls, changes: Set[Tuple[Change, str]]) -> None:
        """
        Processes file changes and determines which actions to take for each cog.
        Processes file changes and determines which actions to take for each cog.
        """
        for change_type, file_path in changes:
            if not file_path.endswith(".py") or os.path.isdir(file_path):
                logging.info(
                    "Detected change event %s at %s. It is not a Python file or is a directory.",
                    change_type.name,
                    file_path,
                )
                continue

            logging.info(
                "Detected change event %s at %s. It is a Python file.",
                change_type.name,
                file_path,
            )

            cog = os.path.splitext(os.path.basename(file_path))[0]

            if change_type != Change.deleted:
                cog_validated = await cls.validate_cog(file_path)
            elif change_type == Change.added and cog_validated:
                await cls.load_cog(cog, file_path)
            elif change_type == Change.modified and cog_validated:
                await cls.reload_cog(cog, file_path)
            elif change_type == Change.deleted:
                await cls.unload_cog(cog)

        cls.accumulated_changes.clear()  # Clears accumulated_changes after processing all changes.


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
        )  # Creates the neccessary databases if needed
        if not setup_check:  # Stops the bot from running if the database setup fails
            logging.critical(
                "Database setup failed, terminating connection to Discord and shutting down the program."
            )
            await self.close()
            sys.exit(1)
        SessionManager.create_session()  # Start a session for network requests
        for cog_name, file_path in COGS:
            self.loop.create_task(FileManager.load_cog(cog_name, file_path))

        self.loop.create_task(FileManager.start_debounce())

    async def on_ready(self) -> None:
        """Logs when the bot is ready."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def close(self) -> None:
        """Closes database and network session when bot shuts down."""
        await Database.close_db()
        await SessionManager.close_session()
        await super().close()


bot = DiscordBot()


@bot.event
async def on_message(message: discord.Message) -> None:
    """Ensures commands will trigger."""
    await bot.process_commands(message)


if __name__ == "__main__":
    bot.run(f"{DISCORD_TOKEN}", root_logger=True)  # Run the bot
