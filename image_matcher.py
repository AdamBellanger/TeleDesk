"""
Recherche l'image correspondant à un modèle d'équipement dans le dossier images/.
Matching souple : on cherche si le nom de fichier contient le modèle (ou vice-versa).
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _words(s: str) -> set[str]:
    """Découpe en mots normalisés de 3+ caractères."""
    return {w for w in re.split(r"[^a-z0-9]+", s.lower()) if len(w) >= 3}


def find_image(model: str, images_dir: Path) -> Path | None:
    """Retourne le chemin de l'image la plus proche pour ce modèle, ou None."""
    if not model or not images_dir.is_dir():
        return None

    model_n = _normalize(model)
    model_w = _words(model)
    if not model_n:
        return None

    candidates = [p for p in images_dir.iterdir() if p.suffix.lower() in EXTENSIONS]

    # 1. Correspondance exacte
    for p in candidates:
        if _normalize(p.stem) == model_n:
            return p

    # 2. Le nom de fichier est contenu dans le modèle
    for p in candidates:
        stem_n = _normalize(p.stem)
        if stem_n and stem_n in model_n:
            return p

    # 3. Le modèle est contenu dans le nom de fichier
    for p in candidates:
        if model_n in _normalize(p.stem):
            return p

    # 4. Tous les mots du modèle sont présents dans le nom de fichier (ordre libre)
    for p in candidates:
        stem_w = _words(p.stem)
        if model_w and model_w.issubset(stem_w):
            return p

    # 5. Tous les mots du fichier sont présents dans le modèle (ordre libre)
    for p in candidates:
        stem_w = _words(p.stem)
        if stem_w and stem_w.issubset(model_w):
            return p

    return None
