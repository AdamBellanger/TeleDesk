"""
Transformation d'une ligne fibre en payload Bob! Desk.
Catégorie : Réseau / Fibre FTTH|FTTO|FTTO+GTR
"""

import logging
from referential import Referential

logger = logging.getLogger(__name__)

# IDs Bob! Desk
CAT_RESEAU   = "69a8566fdf8a4f00136f2e2c"
JOB_RESEAU   = "5ff2f3f5fa15ef0018f7ff9d"

SUBCATEGORY_IDS = {
    "Fibre FTTH":      "69fc57d6faa5740012e78a89",
    "Fibre FTTO":      "69fc57deabf911001a3e2d3c",
    "Fibre FTTO + GTR": "69fc57e8abf911001a3e2dab",
}


class FibreMappingError(Exception):
    pass


def _detect_subcategory(offre: str, gtr: str) -> str:
    offre_l = offre.lower()
    gtr_l   = gtr.lower()

    has_gtr = gtr_l and "sans" not in gtr_l and gtr_l not in ("", "non", "no")

    if "ftth" in offre_l:
        return "Fibre FTTH"
    if "ftto" in offre_l and has_gtr:
        return "Fibre FTTO + GTR"
    if "ftto" in offre_l:
        return "Fibre FTTO"
    # fallback
    if has_gtr:
        return "Fibre FTTO + GTR"
    return "Fibre FTTO"


def _short_offre(offre: str) -> str:
    """Ex: 'FTTH - 1000M (Max)' -> 'FTTH 1000M'"""
    import re
    s = re.sub(r"\(.*?\)", "", offre).strip()  # enlève les parenthèses
    s = s.replace(" - ", " ").replace("-", " ").strip()
    return s


class FibreMapper:

    def __init__(self, operateur: str):
        self.operateur = operateur.strip()

    def map_row(self, row: dict) -> dict:
        ref      = row.get("reference", "").strip()
        offre    = row.get("offre", "").strip()
        gtr      = row.get("gtr", "").strip()
        backup   = row.get("backup", "").strip()
        vpn      = row.get("vpn", "").strip()
        ip       = row.get("ip", "").strip()
        livraison = row.get("livraison", "").strip()
        site     = row.get("site", "").strip()
        sante    = row.get("sante", "").strip()

        if not ref:
            raise FibreMappingError("Référence manquante.")
        if not offre:
            raise FibreMappingError(f"Offre manquante pour {ref}.")

        subcat_name = _detect_subcategory(offre, gtr)
        subcat_id   = SUBCATEGORY_IDS[subcat_name]
        short_offre = _short_offre(offre)

        # Nom : "IP-260330-154939 - FTTH 1000M - Orange"
        name = f"{ref} - {short_offre} - {self.operateur}"

        # Description
        parts = []
        if site:
            parts.append(f"Site: {site}")
        if gtr:
            parts.append(f"GTR: {gtr}")
        if backup:
            parts.append(f"Backup: {backup}")
        if vpn:
            parts.append(f"VPN: {vpn}")
        if ip:
            parts.append(f"IP: {ip}")
        if livraison:
            parts.append(f"Livraison: {livraison}")
        if sante:
            parts.append(f"Santé: {sante}")
        description = " | ".join(parts)

        return {
            "name":                  name,
            "brand":                 self.operateur,
            "model":                 short_offre,
            "serial":                ref,
            "description":           description,
            "_category":    CAT_RESEAU,
            "_subcategory": subcat_id,
            "_jobs":                 [JOB_RESEAU],
        }
