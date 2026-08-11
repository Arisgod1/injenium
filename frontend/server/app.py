"""Local companion API for the Injenium browser experience.

The service is deliberately incapable of signing EVM transactions. It only
validates inert Recipe data, runs whitelisted Go2 primitives against a recorder,
and hosts an isolated MockChain ledger for the no-wallet experience.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any, Literal
import urllib.error
import urllib.request

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from injenium.core.chain.base import inj_to_wei, wei_to_inj
from injenium.core.chain.mock_chain import MockChain
from injenium.core.recipe import Recipe
from injenium.core.registry import PrimitiveRegistry
from injenium.core.sandbox.interpreter import RecipeValidationError, SandboxInterpreter
from injenium.domains.go2 import primitives as go2_primitives


API_VERSION = "1.0"
MAX_RECIPE_BYTES = 256 * 1024
SESSION_TTL_SECONDS = 24 * 60 * 60
BUYER = "0xA0000000000000000000000000000000000000A0"
SELLER = "0xB0000000000000000000000000000000000000B0"
CID_PATTERN = re.compile(r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{20,})$")


def _recipe(intent: str, steps: list[dict[str, Any]], success: str) -> Recipe:
    return Recipe.model_validate(
        {
            "intent": intent,
            "preconditions": ["前方区域已清空", "模拟器处于停止状态"],
            "steps": steps,
            "success_criteria": success,
            "schema_version": 1,
            "payload": {},
        }
    )


CATALOG: dict[str, dict[str, Any]] = {
    "doorway-route": {
        "title": "门口巡检路线",
        "description": "起身、前进并导航至门口，适合体验复合动作与文本导航。",
        "tags": ["导航", "巡检"],
        "price": "0.025",
        "recipe": _recipe(
            "完成门口巡检",
            [
                {"primitive": "execute_sport_command", "params": {"command_name": "BalanceStand"}},
                {"primitive": "relative_move", "params": {"forward": 1.2, "left": 0, "degrees": 0}},
                {"primitive": "navigate_with_text", "params": {"query": "门口"}},
            ],
            "到达门口并保持站立",
        ),
    },
    "safe-greeting": {
        "title": "访客友好问候",
        "description": "执行安全动作白名单中的问候，并留出短暂交互时间。",
        "tags": ["互动", "接待"],
        "price": "0.012",
        "recipe": _recipe(
            "向访客问候",
            [
                {"primitive": "execute_sport_command", "params": {"command_name": "Hello"}},
                {"primitive": "wait", "params": {"seconds": 1.5}},
                {"primitive": "execute_sport_command", "params": {"command_name": "BalanceStand"}},
            ],
            "完成问候并恢复平衡站立",
        ),
    },
    "loading-ramp": {
        "title": "装卸坡道通过",
        "description": "以小步幅调整方向并通过坡道，用于观察参数边界与路径轨迹。",
        "tags": ["移动", "坡道"],
        "price": "0.04",
        "recipe": _recipe(
            "通过装卸坡道",
            [
                {"primitive": "relative_move", "params": {"forward": 0.4, "left": 0.1, "degrees": -8}},
                {"primitive": "relative_move", "params": {"forward": 0.8, "left": 0, "degrees": 8}},
                {"primitive": "execute_sport_command", "params": {"command_name": "RecoveryStand"}},
            ],
            "越过坡道并恢复稳定姿态",
        ),
    },
}


class RecipeSource(BaseModel):
    kind: Literal["builtin", "inline", "ipfs"]
    id: str | None = None
    recipe: dict[str, Any] | None = None
    uri: str | None = None


class InspectRequest(BaseModel):
    source: RecipeSource
    expected_hash: str | None = Field(default=None, alias="expectedHash")

    model_config = ConfigDict(populate_by_name=True)


class LoadRequest(BaseModel):
    source: RecipeSource
    expected_hash: str | None = Field(default=None, alias="expectedHash")

    model_config = ConfigDict(populate_by_name=True)


class PublishRequestBody(BaseModel):
    recipe_hash: str = Field(alias="recipeHash")

    model_config = ConfigDict(populate_by_name=True)


class MarketRequestBody(BaseModel):
    need: str = Field(min_length=3, max_length=240)
    budget: str
    tags: list[str] = Field(default_factory=list, max_length=8)


class OfferBody(BaseModel):
    recipe_hash: str = Field(alias="recipeHash")

    model_config = ConfigDict(populate_by_name=True)


class ListingBody(BaseModel):
    description: str = Field(min_length=3, max_length=180)
    price: str
    tags: list[str] = Field(default_factory=list, max_length=8)
    recipe_hash: str = Field(alias="recipeHash")

    model_config = ConfigDict(populate_by_name=True)


class ScoreBody(BaseModel):
    score: int = Field(ge=1, le=5)


@dataclass
class RecordedCall:
    primitive: str
    args: dict[str, Any]


class SimulatedGo2Provider:
    """A data recorder with the exact methods used by Go2 dispatch adapters."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    def relative_move(self, forward: float = 0, left: float = 0, degrees: float = 0) -> str:
        self.calls.append(RecordedCall("relative_move", {"forward": forward, "left": left, "degrees": degrees}))
        return f"模拟移动：前进 {forward:g}m，横移 {left:g}m，转向 {degrees:g}°"

    def navigate_with_text(self, query: str) -> str:
        self.calls.append(RecordedCall("navigate_with_text", {"query": query}))
        return f"模拟导航至“{query}”"

    def follow_person(self, query: str, initial_bbox: list[float] | None = None) -> str:
        self.calls.append(RecordedCall("follow_person", {"query": query, "initial_bbox": initial_bbox}))
        return f"模拟跟随符合“{query}”的人"

    def execute_sport_command(self, command_name: str) -> str:
        self.calls.append(RecordedCall("execute_sport_command", {"command_name": command_name}))
        return f"模拟执行安全姿态 {command_name}"

    def wait(self, seconds: float) -> str:
        self.calls.append(RecordedCall("wait", {"seconds": seconds}))
        return f"模拟等待 {seconds:g} 秒"


@dataclass
class DemoSession:
    ident: str
    root: Path
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)
    loaded: dict[str, Recipe] = field(default_factory=dict)

    @property
    def state_path(self) -> Path:
        return self.root / "market.json"

    def chain(self, address: str) -> MockChain:
        self.touched_at = time.time()
        return MockChain(self.state_path, address=address)


_sessions: dict[str, DemoSession] = {}
_runtime_root = Path(tempfile.mkdtemp(prefix="injenium_web_"))


def _registry() -> PrimitiveRegistry:
    registry = PrimitiveRegistry()
    go2_primitives.register(registry)
    return registry


REGISTRY = _registry()


def _cleanup_sessions() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    for ident, session in list(_sessions.items()):
        if session.touched_at < cutoff:
            for child in session.root.glob("*"):
                child.unlink(missing_ok=True)
            session.root.rmdir()
            _sessions.pop(ident, None)


def _get_session(session_id: str | None, response: Response) -> DemoSession:
    _cleanup_sessions()
    session = _sessions.get(session_id or "")
    if session is None:
        ident = secrets.token_urlsafe(24)
        root = _runtime_root / ident
        root.mkdir(mode=0o700)
        session = DemoSession(ident, root)
        _sessions[ident] = session
        response.set_cookie(
            "injenium_session",
            ident,
            httponly=True,
            samesite="lax",
            secure=os.environ.get("INJENIUM_SECURE_COOKIE", "false").lower() == "true",
            max_age=SESSION_TTL_SECONDS,
        )
        _seed_market(session)
    session.touched_at = time.time()
    return session


def _seed_market(session: DemoSession) -> None:
    seller = session.chain(SELLER)
    for key, item in CATALOG.items():
        recipe: Recipe = item["recipe"]
        seller.list_skill(
            description=item["title"],
            tags=list(item["tags"]),
            recipe_uri=f"builtin://{key}",
            recipe_hash=recipe.content_hash(),
            price=inj_to_wei(item["price"]),
        )


def _normalize_hash(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.lower().removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise HTTPException(422, "expectedHash 必须是 32 字节十六进制哈希")
    return normalized


def _bounded_demo_amount(value: str, subject: str) -> int:
    maximum = os.environ.get("INJENIUM_DEMO_MAX_INJ", "0.1")
    try:
        amount = inj_to_wei(value)
        maximum_wei = inj_to_wei(maximum)
    except ValueError as exc:
        raise HTTPException(422, f"{subject}必须是有效的十进制 INJ 金额") from exc
    if amount <= 0 or amount > maximum_wei:
        raise HTTPException(422, f"{subject}必须大于 0 且不超过 {maximum} INJ")
    return amount


def _load_ipfs(uri: str) -> Recipe:
    if not uri.startswith("ipfs://"):
        raise HTTPException(422, "只接受 ipfs:// URI")
    value = uri.removeprefix("ipfs://").strip("/")
    cid = value.split("/", 1)[0]
    if not CID_PATTERN.fullmatch(cid):
        raise HTTPException(422, "IPFS URI 中的 CID 格式无效")
    path = value.split("/", 1)[1] if "/" in value else "recipe.json"
    if path != "recipe.json":
        raise HTTPException(422, "首版仅允许读取 CID 根目录下的 recipe.json")
    gateway = os.environ.get("INJENIUM_IPFS_GATEWAY", "https://ipfs.io/ipfs/").rstrip("/")
    request = urllib.request.Request(f"{gateway}/{cid}/{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(MAX_RECIPE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, f"无法从固定 IPFS 网关读取 Recipe：{exc}") from exc
    if len(raw) > MAX_RECIPE_BYTES:
        raise HTTPException(413, "Recipe 超过 256 KiB 限制")
    try:
        return Recipe.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"IPFS 内容不是有效 Recipe：{exc}") from exc


def _resolve_source(source: RecipeSource) -> Recipe:
    if source.kind == "builtin":
        if source.id not in CATALOG:
            raise HTTPException(404, "内置技能不存在")
        return CATALOG[source.id]["recipe"]
    if source.kind == "inline":
        if source.recipe is None:
            raise HTTPException(422, "inline 来源缺少 recipe")
        encoded = json.dumps(source.recipe, ensure_ascii=False).encode()
        if len(encoded) > MAX_RECIPE_BYTES:
            raise HTTPException(413, "Recipe 超过 256 KiB 限制")
        try:
            return Recipe.model_validate(source.recipe)
        except ValueError as exc:
            raise HTTPException(422, f"Recipe 结构无效：{exc}") from exc
    if source.uri is None:
        raise HTTPException(422, "ipfs 来源缺少 uri")
    return _load_ipfs(source.uri)


def _permissions(recipe: Recipe) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for step in recipe.steps:
        counts[step.primitive] = counts.get(step.primitive, 0) + 1
    return [{"primitive": name, "count": count} for name, count in counts.items()]


def _inspection(recipe: Recipe, expected_hash: str | None = None) -> dict[str, Any]:
    problems = SandboxInterpreter(SimulatedGo2Provider(), REGISTRY).validate(recipe)
    actual = recipe.content_hash()
    expected = _normalize_hash(expected_hash)
    matches = expected is None or secrets.compare_digest(actual, expected)
    if not matches:
        problems = ["内容哈希与链上承诺不一致", *problems]
    return {
        "recipe": recipe.model_dump(),
        "hash": actual,
        "expectedHash": expected,
        "hashMatches": matches,
        "validation": {"ok": not problems, "problems": problems},
        "permissions": _permissions(recipe),
        "risk": "low" if not problems else "blocked",
    }


def _run(recipe: Recipe) -> dict[str, Any]:
    provider = SimulatedGo2Provider()
    interpreter = SandboxInterpreter(provider, REGISTRY)
    try:
        report = interpreter.run(recipe)
    except RecipeValidationError as exc:
        raise HTTPException(422, {"message": "Recipe 被白名单沙箱拒绝，未执行任何动作", "problems": exc.problems}) from exc
    return {
        "ok": report.ok,
        "message": report.message,
        "steps": [asdict(step) for step in report.steps],
        "calls": [asdict(call) for call in provider.calls],
    }


def _recipe_from_uri(session: DemoSession, uri: str, expected_hash: str) -> Recipe:
    if uri.startswith("builtin://"):
        key = uri.removeprefix("builtin://")
        recipe = _resolve_source(RecipeSource(kind="builtin", id=key))
    elif uri.startswith("session://"):
        recipe_hash = uri.removeprefix("session://")
        recipe = session.loaded.get(recipe_hash)
        if recipe is None:
            raise HTTPException(404, "该会话中找不到报价引用的 Recipe")
    elif uri.startswith("ipfs://"):
        recipe = _load_ipfs(uri)
    else:
        raise HTTPException(422, "拒绝从本机路径或任意 URL 装载 Recipe")
    inspection = _inspection(recipe, expected_hash)
    if not inspection["validation"]["ok"]:
        raise HTTPException(422, {"message": "交易前验证失败，未产生付款或状态变更", **inspection})
    return recipe


def _snapshot(session: DemoSession) -> dict[str, Any]:
    buyer = session.chain(BUYER)
    seller = session.chain(SELLER)
    requests = list(buyer._read()["requests"].values())  # MockChain owns the schema.
    offers = list(buyer._read()["offers"].values())
    listings = [item.to_dict() for item in buyer.list_active_listings()]
    return {
        "wallets": {
            "buyer": {"address": BUYER, "balance": str(wei_to_inj(buyer.balance_of(BUYER)))},
            "seller": {"address": SELLER, "balance": str(wei_to_inj(seller.balance_of(SELLER)))},
        },
        "requests": requests,
        "offers": offers,
        "listings": listings,
        "ratings": [rating.to_dict() for rating in buyer.ratings()],
        "loadedHashes": list(session.loaded),
    }


app = FastAPI(title="Injenium Companion", version=API_VERSION, docs_url="/api/docs", redoc_url=None)
allowed_origins = [value.strip() for value in os.environ.get("INJENIUM_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if value.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next: Any) -> Response:
    length = request.headers.get("content-length")
    if length and int(length) > MAX_RECIPE_BYTES + 8192:
        return Response("请求体超过限制", status_code=413)
    return await call_next(request)


@app.get("/api/v1/status")
def status() -> dict[str, Any]:
    return {
        "service": "injenium-companion",
        "version": API_VERSION,
        "sandbox": "go2-whitelist",
        "maxRecipeBytes": MAX_RECIPE_BYTES,
        "ipfsRead": True,
        "ipfsPublish": os.environ.get("INJENIUM_ENABLE_IPFS_PUBLISH", "false").lower() == "true",
        "signingCapability": False,
    }


@app.get("/api/v1/catalog")
def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "title": item["title"],
            "description": item["description"],
            "tags": item["tags"],
            "price": item["price"],
            "hash": item["recipe"].content_hash(),
            "stepCount": len(item["recipe"].steps),
        }
        for key, item in CATALOG.items()
    ]


@app.post("/api/v1/recipes/inspect")
def inspect_recipe(body: InspectRequest) -> dict[str, Any]:
    return _inspection(_resolve_source(body.source), body.expected_hash)


@app.post("/api/v1/recipes/publish")
def publish_recipe(
    body: PublishRequestBody,
    response: Response,
    injenium_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    if os.environ.get("INJENIUM_ENABLE_IPFS_PUBLISH", "false").lower() != "true":
        raise HTTPException(503, "当前 companion 未配置 IPFS 发布；模拟市场仍可使用会话 URI")
    session = _get_session(injenium_session, response)
    normalized = _normalize_hash(body.recipe_hash)
    recipe = session.loaded.get(normalized or "")
    if recipe is None:
        raise HTTPException(404, "请先验证并装载该 Recipe")
    inspection = _inspection(recipe)
    if not inspection["validation"]["ok"]:
        raise HTTPException(422, "Recipe 未通过白名单校验")
    from injenium.core.storage import publish_dir

    directory = session.root / f"publish-{normalized}"
    recipe.save(directory)
    return {"uri": publish_dir(directory), "hash": normalized or ""}


@app.post("/api/v1/demo/load")
def load_recipe(
    body: LoadRequest,
    response: Response,
    injenium_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    recipe = _resolve_source(body.source)
    inspection = _inspection(recipe, body.expected_hash)
    if not inspection["validation"]["ok"]:
        raise HTTPException(422, {"message": "Recipe 未装载，未执行任何动作", **inspection})
    session.loaded[inspection["hash"]] = recipe
    return inspection


@app.post("/api/v1/demo/run/{recipe_hash}")
def run_loaded(
    recipe_hash: str,
    response: Response,
    injenium_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    recipe = session.loaded.get(_normalize_hash(recipe_hash) or "")
    if recipe is None:
        raise HTTPException(404, "请先验证并装载该 Recipe")
    return _run(recipe)


@app.get("/api/v1/demo/market")
def demo_market(response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    return _snapshot(_get_session(injenium_session, response))


@app.post("/api/v1/demo/reset")
def reset_demo(response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    session.state_path.unlink(missing_ok=True)
    session.loaded.clear()
    _seed_market(session)
    return _snapshot(session)


@app.post("/api/v1/demo/requests")
def create_request(body: MarketRequestBody, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    budget = _bounded_demo_amount(body.budget, "模拟悬赏金额")
    ident = session.chain(BUYER).publish_request(body.need, budget, body.tags)
    return {"id": ident, "market": _snapshot(session)}


@app.post("/api/v1/demo/requests/{request_id}/offers")
def create_offer(request_id: str, body: OfferBody, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    recipe_hash = _normalize_hash(body.recipe_hash) or ""
    recipe = session.loaded.get(recipe_hash)
    if recipe is None:
        raise HTTPException(404, "供给方需要先装载用于报价的 Recipe")
    request_item = session.chain(SELLER).get_request(request_id)
    ident = session.chain(SELLER).submit_offer(request_id, f"session://{recipe_hash}", recipe_hash, request_item.budget)
    return {"id": ident, "market": _snapshot(session)}


@app.post("/api/v1/demo/offers/{offer_id}/accept-run")
def accept_run(offer_id: str, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    offer = session.chain(BUYER).get_offer(offer_id)
    recipe = _recipe_from_uri(session, offer.recipe_uri, offer.recipe_hash)
    session.chain(BUYER).accept_offer(offer_id)
    return {"run": _run(recipe), "market": _snapshot(session)}


@app.post("/api/v1/demo/offers/{offer_id}/release")
def release_offer(offer_id: str, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    tx = session.chain(BUYER).release_payment(offer_id)
    return {"tx": tx, "market": _snapshot(session)}


@app.post("/api/v1/demo/offers/{offer_id}/rate")
def rate_offer(offer_id: str, body: ScoreBody, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    offer = session.chain(BUYER).get_offer(offer_id)
    tx = session.chain(BUYER).rate(offer_id, offer.responder, body.score)
    return {"tx": tx, "market": _snapshot(session)}


@app.post("/api/v1/demo/requests/{request_id}/cancel")
def cancel_request(request_id: str, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    tx = session.chain(BUYER).cancel_request(request_id)
    return {"tx": tx, "market": _snapshot(session)}


@app.post("/api/v1/demo/listings")
def create_listing(body: ListingBody, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    recipe_hash = _normalize_hash(body.recipe_hash) or ""
    if recipe_hash not in session.loaded:
        raise HTTPException(404, "请先装载要挂牌的 Recipe")
    price = _bounded_demo_amount(body.price, "模拟挂牌价格")
    ident = session.chain(SELLER).list_skill(body.description, body.tags, f"session://{recipe_hash}", recipe_hash, price)
    return {"id": ident, "market": _snapshot(session)}


@app.post("/api/v1/demo/listings/{listing_id}/buy-run")
def buy_run(listing_id: str, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    listing = session.chain(BUYER).get_listing(listing_id)
    recipe = _recipe_from_uri(session, listing.recipe_uri, listing.recipe_hash)
    tx = session.chain(BUYER).buy_skill(listing_id)
    return {"tx": tx, "run": _run(recipe), "market": _snapshot(session)}


@app.delete("/api/v1/demo/listings/{listing_id}")
def delist(listing_id: str, response: Response, injenium_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    session = _get_session(injenium_session, response)
    tx = session.chain(SELLER).delist_skill(listing_id)
    return {"tx": tx, "market": _snapshot(session)}


dist_dir = Path(__file__).resolve().parents[1] / "dist"
if dist_dir.exists():
    assets = dist_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        requested = dist_dir / full_path
        if requested.is_file() and dist_dir in requested.resolve().parents:
            return FileResponse(requested)
        return FileResponse(dist_dir / "index.html")
