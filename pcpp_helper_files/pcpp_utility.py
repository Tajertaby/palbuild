import re
import urllib.parse as parse
from typing import List

import discord
from async_lru import alru_cache

from .pcpp_scraper import PCPPScraper  # <-- Added import

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

ILOVEPCS_BLUE = 9806321


class PCPPUtility:
    """
    Utility class for handling PCPartPicker URL processing and preview generation.
    """

    @staticmethod
    def extract_unique_pcpp_urls(message_content: str) -> list[str]:
        """
        Extract and normalize unique PCPartPicker URLs from a message.
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
        """
        scraper = PCPPScraper()  # <-- Now properly available
        pcpp_message = await scraper.process_pcpartpicker_list(url)
        return discord.Embed(description=pcpp_message, color=ILOVEPCS_BLUE)
