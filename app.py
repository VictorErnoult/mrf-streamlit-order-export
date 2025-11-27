"""
Streamlit app for transforming Shopify order exports to accounting journal entries.

Run locally: streamlit run app.py
Deploy: Push to GitHub, connect to Streamlit Cloud
"""

import streamlit as st
import pandas as pd
from io import StringIO

# Import core logic from the transform script
from transform_order_export import (
    read_orders, aggregate_by_date, generate_entries, OUTPUT_COLUMNS
)

st.set_page_config(page_title="Export Comptable", page_icon="📊", layout="centered")

st.title("📊 Shopify → Journal Comptable")
st.caption("Transforme l'export CSV Shopify en écritures comptables")

# File upload
uploaded_file = st.file_uploader("Téléverser l'export Shopify (CSV)", type=["csv"])

if uploaded_file:
    # Save to temp file for processing
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        content = uploaded_file.getvalue().decode("utf-8")
        tmp.write(content)
        tmp_path = tmp.name
    
    # Process
    try:
        orders = read_orders(tmp_path)
        daily = aggregate_by_date(orders)
        entries = generate_entries(daily)
        
        # Filter out empty separator rows for stats
        real_entries = [e for e in entries if e["N° Compte"]]
        
        # Success message
        st.success(f"✓ {len(orders)} commandes lues · {len(daily)} jours · {len(real_entries)} écritures")
        
        # Create downloadable CSV
        output = StringIO()
        output.write("\t".join(OUTPUT_COLUMNS) + "\n")
        for entry in entries:
            output.write("\t".join(str(entry.get(col, "")) for col in OUTPUT_COLUMNS) + "\n")
        
        st.download_button(
            label="⬇️ Télécharger le journal",
            data=output.getvalue(),
            file_name="journal_comptable.csv",
            mime="text/csv"
        )
        
        # Preview
        st.subheader("Aperçu")
        df = pd.DataFrame(real_entries[:20])
        st.dataframe(df, use_container_width=True, hide_index=True)
        
    except Exception as e:
        st.error(f"Erreur: {e}")
    
    # Cleanup
    import os
    os.unlink(tmp_path)

else:
    st.info("👆 Téléversez un fichier CSV exporté depuis Shopify (Commandes → Exporter)")

