"""
Lecture et validation du fichier Excel Unyc (export utilisateurs Centrex).
"""

import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"Nom", "Numéro(s)"}


def _extract_mobile_operator(services: str) -> str:
    """Extrait l'opérateur depuis la colonne Services. Ex: 'Fournisseur : ORANGE ...' -> 'Orange'"""
    m = re.search(r"fournisseur\s*:\s*([A-Za-zÀ-ÿ0-9 \-]+?)(?:\s+(?:Ligne|Offre|Iccid|$))",
                  services, re.IGNORECASE)
    if m:
        op = m.group(1).strip().title()
        return op
    return "Inconnu"


def _extract_mobile_offre(services: str) -> str:
    """Extrait l'offre depuis la colonne Services. Ex: 'Offre : Forfait full illimité Réseau'"""
    m = re.search(r"offre\s*:\s*([^|;]+?)(?:\s*(?:Orange|Iccid|Etat|$))",
                  services, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _is_mobile_line(services: str, equipement: str) -> bool:
    """Détecte si c'est une ligne mobile (pas de téléphone physique, services contient Ligne mobile ou Forfait)."""
    svc = services.lower()
    return ("ligne mobile" in svc or "forfait" in svc) and not equipement.strip()


def _detect_brand_model(equipment_str: str) -> tuple[str, str, str]:
    """
    Parse la colonne Equipements : 'Yealink_SIP_T53 : 44DBD202F877'
    Retourne (marque, modele, mac).
    """
    if not equipment_str or equipment_str.strip() == "":
        return "", "", ""

    parts = equipment_str.split(":")
    raw_model = parts[0].strip()          # ex: Yealink_SIP_T53
    mac = parts[1].strip() if len(parts) > 1 else ""

    # Nettoyage MAC (enlever espaces, mettre en majuscules)
    mac = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    if len(mac) == 12:
        mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))

    # Extraction marque / modèle depuis ex: Yealink_SIP_T53, Cisco_SPA504G
    segments = raw_model.replace("-", "_").split("_")
    brand = segments[0] if segments else raw_model

    # Modèle = tout après la marque, sans "SIP" qui n'apporte rien
    model_parts = [s for s in segments[1:] if s.upper() != "SIP"]
    model = " ".join(model_parts) if model_parts else raw_model

    return brand, model, mac


def read_unyc_excel(filepath: str | Path) -> list[dict]:
    """
    Lit le fichier Excel Unyc et retourne une liste de dicts normalisés.
    Ignore les lignes sans équipement physique et les lignes résiliées.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {path}")

    logger.info("Lecture Unyc : %s", path)

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
        raise ValueError(f"Impossible de lire le fichier Excel: {last_exc}")

    # Détection ligne d'en-tête (cherche "Nom")
    header_row = None
    for i, row in df.iterrows():
        values = [str(v).strip().lower() for v in row.values]
        if "nom" in values:
            header_row = i
            break
    if header_row is None:
        raise ValueError("Impossible de trouver la ligne d'entête (colonne 'Nom').")

    df.columns = [str(v).strip() for v in df.iloc[header_row].values]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    df.fillna("", inplace=True)
    df.dropna(how="all", inplace=True)

    # Vérification colonnes obligatoires
    found = {c.lower() for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c.lower() not in found]
    if missing:
        raise ValueError(f"Colonnes manquantes: {missing}")

    rows = []
    skipped = 0
    for _, r in df.iterrows():
        nom        = str(r.get("Nom", "")).strip()
        etat       = str(r.get("Etat", "")).strip().lower()
        equipement = str(r.get("Equipements", "") or r.get("Equipement", "")).strip()
        num_court  = str(r.get("Num. court", "")).strip()
        numeros    = str(r.get("Numéro(s)", "")).strip()
        num_pres   = str(r.get("Num. présenté", "")).strip()
        site       = str(r.get("Site/Département", "")).strip()
        services   = str(r.get("Services", "")).strip()

        # Ignorer lignes vides
        if not nom:
            continue

        # Ignorer résiliés
        if "résilié" in etat or "resilie" in etat:
            logger.info("Ignoré (résilié) : %s", nom)
            skipped += 1
            continue

        # Détection type de ligne
        is_speek  = "speek" in services.lower()
        is_mobile = _is_mobile_line(services, equipement)
        brand, model, mac = _detect_brand_model(equipement)

        if not brand and not is_speek and not is_mobile:
            logger.info("Ignoré (pas d'équipement physique) : %s", nom)
            skipped += 1
            continue

        base = {
            "nom":         nom,
            "num_court":   num_court,
            "numeros":     numeros,
            "num_presente": num_pres,
            "site":        site,
            "services":    services,
            "equipement":  equipement,
            "etat":        etat,
            "is_speek":    False,
            "is_mobile":   False,
            "mobile_operateur": "",
            "mobile_offre":     "",
        }

        # Poste physique
        if brand:
            rows.append({**base, "brand": brand, "model": model, "mac": mac})

        # Softphone Speek
        if is_speek:
            rows.append({**base,
                         "brand":    "Unyc",
                         "model":    "Softphone Speek",
                         "mac":      "",
                         "is_speek": True})

        # Ligne mobile
        if is_mobile:
            operateur = _extract_mobile_operator(services)
            offre     = _extract_mobile_offre(services)
            rows.append({**base,
                         "brand":            operateur,
                         "model":            f"Forfait Mobile {operateur}",
                         "mac":              "",
                         "is_mobile":        True,
                         "mobile_operateur": operateur,
                         "mobile_offre":     offre})

    logger.info("%d lignes chargées, %d ignorées.", len(rows), skipped)
    return rows
