import logging
import re
from async_lru import alru_cache
from bs4 import BeautifulSoup
from urllib.parse import quote
from typing import List, Tuple, Dict, Optional, Union
from html_fetcher import HTMLFetcher

SSD_LOG = logging.getLogger("ssd_lookup")
NOT_UNIQUE = "Not unique, cannot generate menu options."
TECH_POWERUP_BASE_URL = "https://www.techpowerup.com"
MAX_MENU_OPTIONS = 25

class SSDScraper:
    """Scraper for TechPowerUp SSD database."""
    
    fetcher = HTMLFetcher(SSD_LOG)

    @staticmethod
    def _get_ssd_list_attributes() -> Tuple[List[str], str]:
        """Get HTML attributes for SSD list page."""
        tag_names = ["table", "tbody", "tr", "td", "div"]
        class_list = "drives-desktop-table"
        return tag_names, class_list
    
    @staticmethod
    def _get_ssd_specs_attributes() -> Tuple[List[str], List[str]]:
        """Get HTML attributes for SSD details page."""
        tag_names = ["div", "section"]
        class_list = ["clearfix", "details", "unreleased p"]
        return tag_names, class_list

    @classmethod
    async def _fetch_ssd_content(cls, url: str, tag_names: List[str], class_list: Union[str, List[str]]) -> BeautifulSoup:
        """Fetch and parse HTML content."""
        return await cls.fetcher.fetch_html_content(url, tag_names, class_list)

    @classmethod
    def _extract_ssd_basic_info(cls, soup: BeautifulSoup) -> Tuple[List[str], List[str], List[str], List[str]]:
        """Extract basic SSD info from search results."""
        ssd_elements = soup.find_all("tr")[2:]  # Skip header rows
        ssd_url_list = []
        name_list = []
        released_list = []
        capacity_list = []
        
        for ssd_element in ssd_elements:
            name = " ".join(ssd_element.select_one("a.drive-name").stripped_strings)
            released = ssd_element.find_all("td")[-3].get_text()
            
            for capacity_element in ssd_element.select("div.drive-capacities a"):
                ssd_url_list.append(capacity_element.get("href"))
                capacity_list.append(capacity_element.get_text())
                name_list.append(name)
                released_list.append(released)
                
                if len(ssd_url_list) >= MAX_MENU_OPTIONS:
                    return name_list, released_list, capacity_list, ssd_url_list
                    
        return name_list, released_list, capacity_list, ssd_url_list
    
    @staticmethod
    def _validate_and_format_results(
        names: List[str], 
        released: List[str], 
        capacities: List[str], 
        urls: List[str]
    ) -> Union[List[Tuple[str, str, str, str]], str]:
        """Validate and format SSD results."""
        if len(urls) != len(set(urls)):
            return NOT_UNIQUE
        return list(zip(names, released, capacities, urls))

    @classmethod
    def _process_ssd_variants(cls, variant_element: BeautifulSoup) -> str:
        """Process SSD variant information."""
        variants = []
        for li in variant_element.select("ul:not([style]) li"):
            config = li.contents[0].strip()
            capacities = [cap.get_text(strip=True) for cap in li.select("span.variants-list--item")]
            variants.append(f"- {config}\n{', '.join(capacities)}")
        return "\n\n".join(variants)

    @classmethod
    def _process_reviews(cls, review_section: BeautifulSoup) -> str:
        """Process review information."""
        reviews = ["**__Reviews__**\n"]
        for a in review_section.find_all("a"):
            reviews.append(f"- [{a.get_text(strip=True)}]({a.get('href')})\n")
        return "".join(reviews)

    @classmethod
    def _get_ssd_specs_mapping(cls) -> Dict[str, List[str]]:
        """Get mapping of SSD specification categories to properties."""
        return {
            "Solid-State-Drive": ["Capacity:", "Hardware Versions:"],
            "NAND Flash": ["Manufacturer:", "Name:", "Type:", "Technology:", "Speed:"],
            "Physical": ["Form Factor:", "Interface:"],
            "Controller": ["Manufacturer:", "Name:"],
            "DRAM Cache": ["Type:", "Name:", "Capacity"],
            "Performance": [
                "Sequential Read:", "Sequential Write:", "Random Read:", 
                "Random Write:", "Endurance:", "Warranty:", "SLC Write Cache:"
            ],
        }

    @classmethod
    def _process_ssd_specs(cls, soup: BeautifulSoup) -> str:
        """Process SSD specifications from details page."""
        message_parts = []
        ssd_name = soup.find("h1", class_="drivename").get_text(strip=True)
        specs_mapping = cls._get_ssd_specs_mapping()
        has_reviews = False
        review_content = ""
        
        for section in soup.find_all("section"):
            table_name = section.find("h1").get_text(strip=True)
            
            if table_name not in specs_mapping:
                if table_name == "Reviews" and not has_reviews:
                    review_content = cls._process_reviews(section)
                    has_reviews = True
                continue
                
            message_parts.append(f"**__{table_name}__**\n")
            table = section.find("table")
            
            for prop in specs_mapping[table_name]:
                th = table.find("th", string=prop)
                if not th:
                    continue
                    
                value_element = th.find_next_sibling()
                if prop != "Hardware Versions:":
                    value = re.sub(r"\n(\t)+", " ", value_element.get_text(strip=True))
                    message_parts.append(f"- {prop} {value}\n")
                else:
                    variants = cls._process_ssd_variants(value_element)
                    warning = "**Warning:** This SSD has multiple unannounced hardware swaps which impacts performance.\n\n"
                    message_parts.insert(0, f"{warning}**__Variants__**\n{variants}\n\n")
            
            message_parts.append("\n")
        
        if has_reviews:
            message_parts.append(review_content)
        ssd_message = "".join(message_parts).rstrip()
            
        return ssd_name, ssd_message

    @classmethod
    async def ssd_scraper_setup(cls, ssd_name: str) -> Union[List[Tuple[str, str, str, str]], str]:
        """Setup and execute SSD search."""
        tag_names, class_list = cls._get_ssd_list_attributes()
        encoded_name = quote(ssd_name)
        url = f"{TECH_POWERUP_BASE_URL}/ssd-specs/?q={encoded_name}"
        
        soup = await cls._fetch_ssd_content(url, tag_names, class_list)
        names, released, capacities, urls = cls._extract_ssd_basic_info(soup)
        return cls._validate_and_format_results(names, released, capacities, urls)
    
    @classmethod
    @alru_cache(maxsize=1024)
    async def specific_ssd_scraper(cls, url: str) -> Tuple[str, str]:
        """Get detailed information for a specific SSD."""
        tag_names, class_list = cls._get_ssd_specs_attributes()
        soup = await cls._fetch_ssd_content(url, tag_names, class_list)
        ssd_name, info_message = cls._process_ssd_specs(soup)
        return ssd_name, info_message