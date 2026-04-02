from dataclasses import dataclass, asdict
import csv
import io
import json


@dataclass
class PriceRecord:
    date: str
    product: str
    category: str  # "dram" or "nand"
    daily_high: float
    daily_low: float
    session_avg: float
    session_change_pct: float
    source: str

    CSV_HEADERS = [
        "date", "product", "category", "daily_high", "daily_low",
        "session_avg", "session_change_pct", "source"
    ]

    def to_csv_row(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            self.date, self.product, self.category,
            f"{self.daily_high:.4f}", f"{self.daily_low:.4f}",
            f"{self.session_avg:.4f}", f"{self.session_change_pct:.2f}",
            self.source,
        ])
        return buf.getvalue().strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def csv_header() -> str:
        return ",".join(PriceRecord.CSV_HEADERS)
