"""
Tests for utils.py using a synthetic CSV fixture matching the Suffio column layout.

No real customer data: all invoice numbers, items and amounts are made up.
"""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import (
    is_valid_csv,
    read_invoices,
    aggregate_by_date,
    generate_entries,
)

HEADER = (
    "Number,Issue date,Status,Payment method,Invoice total,Paid total,Amount due,"
    "Line item,Line item description,Line item tax 1 rate,Line item tax amount,Line item total"
)

# Two invoices on the same day: mixed 20% / 5.5% VAT, one shipping line.
NORMAL_CSV = "\n".join([
    HEADER,
    "F001,2026-07-01,Paid,Card,87.10,87.10,0,Kit fournitures,Kit SKU-123,20%,10.00,60.00",
    ",,,,,,,Livre scolaire,Manuel SKU-456,5.5%,1.10,21.10",
    ",,,,,,,Livraison DPD,Transport a domicile,20%,1.00,6.00",
    "F002,2026-07-01,Paid,Card,12.00,12.00,0,Cahier,Cahier SKU-789,20%,2.00,12.00",
])


def _read(csv_text: str):
    return read_invoices(io.StringIO(csv_text))


# ---------------------------------------------------------------------------
# Encoding pass-through
# ---------------------------------------------------------------------------

def test_latin1_encoding_pass_through():
    """A latin-1 Suffio export must validate AND parse with the same encoding."""
    csv_text = "\n".join([
        HEADER,
        "F100,2026-07-02,Paid,Card,24.00,24.00,0,Livraison légère,Frais de déplacement,20%,4.00,24.00",
    ])
    content_bytes = csv_text.encode("latin-1")

    # utf-8 decode fails on the accented bytes, so latin-1 must be detected
    is_valid, error_msg, detected_encoding = is_valid_csv(content_bytes)
    assert is_valid, error_msg
    assert detected_encoding == "latin-1"

    # Single decode with the detected encoding, then parse from memory
    decoded = content_bytes.decode(detected_encoding)
    invoices_df, diffs = read_invoices(io.StringIO(decoded))

    assert len(invoices_df) == 1
    row = invoices_df.iloc[0]
    assert row["number"] == "F100"
    # "Livraison légère" must survive decoding intact and classify as shipping
    assert row["shipping_ht"] == pytest.approx(20.00)
    assert row["tva_20"] == pytest.approx(4.00)
    assert row["total_ttc"] == pytest.approx(24.00)
    assert diffs == []


# ---------------------------------------------------------------------------
# Rounding-diff detection
# ---------------------------------------------------------------------------

def test_rounding_diff_over_threshold_is_reported():
    """Declared Invoice total 0.10 EUR above the line sum must be reported."""
    csv_text = "\n".join([
        HEADER,
        "F200,2026-07-03,Paid,Card,100.10,100.10,0,Article,Desc article,20%,16.68,100.00",
    ])
    invoices_df, diffs = _read(csv_text)

    assert len(invoices_df) == 1
    assert len(diffs) == 1
    assert diffs[0]["number"] == "F200"
    assert diffs[0]["diff"] == pytest.approx(0.10)


def test_subcent_diff_is_not_reported():
    """A sub-cent discrepancy is normal rounding noise: no warning."""
    csv_text = "\n".join([
        HEADER,
        "F201,2026-07-03,Paid,Card,50.004,50.00,0,Article,Desc article,20%,8.33,50.00",
    ])
    invoices_df, diffs = _read(csv_text)

    assert len(invoices_df) == 1
    assert diffs == []


def test_exact_totals_report_nothing():
    invoices_df, diffs = _read(NORMAL_CSV)
    assert len(invoices_df) == 2
    assert diffs == []


# ---------------------------------------------------------------------------
# Journal entries still balance
# ---------------------------------------------------------------------------

def test_generated_entries_balance():
    """On a normal fixture, total debit equals total credit (per day and overall)."""
    invoices_df, _ = _read(NORMAL_CSV)
    daily_df = aggregate_by_date(invoices_df)
    entries_df = generate_entries(daily_df)

    assert not entries_df.empty

    debit = entries_df["Montant débit"].fillna(0).sum()
    credit = entries_df["Montant crédit"].fillna(0).sum()
    assert debit == pytest.approx(credit)
    assert debit == pytest.approx(99.10)  # 87.10 + 12.00

    # Per-pièce balance too
    for piece, group in entries_df.groupby("N° Pièce"):
        assert group["Montant débit"].fillna(0).sum() == pytest.approx(
            group["Montant crédit"].fillna(0).sum()
        ), f"unbalanced pièce {piece}"

    # Bucket sanity: shipping and reduced-VAT sales landed on their accounts
    by_account = entries_df.set_index("N° Compte")["Montant crédit"]
    assert by_account["708500011"] == pytest.approx(5.00)   # shipping HT
    assert by_account["707000012"] == pytest.approx(20.00)  # sales HT 5.5%
    assert by_account["707000011"] == pytest.approx(60.00)  # sales HT 20%
    assert by_account["445712000"] == pytest.approx(13.00)  # TVA 20%
    assert by_account["445710500"] == pytest.approx(1.10)   # TVA 5.5%
