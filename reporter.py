"""
Rapport d'import : collecte les résultats ligne par ligne et génère un fichier CSV/JSON.
"""

import csv
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Status = Literal["imported", "skipped_duplicate", "skipped_unmappable", "error"]


@dataclass
class RowResult:
    row_index: int
    edn: str
    type: str
    serial: str
    status: Status
    reason: str = ""
    equipment_id: str = ""      # ID Bob! Desk si créé


def _safe_dirname(name: str) -> str:
    """Supprime les caractères interdits dans un nom de dossier Windows."""
    import re
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip("_ ")


class ImportReporter:
    def __init__(self, report_dir: str | Path, client_name: str, dry_run: bool):
        self.results: list[RowResult] = []
        client_folder = Path(report_dir) / _safe_dirname(client_name)
        client_folder.mkdir(parents=True, exist_ok=True)
        self.report_dir = client_folder
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = "DRYRUN" if dry_run else "LIVE"
        self.base_name = f"import_{ts}_{mode}"

    def add(self, result: RowResult):
        self.results.append(result)

    # ------------------------------------------------------------------

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def print_summary(self):
        s = self.summary()
        total = len(self.results)
        logger.info("=" * 60)
        logger.info("RÉSUMÉ D'IMPORT — %d lignes traitées", total)
        logger.info("  ✔ Importées        : %d", s.get("imported", 0))
        logger.info("  ⊘ Doublons ignorés : %d", s.get("skipped_duplicate", 0))
        logger.info("  ✗ Non-mappables    : %d", s.get("skipped_unmappable", 0))
        logger.info("  ! Erreurs          : %d", s.get("error", 0))
        logger.info("=" * 60)

    def save_csv(self):
        out = self.report_dir / f"{self.base_name}.csv"
        if not self.results:
            return
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(self.results[0]).keys()))
            writer.writeheader()
            writer.writerows(asdict(r) for r in self.results)
        logger.info("Rapport CSV enregistré: %s", out)

    def save_json(self):
        out = self.report_dir / f"{self.base_name}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(
                {"summary": self.summary(), "rows": [asdict(r) for r in self.results]},
                f, ensure_ascii=False, indent=2,
            )
        logger.info("Rapport JSON enregistré: %s", out)
