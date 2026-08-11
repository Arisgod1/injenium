"""Repeatable companion API smoke flow; intentionally not a unit test."""

from __future__ import annotations

from http.cookiejar import CookieJar
import json
import urllib.error
import urllib.request


BASE = "http://127.0.0.1:8000/api/v1"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def call(path: str, payload: dict[str, object] | None = None, method: str | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=15) as response:
        return json.load(response)


def expect_error(path: str, payload: dict[str, object], status: int) -> None:
    try:
        call(path, payload)
    except urllib.error.HTTPError as exc:
        assert exc.code == status, f"expected HTTP {status}, got {exc.code}"
    else:
        raise AssertionError(f"expected HTTP {status} from {path}")


def main() -> None:
    status = call("/status")
    catalog = call("/catalog")
    inspected = call("/recipes/inspect", {"source": {"kind": "builtin", "id": "doorway-route"}})
    inline = call("/recipes/inspect", {"source": {"kind": "inline", "recipe": inspected["recipe"]}})
    dangerous = {**inspected["recipe"], "steps": [{"primitive": "run_shell", "params": {"command": "id"}}]}
    expect_error("/demo/load", {"source": {"kind": "inline", "recipe": dangerous}}, 422)
    expect_error("/recipes/inspect", {"source": {"kind": "ipfs", "uri": "ipfs://not-a-cid"}}, 422)
    loaded = call("/demo/load", {"source": {"kind": "builtin", "id": "doorway-route"}})
    recipe_hash = loaded["hash"]
    run = call(f"/demo/run/{recipe_hash}", method="POST")
    request = call("/demo/requests", {"need": "cross the ramp safely", "budget": "0.05", "tags": ["locomotion"]})
    request_id = request["id"]
    offer = call(f"/demo/requests/{request_id}/offers", {"recipeHash": recipe_hash})
    offer_id = offer["id"]
    call(f"/demo/offers/{offer_id}/accept-run", method="POST")
    released = call(f"/demo/offers/{offer_id}/release", method="POST")
    rated = call(f"/demo/offers/{offer_id}/rate", {"score": 5})
    listing = call("/demo/listings", {"description": "smoke listing", "price": "0.01", "tags": ["smoke"], "recipeHash": recipe_hash})
    purchased = call(f"/demo/listings/{listing['id']}/buy-run", method="POST")
    cancellable = call("/demo/requests", {"need": "cancel this smoke request", "budget": "0.01", "tags": []})
    cancelled = call(f"/demo/requests/{cancellable['id']}/cancel", method="POST")
    expect_error("/demo/requests", {"need": "reject an invalid amount", "budget": "NaN", "tags": []}, 422)
    assert status["signingCapability"] is False
    assert len(catalog) == 3
    assert inspected["hash"] == inline["hash"]
    assert run["ok"] is True
    assert released["market"]["requests"][0]["status"] == "settled"
    assert len(rated["market"]["ratings"]) == 1
    assert purchased["run"]["ok"] is True
    cancelled_request = next(item for item in cancelled["market"]["requests"] if item["id"] == cancellable["id"])
    assert cancelled_request["status"] == "cancelled"
    print(
        "companion smoke OK: "
        f"sources=builtin,inline,ipfs-guard catalog={len(catalog)} "
        f"request={request_id} offer={offer_id} run=ok settlement=ok rating=ok "
        "listing=ok refund=ok dangerous=blocked"
    )


if __name__ == "__main__":
    main()
