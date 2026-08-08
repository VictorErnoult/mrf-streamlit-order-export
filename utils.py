"""
Utility functions for CSV validation and invoice transformation processing.

Input:  Suffio invoice export (CSV)
Output: Accounting journal entries (Proginov format)
"""

import pandas as pd
from io import StringIO
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP


def is_valid_csv(content_bytes: bytes) -> tuple[bool, str, str]:
    """
    Validate that the uploaded file content is a valid CSV with required columns.
    
    Args:
        content_bytes: The file content as bytes
    
    Returns:
        (is_valid, error_message, encoding): Tuple of boolean, error message, and detected encoding
    """
    try:
        # Try different encodings
        content_str = None
        detected_encoding = None
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                content_str = content_bytes.decode(encoding)
                detected_encoding = encoding
                break
            except UnicodeDecodeError:
                continue
        
        if content_str is None:
            return False, "Impossible de décoder le fichier. Vérifiez l'encodage.", "utf-8"
        
        # Try to parse as CSV with pandas
        df = None
        for delimiter in [',', ';', '\t']:
            try:
                df = pd.read_csv(StringIO(content_str), delimiter=delimiter, nrows=5)
                if len(df.columns) > 1:
                    break
            except (pd.errors.ParserError, ValueError):
                continue
        
        if df is None or len(df.columns) < 2:
            return False, "Le fichier ne semble pas être un CSV valide (pas assez de colonnes).", detected_encoding
        
        # Check for required columns (Suffio format)
        required_columns = ["Number", "Issue date", "Invoice total", "Line item total"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return False, f"Colonnes requises manquantes: {', '.join(missing_columns)}. Vérifiez que c'est bien un export Suffio.", detected_encoding
        
        return True, "", detected_encoding
        
    except Exception as e:
        return False, f"Erreur lors de la validation: {str(e)}", "utf-8"


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
# CORE LOGIC
# =============================================================================

def _is_shipping_line(line_item_name: str, line_item_desc: str) -> bool:
    """
    Determine if a line item represents shipping.
    
    Shipping if the name contains "Livraison" or "DPD" (case-insensitive)
    AND the description does NOT contain "SKU".
    """
    name = str(line_item_name).lower()
    desc = str(line_item_desc).lower()
    has_shipping_keyword = "livraison" in name or "dpd" in name
    has_sku = "sku" in desc
    return has_shipping_keyword and not has_sku


def _parse_tax_rate(rate_str: str) -> Decimal:
    """Parse a tax rate string like '20%' or '5.5%' into a Decimal (e.g. 0.20)."""
    cleaned = str(rate_str).strip().replace("%", "").replace(",", ".")
    # Handle empty / non-numeric / NaN-like values explicitly
    if cleaned == "" or cleaned.lower() in {"nan", "inf", "-inf"}:
        return Decimal("0")
    try:
        value = Decimal(cleaned)
    except Exception:
        return Decimal("0")
    # Guard against Decimal NaN values that would break comparisons later
    if value.is_nan():
        return Decimal("0")
    return value / Decimal("100")


def _safe_decimal(value) -> Decimal:
    """Convert a value to Decimal, handling NaN and empty strings."""
    if pd.isna(value) or str(value).strip() == "":
        return Decimal("0")
    return Decimal(str(value).strip().replace(",", "."))


def read_invoices(csv_source) -> pd.DataFrame:
    """
    Read a Suffio invoice export and extract per-invoice accounting amounts.

    Args:
        csv_source: An already-decoded text source: a file-like object
            (e.g. io.StringIO) or a path to a text file. Decoding from bytes
            must happen upstream (see is_valid_csv for encoding detection),
            so the file is decoded exactly once.

    The Suffio format has multiple rows per invoice (one per line item).
    The first row of each invoice carries invoice-level data (Number, Issue date,
    Invoice total, etc.), while subsequent rows only carry line-item data.

    Returns a DataFrame with one row per invoice and columns:
        number, date, total_ttc, tva_20, tva_55, sales_20_ht, sales_55_ht, shipping_ht

    Returns are detected via the 'Amount due' column (non-zero = return) and have
    their amounts negated so they subtract from daily totals during aggregation.
    """
    df = pd.read_csv(csv_source, dtype=str)
    
    # Forward-fill the invoice Number so every line item row knows its parent invoice
    df["Number"] = df["Number"].replace("", pd.NA)
    df["Number"] = df["Number"].ffill()
    
    # Drop rows that have no line item data at all (e.g. trailing empty rows)
    df = df[df["Line item total"].notna() & (df["Line item total"].str.strip() != "")]
    
    # Extract invoice-level data from first occurrence of each invoice
    invoice_header = df.groupby("Number").first().reset_index()
    
    invoices = []

    for _, header in invoice_header.iterrows():
        inv_number = header["Number"]
        
        # Parse date (always Issue date)
        date = pd.to_datetime(header.get("Issue date", ""), format="%Y-%m-%d", errors="coerce")
        
        # Determine if this is a return: Amount due > 0 means return
        amount_due = _safe_decimal(header.get("Amount due", "0"))
        paid_total = _safe_decimal(header.get("Paid total", "0"))
        invoice_total = _safe_decimal(header.get("Invoice total", "0"))
        status = str(header.get("Status", "")).strip()
        payment_method = str(header.get("Payment method", "")).strip()

        # Exclude unpaid administrative mandates (e.g. Money Order) from the journal:
        # - normal (positive) invoice total
        # - not yet paid (Paid total empty/0, Amount due > 0)
        # - still in Created status
        # These are commitments, not realised sales yet.
        if (
            invoice_total > 0
            and amount_due > 0
            and paid_total == 0
            and status == "Created"
            and payment_method == "Money Order"
        ):
            continue

        sign = Decimal("-1") if amount_due > 0 and paid_total == 0 else Decimal("1")
        
        # Get all line items for this invoice
        inv_lines = df[df["Number"] == inv_number]
        
        tva_20 = Decimal("0")
        tva_55 = Decimal("0")
        sales_20_ht = Decimal("0")
        sales_55_ht = Decimal("0")
        shipping_ht = Decimal("0")
        total_ttc = Decimal("0")
        
        for _, line in inv_lines.iterrows():
            line_total = _safe_decimal(line.get("Line item total", "0"))
            line_tax = _safe_decimal(line.get("Line item tax amount", "0"))
            line_ht = line_total - line_tax
            total_ttc += line_total
            
            # Determine tax rate from "Line item tax 1 rate"
            rate = _parse_tax_rate(line.get("Line item tax 1 rate", "0"))
            is_reduced = abs(rate - Decimal("0.055")) < Decimal("0.01")
            
            is_shipping = _is_shipping_line(
                line.get("Line item", ""),
                line.get("Line item description", "")
            )
            
            if is_reduced:
                tva_55 += line_tax
                sales_55_ht += line_ht
            else:
                tva_20 += line_tax
                if is_shipping:
                    shipping_ht += line_ht
                else:
                    sales_20_ht += line_ht
        
        # Rounding adjustment: ensure total_ttc == tva_20 + tva_55 + sales_20_ht + sales_55_ht + shipping_ht
        credits_sum = tva_20 + tva_55 + sales_20_ht + sales_55_ht + shipping_ht
        if (diff := total_ttc - credits_sum) != 0:
            sales_20_ht += diff

        # Apply sign (returns become negative)
        invoices.append({
            "number": inv_number,
            "date": date,
            "total_ttc": float(sign * total_ttc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "tva_20": float(sign * tva_20.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "tva_55": float(sign * tva_55.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "sales_20_ht": float(sign * sales_20_ht.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "sales_55_ht": float(sign * sales_55_ht.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "shipping_ht": float(sign * shipping_ht.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })
    
    return pd.DataFrame(invoices)


def aggregate_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group invoices by date, summing all amount columns.
    
    Returns are already negative, so they naturally subtract from daily totals.
    """
    df = df[df["date"].notna()].copy()
    df["date_only"] = df["date"].dt.date
    
    amount_cols = ["total_ttc", "tva_20", "tva_55", "sales_20_ht", "sales_55_ht", "shipping_ht"]
    daily = df.groupby("date_only", as_index=False)[amount_cols].sum()
    
    return daily


def generate_entries(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate journal entries from daily aggregated data.
    
    HT amounts are already computed in the DataFrame (from line-item parsing),
    so no reverse-calculation is needed.
    
    Each day produces up to 6 lines:
      - Clients (debit: total TTC)
      - TVA 20% (credit)
      - TVA 5,5% (credit)
      - Ventes produits TVA réduite (credit: sales HT at 5.5%)
      - Ventes marchandises TVA normale (credit: sales HT at 20%)
      - Ports et frais accessoires (credit: shipping HT)
    
    Lines with a zero amount are skipped.
    """
    entries = []
    
    for idx in daily_df.index:
        date = daily_df.at[idx, "date_only"]
        dt = datetime.combine(date, datetime.min.time())
        date_str = dt.strftime("%d%m%y")
        piece = f"{JOURNAL}{dt.strftime('%y%m%d')}"
        
        def add_entry(account_key: str, debit: float | str = "", credit: float | str = ""):
            account, label = ACCOUNTS[account_key]
            
            def round_if_numeric(val):
                if isinstance(val, (int, float)):
                    return round(float(val), 2)
                return val
            
            debit_val = round_if_numeric(debit) if debit != "" else None
            credit_val = round_if_numeric(credit) if credit != "" else None
            
            entries.append({
                "N° Compte": account,
                "Journal": JOURNAL,
                "Date écriture": date_str,
                "Commentaire": label,
                "Montant débit": debit_val,
                "Montant crédit": credit_val,
                "N° Pièce": piece,
                "Date échéance": "",
                "Lettrage": ""
            })
        
        # Helper to safely get scalar value
        def get_val(col):
            val = daily_df.at[idx, col]
            return round(val.item() if hasattr(val, 'item') else float(val), 2)
        
        total_ttc = get_val("total_ttc")
        tva_20 = get_val("tva_20")
        tva_55 = get_val("tva_55")
        sales_55_ht = get_val("sales_55_ht")
        sales_20_ht = get_val("sales_20_ht")
        shipping_ht = get_val("shipping_ht")
        
        # Debit: clients (total TTC)
        if total_ttc != 0:
            add_entry("clients", debit=total_ttc)
        
        # Credits
        if tva_20 != 0:
            add_entry("tva_20", credit=tva_20)
        if tva_55 != 0:
            add_entry("tva_55", credit=tva_55)
        if sales_55_ht != 0:
            add_entry("sales_55", credit=sales_55_ht)
        if sales_20_ht != 0:
            add_entry("sales_20", credit=sales_20_ht)
        if shipping_ht != 0:
            add_entry("shipping", credit=shipping_ht)
    
    return pd.DataFrame(entries, columns=OUTPUT_COLUMNS)

