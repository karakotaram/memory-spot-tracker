"""Send daily memory spot price email reports via Gmail SMTP."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "daily_report.html"


def _change_cell(pct: float) -> str:
    """Format a change percentage with color coding."""
    if pct > 0:
        color = "#dc3545"  # Red for price increase
        arrow = "&#9650;"  # Up triangle
    elif pct < 0:
        color = "#28a745"  # Green for price decrease
        arrow = "&#9660;"  # Down triangle
    else:
        color = "#6c757d"  # Gray for no change
        arrow = "&#8212;"  # Em dash
    return (
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee;">'
        f'<span style="color:{color}; font-weight:600;">{arrow} {pct:+.2f}%</span></td>'
    )


def _price_row(record: dict) -> str:
    """Generate an HTML table row for a price record."""
    product = record["product"]
    avg = record["session_avg"]
    high = record["daily_high"]
    low = record["daily_low"]
    change = record["session_change_pct"]

    return (
        f'<tr>'
        f'<td style="padding:8px; border-bottom:1px solid #eee;">{product}</td>'
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee; font-family:monospace;">{avg:.2f}</td>'
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee; font-family:monospace; color:#6c757d;">{low:.2f} – {high:.2f}</td>'
        f'{_change_cell(change)}'
        f'</tr>'
    )


def _build_html(latest_data: dict) -> str:
    """Build the email HTML from the template and latest data."""
    template = TEMPLATE_PATH.read_text()

    records = latest_data.get("records", [])
    date = latest_data.get("last_updated", "Unknown")

    dram_records = [r for r in records if r["category"] == "dram"]
    nand_records = [r for r in records if r["category"] == "nand"]

    dram_rows = "\n".join(_price_row(r) for r in dram_records)
    nand_rows = "\n".join(_price_row(r) for r in nand_records)

    html = template.replace("{{date}}", date)
    html = html.replace("{{dram_rows}}", dram_rows)
    html = html.replace("{{nand_rows}}", nand_rows)

    return html


def send_daily_report(latest_data: dict, recipients: list[str]):
    """Send the daily price report email."""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        raise ValueError("GMAIL_USER and GMAIL_APP_PASSWORD env vars must be set")

    date = latest_data.get("last_updated", "Unknown")
    html = _build_html(latest_data)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Memory Spot Prices – {date}"
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)

    # Plain text fallback
    records = latest_data.get("records", [])
    plain_lines = [f"Memory Spot Price Update – {date}", ""]
    for r in records:
        plain_lines.append(
            f"{r['product']:35s}  avg: ${r['session_avg']:.2f}  chg: {r['session_change_pct']:+.2f}%"
        )
    plain_lines.append("")
    plain_lines.append("Source: TrendForce")
    plain_text = "\n".join(plain_lines)

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())

    logger.info(f"Email sent to {recipients}")
