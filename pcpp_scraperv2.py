import os
import urllib
import urllib.request as request
import urllib.parse as parse

# import psycopg2
import traceback
import re
import discord
from async_lru import alru_cache
from bs4 import BeautifulSoup
from discord.ext import commands
from dotenv import load_dotenv
from typing import Optional

# Constants and regex patterns for identifying PCPartPicker URLs
PCPP_LIST_REGEX = (
    r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com/list/(?!$)[a-zA-z0-9]+"
    r"|https?://(?:[a-z]{2}\.)?pcpartpicker\.com/user/[a-zA-z0-9]+/saved/"
    r"(?!$)(?:#view=)?[a-zA-z0-9]+"
)
WRONG_LINK_REGEX = r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com/list/(?!\S)"
DOMAIN_REGEX = r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com"
COUNTRIES = {
    "au.",
    "at.",
    "be.",
    "ca.",
    "cz.",
    "dk.",
    "fi.",
    "fr.",
    "de.",
    "hu.",
    "ie.",
    "it.",
    "nl.",
    "no.",
    "nz.",
    "pt.",
    "ro.",
    "sa.",
    "sk.",
    "es.",
    "se.",
    "uk.",
}  # Excludes US
ITEM_TEMPLATE = (
    "(?:button|menu):channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)"
)


load_dotenv(r"E:\Discord Bot Files\secrets.env")


class PCPPScraper:
    """
    Methods used to scrape the required content from PCPartPicker.
    """

    def __init__(self):
        self.compatibility_emojis = {
            "Problem:": "<:cross:1144351182781943898>",
            "Warning:": "<:exclaimation:1144670756794535996>",
            "Note:": "<:rules:1144938040100388904>",
            "Disclaimer:": None,
        }
        self.power_emoji = "\U0001F50C"
        self.cash_emoji = "\U0001F4B8"

    async def pcpp_domain(self, url) -> str:
        """
        Retrieve the base domain from the URL.
        """
        domain = re.match(DOMAIN_REGEX, url)
        domain_end_index = domain.end()
        return url[:domain_end_index]

    async def get_name_and_no_link(self, product_name) -> str:
        """
        This is only called if there is no provided link or if it is a custom part.
        Only retrieves the name and removes brackets.
        """
        product_name = product_name[1:-1]
        product_link = ""
        return product_name, product_link

    async def extract_product_info(
        self,
        domain: str,
        num_items: int,
        component_elements: str,
        product_elements: str,
        price_elements: str,
    ) -> str:
        """
        Extracts product name, link, and price from the HTML elements.
        Links are not available for custom parts.
        """
        message = []
        for index in range(num_items):
            component_type = component_elements[index].contents[1].text.strip()
            product_elements_contents = product_elements[index].contents
            if len(product_elements_contents) >= 2:
                product_name = f"[{product_elements_contents[1].text.strip()}]"
                find_link = str(product_elements_contents[1])
                if "a href" in find_link:
                    product_link = (
                        f"({domain}{product_elements[index].a.get('href').strip()})"
                    )
                    if "#view_custom_part" in product_link:
                        product_name, product_link = await self.get_name_and_no_link(
                            product_name
                        )
                else:
                    product_name, product_link = await self.get_name_and_no_link(
                        product_name
                    )
            else:
                product_name = f"{product_elements_contents[0].text.strip()}"
                product_link = ""

            price_elements_contents = price_elements[index].contents
            if len(price_elements_contents) >= 2:
                product_price = f" - {price_elements_contents[-2].text.strip()}"
            else:
                product_price = " - No Price Available"

            if product_price == " - No Prices":
                product_price = " - No Price Available"
            elif product_price == " - Price":
                product_price = (
                    f" - {price_elements_contents[-1].text.strip()} (Custom Price)"
                )
            message.append(
                f"**{component_type}:** {product_name}{product_link}{product_price}"
            )

        return "\n".join(message) + "\n"

    async def get_compatibility_notes(self, soup) -> str:
        """
        Extracts compatibility notes from the page.
        """
        message = []
        class_list = [
            soup.select("p.note__text.note__text--problem"),
            soup.select("p.note__text.note__text--warning"),
            soup.select("p.note__text.note__text--info"),
        ]
        class_list = [soup_class for soup_class in class_list if soup_class != []]

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

    async def extract_power_wattage(self, product_message, wattage_elements) -> str:
        """
        Extracts the total power wattage from the list.
        """
        for div in wattage_elements:
            if "Total:" in div.get_text():
                total_td = div.find("td", string="Total:")
                if total_td and product_message.strip() != "":
                    wattage = total_td.find_next_sibling("td").text
                    return f"{self.power_emoji} **Total Estimated Power:** {wattage}\n"
                else:
                    break
        return ""

    async def calculate_total_price(self, product_message, price_elements) -> str:
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

    async def scrape_pcpartpicker(self, url) -> str:
        """
        Main method to scrape the PCPartPicker list.
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            req = request.Request(url, headers=headers)
            page = request.urlopen(req).read().decode("utf-8")
            soup = BeautifulSoup(page, "html.parser")

            component_elements = soup.select("td.td__component")
            product_elements = soup.select("td.td__name")
            price_elements = soup.select("td.td__price")
            num_items = len(component_elements)

            domain = await self.pcpp_domain(url)
            product_message = await self.extract_product_info(
                domain, num_items, component_elements, product_elements, price_elements
            )
            compatibility_message = await self.get_compatibility_notes(soup)
            wattage_elements = soup.select("div.modal__content")
            wattage_message = await self.extract_power_wattage(
                product_message, wattage_elements
            )
            price_message = await self.calculate_total_price(
                product_message, price_elements
            )

            pcpp_message = f"{product_message}{compatibility_message}{wattage_message}{price_message}"

            if len(pcpp_message) > 4096:
                pcpp_message = (
                    "Error in generating a PCPP list preview. "
                    "The returned string exceeds Discord's max character limit of 4096 characters."
                )

            return pcpp_message

        except Exception as e:
            traceback.print_exc()
            return f"Error in generating a PCPP list preview. {e}"


class MessageHelper:
    """
    Utility functions to reduce redundancy in the code for sending previews.
    """

    @staticmethod
    async def find_number_of_lists(pcpp_list_regex, message_content):
        """
        Finds the number of lists in a message
        Removes duplicate urls and then encodes the urls
        """
        pcpp_url_list = re.findall(pcpp_list_regex, message_content)
        pcpp_url_list_duplicates_removed = list(dict.fromkeys(pcpp_url_list))
        encoded_url_list = [
            parse.urlunparse(parse.urlparse(url)._replace(scheme="https")).replace(
                "#view=", ""
            )
            for url in pcpp_url_list_duplicates_removed
        ]
        return encoded_url_list

    @staticmethod
    async def get_embed_from_original_message(interaction: discord.Interaction) -> str:
        """
        Helper function to get the original message's embed description.
        """
        await interaction.response.defer()
        original_message = await interaction.original_response()
        fetch_full_message_object = await original_message.fetch()
        return fetch_full_message_object.embeds[0].description

    @staticmethod
    @alru_cache(maxsize=1024)
    async def fetch_list_preview(url: str) -> str:
        """
        Calls the scraper to get the PCPP message and caches the result.
        Constructs a preview embed
        """
        scraper = PCPPScraper()
        pcpp_message = await scraper.scrape_pcpartpicker(url)
        return discord.Embed(description=pcpp_message, color=9806321)

    @staticmethod
    async def get_preview_embed(urls: list) -> object:
        """
        pcpp_url_list: Takes a list as parameter to join it by using "\n" as a separator.
        This returns a Discord embed object.
        """
        newline_urls = "\n".join(urls)
        return discord.Embed(
            description=f"These are the previews for the following links:\n{newline_urls}",
            color=9806321,
        )


class PCPPItemHelper:
    @staticmethod
    async def get_ids(match: re.Match[str]) -> tuple:
        channel_id = int(match["channel_id"])
        message_id = int(match["message_id"])
        return channel_id, message_id

    @staticmethod
    async def get_pcpp_url_list(bot, channel_id, message_id) -> list:
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)  # Retrieves message onject
        pcpp_url_list = await MessageHelper.find_number_of_lists(
            PCPP_LIST_REGEX, message.content
        )
        return pcpp_url_list

    @staticmethod
    async def send_pcpp_preview(interaction: discord.Interaction, url: str) -> None:
        pcpp_message_embed = await MessageHelper.fetch_list_preview(
            url
        )  # Web scrapes and caches PCPP preview results from that url
        await interaction.response.send_message(
            embed=pcpp_message_embed, ephemeral=True
        )
        return


class PCPPButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template="button:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)",
):

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
        channel_id, message_id = await PCPPItemHelper.get_ids(match)
        pcpp_url_list = await PCPPItemHelper.get_pcpp_url_list(
            interaction.client, channel_id, message_id
        )
        url = pcpp_url_list[0]
        return cls(channel_id, message_id, url)

    async def callback(self, interaction: discord.Interaction) -> None:
        print("button")
        await PCPPItemHelper.send_pcpp_preview(interaction, self.url)


class PCPPMenu(
    discord.ui.DynamicItem[discord.ui.Select],
    template="menu:channel:(?P<channel_id>[0-9]+)message:(?P<message_id>[0-9]+)",
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
        super().__init__(
            discord.ui.Select(
                placeholder="View Previews",
                custom_id=f"menu:channel:{self.channel_id}message:{self.message_id}",
                options=options,
            )
        )

    @staticmethod
    async def calculate_options(pcpp_url_list) -> list:
        """
        On the first creation of the menu, it will calculate menu options and store it in a dictionary.
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
        channel_id, message_id = await PCPPItemHelper.get_ids(match)
        pcpp_url_list = await PCPPItemHelper.get_pcpp_url_list(
            interaction.client, channel_id, message_id
        )
        options = await cls.calculate_options(pcpp_url_list)
        return cls(channel_id, message_id, options)

    async def callback(self, interaction: discord.Interaction) -> None:
        print("menu")
        await PCPPItemHelper.send_pcpp_preview(interaction, self.item.values[0])


class PCPPCog(commands.Cog):
    """
    The Cog for handling PCPartPicker list previews.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Listens for messages containing PCPartPicker URLs and handles them.
        """
        pcpp_url_list = await MessageHelper.find_number_of_lists(
            PCPP_LIST_REGEX, message.content
        )
        pcpp_wrong_link = re.search(WRONG_LINK_REGEX, message.content)

        if len(pcpp_url_list) == 1:
            url = pcpp_url_list[0]
            preview_embed = await MessageHelper.get_preview_embed(pcpp_url_list)
            view = discord.ui.View(timeout=None)
            button = PCPPButton(message.channel.id, message.id, url)
            view.add_item(button)
            await message.reply(embed=preview_embed, view=view)
        elif len(pcpp_url_list) > 1:
            options = await PCPPMenu.calculate_options(pcpp_url_list)
            preview_embed = await MessageHelper.get_preview_embed(pcpp_url_list)
            view = discord.ui.View(timeout=None)
            menu = PCPPMenu(message.channel.id, message.id, options)
            view.add_item(menu)
            await message.reply(embed=preview_embed, view=view)
        else:
            pass

        if (
            pcpp_wrong_link
        ):  # Checks if at least one of the send PCPartPicker link is incorrect.
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


async def setup(bot):
    """Setup function to add the cog to the bot"""
    bot.add_dynamic_items(PCPPButton, PCPPMenu)
    await bot.add_cog(PCPPCog(bot))
