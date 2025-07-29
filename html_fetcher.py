import logging
from asyncio import TimeoutError as AsyncioTimeoutError

from aiohttp import ClientConnectionError, ClientPayloadError, ClientResponseError
from bs4 import BeautifulSoup, SoupStrainer
from sessions import SessionManager


class HTMLFetcher:
    """
    A reusable class for fetching and handling HTML content with error handling and retries.
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    async def fetch_html_content(
        self, url: str, tag_name=None, class_list=None, max_retries: int = 3
    ) -> BeautifulSoup:
        """
        Fetch and parse HTML content with retry logic.

        Args:
            url: URL to fetch
            tag_name: HTML tag to filter for (None for no filtering)
            class_list: List of classes to filter for (None for no filtering)
            max_retries: Maximum number of retry attempts

        Returns:
            BeautifulSoup parsed document

        Raises:
            Various network-related exceptions if all retries fail
        """
        strainer = None
        if tag_name and class_list:
            strainer = SoupStrainer(tag_name, class_=class_list)

        for attempt in range(max_retries, 0, -1):
            try:
                page = await SessionManager.request(url)
                return BeautifulSoup(page, "lxml", parse_only=strainer)
            except AsyncioTimeoutError as e:
                if attempt > 1:
                    self.logger.info(
                        f"Timeout, retrying ({attempt-1} attempts left): {e}"
                    )
                    continue
                raise Exception(f"Web server timeout. URL={url}") from e
            except ClientConnectionError as e:
                if attempt > 1:
                    self.logger.info(
                        f"Connection error, retrying ({attempt-1} attempts left): {e}"
                    )
                    continue
                raise ClientConnectionError(
                    f"Could not connect to web server. URL={url}"
                ) from e
            except ClientPayloadError as e:
                raise ClientPayloadError(
                    f"Invalid payload from web server. URL={url}"
                ) from e
            except ClientResponseError as e:
                raise ClientResponseError(
                    f"Invalid response from web server. URL={url}"
                ) from e
            except Exception as e:
                raise Exception(f"Unexpected error during network request: {e}") from e

    async def fetch_with_retries(
        self, url: str, tag_names=None, class_list=None, max_retries: int = 3
    ) -> BeautifulSoup:
        """
        Wrapper method with retry logic for fetching HTML content.
        """
        return await self.fetch_html_content(
            url, tag_name=tag_names, class_list=class_list, max_retries=max_retries
        )
