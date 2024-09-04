import asyncio
import logging
import re
import sys
import urllib.parse as parse

import discord
from async_lru import alru_cache
from aiohttp import ClientConnectionError, ClientPayloadError, ClientResponseError
from bs4 import BeautifulSoup, SoupStrainer
from discord.ext import commands


sys.path.append(r"E:\Discord Bot Files")

from sessions import SessionManager

pcpp_log = logging.getLogger("pcpp_scraper")

# Constants and regex patterns for identifying PCPartPicker URLs
PCPP_LIST_REGEX: re.Pattern[str] = re.compile(
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

WRONG_LINK_REGEX: re.Pattern[str] = re.compile(
    r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com/list/?(?:(?:by_merchant/?)|(?![a-z0-9/]))",
    re.IGNORECASE,
)
DOMAIN_REGEX: re.Pattern[str] = re.compile(
    r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com", re.IGNORECASE
)

BUTTON_TEMPLATE: str = (
    "button:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)"
)
MENU_TEMPLATE: str = "menu:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)"


class PCPPScraper:
    """
    Methods used to scrape the required content from PCPartPicker.
    """

    def __init__(self) -> None:
        self.compatibility_emojis = {
            "Problem:": "<:cross:1144351182781943898>",
            "Warning:": "<:exclaimation:1144670756794535996>",
            "Note:": "<:rules:1144938040100388904>",
            "Disclaimer:": None,
        }
        self.power_emoji = "\U0001F50C"
        self.cash_emoji = "\U0001F4B8"

    async def scrape_pcpartpicker(self, url, tag_name, class_list) -> BeautifulSoup:
        """
        Fetch the HTML content from the given PCPartPicker URL.
        """
        try:
            strainer = SoupStrainer(
                tag_name, class_=class_list
            )  # Filters the HTML for efficiency
            page = await SessionManager.request(url)
            soup = BeautifulSoup(page, "lxml", parse_only=strainer)
            return soup
        except ClientConnectionError as e:  # Raises exception to pcpartpicker_main
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
            raise Exception(
                f"Some Exception related to the network request has occured: {e}"
            ) from e

    def pcpp_domain(self, url) -> str:
        """
        Retrieve the base domain from the URL.
        """
        domain = DOMAIN_REGEX.match(url)
        return url[: domain.end()]

    def get_name_and_no_link(self, product_name) -> tuple[str, str]:
        """
        Extract the product name and remove brackets if no link is available.
        """
        product_name = product_name[1:-1]
        product_link = ""
        return product_name, product_link

    def extract_product_info(
        self,
        domain: str,
        component_elements: list[str],
        product_elements: list[str],
        price_elements: list[str],
    ) -> str:
        """
        Extracts product name, link, and price from the HTML elements.
        Links are not available for custom parts.
        """
        message = []

        for (
            component_type_element,
            product_element,
            product_price_element,
        ) in zip(component_elements, product_elements, price_elements):
            component_type = component_type_element.contents[1].text.strip()
            product_name, product_link = self.extract_product_name_and_link(
                product_element, domain
            )

            product_price_value = self.extract_product_price(
                product_price_element.contents
            )

            message.append(
                f"**{component_type}:** {product_name}{product_link}{product_price_value}"
            )

        return "\n".join(message) + "\n"

    def extract_product_name_and_link(
        self, product_element, domain: str
    ) -> tuple[str, str]:
        """
        Extracts product name and link from a product element.
        """
        product_contents = product_element.contents
        if len(product_contents) >= 2:
            product_name = f"[{product_contents[1].text.strip()}]"
            find_link = str(product_contents)
            if (
                "a href" in find_link and "#view_custom_part" not in find_link
            ):  # Checks if link is findable.
                product_link = f"({domain}{product_element.a.get('href').strip()})"
            else:
                product_name, product_link = self.get_name_and_no_link(product_name)
        else:
            product_name = product_contents[0].text.strip()
            product_link = ""

        return product_name, product_link

    def extract_product_price(self, price_contents) -> str:
        """
        Extracts the product price from a price element.
        """
        if len(price_contents) >= 2:
            price_key = f" - {price_contents[-2].text.strip()}"
        else:
            price_key = " - No Prices"

        price_dict = {
            " - No Prices": " - No Price Available",
            " - Price": f" - {price_contents[-1].text.strip()} (Custom Price)",
        }

        return price_dict.get(price_key, price_key)

    def get_compatibility_notes(self, soup) -> str:
        """
        Extracts compatibility notes from the page.
        """
        message = []
        class_list = [
            soup.find_all("p", class_="note__text note__text--problem"),
            soup.find_all("p", class_="note__text note__text--warning"),
            soup.find_all("p", class_="note__text note__text--info"),
        ]
        for note_class in class_list:
            for text in note_class:
                note_type = text.contents[0].text.strip()
                note_text = text.contents[1].text.strip()
                note_dict = {
                    "Problem:": f"{self.compatibility_emojis[note_type]} **PROBLEM!** {note_text}",
                    "Warning:": f"{self.compatibility_emojis[note_type]} **WARNING!** {note_text}",
                    "Note:": f"{self.compatibility_emojis[note_type]} **{note_type}** {note_text}",
                    "Disclaimer:": f"> {note_type} {note_text}\n \n",
                }
                message.append(note_dict.get(note_type, ""))

        return "\n".join(message) + "\n"

    def extract_power_wattage(self, product_message, wattage_elements) -> str:
        """
        Extracts the total power wattage from the list.
        """
        if product_message.strip():
            wattage = wattage_elements.text.split(":")[
                -1
            ].strip()  # Get the wattage number
            return f"{self.power_emoji} **Total Estimated Power:** {wattage}\n"
        else:
            return ""

    def calculate_total_price(self, product_message, price_elements) -> str:
        """
        Calculates the total price of the list.
        """
        if not product_message.strip():
            return "Empty"
        else:
            price_check = price_elements[-1].contents[0].text.strip()
            if not price_elements or price_check == "Price":
                price_check = "No Price Available"
            return (
                f"{self.cash_emoji}"
                f"**Total Price:** {price_check}\n*After Rebates/Discounts/Taxes/Shipping*"
            )

    async def pcpartpicker_main(self, url) -> str:
        """
        Main method to scrape the PCPartPicker list.
        """

        domain = self.pcpp_domain(url)  # Finds domain of the link.

        try:
            if (
                "pcpartpicker.com/b/" in url
            ):  # Checks if it's a link from "Completed Builds" section which has "/b/" in the url.
                soup = await self.scrape_pcpartpicker(url, "span", "header-actions")
                find_new_url_ending = soup.select("span.header-actions")
                new_url_ending = find_new_url_ending[0].a.get("href")
                url = f"{domain}{new_url_ending}"
            tag_name_list = ["td", "a", "p"]
            class_list = [
                "td__component",
                "td__name",  # Product Name
                "td__price",  # Product Price
                "actionBox__actions--key-metric-breakdown",  # Wattage
                "note__text note__text--problem",
                "note__text note__text--warning",
                "note__text note__text--info",  # Note and disclaimer
            ]
            soup = await self.scrape_pcpartpicker(url, tag_name_list, class_list)

        except Exception as e:
            logging.exception(e)  # Log the exception
            return str(
                e
            )  # Returns the message whatever was raised in scrape_pcpartpicker.

        component_elements = soup.find_all("td", class_="td__component")
        product_elements = soup.find_all("td", class_="td__name")
        price_elements = soup.find_all("td", class_="td__price")
        wattage_elements = soup.find("a", class_= "actionBox__actions--key-metric-breakdown")
        elements_list = [
            component_elements,
            product_elements,
            price_elements,
            wattage_elements,
        ]

        if any(
            not element for element in elements_list
        ):  # Checks for avaliable elements that can be parsed. If one element from elements_list returns empty list then it returns parsing error.
            pcpp_log.error("Cannot parse the HTML due to a missing element.")
            return "HTML parsing error due to a missing required HTML element"
        try:
            product_message = self.extract_product_info(domain, *elements_list[:3])
            compatibility_message = self.get_compatibility_notes(soup)
            wattage_message = self.extract_power_wattage(
                product_message, wattage_elements
            )
            price_message = self.calculate_total_price(product_message, price_elements)
        except Exception as e:
            pcpp_log.exception("HTML parsing error: %s")
            return f"HTML parsing error: {e}"
        pcpp_message = (
            f"{product_message}{compatibility_message}{wattage_message}{price_message}"
        )

        if len(pcpp_message) > 4096:
            pcpp_message = (
                f"Error in generating a PCPP list preview.\n"
                f"The returned string exceeds Discord's max character limit of 4096 characters."
            )

        return pcpp_message


class OnMessageAndItemHelper:
    """
    Utility functions to reduce redundancy in the code for sending previews.
    """

    @staticmethod
    def find_number_of_lists(message_content: str) -> list[str]:
        """
        Extracts unique PCPartPicker URLs from the message content, normalizes and encodes them.
        """
        # Find all URLs matching the regex
        pcpp_url_list = PCPP_LIST_REGEX.findall(message_content)

        # Remove duplicates by converting the list to a set and then back to a list
        unique_urls = list(
            dict.fromkeys(pcpp_url_list)
        )  # Use dict keys for ordered urls

        # Normalize URLs to HTTPS and remove the "#view=" part
        encoded_url_list = [
            parse.urlunparse(parse.urlparse(url)._replace(scheme="https")).replace(
                "#view=", ""
            )
            for url in unique_urls
        ]
        return encoded_url_list

    @staticmethod
    @alru_cache(maxsize=1024)
    async def fetch_list_preview(url: str) -> discord.Embed:
        """
        Calls the scraper to get the PCPP message for a given URL and caches the result.

        Parameters:
        - url (str): The URL of the PCPartPicker list to scrape.

        Returns:
        - discord.Embed: An embed object containing the preview of the PCPP list.

        Notes:
        - Uses alru_cache to avoid repeated scraping for the same URL.
        - Ensure that PCPPScraper initialization and requests are efficient.
        """
        scraper = PCPPScraper()
        pcpp_message = await scraper.pcpartpicker_main(url)
        return discord.Embed(description=pcpp_message, color=9806321)


class PCPPItemHelper:
    @staticmethod
    def get_ids(match: re.Match[str]) -> tuple:
        channel_id = int(match["channel_id"])
        message_id = int(match["message_id"])
        return channel_id, message_id

    @staticmethod
    @alru_cache(maxsize=1024)
    async def get_pcpp_url_list(bot, channel_id, message_id) -> list[str]:
        """
        Retrieves a list of PCPartPicker URLs from a specific message in a channel.

        Parameters:
        - bot (discord.Client): The bot instance used to access Discord channels.
        - channel_id (int): The ID of the channel where the message is located.
        - message_id (int): The ID of the message containing the URLs.

        Returns:
        - List[str]: A list of PCPartPicker URLs extracted from the message content.
        """
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)  # Retrieves message onject
        pcpp_url_list = OnMessageAndItemHelper.find_number_of_lists(message.content)
        return pcpp_url_list

    @staticmethod
    @alru_cache(maxsize=1024)
    async def send_pcpp_preview(interaction: discord.Interaction, url: str) -> None:
        pcpp_message_embed = await OnMessageAndItemHelper.fetch_list_preview(
            url
        )  # Web scrapes and caches PCPP preview results from that url
        await interaction.response.send_message(
            embed=pcpp_message_embed, ephemeral=True
        )
        return


class PCPPButton(discord.ui.DynamicItem[discord.ui.Button], template=BUTTON_TEMPLATE):

    def __init__(self, channel_id, message_id, url):
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
        item: discord.ui.Select,
        match: re.Match[str],
        /,
    ):
        channel_id, message_id = PCPPItemHelper.get_ids(match)
        pcpp_url_list = await PCPPItemHelper.get_pcpp_url_list(
            interaction.client, channel_id, message_id
        )
        url = pcpp_url_list[0]
        return cls(channel_id, message_id, url)

    async def callback(self, interaction: discord.Interaction) -> discord.Message:
        """
        This is called when a button is pressed.
        """
        await PCPPItemHelper.send_pcpp_preview(interaction, self.url)


class PCPPMenu(
    discord.ui.DynamicItem[discord.ui.Select],
    template=MENU_TEMPLATE,
):

    def __init__(
        self, channel_id, message_id, options: list[discord.SelectOption]
    ) -> None:
        """
        channel_id - ID of the channel that has the menu.
        message_id - ID of the referenced message.
        """
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
    def calculate_options(pcpp_url_list) -> discord.SelectOption:
        """
        OnMessageAndItemHelper the first creation of the menu, it will calculate menu options and store it in a dictionary.
        If the menu needs to be send again, it will retrieve from the dictionary for faster access.
        In case of a bot downtime, it retrieves the contents of the user interacted message to work out the options.
        """
        options = []
        if len(pcpp_url_list) > 25:  # List of options cannot have more than 25 items.
            pcpp_url_list = pcpp_url_list[:25]

        for index, url in enumerate(pcpp_url_list, start=1):
            """
            This is saved to an object-specific variable since each new message creates a new object.
            Repeated button presses on the same message access the PCPP message via the object variable, not the dictionary.
            Only new messages with the same link use the dictionary to get the PCPP Preview message.
            """

            options.append(
                discord.SelectOption(label=f"List Preview {index}", value=url)
            )

        return options  # Returns a list of menu options.

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: re.Match[str],
        /,
    ):
        channel_id, message_id = PCPPItemHelper.get_ids(match)
        pcpp_url_list = await PCPPItemHelper.get_pcpp_url_list(
            interaction.client, channel_id, message_id
        )
        options = cls.calculate_options(pcpp_url_list)
        return cls(channel_id, message_id, options)

    async def callback(self, interaction: discord.Interaction) -> discord.Message:
        """
        This is called when a menu option is pressed.
        """
        # await asyncio.sleep(1)  # Reduces chance of rate limit
        await PCPPItemHelper.send_pcpp_preview(interaction, self.item.values[0])
        await interaction.message.edit()  # Resets user choice after each selection in the menu.


class PCPPCog(commands.Cog):
    """
    The Cog for handling PCPartPicker list previews.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Listens for messages containing PCPartPicker URLs and handles them.
        """
        pcpp_url_list = OnMessageAndItemHelper.find_number_of_lists(message.content)
        pcpp_wrong_link = WRONG_LINK_REGEX.search(message.content)

        if pcpp_url_list:
            await self.handle_pcpp_links(message, pcpp_url_list)
        elif pcpp_wrong_link:
            await self.handle_wrong_links(message)

    def get_preview_embed(self, urls: list) -> discord.Embed:
        """
        pcpp_url_list: Takes a list as parameter to join it by using "\n" as a separator.
        This returns a Discord embed object.
        """
        newline_urls = "\n".join(urls)
        return discord.Embed(
            description=f"These are the previews for the following links:\n{newline_urls}",
            color=9806321,
        )

    async def handle_pcpp_links(
        self, message: discord.Message, pcpp_url_list: list[str]
    ) -> discord.Message:
        """
        Handles PCPartPicker links and sends an appropriate response.
        """
        preview_embed = self.get_preview_embed(pcpp_url_list)
        view = discord.ui.View(timeout=None)

        if len(pcpp_url_list) == 1:
            url = pcpp_url_list[0]
            button = PCPPButton(message.channel.id, message.id, url)
            view.add_item(button)
        else:
            options = PCPPMenu.calculate_options(pcpp_url_list)
            menu = PCPPMenu(message.channel.id, message.id, options)
            view.add_item(menu)

        await message.reply(embed=preview_embed, view=view)

    async def handle_wrong_links(self, message: discord.Message) -> discord.Message:
        """
        Handles incorrect PCPartPicker links and sends an error message.
        """
        wrong_link_embed = discord.Embed(
            title=(
                "**One or more of your PCPartPicker link(s) is wrong, "
                "as these links only make the associated list viewable to you. "
                "Please refer to the image below.**"
            ),
            color=9806321,
        )
        wrong_link_embed.set_image(url="https://i.imgur.com/O0TFvRc.jpeg")
        await message.reply(embed=wrong_link_embed)


async def setup(bot) -> None:
    """Setup function to add the cog to the bot"""
    bot.add_dynamic_items(PCPPButton, PCPPMenu)
    await bot.add_cog(PCPPCog(bot))
