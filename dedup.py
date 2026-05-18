"""
Détection de doublons avant insertion dans Bob! Desk.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DuplicateDetector:
    """
    Construit un index des équipements existants pour un client
    et détecte si un nouvel équipement est déjà présent.
    """

    def __init__(self, existing_equipments: list[dict], dedup_keys: list[str]):
        self.dedup_keys = dedup_keys
        # Index : valeur_clé -> équipement existant
        self._index: dict[str, dict] = {}
        for eq in existing_equipments:
            for key in dedup_keys:
                val = self._extract(eq, key)
                if val:
                    self._index[self._normalize(val)] = eq

        logger.info(
            "Index anti-doublon: %d équipements existants, %d entrées indexées.",
            len(existing_equipments),
            len(self._index),
        )

    def is_duplicate(self, payload: dict) -> tuple[bool, Optional[str]]:
        """
        Retourne (True, raison) si le payload correspond à un équipement existant.
        Retourne (False, None) sinon.
        """
        for key in self.dedup_keys:
            val = self._extract(payload, key)
            if val:
                norm = self._normalize(val)
                if norm in self._index:
                    existing = self._index[norm]
                    return True, (
                        f"Doublon détecté via '{key}'='{val}' "
                        f"(équipement existant id={existing.get('id')})"
                    )
        return False, None

    # ------------------------------------------------------------------

    @staticmethod
    def _extract(obj: dict, key: str) -> Optional[str]:
        """Cherche la clé dans le dict, avec quelques alias courants."""
        aliases = {
            "serial":        ["serial", "serial_number", "numero_materiel"],
            "serial_number": ["serial_number", "serial", "numero_materiel"],
            "mac":           ["mac", "mac_address", "mac_id", "id"],
            "mac_address":   ["mac_address", "mac", "mac_id", "id"],
            "edn":           ["edn"],
            "name":          ["name"],
        }
        for candidate in aliases.get(key, [key]):
            val = obj.get(candidate)
            if val and str(val).strip():
                return str(val).strip()
        return None

    @staticmethod
    def _normalize(val: str) -> str:
        return val.strip().lower().replace(" ", "").replace(":", "").replace("-", "")
