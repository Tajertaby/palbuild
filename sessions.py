import aiohttp
import logging


class SessionManager:
    server = logging.getLogger("aiohttp")
    timeout = aiohttp.ClientTimeout(total=5)

    @classmethod
    def create_session(cls) -> None:
        """
        Creates a session and adds headers
        """
        cls.server.info("Creating session")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        cls.session = aiohttp.ClientSession(headers=headers, timeout=cls.timeout)

    @classmethod
    async def request(cls, url, *args, **kwargs) -> str:
        """
        Make a request to the server
        """
        try:
            async with cls.session.get(url) as response:
                cls.server.info(response.status)
                return await response.text()
        except aiohttp.ClientConnectionError as e:
            cls.server.exception("Failed to connect to server: %s", e)
            raise e
        except aiohttp.ClientPayloadError as e:
            cls.server.exception("Invalid payload from server: %s", e)
            raise e
        except aiohttp.ClientResponseError as e:
            cls.server.exception("Invalid response from server: %s", e)
            raise e

    @classmethod
    async def close_session(cls) -> None:
        if cls.session:
            cls.server.info("Closing session")
            await cls.session.close()
        else:
            logging.error("Bot cannot login due to API issues.")
