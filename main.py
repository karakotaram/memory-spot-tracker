#!/usr/bin/env python3
"""Memory Spot Price Tracker - Daily scraper, emailer, and data manager."""

import csv
import json
import logging
import os
import sys
from pathlib import Path

from scraper.trendforce import scrape_all
from scraper.models import PriceRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DOCS_DATA_DIR = BASE_DIR / "docs" / "data"

DRAM_CSV = DATA_DIR / "dram_spot.csv"
NAND_CSV = DATA_DIR / "nand_spot.csv"
LATEST_JSON = DATA_DIR / "latest.json"


def _ensure_csv(path: Path):
    """Create CSV with headers if it doesn't exist."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            f.write(PriceRecord.csv_header() + "\n")


def _existing_dates(path: Path) -> set[str]:
    """Get all dates already in a CSV file."""
    dates = set()
    if not path.exists():
        return dates
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dates.add(row["date"])
    return dates


def _append_records(path: Path, records: list[PriceRecord]):
    """Append records to CSV, skipping dates that already exist."""
    _ensure_csv(path)
    existing = _existing_dates(path)

    new_records = [r for r in records if r.date not in existing]
    if not new_records:
        logger.info(f"No new records to append to {path.name}")
        return 0

    with open(path, "a", newline="") as f:
        for r in new_records:
            f.write(r.to_csv_row() + "\n")

    logger.info(f"Appended {len(new_records)} records to {path.name}")
    return len(new_records)


def _write_latest_json(records: list[PriceRecord]):
    """Write latest.json with the most recent scrape data."""
    data = {
        "last_updated": records[0].date if records else None,
        "records": [r.to_dict() for r in records],
    }
    LATEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(LATEST_JSON, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Wrote {len(records)} records to latest.json")


def _copy_to_docs():
    """Copy data files to docs/data/ for GitHub Pages."""
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for src in [DRAM_CSV, NAND_CSV, LATEST_JSON]:
        if src.exists():
            dst = DOCS_DATA_DIR / src.name
            dst.write_bytes(src.read_bytes())
            logger.info(f"Copied {src.name} to docs/data/")


def cmd_scrape():
    """Scrape prices and save to CSVs."""
    logger.info("Starting scrape...")
    records = scrape_all()

    if not records:
        logger.error("No records scraped! Check if TrendForce is accessible.")
        sys.exit(1)

    dram_records = [r for r in records if r.category == "dram"]
    nand_records = [r for r in records if r.category == "nand"]

    dram_new = _append_records(DRAM_CSV, dram_records)
    nand_new = _append_records(NAND_CSV, nand_records)

    _write_latest_json(records)
    _copy_to_docs()

    logger.info(f"Scrape complete: {dram_new} new DRAM rows, {nand_new} new NAND rows")


def cmd_email():
    """Send daily email report."""
    from email_report.sender import send_daily_report

    if not LATEST_JSON.exists():
        logger.error("No latest.json found. Run 'scrape' first.")
        sys.exit(1)

    with open(LATEST_JSON) as f:
        latest = json.load(f)

    recipients = os.environ.get("EMAIL_RECIPIENTS", "")
    if not recipients:
        logger.error("EMAIL_RECIPIENTS env var not set")
        sys.exit(1)

    recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]
    send_daily_report(latest, recipient_list)
    logger.info(f"Email sent to {len(recipient_list)} recipients")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [scrape|email|both]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "scrape":
        cmd_scrape()
    elif command == "email":
        cmd_email()
    elif command == "both":
        cmd_scrape()
        cmd_email()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python main.py [scrape|email|both]")
        sys.exit(1)


if __name__ == "__main__":
    main()
