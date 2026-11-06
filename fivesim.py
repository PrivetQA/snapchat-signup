"""Buy a Snapchat verification number. The token is never printed."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

PRICES_URL = "https://5sim.net/v1/guest/prices?product=snapchat"
BUY_URL = "https://5sim.net/v1/user/buy/activation/{country}/any/snapchat"
CHECK_URL = "https://5sim.net/v1/user/check/{order_id}"
CANCEL_URL = "https://5sim.net/v1/user/cancel/{order_id}"

EUROPE = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech", "denmark",
    "england", "estonia", "finland", "france", "germany", "greece", "hungary",
    "ireland", "italy", "latvia", "lithuania", "netherlands", "poland",
    "portugal", "romania", "spain", "sweden", "ukraine",
}


def parse_offers(payload: object) -> list[dict]:
    offers: list[dict] = []

    def walk(node: object, country: str | None = None) -> None:
        if not isinstance(node, dict):
            return
        if "cost" in node and "count" in node:
            if country:
                offers.append({
                    "country": country,
                    "cost": float(node.get("cost") or 0),
                    "count": int(node.get("count") or 0),
                    "rate": float(node.get("rate") or 0),
                })
            return
        for key, value in node.items():
            next_country = country
            if country is None and key not in ("snapchat", "any", "virtual"):
                next_country = str(key).lower()
            walk(value, next_country)

    walk(payload)
    return offers


def choose_country(offers: list[dict]) -> str | None:
    stock = [offer for offer in offers if offer["count"] > 0]
    if not stock:
        return None
    high = [offer for offer in stock if offer["rate"] >= 40]
    pool = high or stock
    pool.sort(key=lambda offer: (offer["cost"], 0 if offer["country"] in EUROPE else 1, -offer["rate"]))
    return pool[0]["country"]


def prepared_countries(offers: list[dict], limit: int = 5) -> list[str]:
    stock = [offer for offer in offers if offer["count"] > 0]
    europe = sorted(
        (offer for offer in stock if offer["country"] in EUROPE),
        key=lambda offer: (offer["cost"], -offer["rate"]),
    )
    others = sorted(
        (offer for offer in stock if offer["country"] not in EUROPE),
        key=lambda offer: (offer["cost"], -offer["rate"]),
    )
    return [offer["country"] for offer in list(europe) + list(others)][:limit]


class FiveSim:
    def __init__(self, token: str) -> None:
        self.token = token

    def prices(self) -> list[dict]:
        return parse_offers(self._get(PRICES_URL, auth=False))

    def buy(self, country: str) -> dict:
        payload = self._get(BUY_URL.format(country=country), auth=True)
        if not isinstance(payload, dict) or not payload.get("phone"):
            raise RuntimeError("no number")
        return payload

    def check(self, order_id: int | str) -> dict:
        payload = self._get(CHECK_URL.format(order_id=order_id), auth=True)
        return payload if isinstance(payload, dict) else {}

    def cancel(self, order_id: int | str) -> None:
        try:
            self._get(CANCEL_URL.format(order_id=order_id), auth=True)
        except Exception:
            return

    def _get(self, url: str, auth: bool) -> object:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:180]
            raise RuntimeError(f"5sim {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError("5sim unreachable") from error
