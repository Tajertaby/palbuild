import logging
import re
from async_lru import alru_cache
from bs4 import BeautifulSoup
from urllib.parse import quote

from html_fetcher import HTMLFetcher

SSD_LOG = logging.getLogger("ssd_lookup")
NOT_UNIQUE = "Not unique, cannot generate menu options."


class SSDScraper:
    fetcher = HTMLFetcher(SSD_LOG)

    @staticmethod
    def ssd_link_list_attr():
        tag_names = ["table", "tbody", "tr", "td", "div"]
        class_list = "drives-desktop-table"
        return tag_names, class_list
    
    @staticmethod
    def ssd_specs_attr():
        tag_names = ["div", "section"]
        class_list = ["details", "unreleased p"]
        return tag_names, class_list

    @classmethod
    async def fetch_ssd_content(cls, url, tag_names, class_list):
        return await cls.fetcher.fetch_html_content(url, tag_names, class_list)

    @classmethod
    def process_ssd_name_and_links(cls, soup):
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
                    return cls.return_info(
                        tpu_ssd_name_list,
                        ssd_released_list,
                        ssd_capacity_list,
                        ssd_url_list,
                    )
        return cls.return_info(
            tpu_ssd_name_list, ssd_released_list, ssd_capacity_list, ssd_url_list
        )
    
    @staticmethod
    def return_info(
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
    
    @staticmethod
    def ssd_info_msg(soup) -> str:
        ssd_message_list = []

        def ssd_variant_info(ssd_value_element, ssd_message_list) -> str:
            variant_elements = ssd_value_element.select(
                "ul:not([style]) li"
            )  # Style attribute has uneccesary info
            variant_config_and_capacities_list = []
            for variant_element in variant_elements:
                variant_config = variant_element.contents[0].strip()
                span_list = variant_element.select("span.variants-list--item")
                capacities = [capacity.get_text(strip=True) for capacity in span_list]
                variant_config_and_capacities_list.append(
                    f"- {variant_config}\n{", ".join(capacities)}"
                )
            variant_configs_and_capacities = "\n\n".join(
                variant_config_and_capacities_list
            )
            ssd_message_list.insert(
                0,
                f"**Warning:** This SSD has multiple unannounced hardware swaps which impacts performance.\n\n**__Variants__**\n{variant_configs_and_capacities}\n\n",
            )

        def review_info(review_section) -> tuple[str, bool]:
            ssd_review_list = ["**__Reviews__**\n"]
            review_elements = review_section.find_all("a")
            for review_element in review_elements:
                review_name = review_element.get_text(strip=True)
                review_link = review_element.get("href")
                ssd_review_list.append(f"- [{review_name}]({review_link})\n")
            ssd_review_parsed = True
            return (
                ssd_review_list,
                ssd_review_parsed,
            )  # Review message to combine into a string

        table_name_and_properties_dict = {
            "Solid-State-Drive": ["Capacity:", "Hardware Versions:"],
            "NAND Flash": ["Manufacturer:", "Name:", "Type:", "Technology:", "Speed:"],
            "Physical": ["Form Factor:", "Interface:"],
            "Controller": ["Manufacturer:", "Name:"],
            "DRAM Cache": ["Type:", "Name:", "Capacity"],
            "Performance": [
                "Sequential Read:",
                "Sequential Write:",
                "Random Read:",
                "Random Write:",
                "Endurance:",
                "Warranty:",
                "SLC Write Cache:",
            ],
        }

        section_list = soup.find_all("section")
        ssd_review_parsed = False
        ssd_review_list = [] # Empty list so variable is still accessible regardless review is avaliable or not
        for section in section_list:
            table = section.find("table")
            table_name = section.find("h1").get_text(strip=True)
            if (
                table_name in table_name_and_properties_dict
            ):  # Checks if table name is found in the dict of select table names
                ssd_property_list = table_name_and_properties_dict[table_name]
                ssd_property_elements = table.find_all("th", string=ssd_property_list)
                ssd_message_list.append(f"**__{table_name}__**\n")
                for ssd_property_element in ssd_property_elements:
                    ssd_property = ssd_property_element.get_text(strip=True)
                    ssd_value_element = ssd_property_element.find_next_sibling()
                    if (
                        ssd_property != "Hardware Versions:"
                    ):  # Checks if ssd has hardware swaps or not
                        ssd_value = ssd_value_element.get_text(strip=True)
                        ssd_value_cleaned = re.sub("\\n(\\t)+", " ", ssd_value)
                        ssd_message_list.append(
                            f"- {ssd_property} {ssd_value_cleaned}\n"
                        )
                    else:
                        ssd_variant_info(
                            ssd_value_element, ssd_message_list
                        )  # Add variant info to ssd message
                ssd_message_list.append(
                    "\n"
                )  # Leave a newline space after each SSD property category
            elif table_name == "Reviews" and not ssd_review_parsed:
                ssd_review_list, ssd_review_parsed = review_info(section)
            else:
                continue

        if ssd_review_parsed:  # Checks if TPU has linked a review
            ssd_message_list.extend(ssd_review_list)
        ssd_message = "".join(ssd_message_list).rstrip() # Final SSD message about a specific SSD
        print(ssd_message)
        return ssd_message

    @classmethod
    async def ssd_scraper_setup(cls, ssd_name):
        tag_names, class_list = cls.ssd_link_list_attr()
        ssd_name_encoded = quote(ssd_name)
        url = f"https://www.techpowerup.com/ssd-specs/?q={ssd_name_encoded}"
        soup = await cls.fetch_ssd_content(url, tag_names, class_list)
        ssd_partial_info = cls.process_ssd_name_and_links(soup)
        return ssd_partial_info
    
    @classmethod
    @alru_cache(maxsize=1024)
    async def specific_ssd_scraper(cls, url):
        tag_names, class_list = cls.ssd_specs_attr()
        soup = await cls.fetch_ssd_content(url, tag_names, class_list)
        specific_ssd_info = cls.ssd_info_msg(soup)
        return specific_ssd_info
