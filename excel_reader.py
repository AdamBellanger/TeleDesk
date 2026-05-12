"""
Lecture et validation du fichier Excel Alcatel-Lucent.
"""

import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

# Colonnes minimales obligatoires dans le fichier Excel
REQUIRED_COLUMNS = {"EDN", "Catégorie", "Type"}


def read_alcatel_excel(filepath: str | Path) -> list[dict]:
    """
    Lit le fichier Excel Alcatel et retourne une liste de dicts (une entrée par ligne).
    Lève ValueError si le fichier est invalide ou manque de colonnes essentielles.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {path}")

    logger.info("Lecture de %s", path)

    # Tentative avec plusieurs moteurs par ordre de tolérance
    last_exc = None
    df = None
    for engine in ("calamine", "openpyxl", "xlrd"):
        try:
            df = pd.read_excel(path, dtype=str, engine=engine, header=None)
            logger.info("Fichier lu avec le moteur '%s'.", engine)
            last_exc = None
            break
        except Exception as exc:
            logger.debug("Moteur '%s' échoué: %s", engine, exc)
            last_exc = exc
    if last_exc is not None:
        raise ValueError(f"Impossible de lire le fichier Excel: {last_exc}") from last_exc

    # Détection automatique de la ligne d'entête (cherche la ligne qui contient "EDN")
    header_row = None
    for i, row in df.iterrows():
        values = [str(v).strip().lower() for v in row.values]
        if "edn" in values:
            header_row = i
            break
    if header_row is None:
        raise ValueError(
            "Impossible de trouver la ligne d'entête (colonne 'EDN') dans le fichier Excel.\n"
            f"Colonnes trouvées sur la première ligne: {list(df.iloc[0].values)}"
        )
    df.columns = [str(v).strip() for v in df.iloc[header_row].values]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    logger.info("Entête détectée à la ligne %d.", header_row + 1)

    # Nettoyage des noms de colonnes
    df.columns = [str(c).strip() for c in df.columns]

    # Vérification des colonnes obligatoires (insensible à la casse)
    found_cols = {c.lower() for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c.lower() not in found_cols]
    if missing:
        raise ValueError(
            f"Colonnes obligatoires manquantes dans le fichier Excel: {missing}\n"
            f"Colonnes trouvées: {list(df.columns)}"
        )

    # Suppression des lignes entièrement vides
    df.dropna(how="all", inplace=True)

    # Remplacement des NaN par chaîne vide
    df.fillna("", inplace=True)

    rows = df.to_dict(orient="records")
    logger.info("%d lignes chargées depuis Excel.", len(rows))
    return rows
