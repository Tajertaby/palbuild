import datetime
import logging
import re
import textwrap
import urllib.parse as parse
from asyncio import TimeoutError as AsyncioTimeoutError
from functools import lru_cache
from typing import List, Tuple, Optional, Union

import discord
from async_lru import alru_cache
from aiohttp import ClientConnectionError, ClientPayloadError, ClientResponseError
from aiosqlite import Error, DatabaseError, OperationalError
from bs4 import BeautifulSoup, SoupStrainer
from discord.ext import commands

from db_setup import SQL_LOG, Database
from sessions import SessionManager

server = SessionManager.server  # Logger
PCPP_LOG = logging.getLogger("pcpp_scraper")
DISCORD_LOG = logging.getLogger("discord")
YEAR_IN_CLASS = 2025

# Constants and regex patterns for identifying PCPartPicker URLs
PCPP_VALID_URL_PATTERN: re.Pattern[str] = re.compile(
    r"""
    https?://                 # Protocol (http or https)
    (?:[a-z]{2}\.)?           # Optional country code subdomain
    pcpartpicker\.com/        # Domain
    (?:
        (?:
            list/(?!(?:by_merchant)/?)(?!$)|               # Valid links with "/list/". "by_merchant" invalidates the link.
            user/[a-z0-9]+/saved/(?!$)(?:\#view=)?|        # Valid links for saved builds.
            b/                                             # Valid links for completed builds.
        )
        [a-z0-9]+|                                         # Alphanumeric identifier for list links except PCPP build guides.

        # End of above links except PCPP build guide links, the regex is below.              
        guide/[a-z0-9]+/                       # PCPP Build guides link.
        (?:
            budget|entry-level|modest|great|excellent|enthusiast|magnificent|glorious # Budget level for builds in PCPP build guides.
        )
        -(?:
            (?:amd|intel)-gaming(?:streaming)?| # CPU brand and gaming/streaming use case.
            homeoffice   # homeoffice build links does not have CPU brand name in it.
        )-build
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

INVALID_URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com/list/?(?:(?:by_merchant/?)|(?![a-z0-9/]))",
    re.IGNORECASE,
)
DOMAIN_PATTERN: re.Pattern[str] = re.compile(
    r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com", re.IGNORECASE
)

BUTTON_TEMPLATE: str = (
    "button:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)timestamp:(?P<timestamp>[0-9]+)"
)
MENU_TEMPLATE: str = (
    "menu:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)timestamp:(?P<timestamp>[0-9]+)"
)
ILOVEPCS_BLUE = 9806321


class PCPPScraper:
    """
    A class for scraping and processing PCPartPicker content.
    """

    def __init__(self) -> None:
        self.power_icon = "\U0001F50C"
        self.earth_icon = "\U0001F30E"
        self.price_icon = "\U0001F4B8"

    async def fetch_html_content(
        self, url: str, tag_name: str, class_list: list
    ) -> BeautifulSoup:
        """
        Fetch and parse the HTML content from the given PCPartPicker URL.

        Args:
            url (str): The URL to fetch content from.
            tag_name (str): The HTML tag to filter.
            class_list (list): A list of classes to filter.

        Returns:
            BeautifulSoup: Parsed HTML content.

        Raises:
            Various exceptions for network and parsing errors.
        """
        try:
            strainer = SoupStrainer(
                tag_name, class_=class_list
            )  # Filters the HTML for efficiency
            page = await SessionManager.request(url)
            return BeautifulSoup(page, "lxml", parse_only=strainer)
        except AsyncioTimeoutError as e:
            raise (f"Web server timeout. URL={url}, {e}") from e
        except ClientConnectionError as e:
            raise ClientConnectionError(
                f"Could not connect to web server. URL={url}, {e}"
            ) from e
        except ClientPayloadError as e:
            raise ClientPayloadError(
                f"Invalid payload from web server. URL={url}, {e}"
            ) from e
        except ClientResponseError as e:
            raise ClientResponseError(
                f"Invalid response from web server. URL={url}, {e}"
            ) from e
        except Exception as e:
            raise Exception(f"Unexpected error during network request: {e}") from e

    def extract_domain(self, url: str) -> str:
        """
        Extract the base domain from the given URL.

        Args:
            url (str): The full URL.

        Returns:
            str: The base domain of the URL.
        """
        domain_match = DOMAIN_PATTERN.match(url)
        return url[: domain_match.end()]

    def parse_product_without_link(self, product_name: str) -> tuple[str, str]:
        """
        Parse a product name when no link is available.

        Args:
            product_name (str): The raw product name.

        Returns:
            tuple: A tuple containing the cleaned product name and an empty link string.
        """
        return product_name[1:-1], ""

    def extract_product_details(
        self,
        domain: str,
        component_elements: list[str],
        product_elements: list[str],
        price_elements: list[str],
        merchant_elements: list[str],
    ) -> str:
        """
        Extract and format product details from HTML elements.

        Args:
            domain (str): The base domain for constructing full URLs.
            component_elements (list): HTML elements containing component types.
            product_elements (list): HTML elements containing product names and links.
            price_elements (list): HTML elements containing price information.
            merchant_elements (list): HTML elemtns containing merchant and purchase information.

        Returns:
            str: Formatted string of product details.
        """
        details = []
        for component, product, price, merchant in zip(
            component_elements, product_elements, price_elements, merchant_elements
        ):
            component_type = component.contents[1].text.strip()
            product_name, product_link = self.parse_product_name_and_link(
                product, domain
            )

            purchase = self.purchase_info(price.contents, merchant.contents)

            details.append(
                f"- **{component_type} ->** {purchase}\n{product_name}{product_link}"
            )

        return "**__PC PARTS__**\n{}\n".format("\n".join(details))

    def parse_product_name_and_link(
        self, product_element, domain: str
    ) -> tuple[str, str]:
        """
        Parse product name and link from a product element.

        Args:
            product_element: BeautifulSoup element containing product information.
            domain (str): The base domain for constructing full URLs.

        Returns:
            tuple: Product name and link (if available).
        """
        product_contents = product_element.contents
        if len(product_contents) >= 2:
            product_name = f"[{product_contents[1].text.strip()}]"
            element_html = str(product_contents)
            if "a href" in element_html and "#view_custom_part" not in element_html:
                product_link = f"({domain}{product_element.a.get('href').strip()})"
            else:
                product_name, product_link = self.parse_product_without_link(
                    product_name
                )
        else:
            product_name = product_contents[0].text.strip()
            product_link = ""

        return product_name, product_link

    def purchase_info(self, price_contents, merchant_contents: list) -> str:
        """
        Parse and format the purchase info.

        Args:
            merchant_contents (list): List of merchant-related HTML elements.

        Returns:
            str: Price and merchant (if avaliable).
        """

        if "alt=" in str(merchant_contents):  # Retrieve merchant
            price = f"{price_contents[-2].text.strip()}"
            merchant = next(
                (
                    f" @{elem.img.get('alt')}"
                    for elem in merchant_contents
                    if "alt=" in str(elem)
                ),
                None,
            )
        else:
            if len(price_contents) < 2 or price_contents[-2].text == "No Prices":
                price = "No Prices Available"
            elif merchant_contents[-1] != "Purchased":
                price = f"{price_contents[-1].text} (Custom Price)"
            else:
                price = f"{price_contents[-1].text} (Custom Price | Purchased)"
            merchant = ""
        return f"{price}{merchant}"

    def extract_compatibility_notes(self, soup: BeautifulSoup) -> str:
        """
        Extract and format compatibility notes from the parsed HTML.

        Args:
            soup (BeautifulSoup): Parsed HTML content.

        Returns:
            str: Formatted string of compatibility notes.
        """
        notes = []
        note_classes = [
            soup.find_all("p", class_="note__text note__text--problem"),
            soup.find_all("p", class_="note__text note__text--warning"),
            soup.find_all("p", class_="note__text note__text--info"),
        ]
        for note_class in note_classes:
            for text in note_class:
                note_type = text.contents[0].text.strip()
                note_text = text.contents[1].text.strip()
                formatted_note = {
                    "Problem:": f"- **Problem ->** {note_text}",
                    "Warning:": f"- **Warning ->** {note_text}",
                    "Note:": f"- **Note ->** {note_text}",
                    "Disclaimer:": f"- **Disclaimer ->** {note_text}",
                }.get(note_type, "")
                notes.append(formatted_note)

        return "\n**__COMPATIBILITY NOTES__**\n{}\n\n".format('\n'.join(notes))

    def format_power_consumption(self, product_message: str, wattage_element) -> str:
        """
        Format the total power consumption information.

        Args:
            product_message (str): The full product message.
            wattage_element: BeautifulSoup element containing wattage information.

        Returns:
            str: Formatted power consumption string.
        """
        if product_message.strip():
            wattage = wattage_element.text.split(":")[-1].strip()
            return f"{self.power_icon} **Total Estimated Power ->** {wattage}\n"
        return ""
    
    def find_country(self, country_elements: str) -> str:
        """
        Find the country of the list.

        Args:
            country_elements (list): List of country-related HTML elements.

        Returns:
        str: Country name.
        """
        selected_country = country_elements.find('option', selected=True)
        return (
            f"{self.earth_icon}"
            f"**Country ->** {selected_country.text}\n"
        )


    def format_total_price(self, product_message: str, price_elements: list) -> str:
        """
        Calculate and format the total price of the list.

        Args:
            product_message (str): The full product message.
            price_elements (list): List of price-related HTML elements.

        Returns:
            str: Formatted total price string.
        """
        if not product_message.strip():
            return "Empty"

        price = price_elements[-1].contents[0].text.strip()
        if not price_elements or price == "Price":
            price = "No Price Available"

        return (
            f"{self.price_icon}"
            f"**Total Price ->** {price}\n*After Rebates/Discounts/Taxes/Shipping*"
        )

    async def process_pcpartpicker_list(self, url: str) -> str:
        """
        Main method to scrape and process a PCPartPicker list.

        Args:
            url (str): The URL of the PCPartPicker list.

        Returns:
            str: Processed and formatted PCPartPicker list information.
        """
        domain = self.extract_domain(url)
        max_retries = 3

        if "pcpartpicker.com/b/" in url:
            url = await self.fetch_list_url(url, domain, max_retries)

        soup= await self.strainer_list(url, max_retries)

        component_elements = soup.find_all("td", class_=f"td__component td__component-{YEAR_IN_CLASS}")
        product_elements = soup.find_all("td", class_=f"td__name td__name-{YEAR_IN_CLASS}")
        price_elements = soup.find_all("td", class_=f"td__price td__price-{YEAR_IN_CLASS}")
        merchant_elements = soup.find_all("td", class_="td__where")
        wattage_element = soup.find(
            "a", class_="actionBox__actions--key-metric-breakdown"
        )
        country_elements = soup.find("select", class_="select select--small language-selector pp-country-select")
        print(wattage_element)
        if not all(
            [component_elements, product_elements, price_elements, merchant_elements, wattage_element, country_elements]
        ):
            PCPP_LOG.error("Cannot parse the HTML due to missing elements.")
            return "HTML parsing error due to missing required HTML elements"

        try:
            product_message = self.extract_product_details(
                domain,
                component_elements,
                product_elements,
                price_elements,
                merchant_elements,
            )
            compatibility_message = self.extract_compatibility_notes(soup)
            wattage_message = self.format_power_consumption(
                product_message, wattage_element
            )
            country = self.find_country(country_elements)
            price_message = self.format_total_price(product_message, price_elements)
        except Exception as e:
            PCPP_LOG.exception("HTML parsing error: %s", e)
            return f"HTML parsing error: {e}"

        pcpp_message = (
            f"{product_message}{compatibility_message}{wattage_message}{country}{price_message}"
        )

        if len(pcpp_message) > 4096:
            return (
                "Error in generating a PCPP list preview.\n"
                "The returned string exceeds Discord's max character limit of 4096 characters."
            )

        return pcpp_message

    async def fetch_list_url(self, url: str, domain: str, max_retries: int) -> str:
        """
        Fetch the actual list URL for completed builds.

        Args:
            url (str): The initial URL.
            domain (str): The base domain.
            max_retries (int): Maximum number of retry attempts.

        Returns:
            str: The actual list URL.

        Raises:
            Exception: If unable to fetch the list URL after max retries.
        """
        for attempt in range(max_retries, 0, -1):
            try:
                soup = await self.fetch_html_content(url, "span", "header-actions")
                new_url_element = soup.find("span", class_="header-actions")
                new_url_ending = new_url_element.a.get("href")
                return f"{domain}{new_url_ending}"
            except (AsyncioTimeoutError, ClientConnectionError) as e:
                server.info("Retrying, %s attempts left: %s", attempt, e)
            except (ClientPayloadError, ClientResponseError) as e:
                server.exception(e)
                raise
            except Exception as e:
                logging.exception(e)
                raise

        raise Exception("Failed to fetch list URL after maximum retries")

    async def strainer_list(self, url: str, max_retries: int) -> BeautifulSoup:
        """
        Fetch the content of a PCPartPicker list.

        Args:
            url (str): The URL of the list.
            max_retries (int): Maximum number of retry attempts.

        Returns:
            BeautifulSoup: Parsed HTML content of the list.

        Raises:
            Exception: If unable to fetch the list content after max retries.
        """
        tag_names = ["td", "a", "p", "select"]
        class_list = [
            f"td__component td__component-{YEAR_IN_CLASS}",
            f"td__name td__name-{YEAR_IN_CLASS}",
            f"td__price td__price-{YEAR_IN_CLASS}",
            f"td__price td__price-{YEAR_IN_CLASS} td__price--none",
            "td__where",
            "td__where td--empty",
            "td__where td__where--purchased",
            "select select--small language-selector pp-country-select",
            "actionBox__actions--key-metric-breakdown",
            "note__text note__text--problem",
            "note__text note__text--warning",
            "note__text note__text--info",
        ]

        for attempt in range(max_retries, 0, -1):
            try:
                return await self.fetch_html_content(url, tag_names, class_list)
            except (AsyncioTimeoutError, ClientConnectionError) as e:
                server.info("Retrying, %s attempts left: %s", attempt, e)
            except (ClientPayloadError, ClientResponseError) as e:
                server.exception(e)
                raise
            except Exception as e:
                logging.exception(e)
                raise

        raise Exception("Failed to fetch list content after maximum retries")


class PCPPUtility:
    """
    Utility class for handling PCPartPicker URL processing and preview generation.
    """

    @staticmethod
    def extract_unique_pcpp_urls(message_content: str) -> list[str]:
        """
        Extract and normalize unique PCPartPicker URLs from a message.

        Args:
            message_content (str): The content of the message to process.

        Returns:
            list[str]: A list of unique, normalized PCPartPicker URLs.
        """
        # Find all URLs matching the regex
        pcpp_urls = PCPP_VALID_URL_PATTERN.findall(message_content)

        # Remove duplicates while preserving order
        unique_urls = list(dict.fromkeys(pcpp_urls))

        # Normalize URLs to HTTPS and remove the "#view=" part
        return [
            parse.urlunparse(parse.urlparse(url)._replace(scheme="https")).replace(
                "#view=", ""
            )
            for url in unique_urls
        ]

    @staticmethod
    @alru_cache(maxsize=1024)
    async def generate_list_preview(url: str) -> discord.Embed:
        """
        Generate a preview embed for a PCPartPicker list URL.

        Args:
            url (str): The URL of the PCPartPicker list.

        Returns:
            discord.Embed: An embed object containing the preview of the PCPP list.

        Notes:
            Uses alru_cache to avoid repeated scraping for the same URL.
        """
        scraper = PCPPScraper()
        pcpp_message = await scraper.process_pcpartpicker_list(url)
        return discord.Embed(description=pcpp_message, color=ILOVEPCS_BLUE)


class PCPPInteractionHandler:
    """
    Handler for PCPartPicker-related Discord interactions.
    """

    @staticmethod
    def parse_interaction_ids(match: re.Match[str]) -> tuple[int, int]:
        """
        Parse channel and message IDs from a regex match.

        Args:
            match (re.Match[str]): The regex match object.

        Returns:
            tuple[int, int]: A tuple containing the channel ID and message ID.
        """
        channel_id = int(match["channel_id"])
        message_id = int(match["message_id"])
        timestamp = int(match["timestamp"])
        return channel_id, message_id, timestamp

    @staticmethod
    @alru_cache(maxsize=1024)
    async def get_msg_object_for_url(
        bot, channel_id: int, message_id: int, timestamp: int
    ) -> list[str]:
        """
        Retrieve PCPartPicker URLs from a specific Discord message.

        Args:
            bot (discord.Client): The bot instance.
            channel_id (int): The ID of the channel containing the message.
            message_id (int): The ID of the message.

        Returns:
            list[str]: A list of PCPartPicker URLs extracted from the message.
        """
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        return PCPPUtility.extract_unique_pcpp_urls(message.content)

    @staticmethod
    @alru_cache(maxsize=1024)
    async def send_preview(interaction: discord.Interaction, url: str) -> None:
        """
        Send a preview of a PCPartPicker list as an ephemeral message.

        Args:
            interaction (discord.Interaction): The Discord interaction object.
            url (str): The URL of the PCPartPicker list.
        """
        preview_embed = await PCPPUtility.generate_list_preview(url)
        await interaction.response.send_message(embed=preview_embed, ephemeral=True)


class PCPPButton(discord.ui.DynamicItem[discord.ui.Button], template=BUTTON_TEMPLATE):
    """
    A custom button for PCPartPicker list previews.
    """

    def __init__(self, channel_id: int, message_id: int, timestamp: int, url: str):
        self.channel_id = channel_id
        self.message_id = message_id
        self.timestamp = timestamp
        self.url = url
        super().__init__(
            discord.ui.Button(
                label="View Preview",
                style=discord.ButtonStyle.blurple,
                custom_id=f"button:channel:{self.channel_id}message:{self.message_id}timestamp:{self.timestamp}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        """
        Create a PCPPButton instance from a custom ID.

        Args:
            interaction (discord.Interaction): The Discord interaction object.
            item (discord.ui.Button): The button item.
            match (re.Match[str]): The regex match object for the custom ID.

        Returns:
            PCPPButton: An instance of the PCPPButton.
        """
        channel_id, message_id, timestamp = (
            PCPPInteractionHandler.parse_interaction_ids(match)
        )
        pcpp_urls = await PCPPInteractionHandler.get_msg_object_for_url(
            interaction.client, channel_id, message_id, timestamp
        )
        url = pcpp_urls[0]
        return cls(channel_id, message_id, timestamp, url)

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle the button press event.

        Args:
            interaction (discord.Interaction): The Discord interaction object.
        """
        await PCPPInteractionHandler.send_preview(interaction, self.url)


class PCPPMenu(discord.ui.DynamicItem[discord.ui.Select], template=MENU_TEMPLATE):
    """
    A custom select menu for multiple PCPartPicker list previews.
    """

    def __init__(
        self,
        channel_id: int,
        message_id: int,
        timestamp: int,
        options: list[discord.SelectOption],
    ) -> None:
        self.channel_id = channel_id
        self.message_id = message_id
        self.timestamp = timestamp
        self.options = options
        super().__init__(
            discord.ui.Select(
                placeholder="View Previews",
                custom_id=f"menu:channel:{self.channel_id}message:{self.message_id}timestamp:{self.timestamp}",
                options=self.options,
            )
        )

    @staticmethod
    def generate_options(pcpp_urls: list[str]) -> list[discord.SelectOption]:
        """
        Generate select options for PCPartPicker URLs.

        Args:
            pcpp_urls (list[str]): A list of PCPartPicker URLs.

        Returns:
            list[discord.SelectOption]: A list of SelectOption objects.
        """
        return [
            discord.SelectOption(label=f"List Preview {i}", value=url)
            for i, url in enumerate(pcpp_urls[:25], start=1)
        ]

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: re.Match[str],
        /,
    ):
        """
        Create a PCPPMenu instance from a custom ID.

        Args:
            interaction (discord.Interaction): The Discord interaction object.
            item (discord.ui.Select): The select menu item.
            match (re.Match[str]): The regex match object for the custom ID.

        Returns:
            PCPPMenu: An instance of the PCPPMenu.
        """
        channel_id, message_id, timestamp = (
            PCPPInteractionHandler.parse_interaction_ids(match)
        )
        pcpp_urls = await PCPPInteractionHandler.get_msg_object_for_url(
            interaction.client, channel_id, message_id, timestamp
        )
        options = cls.generate_options(pcpp_urls)
        return cls(channel_id, message_id, timestamp, options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle the select menu option selection.

        Args:
            interaction (discord.Interaction): The Discord interaction object.
        """
        await PCPPInteractionHandler.send_preview(interaction, self.item.values[0])
        await interaction.message.edit()  # Reset user choice after selection


class HandleLinks:
    @staticmethod
    def handle_valid_links(
        channel_id: int, message_id: int, timestamp: int, pcpp_urls: list[str]
    ) -> discord.Embed:
        """
        Handle valid PCPartPicker links by creating appropriate UI components.

        Args:
            message (discord.Message): The Discord message object.
            pcpp_urls (list[str]): A list of valid PCPartPicker URLs.
        """
        timestamp = str(timestamp.timestamp()).replace(".", "")
        preview_embed = PCPPMessage.create_preview_embed(pcpp_urls)
        view = discord.ui.View(timeout=None)

        if len(pcpp_urls) == 1:
            button = PCPPButton(channel_id, message_id, timestamp, pcpp_urls[0])
            view.add_item(button)

        else:
            options = PCPPMenu.generate_options(pcpp_urls)
            menu = PCPPMenu(channel_id, message_id, timestamp, options)
            view.add_item(menu)

        return preview_embed, view

    @staticmethod
    @lru_cache(maxsize=1)
    def handle_invalid_links() -> discord.Embed:
        """
        Handle invalid PCPartPicker links by sending an error message.

        Args:
            message (discord.Message): The Discord message object.
        """
        error_embed = discord.Embed(
            title=(
                "**One or more of your PCPartPicker link(s) is invalid. "
                "These links only make the associated list viewable to you. "
                "Please refer to the image below for guidance.**"
            ),
            color=ILOVEPCS_BLUE,
        )
        error_embed.set_image(url="https://i.imgur.com/O0TFvRc.jpeg")
        return error_embed


class PCPPMessage:
    """
    Handles message-related operations for PCPartPicker link previews.

    This class provides static methods to manage bot messages associated with
    user messages containing PCPartPicker links.
    """

    @staticmethod
    @alru_cache(maxsize=1024)
    async def extract_bot_msg_using_user_id(
        bot: commands.Bot, bot_message_ids: Tuple[int, ...], channel_id: int
    ) -> Tuple[discord.Message, ...]:
        """
        Fetch bot messages from a specific channel using their message IDs.

        Args:
            bot: The Discord bot instance
            bot_message_ids: Tuple of message IDs to fetch
            channel_id: ID of the channel containing the messages

        Returns:
            Tuple of fetched Discord messages
        """
        channel = bot.get_channel(channel_id)
        bot_messages = [
            await channel.fetch_message(message_id) for message_id in bot_message_ids
        ]
        return tuple(bot_messages)

    @staticmethod
    async def insert_bot_msg_ids(
        pcpp_message_id: int,
        invalid_bot_message_id: int,
        user_message_id: int,
        channel_id: int,
    ) -> None:
        """
        Insert bot message IDs into the database, managing table size.

        Args:
            pcpp_message_id: ID of the PCPP preview bot message
            invalid_bot_message_id: ID of the invalid link bot message
            user_message_id: ID of the original user message
            channel_id: ID of the channel where messages were sent
        """
        # Ensure table doesn't exceed maximum row count
        if (
            PCPPCog.pcpp_user_message_count >= PCPPCog.MAX_USER_MESSAGE_ID_COUNT
        ):  # Table cannot exceed 1000 rows
            try:
                await Database(
                    """
                    DELETE FROM pcpp_message_ids
                    WHERE user_msg_id = (SELECT user_msg_id FROM pcpp_message_ids LIMIT 1);
                    """
                ).run_query()
            except (OperationalError, DatabaseError) as db_error:
                SQL_LOG.exception("Cannot delete the row: %s", db_error)
            else:
                PCPPCog.pcpp_user_message_count -= 1

        # Insert new message IDs if table has space
        if PCPPCog.pcpp_user_message_count <= PCPPCog.MAX_USER_MESSAGE_ID_COUNT - 1:
            try:
                await Database(
                    """
                    INSERT INTO pcpp_message_ids(user_msg_id, pcpp_bot_msg_id, invalid_msg_id, channel_id)
                    VALUES(?, ?, ?, ?);
                    """,
                    (
                        user_message_id,
                        pcpp_message_id,
                        invalid_bot_message_id,
                        channel_id,
                    ),  # First ID - User, Second ID - Bot
                ).run_query(auto_commit=False)
            except (OperationalError, DatabaseError) as db_error:
                SQL_LOG.exception(
                    "Failed to insert the following data, rolling back.\n"
                    "User Message ID: %s\n"
                    "PCPP Preview Message ID: %s\n"
                    "Invalid Message ID: %s\n"
                    "Channel ID: %s\n"
                    "Error: %s",
                    user_message_id,
                    pcpp_message_id,
                    invalid_bot_message_id,
                    channel_id,
                    db_error,
                )
            else:
                PCPPCog.pcpp_user_message_count += 1
                await Database.conn.commit()

    @staticmethod
    @alru_cache(maxsize=1024)
    async def find_bot_msg_ids(user_msg_id: int) -> Tuple[Tuple[int, int], int]:
        """
        Retrieve bot message IDs and channel ID associated with a user message.

        Args:
            user_msg_id: ID of the user message to look up

        Returns:
            Tuple containing (pcpp_bot_msg_id, invalid_msg_id) and channel_id

        Raises:
            Error: If database lookup fails
        """
        try:
            # Fetch bot message IDs and channel ID from database
            database_result = await Database(
                """
                SELECT pcpp_bot_msg_id, invalid_msg_id, channel_id FROM pcpp_message_ids
                WHERE user_msg_id = ?;
                """,
                (user_msg_id,),
            ).run_query()
            pcpp_bot_msg_id, invalid_msg_id, channel_id = database_result[0]
        except (OperationalError, DatabaseError) as db_error:
            SQL_LOG.exception(
                "Failed to search the corresponding bot message id, channel_id and booleans from the user message: %s\n Error: %s",
                user_msg_id,
                db_error,
            )
            raise Error from db_error
        return (pcpp_bot_msg_id, invalid_msg_id), channel_id

    @staticmethod
    async def edit_pcpp_preview(
        bot_message: discord.Message,
        channel_id: int,
        user_msg_id: int,
        timestamp: datetime.datetime,
        pcpp_urls: List[str],
    ) -> None:
        """
        Edit an existing PCPP preview message with new embed and view.

        Args:
            bot_message: The bot message to edit
            channel_id: ID of the channel
            user_msg_id: ID of the original user message
            timestamp: Timestamp of the message edit
            pcpp_urls: List of PCPartPicker URLs
        """
        preview_embed, view = HandleLinks.handle_valid_links(
            channel_id, user_msg_id, timestamp, pcpp_urls
        )
        await bot_message.edit(embed=preview_embed, view=view)

    @staticmethod
    async def edit_invalid_link(bot_message: discord.Message) -> None:
        """
        Edit a message to show an invalid link error.

        Args:
            bot_message: The bot message to edit with invalid link error
        """
        error_embed = HandleLinks.handle_invalid_links()
        await bot_message.edit(embed=error_embed)

    @staticmethod
    async def placeholder_message(
        bot_message: discord.Message,
        no_pcpp_preview: bool = False,
        no_invalid_links: bool = False,
        edit: bool = False,
    ) -> Optional[discord.Message]:
        """
        Create or edit a placeholder message for various scenarios.

        Args:
            bot_message: The message to reply to or edit
            no_pcpp_preview: Flag for no PCPP previews available
            no_invalid_links: Flag for no invalid links detected
            edit: Whether to edit existing message or create a new reply

        Returns:
            Discord message if created, None otherwise
        """
        if no_pcpp_preview:
            embed = discord.Embed(
                title="No PCPP previews available.", color=ILOVEPCS_BLUE
            )
        elif no_invalid_links:
            embed = discord.Embed(
                title="No invalid PCPP links detected.", color=ILOVEPCS_BLUE
            )
        else:
            DISCORD_LOG.error("Failed to get a placeholder message.")
            return None

        if not edit:
            return await bot_message.reply(embed=embed)
        else:
            return await bot_message.edit(embed=embed, view=None)

    @staticmethod
    async def delete_message(
        user_msg_id: int, bot_messages: Tuple[discord.Message, ...]
    ) -> None:
        """
        Delete database record and associated bot messages.

        Args:
            user_msg_id: ID of the user message to delete
            bot_messages: Tuple of bot messages to delete
        """
        try:
            # Remove database entry for the user message
            await Database(
                """
                DELETE FROM pcpp_message_ids
                WHERE user_msg_id = ?;
                """,
                (user_msg_id,),
            ).run_query()

            # Delete all associated bot messages
            for bot_message in bot_messages:
                await bot_message.delete()
        except (OperationalError, DatabaseError) as db_error:
            SQL_LOG.exception(
                "Cannot delete the row containing user id or delete the message: %s. Error: %s",
                user_msg_id,
                db_error,
            )
        else:
            PCPPCog.pcpp_user_message_count -= 1

    @staticmethod
    async def edit_pcpp_message(
        bot_messages: Tuple[discord.Message, discord.Message],
        message: discord.Message,
        pcpp_bools: Tuple[List[str], Union[str, bool]],
        before_pcpp_bools: Tuple[List[str], Union[str, bool]],
    ) -> Optional[discord.Message]:
        """
        Edit PCPP preview messages based on changes in message content.

        Args:
            bot_messages: Tuple of bot messages (PCPP preview and invalid link)
            message: Original Discord message
            pcpp_bools: Tuple of (PCPP URLs, invalid link status) after edit
            before_pcpp_bools: Tuple of (PCPP URLs, invalid link status) before edit

        Returns:
            Optional bot message if any edits were made
        """
        pcpp_urls, invalid_link = pcpp_bools
        pcpp_message, invalid_link_message = bot_messages

        # No URLs or invalid links, no action needed
        if not any((pcpp_urls, invalid_link)):
            return None

        before_pcpp_urls, before_invalid_link = before_pcpp_bools

        # Various conditions for editing messages
        if (all([pcpp_urls, not invalid_link]) and all(before_pcpp_bools)) or (
            all([pcpp_urls, not invalid_link, before_invalid_link])
        ):
            await PCPPMessage.edit_pcpp_preview(
                pcpp_message,
                message.channel.id,
                message.id,
                message.edited_at,
                pcpp_urls,
            )
            await PCPPMessage.placeholder_message(
                invalid_link_message, no_invalid_links=True, edit=True
            )

        elif all([not pcpp_urls, invalid_link]) and all(before_pcpp_bools):
            await PCPPMessage.placeholder_message(
                pcpp_message, no_pcpp_preview=True, edit=True
            )

        elif (
            (all([pcpp_urls, invalid_link]) and all(before_pcpp_bools))
            or (all([pcpp_urls, not invalid_link, before_pcpp_urls]))
            or (all([pcpp_urls, invalid_link, before_invalid_link]))
        ):
            await PCPPMessage.edit_pcpp_preview(
                pcpp_message,
                message.channel.id,
                message.id,
                message.edited_at,
                pcpp_urls,
            )

        elif all([pcpp_urls, invalid_link, before_pcpp_urls]):
            await PCPPMessage.edit_pcpp_preview(
                pcpp_message,
                message.channel.id,
                message.id,
                message.edited_at,
                pcpp_urls,
            )
            await PCPPMessage.edit_invalid_link(invalid_link_message)

        elif all([not pcpp_urls, invalid_link, before_pcpp_urls]):
            await PCPPMessage.placeholder_message(
                pcpp_message, no_pcpp_preview=True, edit=True
            )
            await PCPPMessage.edit_invalid_link(invalid_link_message)

        elif all([not pcpp_urls, invalid_link, before_invalid_link]):
            return None

    @staticmethod
    async def prepare_new_message(
        message: discord.Message,
        pcpp_bools: Tuple[List[str], Union[str, bool]],
    ) -> None:
        """
        Prepare and send bot messages for a new user message with PCPP links.

        Args:
            message: Original Discord message
            pcpp_bools: Tuple of (PCPP URLs, invalid link status)
        """
        pcpp_message: Optional[discord.Message] = None
        invalid_bot_message: Optional[discord.Message] = None
        pcpp_urls, invalid_link = pcpp_bools

        # No URLs or invalid links, no action needed
        if not any((pcpp_urls, invalid_link)):
            return

        # Handle PCPP URLs preview
        if pcpp_urls:
            preview_embed, view = HandleLinks.handle_valid_links(
                message.channel.id, message.id, message.created_at, pcpp_urls
            )
            pcpp_message = await message.reply(embed=preview_embed, view=view)
        elif not pcpp_urls:
            pcpp_message = await PCPPMessage.placeholder_message(
                message, no_pcpp_preview=True
            )

        # Handle invalid links
        if invalid_link:
            error_embed = HandleLinks.handle_invalid_links()
            invalid_bot_message = await message.reply(embed=error_embed)
        elif not invalid_link:
            invalid_bot_message = await PCPPMessage.placeholder_message(
                message, no_invalid_links=True
            )

        # Insert message IDs into database
        await PCPPMessage.insert_bot_msg_ids(
            pcpp_message.id,
            invalid_bot_message.id,
            message.id,
            message.channel.id,
        )

    @staticmethod
    def create_preview_embed(urls: List[str]) -> discord.Embed:
        """
        Create an embed for PCPartPicker list previews.

        Args:
            urls: A list of PCPartPicker URLs.

        Returns:
            Discord embed object with preview information
        """
        url_list = "\n".join(urls)
        return discord.Embed(
            description=textwrap.dedent(
                f"""
                These are the previews for the following links:
                {url_list}
                """
            ),
            color=ILOVEPCS_BLUE,
        )


class PCPPCog(commands.Cog):
    """
    Cog for handling PCPartPicker list previews in Discord.

    Attributes:
        MAX_USER_MESSAGE_ID_COUNT (int): Maximum number of user message IDs to track.
    """

    MAX_USER_MESSAGE_ID_COUNT: int = 1024
    pcpp_user_message_count: int

    def __init__(self, bot: commands.Bot):
        """
        Initialize the PCPPCog with the Discord bot instance.

        Args:
            bot (commands.Bot): The Discord bot instance.
        """
        self.bot: commands.Bot = bot

    @classmethod
    async def find_row_count(cls) -> None:
        """
        Asynchronously count the rows in the PCPP message IDs database table.
        """
        cls.pcpp_user_message_count = await Database.count_rows("pcpp_message_ids")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Listen for messages containing PCPartPicker URLs and handle them.

        Args:
            message (discord.Message): The Discord message object.
        """
        if message.author == self.bot.user:
            return

        # This list can contain the PCPP list or the link invalid response.
        pcpp_urls: List[str]
        invalid_link: Optional[str]
        pcpp_urls, invalid_link = self.pcpp_regex_search(message.content)
        await PCPPMessage.prepare_new_message(
            message, pcpp_bools=(pcpp_urls, invalid_link)
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """
        Handle message edit events for PCPartPicker URLs.

        Args:
            before (discord.Message): The message before editing
            after (discord.Message): The message after editing
        """
        if before.content == after.content:
            return

        pcpp_urls: List[str]
        invalid_link: Optional[str]
        pcpp_urls, invalid_link = self.pcpp_regex_search(after.content)

        before_pcpp_urls: List[str]
        before_invalid_link: Optional[str]
        before_pcpp_urls, before_invalid_link = self.pcpp_regex_search(before.content)

        bot_msg_ids: List[int]
        channel_id_to_fetch: Optional[int]
        bot_msg_ids, channel_id_to_fetch = await PCPPMessage.find_bot_msg_ids(after.id)

        if not all([all(bot_msg_ids), channel_id_to_fetch]):
            return  # Cannot edit message without a valid bot/channel id

        if any([before_pcpp_urls, before_invalid_link]) and any(
            [pcpp_urls, invalid_link]
        ):
            # This list can contain the PCPP list or the link invalid response.
            if (before_pcpp_urls, before_invalid_link) == (pcpp_urls, invalid_link):
                # This checks if the lists found in dict are all still in new message
                return
            else:
                bot_messages = await PCPPMessage.extract_bot_msg_using_user_id(
                    self.bot, bot_msg_ids, channel_id_to_fetch
                )
                await PCPPMessage.edit_pcpp_message(
                    bot_messages,
                    after,
                    pcpp_bools=(pcpp_urls, invalid_link),
                    before_pcpp_bools=(before_pcpp_urls, before_invalid_link),
                )
        elif any([before_pcpp_urls, before_invalid_link]) and not any(
            [pcpp_urls, invalid_link]
        ):
            bot_messages = await PCPPMessage.extract_bot_msg_using_user_id(
                self.bot, bot_msg_ids, channel_id_to_fetch
            )
            await PCPPMessage.delete_message(after.id, bot_messages)
        else:
            return

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """
        Handle message deletion events for PCPartPicker URLs.

        Args:
            message (discord.Message): The deleted message.
        """
        pcpp_urls: List[str]
        invalid_link: Optional[str]
        pcpp_urls, invalid_link = self.pcpp_regex_search(message.content)

        if any([pcpp_urls, invalid_link]):
            bot_msg_ids: List[int]
            channel_id_to_fetch: Optional[int]
            bot_msg_ids, channel_id_to_fetch = await PCPPMessage.find_bot_msg_ids(
                message.id
            )
            bot_messages = await PCPPMessage.extract_bot_msg_using_user_id(
                self.bot, bot_msg_ids, channel_id_to_fetch
            )
            await PCPPMessage.delete_message(message.id, bot_messages)

    @lru_cache(maxsize=1024)
    def pcpp_regex_search(
        self, message_content: str
    ) -> Tuple[List[str], Optional[str]]:
        """
        Search for PCPartPicker URLs and invalid links in a message.

        Args:
            message_content (str): The content of the message to search.

        Returns:
            Tuple[List[str], Optional[str]]: A tuple containing:
            - A list of unique PCPartPicker URLs found
            - An invalid link if found, otherwise None
        """
        pcpp_urls = PCPPUtility.extract_unique_pcpp_urls(message_content)
        invalid_link = INVALID_URL_PATTERN.search(message_content)
        if invalid_link:
            invalid_link = invalid_link.group()
        return pcpp_urls, invalid_link


async def setup(bot: commands.Bot) -> None:
    """
    Setup function to add the cog to the bot.

    Args:
        bot (commands.Bot): The Discord bot instance.
    """
    bot.add_dynamic_items(PCPPButton, PCPPMenu)
    cog_instance = PCPPCog(bot)
    await bot.add_cog(cog_instance)
    await PCPPCog.find_row_count()
