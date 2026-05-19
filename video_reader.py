"""
Lecture des fichiers Excel vidéosurveillance.
Structure variable : en-tête client en haut, tableau après "LISTE MATERIEL INSTALLE".
Colonnes détectées par nom (insensible à la casse, variantes gérées).
"""

import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Variantes acceptées pour chaque colonne cible
_COL_ALIASES = {
    "designation":       ["designation", "désignation"],
    "reference":         ["reference", "référence", "modèle", "modele", "model"],
    "serial":            ["numero serie", "numéro serie", "numéro de série", "numero de serie", "serial", "n° serie"],
    "mac":               ["adresse mac", "mac", "microcode"],
    "ip":                ["adresse ip", "adresse", "ip"],
    "firmware":          ["version logicielle", "firmware", "version fw", "version"],
    "nom":               ["nom", "name"],
    "date_installation": ["date installation", "date d'installation"],
    "remarques":         ["remarques", "remarque", "notes", "commentaires"],
    "enr_regulier":      ["enregistrement regulier", "enregistrement régulier", "enr regulier"],
    "enr_alarme":        ["enregistrement alarme", "enr alarme", "alarme"],
}


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _match_col(header: str) -> str | None:
    h = _normalize(header)
    for target, aliases in _COL_ALIASES.items():
        if any(h == a or h.startswith(a) for a in aliases):
            return target
    return None


def _find_table_start(df_raw: pd.DataFrame) -> int | None:
    """Retourne l'index de la ligne d'en-tête du tableau (après 'LISTE MATERIEL INSTALLE')."""
    found_banner = False
    for i, row in df_raw.iterrows():
        vals = [_normalize(str(v)) for v in row.values if pd.notna(v) and str(v).strip()]
        if not found_banner:
            if any("liste materiel" in v or "liste matériel" in v for v in vals):
                found_banner = True
            continue
        # Ligne après la bannière : cherche "designation" dedans
        if any("designation" in v or "désignation" in v for v in vals):
            return i
    return None


def read_video_excel(path: str) -> list[dict]:
    path = Path(path)
    rows = []

    for engine in ("calamine", "openpyxl", "xlrd"):
        try:
            df_raw = pd.read_excel(path, dtype=str, engine=engine, header=None)
            break
        except Exception:
            continue
    else:
        raise ValueError(f"Impossible de lire le fichier : {path}")

    header_idx = _find_table_start(df_raw)
    if header_idx is None:
        raise ValueError("En-tête 'LISTE MATERIEL INSTALLE' introuvable dans le fichier.")

    # Reconstruit un DataFrame à partir de la ligne d'en-tête
    headers = [str(v).strip() if pd.notna(v) else "" for v in df_raw.iloc[header_idx]]
    data = df_raw.iloc[header_idx + 1:].reset_index(drop=True)
    data.columns = headers

    # Mappe les colonnes détectées
    col_map = {}  # target -> nom colonne Excel
    for col in data.columns:
        target = _match_col(col)
        if target and target not in col_map:
            col_map[target] = col

    logger.info("Colonnes détectées : %s", list(col_map.keys()))

    def get(row, key):
        col = col_map.get(key)
        if col is None:
            return ""
        v = row.get(col, "")
        return "" if pd.isna(v) else str(v).strip()

    ignored = 0
    for _, row in data.iterrows():
        designation = get(row, "designation")
        # Ignore lignes vides ou parasites (IPServeur, Masque, Gateway, DNS…)
        if not designation or _normalize(designation) in (
            "ipserveur (cam)", "ipserveur (data)", "masque", "gateway",
            "dns1", "dns2", "dns", "ipserveur", "nan", "",
        ):
            ignored += 1
            continue

        rows.append({
            "designation":       designation,
            "reference":         get(row, "reference"),
            "serial":            get(row, "serial"),
            "mac":               get(row, "mac"),
            "ip":                get(row, "ip"),
            "firmware":          get(row, "firmware"),
            "nom":               get(row, "nom"),
            "date_installation": get(row, "date_installation"),
            "remarques":         get(row, "remarques"),
            "enr_regulier":      get(row, "enr_regulier"),
            "enr_alarme":        get(row, "enr_alarme"),
        })

    logger.info("Vidéo : %d ligne(s) chargée(s), %d ignorée(s).", len(rows), ignored)
    return rows
