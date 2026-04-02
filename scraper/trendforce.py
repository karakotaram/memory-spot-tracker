import re
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from scraper.models import PriceRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://www.trendforce.com/price"
DRAM_URL = f"{BASE_URL}/dram/dram_spot"
NAND_URL = f"{BASE_URL}/flash/flash_spot"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Tables we want to scrape, identified by the text in their price-title div
DRAM_TABLES = {"DRAM Spot Price"}
NAND_TABLES = {"NAND Flash Spot Price", "Wafer Spot Price"}


def _normalize_product_name(raw: str) -> str:
    """Normalize product name to a clean identifier."""
    name = raw.strip()
    # Remove parenthetical manufacturer info from tooltip, keep the main name
    name = re.sub(r"\s+", " ", name)
    return name


def _parse_change_pct(cell_text: str) -> float:
    """Parse session change like '▼ -0.18 %' or '▲ 9.37 %' to float."""
    text = cell_text.strip().replace("%", "").replace("▼", "").replace("▲", "")
    text = text.replace("\u25bc", "").replace("\u25b2", "")  # Unicode triangles
    text = text.replace("\u2014", "").replace("—", "")  # Em dash
    text = re.sub(r"[^\d.\-+]", "", text)  # Keep only digits, dots, minus, plus
    text = text.strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def _parse_price(text: str) -> float:
    """Parse a price string to float."""
    text = text.strip().replace(",", "")
    if not text or text == "-":
        return 0.0
    return float(text)


def _extract_date(soup: BeautifulSoup) -> Optional[str]:
    """Extract the update date from the page."""
    update_div = soup.find("div", class_="price-last-update")
    if not update_div:
        return None
    text = update_div.get_text()
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else None


def _scrape_table(table, date: str, category: str, source: str = "trendforce") -> list[PriceRecord]:
    """Parse a single price-table element into PriceRecord list."""
    records = []
    tbody = table.find("tbody")
    if not tbody:
        return records

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 7:
            continue

        # Product name is in a <span> with tooltip inside the first <td>
        name_span = cells[0].find("span", attrs={"data-toggle": "tooltip"})
        if name_span:
            product = _normalize_product_name(name_span.get_text())
        else:
            product = _normalize_product_name(cells[0].get_text())

        if not product:
            continue

        daily_high = _parse_price(cells[1].get_text())
        daily_low = _parse_price(cells[2].get_text())
        session_avg = _parse_price(cells[5].get_text())
        change_pct = _parse_change_pct(cells[6].get_text())

        records.append(PriceRecord(
            date=date,
            product=product,
            category=category,
            daily_high=daily_high,
            daily_low=daily_low,
            session_avg=session_avg,
            session_change_pct=change_pct,
            source=source,
        ))

    return records


def _fetch_page(url: str) -> BeautifulSoup:
    """Fetch a URL and return parsed BeautifulSoup."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def _scrape_page(url: str, target_tables: set[str], category: str) -> list[PriceRecord]:
    """Scrape all target tables from a TrendForce price page."""
    soup = _fetch_page(url)
    records = []

    # Each table section is inside a div.price-content
    sections = soup.find_all("div", class_="price-content")

    for section in sections:
        # Get the section title
        title_div = section.find("div", class_="price-title")
        if not title_div:
            continue
        title = title_div.get_text().strip()

        # Check if this is a table we want
        matched = any(target in title for target in target_tables)
        if not matched:
            continue

        # Get the date for this section
        date = _extract_date(section)
        if not date:
            # Fall back to page-level date
            date = _extract_date(soup)
        if not date:
            logger.warning(f"Could not find date for section: {title}")
            continue

        # Find the price table
        table = section.find("table", class_="price-table")
        if not table:
            continue

        section_records = _scrape_table(table, date, category)
        logger.info(f"Scraped {len(section_records)} records from '{title}' (date: {date})")
        records.extend(section_records)

    return records


def scrape_dram() -> list[PriceRecord]:
    """Scrape DRAM spot prices from TrendForce."""
    logger.info(f"Scraping DRAM from {DRAM_URL}")
    return _scrape_page(DRAM_URL, DRAM_TABLES, "dram")


def scrape_nand() -> list[PriceRecord]:
    """Scrape NAND spot prices from TrendForce."""
    logger.info(f"Scraping NAND from {NAND_URL}")
    return _scrape_page(NAND_URL, NAND_TABLES, "nand")


def scrape_all() -> list[PriceRecord]:
    """Scrape all memory spot prices. Returns combined DRAM + NAND records."""
    dram = scrape_dram()
    time.sleep(2)  # Be polite
    nand = scrape_nand()
    return dram + nand
