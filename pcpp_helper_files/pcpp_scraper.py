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
from sessions import SessionManager

server = SessionManager.server  # Logger
PCPP_LOG = logging.getLogger("pcpp_scraper")
DISCORD_LOG = logging.getLogger("discord")
YEAR_IN_CLASS = 2025
DOMAIN_PATTERN: re.Pattern[str] = re.compile(
    r"https?://(?:[a-z]{2}\.)?pcpartpicker\.com", re.IGNORECASE
)


class PCPPScraper:
    """
    A class for scraping and processing PCPartPicker content.
    """

    def __init__(self) -> None:
        self.power_icon = "\U0001f50c"
        self.earth_icon = "\U0001f30e"
        self.price_icon = "\U0001f4b8"

    async def fetch_html_content(
        self, url: str, tag_name: str, class_list: list
    ) -> BeautifulSoup:
        """
        Fetch and parse the HTML content from the given PCPartPicker URL.
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
        """
        domain_match = DOMAIN_PATTERN.match(url)
        return url[: domain_match.end()]

    def parse_product_without_link(self, product_name: str) -> tuple[str, str]:
        """
        Parse a product name when no link is available.
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

        return "\n**__COMPATIBILITY NOTES__**\n{}\n\n".format("\n".join(notes))

    def format_power_consumption(self, product_message: str, wattage_element) -> str:
        """
        Format the total power consumption information.
        """
        if product_message.strip():
            wattage = wattage_element.text.split(":")[-1].strip()
            return f"{self.power_icon} **Total Estimated Power ->** {wattage}\n"
        return ""

    def find_country(self, country_elements: str) -> str:
        """
        Find the country of the list.
        """
        selected_country = country_elements.find("option", selected=True)
        return f"{self.earth_icon}" f"**Country ->** {selected_country.text}\n"

    def format_total_price(self, product_message: str, price_elements: list) -> str:
        """
        Calculate and format the total price of the list.
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
        """
        domain = self.extract_domain(url)
        max_retries = 3

        if "pcpartpicker.com/b/" in url:
            url = await self.fetch_list_url(url, domain, max_retries)

        soup = await self.strainer_list(url, max_retries)

        component_elements = soup.find_all(
            "td", class_=f"td__component td__component-{YEAR_IN_CLASS}"
        )
        product_elements = soup.find_all(
            "td", class_=f"td__name td__name-{YEAR_IN_CLASS}"
        )
        price_elements = soup.select(
            f".td__price.td__price-{YEAR_IN_CLASS}.td__price--none, .td__price.td__price-{YEAR_IN_CLASS}"
        )

        merchant_elements = soup.find_all("td", class_="td__where")
        wattage_element = soup.find(
            "a", class_="actionBox__actions--key-metric-breakdown"
        )
        country_elements = soup.find(
            "select", class_="select select--small language-selector pp-country-select"
        )
        if not all(
            [
                component_elements,
                product_elements,
                price_elements,
                merchant_elements,
                wattage_element,
                country_elements,
            ]
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

        pcpp_message = f"{product_message}{compatibility_message}{wattage_message}{country}{price_message}"

        if len(pcpp_message) > 4096:
            return (
                "Error in generating a PCPP list preview.\n"
                "The returned string exceeds Discord's max character limit of 4096 characters."
            )

        return pcpp_message

    async def fetch_list_url(self, url: str, domain: str, max_retries: int) -> str:
        """
        Fetch the actual list URL for completed builds.
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
