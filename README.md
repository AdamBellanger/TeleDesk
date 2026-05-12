# TéléDesk Import

Outil d'import automatique d'équipements téléphonie et réseau vers **Bob! Desk** (GMAO).  
Interface graphique moderne — drag & drop, thème sombre/clair, rapports CSV/JSON.

---

## Téléchargement

👉 **[Télécharger TeleDesk.exe](https://github.com/AdamBellanger/TeleDesk/releases/latest)**

Windows 10/11 — aucune installation requise. Double-cliquez et c'est parti.

---

## Fonctionnalités

- **Import Alcatel-Lucent** — export EDN Excel → équipements Bob! Desk
- **Import Unyc / Centrex** — export utilisateurs → postes IP, SoftPhone Speek, téléphones mobiles
- **Import Liens Fibre** — FTTH / FTTO / FTTO+GTR avec sélection opérateur
- **Détection automatique** du type de fichier à l'ouverture
- **Anti-doublon** — vérifie les équipements existants avant import
- **Mode test (dry-run)** — simule l'import sans rien écrire dans Bob! Desk
- **Photos équipements** — upload automatique de l'image sur Bob! Desk
- **Rapports** — un dossier par client avec fichiers CSV + JSON horodatés
- **Thème sombre / clair olive** — persisté entre les sessions

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Interface | React + Tailwind CSS (Vite) |
| Fenêtre native | pywebview |
| Backend | Flask (localhost) |
| Packaging | PyInstaller (exe autonome) |

---

## Structure du projet

```
TeleDesk/
├── gui_app.py            # Point d'entrée — lance Flask + ouvre pywebview
├── server.py             # API Flask + sert le frontend React
├── main.py               # Logique d'import (run_import, detect_import_type)
├── bobdesk_client.py     # Client HTTP Bob! Desk (auth, retry, pagination)
├── mapper.py             # Mapping Alcatel -> Bob! Desk
├── unyc_mapper.py        # Mapping Unyc/Centrex -> Bob! Desk
├── unyc_reader.py        # Lecture Excel Unyc (postes, Speek, mobile)
├── fibre_reader.py       # Lecture Excel liens fibre
├── fibre_mapper.py       # Mapping fibre -> Bob! Desk
├── image_matcher.py      # Matching image par mots-clés
├── referential.py        # Cache référentiels Bob! Desk
├── dedup.py              # Détection doublons
├── excel_reader.py       # Lecture Excel Alcatel
├── reporter.py           # Rapports CSV + JSON par client
├── build_exe.spec        # Spec PyInstaller
├── requirements.txt
├── images/               # Photos équipements embarquées dans l'exe
├── config/
│   ├── mapping.yaml      # Table de correspondance (catégories, IDs, dedup_keys)
│   └── .env.example      # Template de configuration
├── frontend/             # Source React (App.jsx, index.css, vite.config.js)
├── reports/              # Rapports d'import — un sous-dossier par client
└── logs/
```

---

## Lancer depuis les sources

**Prérequis :** Python 3.11+, Node.js 18+

```bash
# 1. Dépendances Python
pip install -r requirements.txt

# 2. Configuration
cp config/.env.example config/.env
# Renseigner BOBDESK_EMAIL, BOBDESK_PASSWORD, BOBDESK_INTERFACE_ID dans config/.env

# 3. Build du frontend
cd frontend
npm install
npm run build
cd ..

# 4. Lancer l'application
python gui_app.py
```

---

## Compiler l'exe

```bash
cd frontend && npm run build && cd ..
python -m PyInstaller build_exe.spec --noconfirm
# → dist/TeleDesk.exe
```

---

## Configuration

Le fichier `config/mapping.yaml` contient les correspondances entre les types d'équipements et les IDs Bob! Desk (catégories, sous-catégories, jobs).  
À adapter selon votre instance Bob! Desk.

Les identifiants (email/mot de passe) sont saisis au premier lancement et stockés dans `%APPDATA%\TeleDesk\.env` — jamais dans l'exe ni dans le repo.

---

## Rapports d'import

Après chaque import, deux fichiers sont créés dans `reports/<NomClient>/` :

- `import_<timestamp>_LIVE.csv` — une ligne par équipement traité
- `import_<timestamp>_LIVE.json` — même données + résumé chiffré

Statuts : `imported` · `skipped_duplicate` · `skipped_unmappable` · `error`

---

## Images équipements

Les images sont copiées dans `%APPDATA%\TeleDesk\images\` au premier lancement.  
Pour ajouter une photo : déposer le fichier image dans ce dossier, nommé d'après le modèle (ex: `T53.jpg`). Aucun rebuild nécessaire.
