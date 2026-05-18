"""
Backend Flask — sert l'API consommée par le frontend React.
Tourne sur localhost:7421, lancé par gui_app.py via threading.
"""

import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).parent))
from bobdesk_client import BobDeskClient
from dedup import DuplicateDetector
from excel_reader import read_alcatel_excel
from fibre_mapper import FibreMapper
from fibre_reader import read_fibre_excel
from main import detect_import_type, resolve_client, run_import
from mapper import AlcatelMapper
from referential import load_referential
from reporter import ImportReporter
from unyc_mapper import UnycMapper
from unyc_reader import read_unyc_excel

# ── Chemins ───────────────────────────────────────────────────────────────
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
CONFIG_PATH = _BASE / "config" / "mapping.yaml"

_APPDATA = Path(os.environ.get("APPDATA", Path.home())) / "TeleDesk"
_APPDATA.mkdir(parents=True, exist_ok=True)
ENV_PATH = _APPDATA / ".env"

_template = _BASE / "config" / ".env"
if not ENV_PATH.exists() and _template.exists():
    import shutil
    shutil.copy(_template, ENV_PATH)

load_dotenv(dotenv_path=ENV_PATH, override=True)

import shutil as _shutil
IMAGES_DIR = _APPDATA / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
_embedded = _BASE / "images"
if _embedded.is_dir():
    for _img in _embedded.iterdir():
        _dest = IMAGES_DIR / _img.name
        if not _dest.exists():
            _shutil.copy(_img, _dest)

# ── État global de l'import ───────────────────────────────────────────────
_log_queue: queue.Queue = queue.Queue()
_import_done  = False
_import_error = ""
_import_stats: dict = {}
_import_progress: dict = {"current": 0, "total": 0}

DIST = _BASE / "frontend_dist"
app = Flask(__name__, static_folder=str(DIST), static_url_path="")
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


# ── Logging vers la queue ─────────────────────────────────────────────────
class _QueueHandler(logging.Handler):
    def emit(self, record):
        fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                                datefmt="%H:%M:%S").format(record)
        _log_queue.put(fmt)


_qh = _QueueHandler()
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(_qh)


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return send_from_directory(str(DIST), "index.html")

@app.get("/api/init")
def api_init():
    return jsonify({
        "email":      os.getenv("BOBDESK_EMAIL", ""),
        "images_dir": str(IMAGES_DIR),
    })


@app.get("/api/credentials")
def api_credentials():
    return jsonify({
        "email":    os.getenv("BOBDESK_EMAIL", ""),
        "password": os.getenv("BOBDESK_PASSWORD", ""),
    })


@app.post("/api/save_credentials")
def api_save_credentials():
    data     = request.json
    email    = data.get("email", "").strip()
    password = data.get("password", "").strip()
    iface    = os.getenv("BOBDESK_INTERFACE_ID", "")

    try:
        BobDeskClient(
            base_url=os.getenv("BOBDESK_BASE_URL", "https://prod-api.bob-desk.com/api"),
            email=email, password=password, interface_id=iface, timeout=10,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})

    env_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    updates = {"BOBDESK_EMAIL": email, "BOBDESK_PASSWORD": password}
    new_lines, written = [], set()
    for line in env_lines:
        key = line.split("=")[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in written:
            new_lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["BOBDESK_EMAIL"]    = email
    os.environ["BOBDESK_PASSWORD"] = password
    return jsonify({"ok": True})



@app.post("/api/detect_type")
def api_detect_type():
    path = request.json.get("path", "")
    file_type = detect_import_type(path)
    row_count = 0
    try:
        import pandas as pd
        df = pd.read_excel(path, dtype=str, engine="calamine")
        row_count = max(0, len(df) - 1)
    except Exception:
        pass
    return jsonify({"type": file_type, "rows": row_count})


@app.post("/api/start")
def api_start():
    global _import_done, _import_error, _import_stats
    _import_done  = False
    _import_error = ""
    _import_stats = {}
    while not _log_queue.empty():
        try: _log_queue.get_nowait()
        except: pass

    data      = request.json
    file_path = data["file"]
    client    = data["client"]
    dry_run   = data.get("dry_run", False)
    operator  = data.get("operator", "Orange")
    file_type = data.get("file_type", "alcatel")
    replace   = data.get("replace", False)

    threading.Thread(
        target=_worker,
        args=(file_path, client, dry_run, operator, file_type, replace),
        daemon=True,
    ).start()
    return jsonify({"ok": True})


@app.post("/api/set_on_top")
def api_set_on_top():
    # Implémenté côté gui_app via js_api si besoin
    return jsonify({"ok": True})


@app.get("/api/logs")
def api_logs():
    global _import_done, _import_error
    lines = []
    while True:
        try: lines.append(_log_queue.get_nowait())
        except queue.Empty: break
    return jsonify({
        "lines":    lines,
        "done":     _import_done,
        "error":    _import_error or None,
        "progress": _import_progress,
    })


@app.get("/api/stats")
def api_stats():
    return jsonify(_import_stats or {
        "imported": "—", "skipped_duplicate": "—",
        "skipped_unmappable": "—", "error": "—",
    })


@app.get("/api/open_images")
def api_open_images():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(IMAGES_DIR)])
    return jsonify({"ok": True})


@app.post("/api/open_report")
def api_open_report():
    client_name = request.json.get("client", "").strip()
    import re
    safe = re.sub(r'[\\/:*?"<>|]', "_", client_name).strip("_ ")
    report_dir = Path(os.getenv("REPORT_DIR", str(_APPDATA / "reports"))) / safe
    if not report_dir.exists():
        report_dir = Path(os.getenv("REPORT_DIR", str(_APPDATA / "reports")))
    subprocess.Popen(["explorer", str(report_dir)])
    return jsonify({"ok": True})


@app.get("/api/history")
def api_history():
    rdir = Path(os.getenv("REPORT_DIR", str(_APPDATA / "reports")))
    entries = []
    if rdir.exists():
        for client_dir in sorted(rdir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not client_dir.is_dir():
                continue
            jsons = sorted(client_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if jsons:
                import json as _json
                try:
                    data = _json.loads(jsons[0].read_text(encoding="utf-8"))
                    summary = data.get("summary", {})
                    entries.append({
                        "client": client_dir.name.replace("_", " "),
                        "imported": summary.get("imported", 0),
                        "error": summary.get("error", 0),
                        "date": jsons[0].stem.split("_")[1] + "_" + jsons[0].stem.split("_")[2] if len(jsons[0].stem.split("_")) >= 3 else "",
                    })
                except Exception:
                    pass
            if len(entries) >= 5:
                break
    return jsonify(entries)


# ── Worker import ─────────────────────────────────────────────────────────

# Sous-catégories à supprimer selon le type de fichier
_SUBCATS_TO_DELETE = {
    "alcatel": {
        "69c2a7cd336965001288858c",  # Téléphone IP
        "69b16f9f645226001a7dccdf",  # Téléphone Analogique
        "6980b6b0129f190019d26836",  # Téléphone Numérique
        "6980b6ba8b3f890013b5177a",  # DECT
        "69afd6d86d57751a808cfc9b",  # Module de touches
        "69b16a73d68e320019289bd1",  # SoftPhone
    },
    "unyc": {
        "69c2a7cd336965001288858c",  # Téléphone IP
        "69b16a73d68e320019289bd1",  # SoftPhone
        "6a0321819bf84b0308fb58e4",  # Téléphone Mobile
    },
    "fibre": {
        "69fc57d6faa5740012e78a89",  # Fibre FTTH
        "69fc57deabf911001a3e2d3c",  # Fibre FTTO
        "69fc57e8abf911001a3e2dab",  # Fibre FTTO + GTR
    },
}


def _worker(excel_path, client_name, dry_run, operator, file_type, replace=False):
    global _import_done, _import_error, _import_stats, _import_progress
    logger = logging.getLogger("import")
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        bob = BobDeskClient(
            base_url=os.getenv("BOBDESK_BASE_URL", "https://prod-api.bob-desk.com/api"),
            email=os.getenv("BOBDESK_EMAIL", ""),
            password=os.getenv("BOBDESK_PASSWORD", ""),
            interface_id=os.getenv("BOBDESK_INTERFACE_ID", ""),
            timeout=int(os.getenv("HTTP_TIMEOUT", "30")),
            dry_run=dry_run,
        )

        if dry_run:
            logger.info("━" * 50)
            logger.info("MODE DRY-RUN — aucune écriture dans Bob! Desk")
            logger.info("━" * 50)

        rec    = resolve_client(bob, client_name, None)
        cid    = rec["_id"]
        clabel = rec.get("name", cid)
        logger.info("Client : %s", clabel)

        ref = load_referential(bob, cfg)

        if file_type == "unyc":
            logger.info("Type : Unyc / Centrex")
            rows    = read_unyc_excel(excel_path)
            mapper  = UnycMapper(cfg, ref)
            dd_keys = ["mac", "name"]
        elif file_type == "fibre":
            logger.info("Type : Liens Fibre")
            rows    = read_fibre_excel(excel_path)
            mapper  = FibreMapper(operator)
            dd_keys = ["serial"]
        else:
            logger.info("Type : Alcatel-Lucent")
            rows    = read_alcatel_excel(excel_path)
            mapper  = AlcatelMapper(cfg, ref)
            dd_keys = cfg.get("dedup_keys", ["serial"])

        # Suppression préalable si mode Remplacer activé
        _eq_index_path = _APPDATA / f"equipments_{cid}.json"
        if replace:
            logger.info("━" * 50)
            logger.info("MODE REMPLACER — suppression des équipements existants (%s)", file_type)
            if _eq_index_path.exists():
                import json as _json
                eq_ids = _json.loads(_eq_index_path.read_text(encoding="utf-8"))
                total_del = len(eq_ids)
                logger.info("%d équipement(s) à supprimer (index local).", total_del)
                deleted = 0
                for eid in eq_ids:
                    if bob.delete_equipment(eid):
                        deleted += 1
                    logger.info("⏳ Suppression en cours… (%d/%d)", deleted, total_del)
                logger.info("✓ %d équipement(s) supprimé(s).", deleted)
                _eq_index_path.unlink(missing_ok=True)
            else:
                logger.warning("Aucun index local trouvé — impossible de supprimer les équipements précédents.")
                logger.warning("Conseil : effectuez d'abord un import normal, puis utilisez Remplacer.")
            logger.info("━" * 50)

        loc = bob.get_client_location(cid)
        ex  = []  # /equipments/list est indisponible sur cette instance
        dd  = DuplicateDetector(ex, dd_keys)

        rdir     = os.getenv("REPORT_DIR", str(_APPDATA / "reports"))
        reporter = ImportReporter(rdir, clabel.replace(" ", "_"), dry_run)

        _import_progress["total"] = len(rows)
        _import_progress["current"] = 0
        run_import(rows, mapper, dd, bob, cid, loc, reporter, IMAGES_DIR if IMAGES_DIR.is_dir() else None, _import_progress)

        reporter.print_summary()
        reporter.save_csv()
        reporter.save_json()

        # Sauvegarde l'index des IDs créés pour le mode Remplacer
        if not dry_run:
            import json as _json
            created_ids = [r.equipment_id for r in reporter.results if r.status == "imported" and r.equipment_id]
            _eq_index_path.write_text(_json.dumps(created_ids), encoding="utf-8")
            logger.info("Index équipements sauvegardé : %d ID(s) → %s", len(created_ids), _eq_index_path)

        counts = {}
        for r in reporter.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        _import_stats = {
            "imported":           counts.get("imported", 0),
            "skipped_duplicate":  counts.get("skipped_duplicate", 0),
            "skipped_unmappable": counts.get("skipped_unmappable", 0),
            "error":              counts.get("error", 0),
        }
        _import_done = True

    except Exception as exc:
        logger.error("Erreur : %s", exc, exc_info=True)
        _import_error = str(exc)
        _import_done  = True


def run(port=7421):
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
