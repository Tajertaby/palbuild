import logging
from bs4 import BeautifulSoup

from html_fetcher import HTMLFetcher

SSD_LOG = logging.getLogger("ssd_lookup")


class SSDScraper:

    def __init__(self):
        self.fetcher = HTMLFetcher(SSD_LOG)

    def ssd_link_list_attr(self):
        tag_names = ["table", "tbody", "tr", "td"]
        class_list = "drives-desktop-table"
        return tag_names, class_list

    def ssd_specs_attr(self):
        tag_names = []
        class_list = []
        return tag_names, class_list

    async def fetch_ssd_content(self, url, tag_names, class_list):
        return await self.fetcher.fetch_html_content(url, tag_names, class_list)

    def process_ssd_name_and_links(self, soup):
        ssd_elements = soup.find_all("tr")[2:27] # Excludes empty tr's from thead which are empty.
        ssd_url_list = []
        tpu_ssd_name_list = []
        ssd_released_list = []
        for ssd_element in ssd_elements:
            ssd_url = f"https://www.techpowerup.com{ssd_element.a.get("href")}"
            tpu_ssd_name = ' '.join(ssd_element.select_one('a.drive-name').stripped_strings)
            ssd_released = ssd_element.find_all("td")[-3].get_text() # Month and year of SSD released
            ssd_url_list.append(ssd_url)
            tpu_ssd_name_list.append(tpu_ssd_name)
            ssd_released_list.append(ssd_released)
    
        return zip(tpu_ssd_name_list, ssd_released_list, ssd_url_list) # Combines the list items into a list of tuples

    async def ssd_scraper_setup(self, ssd_name):
        tag_names, class_list = self.ssd_link_list_attr()
        url = f"https://www.techpowerup.com/ssd-specs/?q={ssd_name}"
        soup = await self.fetch_ssd_content(url, tag_names, class_list)
        ssd_partial_info = self.process_ssd_name_and_links(soup)
        return ssd_partial_info
