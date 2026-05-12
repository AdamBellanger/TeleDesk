"""
Lecture et validation du fichier Excel liens fibre (Orange, Unyc, Kiosque...).
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"Référence", "Offre"}


def read_fibre_excel(filepath: str | Path) -> list[dict]:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {path}")

    logger.info("Lecture fibre : %s", path)

    df = None
    last_exc = None
    for engine in ("calamine", "openpyxl", "xlrd"):
        try:
            df = pd.read_excel(path, dtype=str, engine=engine, header=None)
            logger.info("Fichier lu avec '%s'.", engine)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc

    if last_exc is not None:
        raise ValueError(f"Impossible de lire le fichier: {last_exc}")

    # Détection ligne d'en-tête (cherche "Référence" ou "Etat")
    header_row = None
    for i, row in df.iterrows():
        vals = [str(v).strip().lower() for v in row.values]
        if "référence" in vals or "reference" in vals or "etat" in vals or "état" in vals:
            header_row = i
            break
    if header_row is None:
        raise ValueError("Impossible de trouver la ligne d'entête.")

    df.columns = [str(v).strip() for v in df.iloc[header_row].values]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    df.fillna("", inplace=True)
    df.dropna(how="all", inplace=True)

    rows = []
    skipped = 0
    for _, r in df.iterrows():
        ref      = str(r.get("Référence", "")).strip()
        etat     = str(r.get("Etat", r.get("État", ""))).strip()
        site     = str(r.get("Site installation", "")).strip()
        offre    = str(r.get("Offre", "")).strip()
        gtr      = str(r.get("GTR", "")).strip()
        backup   = str(r.get("Backup", "")).strip()
        vpn      = str(r.get("VPN", "")).strip()
        ip       = str(r.get("Adresse IP", "")).strip()
        livraison = str(r.get("Date de livraison", "")).strip()
        sante    = str(r.get("Santé", r.get("Sante", ""))).strip()

        if not ref:
            continue

        # Ignorer résiliés
        if "résilié" in etat.lower() or "resilie" in etat.lower():
            logger.info("Ignoré (résilié) : %s", ref)
            skipped += 1
            continue

        rows.append({
            "reference": ref,
            "etat":      etat,
            "sante":     sante,
            "site":      site,
            "offre":     offre,
            "gtr":       gtr,
            "backup":    backup,
            "vpn":       vpn,
            "ip":        ip,
            "livraison": livraison,
        })

    logger.info("%d liens chargés, %d ignorés.", len(rows), skipped)
    return rows
