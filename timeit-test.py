import timeit
import urllib.request as request
from bs4 import BeautifulSoup, SoupStrainer

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
req_obj = request.Request("https://pcpartpicker.com/list/B7CCjH", headers=headers)
with request.urlopen(req_obj) as response:
    html = response.read()
strainer = SoupStrainer(["a", "td", "p"])
soup = BeautifulSoup(html, "lxml", parse_only=strainer)
#soup_lxml = BeautifulSoup(html, "lxml")


def setup_find_all():
    return f"""
{soup}.find_all("td", class_="td__component")
{soup}.find_all("td", class_="td__name")
{soup}.find_all("td", class_="td__price")
{soup}.find("a", class_="actionBox__actions--key-metric-breakdown")
{soup}.select("p", class_="note__text.note__text--problem"),
{soup}.select("p", class_="note__text.note__text--warning"),
{soup}.select("p", class_="note__text.note__text--info")
"""


def setup_select():
    return f"""
{soup}.select("td.td__component")
{soup}.select("td.td__name")
{soup}.select("td.td__price")
{soup}.select_one("a.actionBox__actions--key-metric-breakdown")
{soup}.select("p.note__text.note__text--problem"),
{soup}.select("p.note__text.note__text--warning"),
{soup}.select("p.note__text.note__text--info")
"""


print("find_all:", timeit.timeit(stmt=setup_find_all, number=1))
print("select:", timeit.timeit(stmt=setup_select, number=1))