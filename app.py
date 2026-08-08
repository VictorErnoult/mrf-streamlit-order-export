"""
Streamlit app for transforming Suffio invoice exports to accounting journal entries.

Run locally: streamlit run app.py
Deploy: Push to GitHub, connect to Streamlit Cloud
"""

import hmac
import io
import traceback

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


def check_password() -> None:
    """
    Optional password gate.

    If an "app_password" secret is configured (Streamlit Cloud secrets or a
    local .streamlit/secrets.toml), require it before showing the app.
    If no secret is configured, the app runs open as before.
    """
    try:
        expected = st.secrets["app_password"]
    except Exception:
        # No secrets.toml or no "app_password" key: open access (local usage)
        return

    if st.session_state.get("password_ok"):
        return

    password = st.text_input("🔒 Mot de passe", type="password")
    if not password:
        st.stop()
    if hmac.compare_digest(str(password), str(expected)):
        st.session_state["password_ok"] = True
        return
    st.error("Mot de passe incorrect.")
    st.stop()


check_password()

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

    # Process entirely in memory (no temp file on disk)
    try:
        content_str = content_bytes.decode(detected_encoding)
        invoices_df, rounding_diffs = read_invoices(io.StringIO(content_str))
        daily_df = aggregate_by_date(invoices_df)
        entries_df = generate_entries(daily_df)

        # Success message
        st.success(f"✓ {len(invoices_df)} factures lues · {len(daily_df)} jours · {len(entries_df)} écritures")

        # Warn if some invoices have a suspicious rounding difference
        if rounding_diffs:
            details = "\n".join(
                f"- Facture {d['number']} : écart de {d['diff']:+.2f} €"
                for d in rounding_diffs
            )
            st.warning(
                "⚠️ Écart d'arrondi supérieur à 0,05 € détecté sur certaines factures "
                "(différence entre le total TTC déclaré et la somme des lignes). "
                "L'écart a été absorbé dans les ventes TVA 20%, mais vérifiez ces factures dans Suffio :\n\n"
                + details
            )

        # Create downloadable Excel file
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

    except Exception:
        # Full traceback goes to the server logs only, never to the visitor
        traceback.print_exc()
        st.error("Une erreur est survenue lors du traitement du fichier. Vérifiez le format du fichier et réessayez.")

else:
    st.info("👆 Insère un fichier CSV exporté depuis Suffio (Factures → Exporter)")
