import logging
import re
import textwrap
import urllib.parse as parse
from asyncio import TimeoutError as AsyncioTimeoutError
from functools import lru_cache

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
    "button:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)"
)
MENU_TEMPLATE: str = "menu:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)"


class PCPPScraper:
    """
    A class for scraping and processing PCPartPicker content.
    """

    def __init__(self) -> None:
        self.compatibility_icons = {
            "Problem:": "<:cross:1144351182781943898>",
            "Warning:": "<:exclaimation:1144670756794535996>",
            "Note:": "<:rules:1144938040100388904>",
            "Disclaimer:": None,
        }
        self.power_icon = "\U0001F50C"
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
                f"**{component_type}:** {product_name}{product_link}{purchase}"
            )

        return "\n".join(details) + "\n"

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
            price = f" - {price_contents[-2].text.strip()}"
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
                price = " - No Prices Available"
            elif merchant_contents[-1] != "Purchased":
                price = f" - {price_contents[-1].text} (Custom Price)"
            else:
                price = f" - {price_contents[-1].text} (Custom Price | Purchased)"
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
                    "Problem:": f"{self.compatibility_icons[note_type]} **PROBLEM!** {note_text}",
                    "Warning:": f"{self.compatibility_icons[note_type]} **WARNING!** {note_text}",
                    "Note:": f"{self.compatibility_icons[note_type]} **{note_type}** {note_text}",
                    "Disclaimer:": f"> {note_type} {note_text}\n \n",
                }.get(note_type, "")
                notes.append(formatted_note)

        return "\n".join(notes) + "\n"

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
            return f"{self.power_icon} **Total Estimated Power:** {wattage}\n"
        return ""

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
            f"**Total Price:** {price}\n*After Rebates/Discounts/Taxes/Shipping*"
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

        soup = await self.fetch_list_content(url, max_retries)

        component_elements = soup.find_all("td", class_="td__component")
        product_elements = soup.find_all("td", class_="td__name")
        price_elements = soup.find_all("td", class_="td__price")
        merchant_elements = soup.find_all("td", class_="td__where")
        wattage_element = soup.find(
            "a", class_="actionBox__actions--key-metric-breakdown"
        )

        if not all(
            [component_elements, product_elements, price_elements, wattage_element]
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
            price_message = self.format_total_price(product_message, price_elements)
        except Exception as e:
            PCPP_LOG.exception("HTML parsing error: %s", e)
            return f"HTML parsing error: {e}"

        pcpp_message = (
            f"{product_message}{compatibility_message}{wattage_message}{price_message}"
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

    async def fetch_list_content(self, url: str, max_retries: int) -> BeautifulSoup:
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
        tag_names = ["td", "a", "p"]
        classes = [
            "td__component",
            "td__name",
            "td__price",
            "td__price td__price--none",
            "td__where",
            "td__where td--empty",
            "td__where td__where--purchased",
            "actionBox__actions--key-metric-breakdown",
            "note__text note__text--problem",
            "note__text note__text--warning",
            "note__text note__text--info",
        ]

        for attempt in range(max_retries, 0, -1):
            try:
                return await self.fetch_html_content(url, tag_names, classes)
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
        return discord.Embed(description=pcpp_message, color=9806321)


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
        return channel_id, message_id

    @staticmethod
    @alru_cache(maxsize=1024)
    async def fetch_pcpp_urls_persist(
        bot, channel_id: int, message_id: int
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

    def __init__(self, channel_id: int, message_id: int, url: str):
        self.channel_id = channel_id
        self.message_id = message_id
        self.url = url
        super().__init__(
            discord.ui.Button(
                label="View Preview",
                style=discord.ButtonStyle.blurple,
                custom_id=f"button:channel:{self.channel_id}message:{self.message_id}",
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
        channel_id, message_id = PCPPInteractionHandler.parse_interaction_ids(match)
        pcpp_urls = await PCPPInteractionHandler.fetch_pcpp_urls_persist(
            interaction.client, channel_id, message_id
        )
        url = pcpp_urls[0]
        return cls(channel_id, message_id, url)

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
        self, channel_id: int, message_id: int, options: list[discord.SelectOption]
    ) -> None:
        self.channel_id = channel_id
        self.message_id = message_id
        self.options = options
        super().__init__(
            discord.ui.Select(
                placeholder="View Previews",
                custom_id=f"menu:channel:{self.channel_id}message:{self.message_id}",
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
        channel_id, message_id = PCPPInteractionHandler.parse_interaction_ids(match)
        pcpp_urls = await PCPPInteractionHandler.fetch_pcpp_urls_persist(
            interaction.client, channel_id, message_id
        )
        options = cls.generate_options(pcpp_urls)
        return cls(channel_id, message_id, options)

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
        channel_id, message_id, pcpp_urls: list[str]
    ) -> discord.Embed:
        """
        Handle valid PCPartPicker links by creating appropriate UI components.

        Args:
            message (discord.Message): The Discord message object.
            pcpp_urls (list[str]): A list of valid PCPartPicker URLs.
        """
        preview_embed = PCPPMessage.create_preview_embed(pcpp_urls)
        view = discord.ui.View(timeout=None)

        if len(pcpp_urls) == 1:
            button = PCPPButton(channel_id, message_id, pcpp_urls[0])
            view.add_item(button)
        else:
            options = PCPPMenu.generate_options(pcpp_urls)
            menu = PCPPMenu(channel_id, message_id, options)
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
            color=9806321,
        )
        error_embed.set_image(url="https://i.imgur.com/O0TFvRc.jpeg")
        return error_embed


class PCPPMessage:
    @staticmethod
    @alru_cache(maxsize=1024)
    async def extract_bot_msg_using_user_id(
        bot, bot_msg_ids, channel_id
    ) -> discord.Message:
        channel = bot.get_channel(channel_id)
        return tuple(
            [await channel.fetch_message(message_id) for message_id in bot_msg_ids]
        )

    @staticmethod
    async def insert_bot_msg_ids(
        pcpp_message_id,
        invalid_bot_message_id,
        user_message_id,
        channel_id,
    ):

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
            except (OperationalError, DatabaseError) as e:
                SQL_LOG.exception("Cannot delete the row: %s", e)
            else:
                PCPPCog.pcpp_user_message_count -= 1

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
            except (OperationalError, DatabaseError) as e:
                SQL_LOG.exception(
                    "Failed to insert the following data, rolling back.\nUser Message ID: %s\n PCPP Preview Message ID: %s\n Invalid Message ID: %s\n Channel ID: %s\n Error: %s",
                    user_message_id,
                    pcpp_message_id,
                    invalid_bot_message_id,
                    channel_id,
                    e,
                )
            else:
                PCPPCog.pcpp_user_message_count += 1
                await Database.conn.commit()

    @staticmethod
    async def find_bot_msg_ids(user_msg_id: int):
        try:
            select_data = await Database(
                """
                SELECT pcpp_bot_msg_id, invalid_msg_id, channel_id FROM pcpp_message_ids
                WHERE user_msg_id = ?;
                """,
                (user_msg_id,),
            ).run_query()
            pcpp_bot_msg_id, invalid_msg_id, channel_id = select_data[0]
        except (OperationalError, DatabaseError) as e:
            SQL_LOG.exception(
                "Failed to search the corresponding bot message id, channel_id and booleans from the user message: %s\n Error: %s",
                user_msg_id,
                e,
            )
            raise Error from e
        return [pcpp_bot_msg_id, invalid_msg_id], channel_id

    @staticmethod
    async def edit_pcpp_preview(bot_message, message, pcpp_urls):
        preview_embed, view = HandleLinks.handle_valid_links(
            bot_message.id, message.id, pcpp_urls
        )
        await bot_message.edit(preview_embed, view)

    @staticmethod
    async def edit_invalid_link(bot_message):
        error_embed = HandleLinks.handle_invalid_links()
        await bot_message.edit(error_embed)

    @staticmethod
    async def placeholder_message(
        bot_message: discord.Message,
        no_pcpp_preview: bool = True,
        no_invalid_links: bool = True,
        edit: bool = False,
    ) -> discord.Message:

        if no_pcpp_preview:
            embed = discord.Embed(
                title=("No invalid PCPP links detected."), color=9806321
            )
        elif no_invalid_links:
            embed = discord.Embed(title=("No PCPP previews available."), color=9806321)
        else:
            DISCORD_LOG.error("Failed to get a placehold message.")
            return

        if not edit:
            return await bot_message.reply(embed=embed)
        else:
            return await bot_message.edit(embed=embed)

    @staticmethod
    async def delete_message(user_msg_id, bot_messages) -> None:
        try:
            await Database(
                """
                DELETE FROM pcpp_message_ids
                WHERE user_msg_id = ?;
                """,
                (user_msg_id,),
            ).run_query()
            for bot_message in bot_messages:
                await bot_message.delete()
        except (OperationalError, DatabaseError) as e:
            SQL_LOG.exception(
                "Cannot delete the row containing user id or delete the message: %s. Error: %s",
                user_msg_id,
                e,
            )
        else:
            PCPPCog.pcpp_user_message_count -= 1

    @staticmethod
    async def edit_pcpp_message(
        bot_messages: tuple[discord.Message, discord.Message],
        user_msg_id: int,
        pcpp_bools: tuple,
        before_pcpp_bools: tuple,
    ) -> discord.Message:
        """
        Args:
            message (discord.Message): The Discord message object.
        Returns:
            bot_message_list discord.Message: Message object of the bot's reply.
        """

        pcpp_urls, invalid_link = pcpp_bools
        pcpp_message, invalid_link_message = bot_messages
        if not any((pcpp_urls, invalid_link)):
            return
        before_pcpp_urls, before_invalid_link = before_pcpp_bools

        if (all([pcpp_urls, not invalid_link]) and all(before_pcpp_bools)) or (
            all([pcpp_urls, not invalid_link, before_invalid_link])
        ):
            await PCPPMessage.edit_pcpp_preview(pcpp_message, user_msg_id, pcpp_urls)
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
            await PCPPMessage.edit_pcpp_preview(pcpp_message, user_msg_id, pcpp_urls)

        elif all([pcpp_urls, invalid_link, before_pcpp_urls]):
            await PCPPMessage.edit_pcpp_preview(pcpp_message, user_msg_id, pcpp_urls)
            await PCPPMessage.edit_invalid_link(invalid_link_message)

        elif all([not pcpp_urls, invalid_link, before_pcpp_urls]):
            await PCPPMessage.placeholder_message(
                pcpp_message, no_pcpp_preview=True, edit=True
            )
            await PCPPMessage.edit_invalid_link(invalid_link_message)

        elif all([not pcpp_urls, invalid_link, before_invalid_link]):
            return

    @staticmethod
    async def prepare_new_message(
        message: discord.Message,
        pcpp_bools: tuple,
    ) -> None:
        pcpp_message = None
        invalid_bot_message = None
        pcpp_urls, invalid_link = pcpp_bools
        if not any((pcpp_urls, invalid_link)):
            return

        if pcpp_urls:
            preview_embed, view = HandleLinks.handle_valid_links(
                message.channel.id, message.id, pcpp_urls
            )
            pcpp_message: discord.Message = await message.reply(
                embed=preview_embed, view=view
            )
        elif not pcpp_urls:
            pcpp_message = await PCPPMessage.placeholder_message(
                message, no_pcpp_preview=True
            )
        if invalid_link:
            error_embed = HandleLinks.handle_invalid_links()
            invalid_bot_message: discord.Message = await message.reply(
                embed=error_embed
            )
        elif not invalid_link:
            invalid_bot_message = await PCPPMessage.placeholder_message(
                message, no_invalid_links=True
            )

        await PCPPMessage.insert_bot_msg_ids(
            pcpp_message.id,
            invalid_bot_message.id,
            message.id,
            message.channel.id,
        )

    @staticmethod
    def create_preview_embed(urls: list[str]) -> discord.Embed:
        """
        Create an embed for PCPartPicker list previews.

        Args:
            urls (list[str]): A list of PCPartPicker URLs.

        Returns:
            discord.Embed: An embed object with the preview information.
        """
        url_list = "\n".join(urls)
        return discord.Embed(
            description=textwrap.dedent(
                f"""
            These are the previews for the following links:
            {url_list}
            To finanically support us without any additional cost to you, please use the affiliate links listed in <#1306012582892535849> (`🛠┃freq-part-recs`).
            If you found a better deal, please let `@Oquenbier` know.
            """
            ),
            color=9806321,
        )


class PCPPCog(commands.Cog):
    """
    Cog for handling PCPartPicker list previews in Discord.
    """

    MAX_USER_MESSAGE_ID_COUNT = 2

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @classmethod
    async def find_row_count(cls):
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
        pcpp_urls, invalid_link = self.pcpp_regex_search(message.content)
        await PCPPMessage.prepare_new_message(
            message, pcpp_bools=(pcpp_urls, invalid_link)
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """
        'before' contains the message before the edit
        'after' contains the message after the edit
        """

        if before.content == after.content:
            return

        pcpp_urls, invalid_link = self.pcpp_regex_search(after.content)
        before_pcpp_urls, before_invalid_link = self.pcpp_regex_search(before.content)
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
                bot_messages = PCPPMessage.extract_bot_msg_using_user_id(
                    self.bot, bot_msg_ids, channel_id_to_fetch
                )
                await PCPPMessage.edit_pcpp_message(
                    bot_messages,
                    after.id,
                    pcpp_bools=(pcpp_urls, invalid_link),
                    before_pcpp_bools=(before_pcpp_urls, before_invalid_link),
                )
        elif any([before_pcpp_urls, before_invalid_link]) and not any(
            [pcpp_urls, invalid_link]
        ):
            bot_messages = PCPPMessage.extract_bot_msg_using_user_id(
                self.bot, bot_msg_ids, channel_id_to_fetch
            )
            PCPPMessage.delete_message(after.id, bot_messages)
        else:
            return

    @commands.Cog.listener()
    async def on_message_delete(self, message) -> None:
        pcpp_urls, invalid_link = self.pcpp_regex_search(message.content)
        if any([pcpp_urls, invalid_link]):
            bot_msg_ids, channel_id_to_fetch = await PCPPMessage.find_bot_msg_ids(
                message.id
            )
            bot_messages = PCPPMessage.extract_bot_msg_using_user_id(
                self.bot, bot_msg_ids, channel_id_to_fetch
            )
            PCPPMessage.delete_message(message.id, bot_messages)

    @lru_cache(maxsize=1024)
    def pcpp_regex_search(self, message_content):
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
