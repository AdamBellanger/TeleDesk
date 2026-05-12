"""
Transformation d'une ligne Unyc en payload Bob! Desk.
Catégorie : Téléphonie / Téléphone IP pour tous les postes Centrex.
"""

import logging
from referential import Referential

logger = logging.getLogger(__name__)


class UnycMappingError(Exception):
    pass


class UnycMapper:

    def __init__(self, mapping_config: dict, referential: Referential):
        self.cfg = mapping_config
        self.ref = referential

    def map_row(self, row: dict) -> dict:
        num_court = row.get("num_court", "").strip()
        brand     = row.get("brand", "").strip()
        model     = row.get("model", "").strip()
        mac       = row.get("mac", "").strip()
        numeros   = row.get("numeros", "").strip()
        num_pres  = row.get("num_presente", "").strip()
        site      = row.get("site", "").strip()
        services  = row.get("services", "").strip()

        # Nom de l'équipement
        is_mobile   = row.get("is_mobile", False)
        full_model  = f"{brand} {model}".strip()
        if is_mobile:
            operateur = row.get("mobile_operateur", brand)
            numeros_  = row.get("numeros", "").strip()
            num_ref   = numeros_.split("\n")[0].strip() if numeros_ else num_court
            name = f"{num_ref} - Forfait {operateur}"
        elif num_court:
            name = f"{num_court} - {full_model}"
        else:
            name = full_model

        # Catégorie et sous-catégorie selon le type
        is_speek    = row.get("is_speek", False)
        is_mobile   = row.get("is_mobile", False)
        cat_name    = self.cfg["defaults"]["category"]       # Téléphonie
        if is_speek:
            subcat_name = "SoftPhone"
        elif is_mobile:
            subcat_name = "Téléphone Mobile"
        else:
            subcat_name = self.cfg["unyc_defaults"]["subcategory"]
        job_name    = self.cfg["defaults"].get("job", "Telephonie")

        category = self.ref.find_category(cat_name)
        if category is None:
            raise UnycMappingError(f"Catégorie '{cat_name}' introuvable dans Bob! Desk.")

        subcategory = self.ref.find_subcategory(subcat_name)
        if subcategory is None:
            raise UnycMappingError(f"Sous-catégorie '{subcat_name}' introuvable dans Bob! Desk.")

        job_id = self.cfg.get("bobdesk_ids", {}).get("jobs", {}).get(job_name)

        # Description
        parts = []
        if numeros:
            parts.append(f"Numéro(s): {numeros}")
        if num_pres:
            parts.append(f"Num. présenté: {num_pres}")
        if site:
            parts.append(f"Site: {site}")
        if services:
            # On tronque les services pour rester lisible
            svc_short = " | ".join(
                s.strip() for s in services.split("|")
                if s.strip() and "Fournisseur" not in s
            )
            if svc_short:
                parts.append(f"Services: {svc_short}")
        description = " | ".join(parts)

        payload: dict = {
            "name":                  name,
            "brand":                 brand,
            "model":                 full_model,
            "serial":                "",
            "description":           description,
            "_category":    category["_id"],
            "_subcategory": subcategory["_id"],
        }

        if job_id:
            payload["_jobs"] = [job_id]

        # Champs personnalisés
        custom_fields = self.cfg.get("bobdesk_ids", {}).get("custom_fields", {})
        fields_values = []
        if mac and "Adresse MAC" in custom_fields:
            fields_values.append({"_field": custom_fields["Adresse MAC"], "value": mac})
        if numeros and "Numéro de ligne" in custom_fields:
            fields_values.append({"_field": custom_fields["Numéro de ligne"], "value": numeros})
        if fields_values:
            payload["fields"] = fields_values

        return payload
