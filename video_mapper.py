"""
Mapping vidéosurveillance -> Bob! Desk.
Détecte la catégorie/sous-catégorie selon la DESIGNATION.
"""

import logging
import re

logger = logging.getLogger(__name__)


class VideoMappingError(Exception):
    pass


# IDs Bob! Desk — catégories
_CAT_CAMERA  = "683eb1f03ed3af001255ea0b"
_CAT_SERVEUR = "683eb21d3e53c0001925ca6f"

# IDs Bob! Desk — sous-catégories
_SUBCAT = {
    "Caméra IP":                "6a0c34a1338bbc0013e1a227",
    "Caméra Analogique":        "6a0c34a12f81e00019972ef3",
    "Caméra Dôme":              "6a0c34a1c3897c0012284f47",
    "Caméra PTZ":               "6a0c34a12f81e00019972ef5",
    "NVR":                      "6a0c34a1c3897c0012284f49",
    "DVR":                      "6a0c34a1338bbc0013e1a229",
    "Encodeur":                 "6a0c34a12f81e00019972ef7",
    "Serveur d'enregistrement": "6a0c34a1338bbc0013e1a22b",
}

# Règles de détection par mots-clés dans la DESIGNATION (ordre = priorité)
_DETECTION_RULES = [
    # Serveur vidéo
    (r"nvr",                       _CAT_SERVEUR, "NVR"),
    (r"dvr",                       _CAT_SERVEUR, "DVR"),
    (r"encodeur|encoder",          _CAT_SERVEUR, "Encodeur"),
    (r"camtrace|serveur|recorder|enregistr", _CAT_SERVEUR, "Serveur d'enregistrement"),
    # Caméras spécialisées
    (r"ptz|motoris",               _CAT_CAMERA,  "Caméra PTZ"),
    (r"d[oô]me|dome",              _CAT_CAMERA,  "Caméra Dôme"),
    (r"analog",                    _CAT_CAMERA,  "Caméra Analogique"),
    # Caméra générique (AXIS, Caméra IP, Camera…)
    (r"cam[eé]ra|camera|axis|dahua|hikvision|bosch|hanwha|vivotek|mobotix", _CAT_CAMERA, "Caméra IP"),
]


def _detect(designation: str) -> tuple[str, str, str]:
    """Retourne (cat_id, subcat_id, subcat_name) selon la désignation."""
    d = designation.lower()
    for pattern, cat_id, subcat_name in _DETECTION_RULES:
        if re.search(pattern, d):
            return cat_id, _SUBCAT[subcat_name], subcat_name
    # Fallback : Caméra IP
    return _CAT_CAMERA, _SUBCAT["Caméra IP"], "Caméra IP"


class VideoMapper:

    def __init__(self, custom_fields: dict):
        self.custom_fields = custom_fields  # {"Adresse MAC": id, "Adresse IP": id}

    def map_row(self, row: dict) -> dict:
        designation = row.get("designation", "").strip()
        if not designation:
            raise VideoMappingError("Désignation vide.")

        reference   = row.get("reference", "").strip()
        serial      = row.get("serial", "").strip()
        mac         = row.get("mac", "").strip()
        ip          = row.get("ip", "").strip()
        firmware    = row.get("firmware", "").strip()
        nom         = row.get("nom", "").strip()
        remarques   = row.get("remarques", "").strip()
        enr_reg     = row.get("enr_regulier", "").strip()
        enr_alarme  = row.get("enr_alarme", "").strip()
        date_inst   = row.get("date_installation", "").strip()

        cat_id, subcat_id, subcat_name = _detect(designation)

        # Nom de l'équipement : NOM si dispo, sinon DESIGNATION + REFERENCE
        if nom and nom != "?":
            name = f"{nom} - {reference}" if reference else nom
        elif reference:
            name = f"{designation} {reference}"
        else:
            name = designation

        # Description : regroupe les infos utiles
        parts = []
        if firmware:
            parts.append(f"Firmware: {firmware}")
        if date_inst and date_inst != "?":
            parts.append(f"Installation: {date_inst}")
        if enr_reg:
            parts.append(f"Enr. régulier: {enr_reg}")
        if enr_alarme:
            parts.append(f"Enr. alarme: {enr_alarme}")
        if remarques:
            parts.append(remarques)
        description = " | ".join(parts)

        payload: dict = {
            "name":          name,
            "brand":         self._detect_brand(designation, reference),
            "model":         reference,
            "serial":        serial,
            "description":   description,
            "_category":     cat_id,
            "_subcategory":  subcat_id,
        }

        # Champs personnalisés
        fields = []
        if mac and "Adresse MAC" in self.custom_fields:
            fields.append({"_field": self.custom_fields["Adresse MAC"], "value": mac})
        if ip and "Adresse IP" in self.custom_fields:
            fields.append({"_field": self.custom_fields["Adresse IP"], "value": ip})
        if fields:
            payload["fields"] = fields

        logger.debug("Mapped: %s -> %s / %s", name, cat_id, subcat_name)
        return payload

    @staticmethod
    def _detect_brand(designation: str, reference: str) -> str:
        text = f"{designation} {reference}".lower()
        brands = {
            "axis":      "AXIS",
            "dahua":     "Dahua",
            "hikvision": "Hikvision",
            "bosch":     "Bosch",
            "hanwha":    "Hanwha",
            "vivotek":   "Vivotek",
            "mobotix":   "Mobotix",
            "camtrace":  "Camtrace",
            "sony":      "Sony",
            "pelco":     "Pelco",
        }
        for key, name in brands.items():
            if key in text:
                return name
        return ""
