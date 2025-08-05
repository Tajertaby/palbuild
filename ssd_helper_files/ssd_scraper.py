import logging
from bs4 import BeautifulSoup
from urllib.parse import quote

from html_fetcher import HTMLFetcher

SSD_LOG = logging.getLogger("ssd_lookup")
NOT_UNIQUE = "Not unique, cannot generate menu options."


class SSDScraper:

    def __init__(self):
        self.fetcher = HTMLFetcher(SSD_LOG)

    def ssd_link_list_attr(self):
        tag_names = ["table", "tbody", "tr", "td", "div"]
        class_list = "drives-desktop-table"
        return tag_names, class_list

    def ssd_specs_attr(self):
        tag_names = ["div", "section"]
        class_list = ["details", "unreleased p"]
        return tag_names, class_list

    async def fetch_ssd_content(self, url, tag_names, class_list):
        return await self.fetcher.fetch_html_content(url, tag_names, class_list)

    def process_ssd_name_and_links(self, soup):
        ssd_elements = soup.find_all("tr")[
            2:
        ]  # Excludes empty tr's from thead which are empty.
        ssd_url_list = []
        tpu_ssd_name_list = []
        ssd_released_list = []
        ssd_capacity_list = []
        ssd_option_count = 0
        for ssd_element in ssd_elements:
            tpu_ssd_name = " ".join(
                ssd_element.select_one("a.drive-name").stripped_strings
            )
            ssd_released = ssd_element.find_all("td")[
                -3
            ].get_text()  # Month and year of SSD released
            capacity_elements = ssd_element.select("div.drive-capacities a")
            for capacity_element in capacity_elements:
                ssd_url = f"https://www.techpowerup.com{capacity_element.get("href")}"
                ssd_capacity = capacity_element.get_text()
                ssd_capacity_list.append(ssd_capacity)
                ssd_url_list.append(ssd_url)
                tpu_ssd_name_list.append(tpu_ssd_name)
                ssd_released_list.append(ssd_released)
                ssd_option_count += 1
                if (
                    ssd_option_count >= 25
                ):  # Discord menus can only have up to 25 options
                    return self.return_info(
                        tpu_ssd_name_list,
                        ssd_released_list,
                        ssd_capacity_list,
                        ssd_url_list,
                    )
        return self.return_info(
            tpu_ssd_name_list, ssd_released_list, ssd_capacity_list, ssd_url_list
        )

    def return_info(
        self,
        tpu_ssd_name_list: list[str],
        ssd_released_list: list[str],
        ssd_capacity_list: list[str],
        ssd_url_list: list[str],
    ):
        if len(ssd_url_list) == len(set(ssd_url_list)):  # Checks for unique values
            return zip(
                tpu_ssd_name_list, ssd_released_list, ssd_capacity_list, ssd_url_list
            )  # Combines the list items into a list of tuples
        else:
            return NOT_UNIQUE

    def ssd_info_msg(self, soup) -> str:
        string_list = []
        hardware_swap_check = soup.find("div", class_="unreleased p")
        if hardware_swap_check:
            string_list.append(
                "**Warning:** This SSD has multiple unannounced hardware swaps which impacts performance."
            )
            variant_elements = soup.select(
                "td.variants-list ul:not([style]) li"
            )  # Style attribute has uneccesary info
            print(variant_elements)
            for variant_element in variant_elements:
                variant_config = variant_element.contents[0].strip()
                print(variant_config)
                span_list = variant_element.select("span.variants-list--item")
                capacities = [capacity.get_text().strip() for capacity in span_list]
                print(capacities)

    async def ssd_scraper_setup(self, ssd_name):
        tag_names, class_list = self.ssd_link_list_attr()
        ssd_name_encoded = quote(ssd_name)
        url = f"https://www.techpowerup.com/ssd-specs/?q={ssd_name_encoded}"
        soup = await self.fetch_ssd_content(url, tag_names, class_list)
        ssd_partial_info = self.process_ssd_name_and_links(soup)
        return ssd_partial_info

    async def specific_ssd_scraper(self, url):
        tag_names, class_list = self.ssd_specs_attr()
        url = "https://www.techpowerup.com/ssd-specs/samsung-990-pro-1-tb.d861"
        soup = await self.fetch_ssd_content(url, tag_names, class_list)
        self.ssd_info_msg(soup)
