"""
Streamlit app for transforming Shopify order exports to accounting journal entries.

Run locally: streamlit run app.py
Deploy: Push to GitHub, connect to Streamlit Cloud
"""

import streamlit as st
import pandas as pd
from io import StringIO

# Import core logic from utils module
from utils import (
    is_valid_csv,
    read_orders,
    aggregate_by_date,
    generate_entries,
    OUTPUT_COLUMNS
)

st.set_page_config(page_title="Martha la Compta", page_icon="📊", layout="centered")

st.title(":nerd_face: Martha la Compta ")
st.subheader("📊 Shopify → Journal Comptable")
st.caption("Transforme l'export CSV Shopify brut en journal comptable formaté pour Proginov.")

# File upload
uploaded_file = st.file_uploader("Ajoute l'export Shopify (CSV)", type=["csv"])

if uploaded_file:

    # Read file content once
    content_bytes = uploaded_file.getvalue()
    
    # Check if the file is a valid CSV
    is_valid, error_msg, detected_encoding = is_valid_csv(content_bytes)
    
    if not is_valid:
        st.error(f"❌ Fichier invalide: {error_msg}")
        st.stop()
    

    # Save to temp file for processing
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding=detected_encoding) as tmp:
        content_str = content_bytes.decode(detected_encoding)
        tmp.write(content_str)
        tmp_path = tmp.name
    
    # Process
    try:
        orders_df = read_orders(tmp_path)
        daily_df = aggregate_by_date(orders_df)
        entries_df = generate_entries(daily_df)
        
        # Success message
        st.success(f"✓ {len(orders_df)} commandes lues · {len(daily_df)} jours · {len(entries_df)} écritures")
        
        # Create downloadable CSV with semicolon delimiter and UTF-8 BOM for Excel compatibility
        output = StringIO()
        entries_df.to_csv(output, sep=";", index=False, encoding="utf-8-sig")
        
        st.download_button(
            label="⬇️ Télécharger le journal",
            data=output.getvalue(),
            file_name="journal_comptable.csv",
            mime="text/csv"
        )
        
        # Preview
        st.subheader("Aperçu")
        st.dataframe(entries_df.head(20), use_container_width=True, hide_index=True)
        
    except Exception as e:
        st.error(f"Erreur: {e}")
    
    # Cleanup
    import os
    os.unlink(tmp_path)

else:
    st.info("👆 Insère un fichier CSV exporté depuis Shopify (Commandes → Exporter)")

