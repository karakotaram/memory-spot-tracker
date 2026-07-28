"""Send daily memory spot price email reports via Gmail SMTP."""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from scraper.stocks import fetch_week_returns

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "daily_report.html"

EQUITY_TICKERS = ["MU", "EWY", "SNDK", "WDC", "STX"]


def _change_cell(pct: float) -> str:
    """Format a change percentage with color coding."""
    if pct > 0:
        color = "#28a745"  # Green for price increase
        arrow = "&#9650;"  # Up triangle
    elif pct < 0:
        color = "#dc3545"  # Red for price decrease
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
    date = record.get("date", "—")
    category = record.get("category", "dram")
    source_url = ("https://www.trendforce.com/price/dram/dram_spot" if category == "dram"
                  else "https://www.trendforce.com/price/flash/flash_spot")

    return (
        f'<tr>'
        f'<td style="padding:8px; border-bottom:1px solid #eee;"><a href="{source_url}" style="color:#2563eb; text-decoration:none;">{product}</a></td>'
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee; font-family:monospace;">{avg:.2f}</td>'
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee; font-family:monospace; color:#6c757d;">{low:.2f} – {high:.2f}</td>'
        f'{_change_cell(change)}'
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee; font-family:monospace; color:#6c757d;">{date}</td>'
        f'</tr>'
    )


def _equity_row(s: dict) -> str:
    """Generate an HTML table row for an equity 1W return."""
    ticker = s["ticker"]
    price = s["price"]
    ret = s["return_1w"]
    source_url = f"https://finance.yahoo.com/quote/{ticker}"

    return (
        f'<tr>'
        f'<td style="padding:8px; border-bottom:1px solid #eee;"><a href="{source_url}" style="color:#2563eb; text-decoration:none; font-weight:600;">{ticker}</a></td>'
        f'<td align="right" style="padding:8px; border-bottom:1px solid #eee; font-family:monospace;">{price:,.2f}</td>'
        f'{_change_cell(ret)}'
        f'</tr>'
    )


def _chart_img(cid: str, alt: str, available: set) -> str:
    """Inline <img> referencing an attached chart, or empty string if unavailable."""
    if cid not in available:
        return ""
    return (
        f'<img src="cid:{cid}" width="540" alt="{alt}" '
        f'style="display:block; width:100%; max-width:540px; height:auto; '
        f'margin:4px 0 14px; border:1px solid #eee; border-radius:6px;">'
    )


def _build_html(latest_data: dict, equities: list[dict], chart_cids: set) -> str:
    """Build the email HTML from the template and latest data."""
    template = TEMPLATE_PATH.read_text()

    records = latest_data.get("records", [])

    dram_records = [r for r in records if r["category"] == "dram"]
    nand_records = [r for r in records if r["category"] == "nand"]

    dram_rows = "\n".join(_price_row(r) for r in dram_records)
    nand_rows = "\n".join(_price_row(r) for r in nand_records)

    if equities:
        equity_rows = "\n".join(_equity_row(e) for e in equities)
        equities_as_of = max(e["as_of"] for e in equities)
    else:
        equity_rows = (
            '<tr><td colspan="3" style="padding:8px; color:#6c757d; font-style:italic;">'
            'Equity data unavailable.</td></tr>'
        )
        equities_as_of = "Unknown"

    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    html = template.replace("{{report_date}}", report_date)
    html = html.replace("{{dram_chart}}", _chart_img("dram_chart", "DRAM YTD relative performance", chart_cids))
    html = html.replace("{{nand_chart}}", _chart_img("nand_chart", "NAND YTD relative performance", chart_cids))
    html = html.replace("{{dram_rows}}", dram_rows)
    html = html.replace("{{nand_rows}}", nand_rows)
    html = html.replace("{{equity_rows}}", equity_rows)
    html = html.replace("{{equities_as_of}}", equities_as_of)

    return html


def send_daily_report(latest_data: dict, recipients: list[str]):
    """Send the daily price report email."""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        raise ValueError("GMAIL_USER and GMAIL_APP_PASSWORD env vars must be set")

    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    equities = fetch_week_returns(EQUITY_TICKERS)

    # YTD indexed charts (PNG). Never fatal — the email still sends with tables if this fails.
    try:
        from email_report.charts import generate_ytd_charts

        charts = generate_ytd_charts()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Chart generation unavailable, sending tables only: {e}")
        charts = {}

    html = _build_html(latest_data, equities, set(charts.keys()))

    # "related" wraps the "alternative" body plus the inline chart images (cid: refs).
    msg = MIMEMultipart("related")
    msg["Subject"] = f"Memory Spot Prices – {report_date}"
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)

    body = MIMEMultipart("alternative")

    # Plain text fallback
    records = latest_data.get("records", [])
    plain_lines = [f"Memory Spot Price Update – Report generated {report_date}", ""]
    for r in records:
        plain_lines.append(
            f"{r['product']:35s}  avg: ${r['session_avg']:.2f}  chg: {r['session_change_pct']:+.2f}%  (updated {r.get('date', '—')})"
        )
    plain_lines.append("")
    if equities:
        plain_lines.append(f"Memory Equities – 1W Total Return (as of {max(e['as_of'] for e in equities)}):")
        for e in equities:
            plain_lines.append(f"  {e['ticker']:6s}  ${e['price']:,.2f}  {e['return_1w']:+.2f}%")
        plain_lines.append("")
    plain_lines.append("Sources: TrendForce, Yahoo Finance")
    plain_text = "\n".join(plain_lines)

    body.attach(MIMEText(plain_text, "plain"))
    body.attach(MIMEText(html, "html"))
    msg.attach(body)

    for cid, png in charts.items():
        img = MIMEImage(png, _subtype="png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())

    logger.info(f"Email sent to {recipients}")
