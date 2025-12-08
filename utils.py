"""
Utility functions for CSV validation and order transformation processing.
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
        # pandas can auto-detect delimiter, but we'll try common ones
        df = None
        for delimiter in [',', ';', '\t']:
            try:
                df = pd.read_csv(StringIO(content_str), delimiter=delimiter, nrows=5)
                if len(df.columns) > 1:  # Valid CSV should have multiple columns
                    break
            except (pd.errors.ParserError, ValueError):
                continue
        
        if df is None or len(df.columns) < 2:
            return False, "Le fichier ne semble pas être un CSV valide (pas assez de colonnes).", detected_encoding
        
        # Check for required columns (at minimum, we need "Name" column)
        required_columns = ["Name"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return False, f"Colonnes requises manquantes: {', '.join(missing_columns)}. Vérifiez que c'est bien un export Shopify.", detected_encoding
        
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

def read_orders(csv_path: str) -> pd.DataFrame:
    """Read CSV and extract order totals (first row of each order has the data)."""
    df = pd.read_csv(csv_path, encoding="utf-8")
    
    # Keep only first row per order (drop duplicates on Name)
    df = df[df["Name"].notna() & (df["Name"].str.strip() != "")].drop_duplicates(subset="Name", keep="first")
    
    # Parse dates (use "Paid at" or fallback to "Created at")
    date_col = df["Paid at"].fillna(df["Created at"])
    df["date"] = pd.to_datetime(date_col.str[:10], format="%Y-%m-%d", errors="coerce")
    
    # Parse amounts (replace comma with dot, convert to float)
    for col in ["Total", "Shipping", "Tax 1 Value", "Tax 2 Value"]:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "."), errors="coerce").fillna(0)
    
    # Calculate TVA amounts
    df["tva_20"] = 0.0
    df["tva_55"] = 0.0
    
    for i in [1, 2]:
        tax_name_col = f"Tax {i} Name"
        tax_value_col = f"Tax {i} Value"
        if tax_name_col in df.columns:
            is_reduced = df[tax_name_col].astype(str).str.contains("5[,.]5", na=False, regex=True)
            df["tva_55"] += df[tax_value_col].where(is_reduced, 0)
            df["tva_20"] += df[tax_value_col].where(~is_reduced & (df[tax_value_col] > 0), 0)
    
    return df[["Name", "date", "Total", "Shipping", "tva_20", "tva_55"]].rename(columns={"Total": "total", "Shipping": "shipping"})


def aggregate_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Group orders by date, summing all amounts."""
    df = df[df["date"].notna()].copy()
    df["date_only"] = df["date"].dt.date
    
    daily = df.groupby("date_only", as_index=False).agg({
        "total": "sum",
        "shipping": "sum",
        "tva_20": "sum",
        "tva_55": "sum"
    })
    
    return daily


def calculate_ht(row: pd.Series) -> pd.Series:
    """
    Calculate HT amounts from TTC values.
    Returns Series with keys: tva_20, tva_55, sales_20, sales_55, shipping
    """
    total = Decimal(str(row["total"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    shipping = Decimal(str(row["shipping"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tva_20 = Decimal(str(row["tva_20"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tva_55 = Decimal(str(row["tva_55"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
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
    
    return pd.Series({
        "tva_20": float(tva_20),
        "tva_55": float(tva_55),
        "sales_20": float(sales_20),
        "sales_55": float(sales_55),
        "shipping": float(shipping_ht)
    })


def generate_entries(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Generate journal entries from daily aggregated data."""
    entries = []
    
    # Calculate HT amounts for each day
    amounts_df = daily_df.apply(calculate_ht, axis=1)
    
    # Helper to safely get scalar value
    def get_scalar(df, idx, col):
        val = df.at[idx, col]
        return val.item() if hasattr(val, 'item') else float(val)
    
    for idx in daily_df.index:
        date = daily_df.at[idx, "date_only"]
        dt = datetime.combine(date, datetime.min.time())
        date_str = dt.strftime("%d%m%y")
        piece = f"{JOURNAL}{dt.strftime('%y%m%d')}"
        
        def add_entry(account_key: str, debit: float | str = "", credit: float | str = ""):
            account, label = ACCOUNTS[account_key]
            entries.append({
                "N° Compte": account,
                "Journal": JOURNAL,
                "Date écriture": date_str,
                "Commentaire": label,
                "Montant débit": debit if debit != "" else "",
                "Montant crédit": credit if credit != "" else "",
                "N° Pièce": piece,
                "Date échéance": "",
                "Lettrage": ""
            })
        
        # Debit: clients
        total_val = get_scalar(daily_df, idx, "total")
        add_entry("clients", debit=total_val)
        
        # Credits: TVA from original data, sales/shipping from calculated amounts
        tva_20_val = get_scalar(daily_df, idx, "tva_20")
        tva_55_val = get_scalar(daily_df, idx, "tva_55")
        sales_55_val = get_scalar(amounts_df, idx, "sales_55")
        sales_20_val = get_scalar(amounts_df, idx, "sales_20")
        shipping_val = get_scalar(amounts_df, idx, "shipping")
        
        if tva_20_val > 0:
            add_entry("tva_20", credit=tva_20_val)
        if tva_55_val > 0:
            add_entry("tva_55", credit=tva_55_val)
        if sales_55_val > 0:
            add_entry("sales_55", credit=sales_55_val)
        if sales_20_val > 0:
            add_entry("sales_20", credit=sales_20_val)
        if shipping_val > 0:
            add_entry("shipping", credit=shipping_val)
    
    return pd.DataFrame(entries, columns=OUTPUT_COLUMNS)

