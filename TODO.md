# TODO

## 🔴 Critique

- [x] **Validation des variables d'environnement au démarrage**
  Afficher un message clair si `NOTION_TOKEN`, `ODOO_URL`, `ODOO_DB`, `ODOO_USER` ou `ODOO_PASSWORD` sont absents avant toute requête réseau.
  _Fichier : `main.py`_ — implemented via `_require_env()`.

- [x] **Gestion des erreurs réseau dans OdooClient**
  Retry avec backoff exponentiel sur les erreurs 5xx et `ConnectionError`, aligné sur NotionClient.
  _Fichier : `src/odoo/client.py`_ — `max_retries=3`, backoff 2/4/8 s.

- [x] **Timeout configurable via env**
  `NOTION_TIMEOUT` et `ODOO_TIMEOUT` lus depuis l'environnement (défaut : 30 s).
  _Fichiers : `main.py`, `.env.example`_

## 🟠 Important

- [x] **Mapping d'IDs persistant (SQLite)**
  Remplacer le upsert basé sur le nom par un fichier SQLite qui stocke `notion_page_id → odoo_article_id`.
  Élimine les collisions de noms et permet les renommages.
  _Fichiers : `src/store.py`, `src/sync.py`, `main.py`_ — les pages non mappées retombent sur l'upsert par nom (migration transparente). Chemin configurable via `--store-path` / `SYNC_STORE_PATH`.

- [x] **Support des propriétés Notion**
  Synchroniser les propriétés des pages (tags, date de création, statut) vers des champs Odoo ou des tags d'articles.
  _Fichiers : `src/notion/parser.py`, `src/sync.py`_ — flag `--include-properties` : les propriétés sont rendues en table HTML en tête d'article (`knowledge.article` n'expose pas de champ tags natif).

- [x] **Flag `--since DATE`**
  Ne synchroniser que les pages modifiées depuis une date donnée (utiliser `last_edited_time` de l'API Notion).
  _Fichiers : `main.py`, `src/sync.py`_ — les pages ignorées sont comptées comme "skipped" ; les pages enfants sont toujours visitées.

- [x] **Couverture de tests ≥ 90 %**
  Ajouter des tests pour les cas limites : blocs imbriqués profonds, pages sans titre, réponses tronquées.
  _Couverture `src/` : 94 % (parser 99 %, sync et store 100 %)._

- [x] **Logging structuré (JSON)**
  Option `--log-format json` pour faciliter l'intégration avec des outils de monitoring (Datadog, CloudWatch).
  _Fichier : `main.py`_ — `JsonFormatter` (timestamp ISO, level, logger, message, exc_info).

- [x] **Support Odoo 15 (document.page)**
  Ajouter un client alternatif pour les instances Odoo 15 qui utilisent `document.page` au lieu de `knowledge.article`.
  _Fichiers : `src/odoo/client.py`, `main.py`_ — `OdooDocumentPageClient` (champ `content`, sans icône/publication), sélectionné via `--odoo-version 15` / `ODOO_VERSION`.

## 🟢 Nice to have

- [x] **Image re-hosting**
  Les URLs Notion pour les fichiers hébergés expirent après 1 heure. Télécharger les images et les uploader dans le stockage Odoo (ir.attachment).
  _Fichiers : `src/rehost.py`, `src/odoo/client.py`_ — flag `--rehost-images` : les images hébergées par Notion sont réuploadées en `ir.attachment` publics (`/web/image/<id>`) ; en cas d'échec l'URL d'origine est conservée.

- [x] **Docker image**
  `Dockerfile` + `docker-compose.yml` pour une utilisation sans Python local.
  _Fichiers : `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`_ — job CI « Docker build » (build-only, pas de credentials registry configurés).

- [x] **Interface web minimale**
  Un formulaire Flask/FastAPI pour déclencher une sync depuis un navigateur.
  _Fichiers : `src/web.py`, `requirements-web.txt`_ — `flask --app src.web run` (dépendance optionnelle, non incluse dans requirements.txt).

- [x] **Webhook Notion**
  Déclencher automatiquement une sync quand une page Notion est modifiée (via Notion webhooks ou polling).
  _Fichier : `main.py`_ — implémenté via polling : `--watch SECONDS` re-synchronise en boucle les pages modifiées depuis la passe précédente. Les vrais webhooks Notion nécessitent un endpoint public (infrastructure externe), non couverts ici.

- [x] **Rapport HTML de sync**
  Générer un rapport `sync-report.html` avec la liste des articles créés/mis à jour/en erreur.
  _Fichiers : `src/report.py`, `src/sync.py`, `main.py`_ — flag `--report FILE` : rapport HTML autonome (résumé + une ligne par page).

- [x] **Support des bases de données en vue Tableau**
  Convertir les databases Notion en tables HTML dans un article Odoo de synthèse.
  _Fichiers : `src/sync.py`, `src/notion/client.py`, `main.py`_ — `database <ID> --as-table` : un seul article de synthèse avec une colonne par propriété et une ligne par page.

- [x] **Internationalisation (i18n)**
  Messages CLI en français et en anglais selon `LANG`.
  _Fichier : `src/i18n.py`_ — messages utilisateur (erreurs CLI, rapport de sync) traduits en français selon `LANGUAGE`/`LC_ALL`/`LANG`.
