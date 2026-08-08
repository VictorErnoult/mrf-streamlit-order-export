# Suffio → Journal Comptable

Application Streamlit pour transformer les exports CSV Suffio (factures) en écritures de journal comptable au format Proginov.

## Utilisation

1. Exporter les factures depuis Suffio (format CSV)
2. Téléverser le fichier sur l'application
3. Télécharger le journal comptable généré

## Format d'entrée (Suffio)

Export CSV multi-lignes : chaque facture occupe une ou plusieurs lignes (une par article).

| Champ clé | Usage |
|-----------|-------|
| `Number` | Numéro de facture (regroupe les lignes) |
| `Issue date` | Date utilisée pour les écritures (toujours) |
| `Invoice total` | Total TTC de la facture |
| `Paid total` | Montant payé → facture classique |
| `Amount due` | Montant dû (> 0 et Paid total = 0) → **avoir / retour** |
| `Line item` | Nom de l'article |
| `Line item description` | Description (utilisée pour détecter les SKU) |
| `Line item tax 1 rate` | Taux de TVA de l'article (20% ou 5,5%) |
| `Line item tax amount` | Montant de TVA de l'article |
| `Line item total` | Total TTC de l'article |

## Règles de traitement

### Identification des livraisons

Un article est considéré comme **frais de port** si :
- Son nom (`Line item`) contient « Livraison » ou « DPD » (insensible à la casse)
- **ET** sa description (`Line item description`) ne contient **pas** « SKU »

Tous les autres articles sont des **ventes de marchandises**.

### Identification des retours (avoirs)

- Si `Amount due` > 0 **et** `Paid total` = 0 → la facture est un **retour**
- Les montants du retour sont **négatifs** et se soustraient des totaux journaliers

### Calcul des montants HT

Les montants HT sont calculés directement depuis les articles :
- `HT article = Line item total − Line item tax amount`
- Chaque article est classé par taux de TVA (20% ou 5,5%) et par type (livraison ou vente)
- Un ajustement d'arrondi est appliqué sur les ventes TVA 20% pour équilibrer débit et crédits

### Regroupement

Les factures sont agrégées **par date** (`Issue date`). Toutes les factures sont incluses quel que soit leur statut.

## Format de sortie (Proginov)

Chaque jour produit jusqu'à 6 lignes d'écriture :

| Compte | Libellé | Débit / Crédit |
|--------|---------|----------------|
| 411200000 | Clients | Débit : total TTC |
| 445712000 | TVA 20% | Crédit : TVA collectée à 20% |
| 445710500 | TVA 5,5% | Crédit : TVA collectée à 5,5% |
| 707000012 | Ventes produits finis TVA réduite | Crédit : ventes HT à 5,5% |
| 707000011 | Ventes marchandises TVA normale | Crédit : ventes HT à 20% |
| 708500011 | Ports et frais accessoires facturés | Crédit : livraison HT |

Les lignes avec un montant nul sont omises.

## Colonnes de sortie

| Colonne | Description |
|---------|-------------|
| N° Compte | Numéro de compte comptable |
| Journal | Code journal (VT2) |
| Date écriture | Date au format JJMMAA |
| Commentaire | Libellé de l'écriture |
| Montant débit | Montant au débit |
| Montant crédit | Montant au crédit |
| N° Pièce | Référence (JOURNAL + AAMMJJ) |
| Date échéance | (vide) |
| Lettrage | (vide) |

## Développement local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Déploiement

Déployable gratuitement sur [Streamlit Cloud](https://share.streamlit.io).

### Mot de passe (optionnel)

L'application peut être protégée par un mot de passe via les secrets Streamlit. Si aucun secret n'est configuré, l'application reste en accès libre (pratique en local).

Sur Streamlit Cloud : ouvrir l'application → **Settings** → **Secrets**, puis ajouter :

```toml
app_password = "votre-mot-de-passe"
```

En local, créer un fichier `.streamlit/secrets.toml` avec la même clé (ne pas le committer).
