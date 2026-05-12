# Import automatique Alcatel-Lucent → Bob! Desk

Script Python pour importer des équipements téléphoniques Alcatel depuis un export Excel
vers la fiche client correspondante dans Bob! Desk, via l'API REST.

---

## Structure du projet

```
alcatel_import/
├── main.py                  # Point d'entrée CLI
├── bobdesk_client.py        # Client HTTP Bob! Desk (retry, pagination)
├── referential.py           # Cache des référentiels Bob! Desk
├── mapper.py                # Logique de mapping Alcatel -> Bob! Desk
├── dedup.py                 # Détection de doublons
├── excel_reader.py          # Lecture et validation du fichier Excel
├── reporter.py              # Rapport CSV + JSON d'import
├── requirements.txt
├── config/
│   ├── mapping.yaml         # Table de correspondance configurable
│   └── .env.example         # Template de configuration
├── logs/                    # Logs horodatés (créés automatiquement)
├── reports/                 # Rapports d'import (créés automatiquement)
└── samples/                 # Exemples de fichiers Excel
```

---

## Installation

```bash
pip install -r requirements.txt
cp config/.env.example config/.env
# Éditer config/.env avec votre URL et token Bob! Desk
```

---

## Utilisation

### Dry-run (simulation — aucune écriture)
```bash
python main.py --file export_alcatel.xlsx --client "Nom du client" --dry-run
```

### Import réel
```bash
python main.py --file export_alcatel.xlsx --client "Nom du client"
```

### Cibler par ID client (évite les ambiguïtés)
```bash
python main.py --file export_alcatel.xlsx --client-id 42
```

---

## Table de mapping métier (résumé)

| Catégorie Alcatel | Interface | Type Alcatel         | → Catégorie Bob! Desk | → Sous-catégorie Bob! Desk |
|-------------------|-----------|----------------------|----------------------|---------------------------|
| Phone             | IP        | 4008/4018/4028/4038… | Téléphonie           | Téléphone IP              |
| Phone             | Z / A     | Analogic             | Téléphonie           | Téléphone analogique      |
| Phone             | UA        | —                    | Téléphonie           | Téléphone numérique       |
| AOM               | —         | Add-On 10/40         | Téléphonie           | Module d'extension        |
| Tool              | —         | Virtual Terminal     | Téléphonie           | Téléphone IP (à affiner)  |
| Tool              | —         | Remote Access V34    | —                    | **ignoré (null)**         |
| Tool              | —         | Internal Voice Mail  | —                    | **ignoré (null)**         |

> Modifier `config/mapping.yaml` pour ajuster sans toucher au code.

---

## Champs mappés

| Champ Excel Alcatel     | → Champ Bob! Desk       |
|-------------------------|-------------------------|
| EDN + Type              | name (construit)        |
| Numéro matériel         | serial_number           |
| ID                      | mac_address             |
| Adresse IP              | ip_address              |
| Type (préfixe numérique)| model                   |
| *(fixe)*                | brand = Alcatel-Lucent  |
| Version SW, États, etc. | description             |

---

## Rapport d'import

Après chaque exécution, deux fichiers sont créés dans `reports/` :
- `import_<client>_<date>_<mode>.csv` — une ligne par équipement traité
- `import_<client>_<date>_<mode>.json` — même données + résumé chiffré

Statuts possibles : `imported` | `skipped_duplicate` | `skipped_unmappable` | `error`

---

## Inconnues API à vérifier avant mise en production

> Ces points dépendent de la version et de la configuration de votre instance Bob! Desk.
> À vérifier dans la documentation API ou par inspection des requêtes réseau.

1. **Endpoint clients** : `GET /clients` avec paramètre `search` ?
2. **Endpoint création équipement** : `POST /clients/{id}/equipments` ou autre chemin ?
3. **Endpoint catégories** : `GET /categories` puis `GET /categories/{id}/subcategories` ?
4. **Endpoint métiers** : `GET /trades` ?
5. **Format d'authentification** : `Authorization: Bearer <token>` ou clé en query string ?
6. **Pagination** : paramètres `page` + `per_page` ? ou `offset` + `limit` ?
7. **Champs personnalisés** : endpoint disponible ? format attendu dans le payload ?
8. **Nom exact des champs** dans le payload d'équipement (`category_id`, `subcategory_id`, `trade_id`…) ?

---

## Anti-doublon

Le script vérifie les équipements déjà présents sur la fiche client avant toute insertion.
Clés testées dans l'ordre (configurable dans `mapping.yaml` > `dedup_keys`) :
1. `serial_number` (Numéro matériel)
2. `mac_address` (ID Alcatel)
3. `edn`

---

## Contraintes respectées

- Ne crée jamais de catégorie, sous-catégorie, métier ou lieu.
- Ne crée jamais de nouvelle fiche client.
- Ne modifie pas les équipements existants.
- Journalise toutes les lignes non-importées avec la raison.
