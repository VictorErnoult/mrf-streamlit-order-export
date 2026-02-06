"""
Streamlit app for transforming Suffio invoice exports to accounting journal entries.

Run locally: streamlit run app.py
Deploy: Push to GitHub, connect to Streamlit Cloud
"""

import streamlit as st
import pandas as pd

# Import core logic from utils module
from utils import (
    is_valid_csv,
    read_invoices,
    aggregate_by_date,
    generate_entries,
    OUTPUT_COLUMNS
)

st.set_page_config(page_title="Martha la Compta", page_icon="📊", layout="centered")

st.title(":nerd_face: Martha la Compta ")
st.subheader("📊 Suffio → Journal Comptable")
st.caption("Transforme l'export CSV Suffio en journal comptable formaté pour Proginov.")

# File upload
uploaded_file = st.file_uploader("Ajoute l'export Suffio (CSV)", type=["csv"])

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
        invoices_df = read_invoices(tmp_path)
        daily_df = aggregate_by_date(invoices_df)
        entries_df = generate_entries(daily_df)
        
        # Success message
        st.success(f"✓ {len(invoices_df)} factures lues · {len(daily_df)} jours · {len(entries_df)} écritures")
        
        # Create downloadable Excel file
        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            entries_df.to_excel(writer, index=False, sheet_name="Journal")
        output.seek(0)
        
        st.download_button(
            label="⬇️ Télécharger le journal",
            data=output.getvalue(),
            file_name="journal_comptable.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Preview
        st.subheader("Aperçu")
        st.dataframe(entries_df.head(20), width='stretch', hide_index=True)
        
    except Exception as e:
        st.error(f"Erreur: {e}")
    
    # Cleanup
    import os
    os.unlink(tmp_path)

else:
    st.info("👆 Insère un fichier CSV exporté depuis Suffio (Factures → Exporter)")

