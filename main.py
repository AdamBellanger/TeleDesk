"""
Point d'entrée — import équipements Alcatel-Lucent -> Bob! Desk.

Usage:
    python main.py --file export.xlsx --client "Nom du client" --dry-run
    python main.py --file export.xlsx --client "Nom du client"
    python main.py --file export.xlsx --client-id 6835d2a5af431c7178e914a7
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from bobdesk_client import BobDeskClient, BobDeskAPIError
from dedup import DuplicateDetector
from excel_reader import read_alcatel_excel
from mapper import AlcatelMapper, MappingError
from referential import load_referential
from reporter import ImportReporter, RowResult
from unyc_reader import read_unyc_excel
from unyc_mapper import UnycMapper, UnycMappingError
from fibre_reader import read_fibre_excel
from fibre_mapper import FibreMapper, FibreMappingError
from image_matcher import find_image


def setup_logging(log_dir: str, level: str) -> None:
    from datetime import datetime
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def resolve_client(bob: BobDeskClient, name: str | None, client_id: str | None) -> dict:
    if client_id:
        clients = bob.get_clients()
        found = [c for c in clients if c.get("_id") == client_id]
        if not found:
            raise SystemExit(f"Aucun client avec l'ID '{client_id}'.")
        return found[0]

    clients = bob.get_clients(search=name)
    exact = [c for c in clients if c.get("name", "").strip().lower() == name.strip().lower()]
    if exact:
        return exact[0]
    if len(clients) == 1:
        return clients[0]
    if len(clients) == 0:
        raise SystemExit(f"Aucun client trouvé pour '{name}'.")

    logger = logging.getLogger("resolve_client")
    logger.warning("%d clients correspondent à '%s' :", len(clients), name)
    for c in clients[:10]:
        logger.warning("  _id=%s  nom=%s", c.get("_id"), c.get("name"))
    raise SystemExit("Ambiguïté client — utiliser --client-id.")


def detect_import_type(filepath: str) -> str:
    """Détecte automatiquement le type d'import (alcatel, unyc, fibre ou video) selon les colonnes."""
    import pandas as pd
    from pathlib import Path
    path = Path(filepath)
    for engine in ("calamine", "openpyxl", "xlrd"):
        try:
            df = pd.read_excel(path, dtype=str, engine=engine, header=None, nrows=20)
            all_vals = set()
            for _, row in df.iterrows():
                vals = [str(v).strip().lower() for v in row.values if str(v).strip()]
                all_vals.update(vals)
                if "edn" in vals:
                    return "alcatel"
                if "num. court" in vals or "numéro(s)" in vals:
                    return "unyc"
                if "référence" in vals or "reference" in vals:
                    if "offre" in vals or "site installation" in vals:
                        return "fibre"
            # Vidéosurveillance : "liste materiel installe" + "designation"
            if any("liste materiel" in v or "liste matériel" in v for v in all_vals):
                if any("designation" in v or "désignation" in v for v in all_vals):
                    return "video"
            break
        except Exception:
            continue
    return "alcatel"  # fallback


def run_import(
    rows: list[dict],
    mapper,
    dedup: DuplicateDetector,
    bob: BobDeskClient,
    client_id: str,
    location_id: str | None,
    reporter: ImportReporter,
    images_dir: Path | None = None,
    progress: dict | None = None,
) -> None:
    logger = logging.getLogger("import")
    is_unyc  = isinstance(mapper, UnycMapper)
    is_fibre = isinstance(mapper, FibreMapper)

    for idx, raw_row in enumerate(rows, start=2):
        if progress is not None:
            progress["current"] = idx - 1
        if is_unyc:
            edn    = raw_row.get("num_court", "")
            type_  = raw_row.get("model", "")
            serial = raw_row.get("mac", "")
        elif is_fibre:
            edn    = raw_row.get("reference", "")
            type_  = raw_row.get("offre", "")
            serial = raw_row.get("reference", "")
        else:
            edn    = str(raw_row.get("EDN", raw_row.get("edn", ""))).strip()
            type_  = str(raw_row.get("Type", raw_row.get("type", ""))).strip()
            serial = str(raw_row.get("Numéro matériel", raw_row.get("numero_materiel", ""))).strip()

        try:
            payload = mapper.map_row(raw_row)
        except (MappingError, UnycMappingError, FibreMappingError) as exc:
            reason = str(exc)
            logger.warning("Ligne %d (%s): %s", idx, edn, reason)
            reporter.add(RowResult(idx, edn, type_, serial, "skipped_unmappable", reason))
            continue

        payload["_client"] = client_id
        if location_id:
            payload["_location"] = location_id

        is_dup, dup_reason = dedup.is_duplicate(payload)
        if is_dup:
            logger.info("Ligne %d (%s): %s", idx, edn, dup_reason)
            reporter.add(RowResult(idx, edn, type_, serial, "skipped_duplicate", dup_reason))
            continue

        try:
            result = bob.create_equipment(payload)
            eq_id = str(result.get("element", {}).get("_id", ""))
            logger.info("Ligne %d (%s): créé id=%s", idx, edn, eq_id)
            reporter.add(RowResult(idx, edn, type_, serial, "imported", equipment_id=eq_id))

            # Upload image si dossier fourni et équipement réellement créé
            if images_dir and eq_id and eq_id != "DRY_RUN":
                model = payload.get("model", type_)
                img = find_image(model, images_dir)
                if img:
                    ok = bob.set_equipment_image(eq_id, img)
                    if ok:
                        logger.info("Ligne %d (%s): image uploadée (%s)", idx, edn, img.name)
                    else:
                        logger.debug("Ligne %d (%s): upload image échoué", idx, edn)
        except BobDeskAPIError as exc:
            reason = f"Erreur API: {exc} | {exc.response_body}"
            logger.error("Ligne %d (%s): %s", idx, edn, reason)
            reporter.add(RowResult(idx, edn, type_, serial, "error", reason))


def main():
    load_dotenv(dotenv_path=Path(__file__).parent / "config" / ".env")

    log_dir   = os.getenv("LOG_DIR", "logs")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(log_dir, log_level)
    logger = logging.getLogger("main")

    parser = argparse.ArgumentParser(description="Import Alcatel-Lucent -> Bob! Desk")
    parser.add_argument("--file",      required=True)
    parser.add_argument("--client",    help="Nom du client Bob! Desk")
    parser.add_argument("--client-id", help="ID MongoDB du client Bob! Desk")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--config",    default="config/mapping.yaml")
    args = parser.parse_args()

    if not args.client and not args.client_id:
        parser.error("Préciser --client 'Nom' ou --client-id ID")

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("MODE DRY-RUN — aucune écriture dans Bob! Desk")
        logger.info("=" * 60)

    # Config
    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config introuvable: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        mapping_cfg = yaml.safe_load(f)

    # Connexion
    bob = BobDeskClient(
        base_url=os.getenv("BOBDESK_BASE_URL", "https://prod-api.bob-desk.com/api"),
        email=os.getenv("BOBDESK_EMAIL", ""),
        password=os.getenv("BOBDESK_PASSWORD", ""),
        interface_id=os.getenv("BOBDESK_INTERFACE_ID", ""),
        timeout=int(os.getenv("HTTP_TIMEOUT", "30")),
        dry_run=args.dry_run,
    )

    # Client
    client_record = resolve_client(bob, args.client, args.client_id)
    client_id   = client_record["_id"]
    client_name = client_record.get("name", client_id)
    logger.info("Client : '%s' (_id=%s)", client_name, client_id)

    # Référentiels
    ref = load_referential(bob, mapping_cfg)

    # Excel
    rows = read_alcatel_excel(args.file)

    # Lieu du client (obligatoire pour que les équipements apparaissent dans Bob! Desk)
    location_id = bob.get_client_location(client_id)
    if location_id:
        logger.info("Lieu associé : %s", location_id)
    else:
        logger.warning("Aucun lieu trouvé — les équipements seront créés sans lieu et n'apparaîtront pas dans la vue principale.")

    # Anti-doublon
    logger.info("Chargement des équipements existants de '%s'...", client_name)
    existing = bob.get_client_equipments(client_id)
    dedup_keys = mapping_cfg.get("dedup_keys", ["serial", "mac_address"])
    dedup = DuplicateDetector(existing, dedup_keys)

    # Import
    report_dir = os.getenv("REPORT_DIR", "reports")
    reporter = ImportReporter(report_dir, client_name.replace(" ", "_"), args.dry_run)
    logger.info("Import de %d lignes...", len(rows))
    run_import(rows, AlcatelMapper(mapping_cfg, ref), dedup, bob, client_id, location_id, reporter)

    reporter.print_summary()
    reporter.save_csv()
    reporter.save_json()
    logger.info("Terminé.")


if __name__ == "__main__":
    main()
