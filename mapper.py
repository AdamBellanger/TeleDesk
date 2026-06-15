"""
Transformation d'une ligne Alcatel-Lucent en payload Bob! Desk.
Utilise les IDs réels récupérés depuis /scopes/list.
Champ serial = numéro de série (vérifié sur l'API Bob! Desk).
"""

import logging
import re
from typing import Optional
from referential import Referential

logger = logging.getLogger(__name__)

# Normalisation des colonnes Excel Alcatel
ALCATEL_COLUMNS = {
    "edn":                 "edn",
    "catégorie":           "categorie",
    "categorie":           "categorie",
    "type":                "type",
    "interface":           "interface",
    "état physique":       "etat_physique",
    "etat physique":       "etat_physique",
    "état logique":        "etat_logique",
    "etat logique":        "etat_logique",
    "utilisateur distant": "utilisateur_distant",
    "hot desking":         "hot_desking",
    "numéro matériel":     "numero_materiel",
    "numero materiel":     "numero_materiel",
    "version logicielle":  "version_logicielle",
    "id":                  "mac_id",
    "adresse ip":          "adresse_ip",
}


class MappingError(Exception):
    """Ligne non mappable — journalisée et ignorée, rien n'est créé."""


class AlcatelMapper:
    def __init__(self, mapping_config: dict, referential: Referential):
        self.cfg = mapping_config
        self.ref = referential

    def map_row(self, raw_row: dict) -> dict:
        """
        Retourne un payload prêt pour POST /equipments.
        Lève MappingError si la ligne est non-mappable.
        Ne crée JAMAIS de catégorie, sous-catégorie ou métier.
        """
        alcatel = self._normalize_row(raw_row)

        category_name = self._resolve_category(alcatel)
        subcat_name   = self._resolve_subcategory(alcatel)
        model         = self._resolve_model(alcatel)
        name          = self._build_name(alcatel, model)
        description   = self._build_description(alcatel)

        # Résolution des IDs Bob! Desk — jamais de création
        category = self.ref.find_category(category_name)
        if category is None:
            raise MappingError(
                f"Catégorie '{category_name}' introuvable dans Bob! Desk — "
                "vérifier mapping.yaml ou ajouter la catégorie manuellement dans Bob! Desk."
            )

        subcategory = self.ref.find_subcategory(subcat_name) if subcat_name else None
        if subcat_name and subcategory is None:
            raise MappingError(
                f"Sous-catégorie '{subcat_name}' introuvable dans Bob! Desk — "
                "vérifier mapping.yaml ou ajouter la sous-catégorie manuellement."
            )

        # Résolution du métier (job) pour la visibilité dans Bob! Desk
        job_name = self.cfg["defaults"].get("job", "Telephonie")
        job_id = self.cfg.get("bobdesk_ids", {}).get("jobs", {}).get(job_name)

        # Tous postes : ID = numéro de série, Numéro matériel = adresse MAC, pas d'IP
        payload: dict = {
            "name":        name,
            "brand":       self.cfg["defaults"]["brand"],
            "model":       model,
            "serial":      alcatel.get("mac_id") or "",           # colonne "ID" = numéro de série
            "description": description,
            "_category":   category["_id"],
        }

        if job_id:
            payload["_jobs"] = [job_id]

        if subcategory:
            payload["_subcategory"] = subcategory["_id"]

        # Champs personnalisés — MAC uniquement, pas d'IP
        custom_fields = self.cfg.get("bobdesk_ids", {}).get("custom_fields", {})
        fields_values = []
        ip  = ""
        mac = alcatel.get("numero_materiel", "").strip()          # Numéro matériel = adresse MAC

        if ip and "Adresse IP" in custom_fields:
            fields_values.append({"_field": custom_fields["Adresse IP"], "value": ip})
        if mac and "Adresse MAC" in custom_fields:
            fields_values.append({"_field": custom_fields["Adresse MAC"], "value": mac})

        if fields_values:
            payload["fields"] = fields_values

        return payload

    # ------------------------------------------------------------------

    def _resolve_category(self, alcatel: dict) -> str:
        alcatel_cat = alcatel.get("categorie", "")
        override = self.cfg.get("alcatel_category_override", {})
        return override.get(alcatel_cat, self.cfg["defaults"]["category"])

    def _resolve_subcategory(self, alcatel: dict) -> Optional[str]:
        interface   = (alcatel.get("interface") or "").strip()
        type_val    = (alcatel.get("type") or "").strip()
        alcatel_cat = (alcatel.get("categorie") or "").strip()

        # 1. Mapping par Interface (prioritaire) — insensible à la casse, préfixe inclus
        imap = self.cfg.get("interface_to_subcategory", {})
        imap_upper = {k.upper(): v for k, v in imap.items()}
        logger.info("Mapping sous-cat — Interface: %r | Type: %r | Catégorie: %r", interface, type_val, alcatel_cat)
        if interface:
            # Correspondance exacte
            if interface.upper() in imap_upper:
                return imap_upper[interface.upper()]
            # Correspondance par préfixe (ex: "UA3" → "UA")
            for key_up, val in imap_upper.items():
                if interface.upper().startswith(key_up):
                    return val

        # 2. Mapping par Type exact
        tmap = self.cfg.get("type_to_subcategory", {})
        if type_val in tmap:
            result = tmap[type_val]
            if result is None:
                raise MappingError(
                    f"Type '{type_val}' (catégorie: '{alcatel_cat}') "
                    "explicitement non-mappable (null dans mapping.yaml)."
                )
            return result

        # 3. Tentative par préfixe numérique (ex: "4038 EE" -> "4038")
        match = re.match(r"^(\d{4})", type_val)
        if match and match.group(1) in tmap:
            result = tmap[match.group(1)]
            if result is None:
                raise MappingError(f"Modèle '{type_val}' non-mappable.")
            return result

        raise MappingError(
            f"Impossible de déterminer la sous-catégorie : "
            f"Interface='{interface}', Type='{type_val}', Catégorie='{alcatel_cat}'"
        )

    def _resolve_model(self, alcatel: dict) -> str:
        type_val = (alcatel.get("type") or "").strip()
        # Conversion des noms Alcatel -> noms lisibles Bob! Desk
        model_map = self.cfg.get("model_name_override", {})
        for pattern, label in model_map.items():
            if re.search(pattern, type_val, re.IGNORECASE):
                return label
        match = re.match(r"^(\d{4})", type_val)
        if match:
            return f"Alcatel {type_val}"  # Garde le suffixe complet (ex: 8039s, 4038 EE)
        return type_val or "Inconnu"

    def _build_name(self, alcatel: dict, model: str) -> str:
        edn = alcatel.get("edn", "").strip()
        if not edn:
            return model
        template = self.cfg.get("equipment_name_template", "{edn} - {model}")
        return template.format(
            edn=edn,
            model=model,
            interface=alcatel.get("interface", ""),
            ip=alcatel.get("adresse_ip", ""),
        ).strip(" -")

    def _build_description(self, alcatel: dict) -> str:
        parts = []
        for label, key in [
            ("Type Alcatel", "type"),
            ("Interface",    "interface"),
            ("Version SW",   "version_logicielle"),
            ("État logique", "etat_logique"),
            ("État physique","etat_physique"),
            ("Utilisateur",  "utilisateur_distant"),
            ("Hot Desking",  "hot_desking"),
        ]:
            val = alcatel.get(key, "").strip()
            if val:
                parts.append(f"{label}: {val}")
        return " | ".join(parts)

    @staticmethod
    def _normalize_row(row: dict) -> dict:
        normalized = {}
        for raw_key, value in row.items():
            clean = raw_key.strip().lower()
            internal = ALCATEL_COLUMNS.get(clean, clean)
            normalized[internal] = str(value).strip() if value else ""
        return normalized
