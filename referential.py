"""
Chargement et résolution des référentiels Bob! Desk depuis /scopes/list.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from bobdesk_client import BobDeskClient, BobDeskAPIError

logger = logging.getLogger(__name__)


@dataclass
class Referential:
    categories: dict[str, dict] = field(default_factory=dict)    # nom -> scope
    subcategories: dict[str, dict] = field(default_factory=dict) # nom -> scope
    # index parent_id -> liste de sous-catégories
    subcats_by_parent: dict[str, list] = field(default_factory=dict)

    def find_category(self, name: str) -> Optional[dict]:
        return self._iget(self.categories, name)

    def find_subcategory(self, name: str) -> Optional[dict]:
        return self._iget(self.subcategories, name)

    @staticmethod
    def _iget(d: dict, name: str) -> Optional[dict]:
        target = name.strip().lower()
        for k, v in d.items():
            if k.strip().lower() == target:
                return v
        return None


def load_referential(client: BobDeskClient, mapping_cfg: dict) -> Referential:
    ref = Referential()
    logger.info("Chargement des référentiels Bob! Desk via /scopes/list...")

    try:
        scopes = client.get_scopes()
    except BobDeskAPIError as exc:
        raise RuntimeError(f"Impossible de charger les référentiels: {exc}") from exc

    for scope in scopes:
        t = scope.get("type", "")
        name = scope.get("name", "")
        if t == "equipmentCategory":
            ref.categories[name] = scope
        elif t == "equipmentSubCategory":
            ref.subcategories[name] = scope
            parent = scope.get("_parent")
            if parent:
                ref.subcats_by_parent.setdefault(parent, []).append(scope)

    logger.info(
        "%d catégories, %d sous-catégories chargées.",
        len(ref.categories), len(ref.subcategories),
    )

    # Validation croisée avec le mapping.yaml
    cfg_cats = mapping_cfg.get("bobdesk_ids", {}).get("categories", {})
    cfg_subcats = mapping_cfg.get("bobdesk_ids", {}).get("subcategories", {})
    for name in cfg_cats:
        if ref.find_category(name) is None:
            logger.warning("Catégorie '%s' dans mapping.yaml introuvable dans Bob! Desk", name)
    for name in cfg_subcats:
        if ref.find_subcategory(name) is None:
            logger.warning("Sous-catégorie '%s' dans mapping.yaml introuvable dans Bob! Desk", name)

    return ref
