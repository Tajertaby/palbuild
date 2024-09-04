import asyncio
import aiohttp


async def main():
    async with aiohttp.ClientSession() as session:
        headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        async with session.get("https://uk.pcpartpicker.com/list/PCTqTn", headers=headers) as resp:
            print(resp.status)
            print(await resp.text())


asyncio.run(main())
