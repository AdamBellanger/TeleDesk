"""
Client HTTP pour l'API Bob! Desk.
Auth : POST /auth/login -> cookie HttpOnly auth-production + header x-auth: ok + header client: interface_id
"""

import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class BobDeskAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class BobDeskClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        interface_id: str,
        timeout: int = 30,
        dry_run: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.interface_id = interface_id
        self.timeout = timeout
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://app.bob-desk.com",
            "Referer": "https://app.bob-desk.com/",
        })
        self._login()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _login(self):
        url = f"{self.base_url}/auth/login"
        payload = {
            "email": self.email,
            "password": self.password,
            "interface_id": self.interface_id,
        }
        logger.info("Connexion Bob! Desk (%s)...", self.email)
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise BobDeskAPIError(f"Erreur réseau login: {exc}") from exc

        if resp.status_code == 401:
            raise BobDeskAPIError(
                "Login échoué (401) — vérifier BOBDESK_EMAIL / BOBDESK_PASSWORD",
                401, resp.text[:300],
            )
        if resp.status_code >= 400:
            raise BobDeskAPIError(
                f"Login échoué HTTP {resp.status_code}", resp.status_code, resp.text[:300]
            )

        # cookie auth-production stocké automatiquement dans self.session
        self.session.headers.update({
            "x-auth": "ok",
            "client": self.interface_id,
        })
        logger.info("Connecté.")

    # ------------------------------------------------------------------
    # HTTP interne
    # ------------------------------------------------------------------

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{self.base_url}{endpoint}"
        for attempt in range(1, 4):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if resp.status_code == 401 and attempt == 1:
                    logger.warning("Session expirée, reconnexion...")
                    self._login()
                    continue
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                    logger.warning("Rate-limit, attente %ss", wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    logger.debug("Erreur serveur %s (tentative %s/3)", resp.status_code, attempt)
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code >= 400:
                    raise BobDeskAPIError(
                        f"HTTP {resp.status_code} {method} {url}",
                        resp.status_code, resp.text[:500],
                    )
                return resp.json() if resp.content else {}
            except requests.RequestException as exc:
                if attempt == 3:
                    raise BobDeskAPIError(f"Erreur réseau: {exc}") from exc
                time.sleep(2 ** attempt)
        raise BobDeskAPIError(f"Échec après 3 tentatives: {url}")

    def _get_all_post(self, endpoint: str, body: Optional[dict] = None) -> list:
        """Pagination via POST (pattern Bob! Desk /xxx/list)."""
        results, page = [], 1
        while True:
            data = self._request("POST", endpoint, json={**(body or {}), "page": page, "per_page": 100})
            items = data.get("elements", data.get("data", data.get("items", [])))
            if not items:
                logger.debug("_get_all_post %s page %d: 0 éléments, clés disponibles: %s", endpoint, page, list(data.keys()) if isinstance(data, dict) else type(data))
                break
            results.extend(items)
            if len(items) < 100:
                break
            page += 1
        return results

    # ------------------------------------------------------------------
    # Référentiels
    # ------------------------------------------------------------------

    def get_scopes(self) -> list[dict]:
        """Retourne catégories, sous-catégories et typologies (endpoint /scopes/list)."""
        return self._get_all_post("/scopes/list")

    def get_clients(self, search: Optional[str] = None) -> list[dict]:
        body = {"search": search} if search else {}
        return self._get_all_post("/clients/list", body)

    def get_client_location(self, client_id: str) -> str | None:
        """Retourne l'_id du premier lieu associé au client, ou None."""
        try:
            data = self._request("POST", "/locations/list", json={"search": ""})
            els = data.get("elements", [])
            for loc in els:
                client = loc.get("_client", {})
                cid = client.get("_id") if isinstance(client, dict) else client
                if str(cid) == str(client_id):
                    logger.info("Lieu trouvé pour client %s : %s (%s)", client_id, loc.get("name"), loc.get("_id"))
                    return loc["_id"]
            logger.warning("Aucun lieu trouvé pour le client %s — équipements créés sans lieu.", client_id)
            return None
        except BobDeskAPIError as exc:
            logger.warning("Impossible de récupérer le lieu du client: %s", exc)
            return None

    def get_client_equipments(self, client_id: str) -> list[dict]:
        try:
            results = self._get_all_post("/equipments/list", {"_client": client_id})
            logger.info("get_client_equipments (filtre API): %d équipement(s) pour client %s", len(results), client_id)
            if results:
                return results
            # Fallback : certaines instances retournent tous les équipements sans filtre
            logger.info("Fallback: récupération sans filtre et filtrage côté client...")
            all_eq = self._get_all_post("/equipments/list", {})
            filtered = [
                eq for eq in all_eq
                if self._match_client(eq, client_id)
            ]
            logger.info("get_client_equipments (fallback): %d équipement(s) pour client %s (total %d)", len(filtered), client_id, len(all_eq))
            return filtered
        except BobDeskAPIError as exc:
            logger.warning("Impossible de charger les équipements existants (%s) — anti-doublon désactivé.", exc)
            return []

    @staticmethod
    def _match_client(eq: dict, client_id: str) -> bool:
        """Vérifie si un équipement appartient au client, quelle que soit la forme du champ _client."""
        raw = eq.get("_client")
        if raw is None:
            return False
        if isinstance(raw, dict):
            return str(raw.get("_id", "")) == str(client_id)
        return str(raw) == str(client_id)

    def get_field_sections(self) -> list[dict]:
        data = self._request("GET", "/fieldSections/equipment")
        return data.get("elements", [])

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------

    def create_equipment(self, payload: dict) -> dict:
        if self.dry_run:
            logger.info("[DRY-RUN] POST /equipments %s", payload.get("name"))
            return {"element": {"_id": "DRY_RUN", **payload}}
        return self._request("POST", "/equipments", json=payload)

    def set_equipment_image(self, equipment_id: str, image_path) -> bool:
        """Upload une image sur un équipement via PUT _cover en base64. Retourne True si OK."""
        import base64
        from pathlib import Path as _Path
        path = _Path(image_path)
        suffix = path.suffix.lower().lstrip(".")
        mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            data_uri = f"data:{mime};base64,{b64}"
            self._request("PUT", f"/equipments/{equipment_id}", json={"_cover": data_uri})
            return True
        except Exception as exc:
            logger.debug("Upload image échoué pour %s : %s", equipment_id, exc)
            return False

    def delete_equipment(self, equipment_id: str) -> bool:
        if self.dry_run:
            logger.info("[DRY-RUN] DELETE /equipments/%s", equipment_id)
            return True
        try:
            self._request("DELETE", f"/equipments/{equipment_id}")
            return True
        except BobDeskAPIError as exc:
            logger.warning("Suppression échouée %s : %s", equipment_id, exc)
            return False

    def delete_client_equipments_by_subcategories(
        self, client_id: str, subcategory_ids: set[str]
    ) -> int:
        """Supprime tous les équipements du client dont la sous-catégorie est dans subcategory_ids.
        Retourne le nombre d'équipements supprimés."""
        equipments = self.get_client_equipments(client_id)
        to_delete = []
        for eq in equipments:
            subcat = eq.get("_subcategory")
            if isinstance(subcat, dict):
                subcat = subcat.get("_id", "")
            if subcat in subcategory_ids:
                to_delete.append(eq["_id"])

        logger.info("%d équipement(s) à supprimer avant import.", len(to_delete))
        deleted = 0
        for eq_id in to_delete:
            if self.delete_equipment(eq_id):
                deleted += 1
        logger.info("%d équipement(s) supprimé(s).", deleted)
        return deleted
