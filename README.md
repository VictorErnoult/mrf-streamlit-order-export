# Shopify → Journal Comptable

Application Streamlit pour transformer les exports CSV Shopify en écritures de journal comptable.

## Utilisation

1. Exporter les commandes depuis Shopify (Commandes → Exporter → CSV)
2. Téléverser le fichier sur l'application
3. Télécharger le journal comptable généré

## Format de sortie

| Colonne | Description |
|---------|-------------|
| N° Compte | Numéro de compte comptable |
| Journal | Code journal (VT2) |
| Date écriture | Date au format JJMMAA |
| Commentaire | Libellé de l'écriture |
| Montant débit | Montant au débit |
| Montant crédit | Montant au crédit |
| N° Pièce | Référence (JOURNAL + AAMMJJ) |

## Comptes utilisés

| Compte | Libellé |
|--------|---------|
| 411200000 | Clients |
| 445712000 | TVA 20% |
| 445710500 | TVA 5,5% |
| 707000012 | Ventes produits finis TVA réduite |
| 707000011 | Ventes marchandises TVA normale |
| 708500011 | Ports et frais accessoires facturés |

## Développement local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Déploiement

Déployable gratuitement sur [Streamlit Cloud](https://share.streamlit.io).

