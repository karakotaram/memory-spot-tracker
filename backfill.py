#!/usr/bin/env python3
"""Backfill historical data from Wayback Machine snapshots of TrendForce."""

import json
import logging
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from scraper.models import PriceRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

DRAM_URL = "https://www.trendforce.com/price/dram/dram_spot"
NAND_URL = "https://www.trendforce.com/price/flash/flash_spot"

DRAM_TABLES = {"DRAM Spot Price"}
NAND_TABLES = {"NAND Flash Spot Price", "Wafer Spot Price"}


def get_wayback_snapshots(url: str, from_date: str, to_date: str) -> list[str]:
    """Get all Wayback Machine snapshot timestamps for a URL."""
    cdx_url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={url.replace('https://', '')}"
        f"&output=json&from={from_date}&to={to_date}"
    )
    resp = requests.get(cdx_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if len(data) <= 1:
        return []
    return [row[1] for row in data[1:]]  # skip header row


def parse_snapshot(html: str, target_tables: set[str], category: str) -> list[PriceRecord]:
    """Parse a TrendForce page (possibly from Wayback) for price records."""
    soup = BeautifulSoup(html, "lxml")
    records = []

    for section in soup.find_all("div", class_="price-content"):
        title_div = section.find("div", class_="price-title")
        if not title_div:
            continue
        title = title_div.get_text().strip()

        matched = any(target in title for target in target_tables)
        if not matched:
            continue

        # Get date
        update_div = section.find("div", class_="price-last-update")
        if not update_div:
            continue
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", update_div.get_text())
        if not date_match:
            continue
        date = date_match.group(1)

        table = section.find("table", class_="price-table")
        if not table:
            continue

        tbody = table.find("tbody")
        if not tbody:
            continue

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 7:
                continue

            name_span = cells[0].find("span", attrs={"data-toggle": "tooltip"})
            product = (name_span.get_text().strip() if name_span
                       else cells[0].get_text().strip())
            if not product:
                continue

            try:
                daily_high = _parse_num(cells[1].get_text())
                daily_low = _parse_num(cells[2].get_text())
                session_avg = _parse_num(cells[5].get_text())
                change_text = cells[6].get_text().strip()
                change_pct = _parse_change(change_text)
            except (ValueError, IndexError):
                continue

            if session_avg <= 0:
                continue

            records.append(PriceRecord(
                date=date,
                product=product,
                category=category,
                daily_high=daily_high,
                daily_low=daily_low,
                session_avg=session_avg,
                session_change_pct=change_pct,
                source="trendforce",
            ))

    return records


def _parse_num(text: str) -> float:
    text = text.strip().replace(",", "")
    if not text or text == "-":
        return 0.0
    return float(text)


def _parse_change(text: str) -> float:
    text = re.sub(r"[^\d.\-+]", "", text)
    if not text:
        return 0.0
    # Handle negative: if original had ▼ or fall-trend
    if "▼" in text or "\u25bc" in text:
        return -abs(float(text))
    return float(text)


def fetch_wayback(url: str, timestamp: str) -> str:
    """Fetch a page from the Wayback Machine."""
    wb_url = f"https://web.archive.org/web/{timestamp}/{url}"
    resp = requests.get(wb_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def backfill():
    """Main backfill: fetch all Wayback snapshots and extract unique date records."""
    # Calculate date range: last 3 months
    end = datetime.now()
    start = end - timedelta(days=90)
    from_date = start.strftime("%Y%m%d")
    to_date = end.strftime("%Y%m%d")

    all_records: dict[tuple[str, str, str], PriceRecord] = {}  # (date, product, category) -> record

    # Process DRAM snapshots
    logger.info("Fetching DRAM Wayback snapshots...")
    dram_timestamps = get_wayback_snapshots(DRAM_URL, from_date, to_date)
    logger.info(f"Found {len(dram_timestamps)} DRAM snapshots")

    for ts in dram_timestamps:
        try:
            logger.info(f"  Fetching DRAM snapshot {ts}...")
            html = fetch_wayback(DRAM_URL, ts)
            records = parse_snapshot(html, DRAM_TABLES, "dram")
            for r in records:
                key = (r.date, r.product, r.category)
                if key not in all_records:
                    all_records[key] = r
            logger.info(f"    Found {len(records)} records")
            time.sleep(1)  # Be polite to Wayback
        except Exception as e:
            logger.warning(f"    Failed: {e}")

    # Process NAND snapshots
    logger.info("Fetching NAND Wayback snapshots...")
    nand_timestamps = get_wayback_snapshots(NAND_URL, from_date, to_date)
    logger.info(f"Found {len(nand_timestamps)} NAND snapshots")

    for ts in nand_timestamps:
        try:
            logger.info(f"  Fetching NAND snapshot {ts}...")
            html = fetch_wayback(NAND_URL, ts)
            records = parse_snapshot(html, NAND_TABLES, "nand")
            for r in records:
                key = (r.date, r.product, r.category)
                if key not in all_records:
                    all_records[key] = r
            logger.info(f"    Found {len(records)} records")
            time.sleep(1)
        except Exception as e:
            logger.warning(f"    Failed: {e}")

    # Sort and write
    records = sorted(all_records.values(), key=lambda r: (r.date, r.category, r.product))

    dram_records = [r for r in records if r.category == "dram"]
    nand_records = [r for r in records if r.category == "nand"]

    logger.info(f"Total unique records: {len(dram_records)} DRAM, {len(nand_records)} NAND")
    logger.info(f"Date range: {records[0].date} to {records[-1].date}" if records else "No records")

    # Print unique dates
    dram_dates = sorted(set(r.date for r in dram_records))
    nand_dates = sorted(set(r.date for r in nand_records))
    logger.info(f"DRAM dates ({len(dram_dates)}): {dram_dates}")
    logger.info(f"NAND dates ({len(nand_dates)}): {nand_dates}")

    # Write CSVs (overwrite with all historical + current data)
    from pathlib import Path
    data_dir = Path(__file__).parent / "data"
    docs_data_dir = Path(__file__).parent / "docs" / "data"

    for path, recs in [
        (data_dir / "dram_spot.csv", dram_records),
        (data_dir / "nand_spot.csv", nand_records),
    ]:
        with open(path, "w", newline="") as f:
            f.write(PriceRecord.csv_header() + "\n")
            for r in recs:
                f.write(r.to_csv_row() + "\n")
        logger.info(f"Wrote {len(recs)} records to {path.name}")

        # Copy to docs
        dst = docs_data_dir / path.name
        dst.write_bytes(path.read_bytes())

    # Update latest.json
    import json
    latest_records = [r for r in records if r.date == records[-1].date] if records else []
    latest = {
        "last_updated": records[-1].date if records else None,
        "records": [r.to_dict() for r in latest_records],
    }
    latest_path = data_dir / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(latest, f, indent=2)
    (docs_data_dir / "latest.json").write_bytes(latest_path.read_bytes())

    logger.info("Backfill complete!")


if __name__ == "__main__":
    backfill()
