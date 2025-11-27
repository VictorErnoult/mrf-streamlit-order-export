#!/usr/bin/env python3
"""
Transform Shopify order export CSV to accounting journal entries.

Usage: python transform_order_export.py [input.csv] [-o output.csv]
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# =============================================================================
# CONFIGURATION - Edit these values as needed
# =============================================================================

JOURNAL = "VT2"

# Account numbers and labels
ACCOUNTS = {
    "clients":     ("411200000", "Clients"),
    "tva_20":      ("445712000", "TVA 20%"),
    "tva_55":      ("445710500", "TVA 5,5%"),
    "sales_55":    ("707000012", "Ventes produits finis TVA reduite"),
    "sales_20":    ("707000011", "Ventes marchandises TVA normale"),
    "shipping":    ("708500011", "Ports et frais accessoires factures"),
}

OUTPUT_COLUMNS = [
    "N° Compte", "Journal", "Date écriture", "Commentaire",
    "Montant débit", "Montant crédit", "N° Pièce", "Date échéance", "Lettrage"
]


# =============================================================================
# HELPERS
# =============================================================================

def parse_amount(value: str) -> Decimal:
    """Parse monetary amount, returns 0 for empty values."""
    if not value or not value.strip():
        return Decimal("0")
    return Decimal(value.replace(",", ".")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date(date_str: str) -> datetime | None:
    """Parse Shopify date like '2025-10-20 18:13:20 +0200'."""
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None


def is_reduced_rate(tax_name: str) -> bool:
    """Check if tax name indicates 5.5% rate."""
    return "5,5" in tax_name or "5.5" in tax_name


# =============================================================================
# CORE LOGIC
# =============================================================================

def read_orders(csv_path: str) -> dict:
    """Read CSV and extract order totals (first row of each order has the data)."""
    orders = {}
    
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            order_name = row.get("Name", "").strip()
            if not order_name or order_name in orders:
                continue  # Skip empty or already-seen orders
            
            # Get tax amounts
            tva_20, tva_55 = Decimal("0"), Decimal("0")
            for i in [1, 2]:
                tax_name = row.get(f"Tax {i} Name", "")
                tax_value = parse_amount(row.get(f"Tax {i} Value", "0"))
                if is_reduced_rate(tax_name):
                    tva_55 += tax_value
                elif tax_value > 0:
                    tva_20 += tax_value
            
            orders[order_name] = {
                "date": parse_date(row.get("Paid at") or row.get("Created at", "")),
                "total": parse_amount(row.get("Total", "0")),
                "shipping": parse_amount(row.get("Shipping", "0")),
                "tva_20": tva_20,
                "tva_55": tva_55,
            }
    
    return orders


def aggregate_by_date(orders: dict) -> dict:
    """Group orders by date, summing all amounts."""
    daily = defaultdict(lambda: {"total": Decimal("0"), "shipping": Decimal("0"), 
                                  "tva_20": Decimal("0"), "tva_55": Decimal("0")})
    
    for order in orders.values():
        if order["date"]:
            day = order["date"].date()
            for key in ["total", "shipping", "tva_20", "tva_55"]:
                daily[day][key] += order[key]
    
    return dict(daily)


def calculate_ht(total: Decimal, shipping: Decimal, tva_20: Decimal, tva_55: Decimal) -> dict:
    """
    Calculate HT amounts from TTC values.
    Returns dict with keys: tva_20, tva_55, sales_20, sales_55, shipping
    """
    # Shipping HT (assuming 20% VAT)
    shipping_ht = (shipping / Decimal("1.20")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if shipping else Decimal("0")
    shipping_tva = shipping - shipping_ht
    
    # Product TVA at 20% = total TVA 20% minus shipping TVA
    product_tva_20 = max(Decimal("0"), tva_20 - shipping_tva)
    
    # HT from TVA amounts
    sales_20 = (product_tva_20 / Decimal("0.20")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if product_tva_20 else Decimal("0")
    sales_55 = (tva_55 / Decimal("0.055")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if tva_55 else Decimal("0")
    
    # Adjust for rounding to ensure balance (debit = sum of credits)
    credits = tva_20 + tva_55 + sales_20 + sales_55 + shipping_ht
    if (diff := total - credits) != 0:
        sales_20 += diff
    
    return {"tva_20": tva_20, "tva_55": tva_55, "sales_20": sales_20, "sales_55": sales_55, "shipping": shipping_ht}


def generate_entries(daily_data: dict) -> list[dict]:
    """Generate journal entries from daily aggregated data."""
    entries = []
    
    for date in sorted(daily_data.keys()):
        data = daily_data[date]
        dt = datetime.combine(date, datetime.min.time())
        date_str = dt.strftime("%d%m%y")
        piece = f"{JOURNAL}{dt.strftime('%y%m%d')}"
        
        amounts = calculate_ht(data["total"], data["shipping"], data["tva_20"], data["tva_55"])
        
        def add_entry(account_key: str, debit: Decimal | str = "", credit: Decimal | str = ""):
            account, label = ACCOUNTS[account_key]
            entries.append({
                "N° Compte": account, "Journal": JOURNAL, "Date écriture": date_str,
                "Commentaire": label, "Montant débit": debit, "Montant crédit": credit,
                "N° Pièce": piece, "Date échéance": "", "Lettrage": ""
            })
        
        # Debit: clients
        add_entry("clients", debit=data["total"])
        
        # Credits: TVA, sales, shipping (only if > 0)
        if amounts["tva_20"] > 0:
            add_entry("tva_20", credit=amounts["tva_20"])
        if amounts["tva_55"] > 0:
            add_entry("tva_55", credit=amounts["tva_55"])
        if amounts["sales_55"] > 0:
            add_entry("sales_55", credit=amounts["sales_55"])
        if amounts["sales_20"] > 0:
            add_entry("sales_20", credit=amounts["sales_20"])
        if amounts["shipping"] > 0:
            add_entry("shipping", credit=amounts["shipping"])
    
    return entries


def write_csv(entries: list[dict], path: str):
    """Write entries to tab-separated CSV."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(entries)


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Parse args
    args = sys.argv[1:]
    input_path = Path(args[0]) if args and not args[0].startswith("-") else Path(__file__).parent / "orders_export.csv"
    output_path = Path(args[args.index("-o") + 1]) if "-o" in args else input_path.with_stem(f"{input_path.stem}_journal")
    
    if not input_path.exists():
        sys.exit(f"Error: File not found: {input_path}")
    
    # Process
    orders = read_orders(str(input_path))
    daily = aggregate_by_date(orders)
    entries = generate_entries(daily)
    write_csv(entries, str(output_path))
    
    # Summary
    print(f"✓ Read {len(orders)} orders from {input_path.name}")
    print(f"✓ Generated {len([e for e in entries if e['N° Compte']])} entries for {len(daily)} days")
    print(f"✓ Output: {output_path}")


if __name__ == "__main__":
    main()
