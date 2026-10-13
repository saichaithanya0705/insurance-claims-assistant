import logging
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, SecretStr, field_validator

from claims.agents import roster
from claims.api.auth import AuthStore, csrf_token
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput, ReviewDecision, SearchFilters, StrictModel
from claims.core.settings import Settings
from claims.evaluation.service import EvaluationBusy, EvaluationService
from claims.investigation.intake_extract import IntakeExtractor, IntakeUnavailable
from claims.investigation.sidechat import (
    MAX_PER_RUN,
    MAX_QUESTION,
    SideChat,
    SideChatError,
    suggestions,
    view_for,
)
from claims.investigation.workflow import InvestigationService
from claims.ml.analytics import AnalyticsService
from claims.observability import agent_activity
from claims.observability.explain import explain_run
from claims.observability.observatory import Observatory
from claims.observability.preview import preview_of
from claims.retrieval.fallback import LocalKnowledge
from claims.retrieval.graph import structure as graph_structure
from claims.storage.saved_search import SavedCaseSearch
from claims.synapt import query_feedback
from claims.synapt.adapter import build_synapt_adapter
from claims.synapt.query_agent import present as present_query_agent
from claims.synapt.query_feedback import FeedbackError
from claims.synapt.stats import SynaptStats

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
# Production build of frontend/ (see frontend/vite.config.ts).
APP_DIR = STATIC_DIR / "app"
# Technical sub-resources of an investigation: prompts, raw events and the recorded trace are for
# administrators; handlers get the plain-language explanation instead.
ADMIN_SUBPATH = re.compile(r"/(?:review|audit|trace)(?:/\d+)?/?$")
ID_SEGMENT = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}")


class QueryFeedbackRequest(StrictModel):
    target: str = Field(min_length=4, max_length=24, pattern=r"^(?:investigation|side:[0-9]{1,9})$")
    choice: str = Field(pattern=r"^(?:helpful|partly|not_helpful)$")
    reason: str | None = Field(default=None, max_length=600)


class SideChatRequest(StrictModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION)


UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class InvestigationRequest(StrictModel):
    claim: ClaimInput
    filters: SearchFilters = Field(default_factory=SearchFilters)
    # The page may choose the ID so it can follow the run live (GET .../progress) while this request is in flight.
    run_id: str | None = Field(default=None, pattern=UUID_PATTERN)


class IntakeExtractRequest(StrictModel):
    description: str = Field(min_length=10, max_length=6000)

    @field_validator("description")
    @classmethod
    def has_words(cls, value):
        if len(value.strip()) < 10 or sum(ch.isalpha() for ch in value) < 5:
            raise ValueError("Write the incident in words: at least 10 characters with letters")
        return value


class FeedbackRequest(StrictModel):
    rating: int = Field(ge=1, le=5)
    note: str = Field(min_length=3, max_length=2000)


class EvaluationRequest(StrictModel):
    judge: bool = False
    # True: start in the background and poll /api/evaluations/status for progress.
    background: bool = False


class LoginRequest(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)


class AccountRequest(LoginRequest):
    password: SecretStr = Field(min_length=15, max_length=128)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


def create_app(settings=None, adapter=None, analytics=None, fallback=None):
    settings = settings or Settings()
    analytics = analytics or AnalyticsService(
        settings.claims_data_path,
        settings.claims_artifact_dir,
        settings.claims_parquet_path,
        settings.claims_train_rows,
        settings.claims_duckdb_memory,
    )
    if fallback is None and settings.claims_fallback_enabled:
        fallback = LocalKnowledge(settings)
    service = InvestigationService(
        settings, adapter or build_synapt_adapter(settings), analytics, fallback
    )
    if fallback is not None and fallback.available():
        # Build or load the local index now so the first degraded run is not slowed by it.
        def warm_fallback():
            try:
                fallback.warm()
            except Exception as exc:  # noqa: BLE001 - a failed warm-up must never stop the service
                logger.warning("Local fallback index not ready (%s)", type(exc).__name__)

        threading.Thread(target=warm_fallback, name="fallback-warm", daemon=True).start()
    evaluation = EvaluationService(service, settings)
    side_chat = SideChat(service.store, service.adapter)
    synapt_stats = SynaptStats(service.adapter, settings.synapt_provider_id)
    case_search = SavedCaseSearch(service.store, settings)
    observatory = Observatory(service.store)
    auth = (
        AuthStore(
            settings.claims_auth_database_path
            or settings.claims_database_path.with_name("auth.sqlite")
        )
        if settings.claims_auth_enabled
        else None
    )
    preauth_csrf = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
        if auth:
            auth.close()

    app = FastAPI(title="Synapt Claims Investigator", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.state.evaluation = evaluation
    app.state.side_chat = side_chat
    app.state.case_search = case_search
    app.state.observatory = observatory
    app.state.auth = auth

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        if request.url.path.startswith(("/api/auth/", "/api/admin/")):
            return JSONResponse(
                {
                    "detail": [
                        {key: item[key] for key in ("loc", "msg", "type")}
                        for item in error.errors()
                    ]
                },
                status_code=422,
            )
        return await request_validation_exception_handler(request, error)

    def owner(request):
        actor = request.state.actor
        return actor["id"] if actor["role"] != "admin" else None

    def require_case(request, run_id):
        if owner(request) is not None and not service.store.can_access(run_id, owner(request)):
            raise HTTPException(404, "Investigation not found")
        run = service.store.get(run_id)
        if run is None:
            raise HTTPException(404, "Investigation not found")
        return run

    def present_run(request, run):
        if request.state.actor["role"] == "admin":
            return run
        run = deepcopy(run)
        run.pop("mode", None)
        run.pop("agent_mode", None)
        if run.get("supervisor"):
            # The Supervisor's instructions to the investigator and the reason a summary was dropped are for administrators.
            run["supervisor"] = {k: v for k, v in run["supervisor"].items() if k not in ("summary_rejected", "rejected_text")}
            if run["supervisor"].get("revision"):
                run["supervisor"]["revision"] = {k: v for k, v in run["supervisor"]["revision"].items() if k != "instructions"}
        if run.get("judge"):
            run["judge"] = {k: v for k, v in run["judge"].items() if k not in ("model", "independent")}
        run["trace"] = [
            {"stage": t["stage"], "status": t["status"], "detail": ""} for t in run.get("trace", [])
        ]
        technical = lambda text: bool(
            re.search(r"\b(?:synapt|nvidia|mcp|llm)\b", text or "", re.IGNORECASE)
        )
        for finding in run.get("findings", []):
            if re.search(
                r"Optional Synapt .*lacks supported provenance",
                finding.get("text", ""),
                re.IGNORECASE,
            ):
                finding["text"] = (
                    "Some retrieved material could not be linked to a supported source and was excluded."
                )
            else:
                finding["text"] = re.sub(
                    r"\bSynapt\b", "retrieved source", finding.get("text", ""), flags=re.IGNORECASE
                )
        if run.get("classification"):
            run["classification"].pop("method", None)
        if technical(run.get("error", "")):
            run["error"] = (
                "Investigation could not complete. An administrator can inspect Activity for technical details."
            )
        for source in run.get("evidence", []):
            source.pop("provider_id", None)
            source["text"] = "\n".join(
                line
                for line in source.get("text", "").splitlines()
                if not re.match(
                    r"^\s*(?:provider_id|source_url|attribution|provenance):", line, re.IGNORECASE
                )
            )
            if source.get("provenance") == "synapt":
                source["provenance"] = "retrieved_source"
        for comparison in run.get("similar_cases", []):
            if comparison.get("provenance") == "synapt":
                comparison["provenance"] = "retrieved_source"
        if run.get("query_agent"):
            run["query_agent"] = present_query_agent(run["query_agent"], False)
        return run

    @app.middleware("http")
    async def protect(request: Request, call_next):
        request.state.actor = {"id": "local", "username": "local", "role": "admin"}
        key = settings.claims_api_key.get_secret_value()
        path = request.url.path
        if auth and path.startswith("/api/"):
            public = path in ("/api/auth/session", "/api/auth/login", "/api/auth/setup")
            token = request.cookies.get("claims_session", "")
            actor = auth.actor(token)
            request.state.actor = actor
            if not public and actor is None:
                return JSONResponse({"detail": "Please sign in to continue."}, status_code=401)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if origin and origin != str(request.base_url).rstrip("/"):
                    return JSONResponse(
                        {"detail": "Cross-origin request rejected"}, status_code=403
                    )
                expected = (
                    preauth_csrf
                    if path in ("/api/auth/login", "/api/auth/setup")
                    else csrf_token(token)
                )
                if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), expected):
                    return JSONResponse(
                        {"detail": "Refresh the page before trying again."}, status_code=403
                    )
            user_paths = path in (
                "/api/health",
                "/api/demo-cases",
                "/api/case-suggestions",
                "/api/investigations",
                "/api/intake/extract",
                "/api/queue",
                "/api/predictions",
                "/api/auth/logout",
            ) or path.startswith("/api/investigations/")
            if (
                actor
                and actor["role"] != "admin"
                and not public
                and (not user_paths or ADMIN_SUBPATH.search(path))
            ):
                return JSONResponse({"detail": "Administrator access required"}, status_code=403)
        if (
            not auth
            and request.url.path.startswith("/api/")
            and key
            and not secrets.compare_digest(request.headers.get("X-Claims-Api-Key", ""), key)
        ):
            return JSONResponse({"detail": "API key required"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = request.url.path
            if path.startswith("/api/"):
                route = getattr(request.scope.get("route"), "path", None) or ID_SEGMENT.sub(
                    "/{id}", path
                )
                actor = getattr(request.state, "actor", None) or {}
                try:
                    service.store.add_request(
                        method=request.method,
                        route=route,
                        status=status,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        role=actor.get("role"),
                    )
                except Exception as error:  # noqa: BLE001 - metrics must never fail a request
                    logger.debug("request metric not recorded (%s)", type(error).__name__)

    @app.get("/api/auth/session")
    def session(request: Request):
        token = request.cookies.get("claims_session", "")
        actor = auth.actor(token) if auth else request.state.actor
        return {
            "user": actor,
            "setup_required": bool(auth and auth.needs_setup()),
            "csrf_token": csrf_token(token) if actor and auth else preauth_csrf,
            "auth_enabled": bool(auth),
        }

    @app.post("/api/auth/setup")
    def setup(request: Request, body: AccountRequest):
        if not auth:
            raise HTTPException(409, "Authentication is disabled")
        if request.client.host not in ("127.0.0.1", "::1"):
            raise HTTPException(403, "Initial administrator setup is available on localhost only")
        try:
            user = auth.create_user(
                body.username, body.password.get_secret_value(), "admin", first=True
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"user": user}

    @app.post("/api/auth/login")
    def login(request: Request, body: LoginRequest):
        if not auth:
            raise HTTPException(409, "Authentication is disabled")
        try:
            result = auth.login(
                body.username, body.password.get_secret_value(), request.client.host
            )
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from None
        if result is None:
            raise HTTPException(401, "Username or password is incorrect")
        token, actor = result
        response = JSONResponse({"user": actor, "csrf_token": csrf_token(token)})
        response.set_cookie(
            "claims_session",
            token,
            max_age=43200,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request):
        if auth:
            auth.logout(request.cookies.get("claims_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("claims_session", path="/")
        return response

    @app.get("/api/admin/users")
    def users():
        return {"users": auth.users() if auth else []}

    @app.post("/api/admin/users")
    def create_user(request: Request, body: AccountRequest):
        if not auth:
            raise HTTPException(409, "Authentication is disabled")
        try:
            return auth.create_user(
                body.username,
                body.password.get_secret_value(),
                body.role,
                actor_id=request.state.actor["id"],
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/")
    def index():
        built = APP_DIR / "index.html"
        return FileResponse(built if built.exists() else STATIC_DIR / "index.html")

    @app.get("/classic")
    def classic():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=APP_DIR / "assets", check_dir=False), name="assets")

    @app.get("/api/health")
    def health(request: Request):
        if request.state.actor["role"] != "admin":
            return {"status": "ok"}
        return {
            "status": "ok",
            "synapt_mode": settings.synapt_mode,
            "agent_mode": settings.agent_mode,
            "synapt_live_verified": bool(getattr(service.adapter, "live_verified", False)),
            "last_retrieval": service.last_retrieval,
            "fallback": fallback.status() if fallback else None,
            "notice": "Verification means this process retrieved source-bearing Synapt passages; it does not certify answer accuracy.",
        }

    @app.get("/api/demo-cases")
    def demos():
        return DEMO_CASES

    intake_extractor = IntakeExtractor(settings)

    @app.post("/api/intake/extract")
    def extract_intake(body: IntakeExtractRequest):
        """Suggest intake fields from free-text notes; advisory, never starts an investigation."""
        try:
            return intake_extractor.extract(body.description)
        except IntakeUnavailable as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.post("/api/investigations")
    def investigate(request: Request, body: InvestigationRequest):
        run_id = body.run_id.lower() if body.run_id else None
        if run_id and (service.progress.known(run_id) or service.store.get(run_id) is not None):
            raise HTTPException(409, "This investigation ID is already in use")
        run = service.create(body.claim, body.filters, run_id=run_id, owner=request.state.actor["id"])
        service.store.set_owner(run["run_id"], request.state.actor["id"])
        service.store.event(run["run_id"], "submitted_by", request.state.actor)
        return present_run(request, run)

    @app.get("/api/investigations/{run_id}")
    def get_run(request: Request, run_id: str):
        return present_run(request, require_case(request, run_id))

    @app.get("/api/investigations/{run_id}/preview")
    def preview_run(request: Request, run_id: str):
        """What has landed so far in an investigation that is still running: the page shows each part as it arrives."""
        return preview_of(present_run(request, require_case(request, run_id)))

    @app.get("/api/investigations/{run_id}/side-chat")
    def side_chat_history(request: Request, run_id: str):
        """The questions already asked beside this investigation, and questions worth asking about it."""
        run = require_case(request, run_id)
        admin = request.state.actor["role"] == "admin"
        return {
            "items": [view_for(item, admin) for item in side_chat.history(run_id)],
            "suggestions": suggestions(present_run(request, run)),
            "limits": {"max_question": MAX_QUESTION, "max_per_run": MAX_PER_RUN},
        }

    @app.post("/api/investigations/{run_id}/side-chat")
    def side_chat_ask(request: Request, run_id: str, body: SideChatRequest):
        """Ask a question about this claim on the side: answered from the saved run or Synapt's knowledge base, whichever
        can answer it, and kept apart from the brief (nothing here changes the investigation)."""
        run = require_case(request, run_id)
        actor = request.state.actor
        admin = actor["role"] == "admin"
        try:
            answer = side_chat.ask(present_run(request, run), body.question, owner=actor["id"])
        except SideChatError as error:
            raise HTTPException(error.status, str(error)) from None
        return view_for(answer, admin)

    @app.get("/api/investigations/{run_id}/query-feedback")
    def query_feedback_list(request: Request, run_id: str):
        """Which of this case's knowledge-base answers have been rated, and how."""
        require_case(request, run_id)
        return {"items": query_feedback.listing(service.store, run_id)}

    @app.post("/api/investigations/{run_id}/query-feedback")
    def query_feedback_send(request: Request, run_id: str, body: QueryFeedbackRequest):
        """Send a handler's verdict on a knowledge-base answer to Synapt (once per answer). Does not change the brief."""
        run = require_case(request, run_id)  # the saved run, not the role-filtered copy: it holds the query ID
        try:
            return query_feedback.submit(
                service.store, service.adapter, run, target=body.target, choice=body.choice, reason=body.reason,
                owner=request.state.actor["id"],
            )
        except FeedbackError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.get("/api/investigations/{run_id}/progress")
    def run_progress(request: Request, run_id: str, after: int = Query(0, ge=0)):
        """What an investigation is doing right now: the spans that opened or closed after `after`.

        Works while the run is in flight (the page supplied the ID) and for a while after it ends. Everyone who may
        see the run gets plain-language steps; the technical line (tool, query, model) is administrators only."""
        actor = request.state.actor
        data = service.progress.read(
            run_id.lower(), after, viewer_id=actor["id"], admin=actor["role"] == "admin"
        )
        if data is None:
            raise HTTPException(404, "No live progress for this investigation")
        return data

    @app.get("/api/agents")
    def agents(request: Request):
        """The agents of an investigation: who each is, what it is for and what it may use. Everyone gets names, purposes and
        what each can use in plain words; tool IDs, identities and role prompts are for administrators."""
        return roster.describe(admin=request.state.actor["role"] == "admin", client_id_for=settings.agent_client_id)

    @app.get("/api/agents/graph")
    def agents_graph():
        """The LangGraph graphs the agents run in, read from the compiled graphs themselves: the investigation (one node per stage)
        and the retrieve stage (four agents side by side). Mermaid text is included for pasting into a diagram tool."""
        return graph_structure(service.retrieval, service.graph, service.supervisor.graph)

    @app.get("/api/investigations/{run_id}/agents")
    def run_agents(request: Request, run_id: str):
        """One investigation read agent by agent: who worked, for how long, with how many tool calls."""
        require_case(request, run_id)
        return agent_activity.summary(service.store.spans(run_id), admin=request.state.actor["role"] == "admin")

    @app.get("/api/investigations/{run_id}/audit")
    def run_audit(
        request: Request,
        run_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
    ):
        require_case(request, run_id)
        return service.store.audit_records(run_id, offset, limit)

    @app.get("/api/investigations/{run_id}/audit/{event_id}")
    def audit_event(request: Request, run_id: str, event_id: int):
        """One audit event in full (a model prompt or answer); administrators only."""
        require_case(request, run_id)
        if request.state.actor["role"] != "admin":
            raise HTTPException(403, "Administrator access required")
        event = service.store.audit_event(run_id, event_id)
        if event is None:
            raise HTTPException(404, "Event not found")
        return event

    @app.get("/api/investigations/{run_id}/trace")
    def run_trace(request: Request, run_id: str):
        """Every recorded step of one investigation, with timings; administrators only."""
        require_case(request, run_id)
        if request.state.actor["role"] != "admin":
            raise HTTPException(403, "Administrator access required")
        trace = observatory.trace(run_id)
        if trace is None:
            raise HTTPException(404, "No trace is available for this investigation")
        return trace

    @app.get("/api/investigations/{run_id}/explanation")
    def run_explanation(request: Request, run_id: str):
        """How the brief was generated and evaluated, written for the caller's role."""
        run = require_case(request, run_id)
        admin = request.state.actor["role"] == "admin"
        return explain_run(
            run,
            observatory.trace(run_id),
            "admin" if admin else "user",
            evaluation.status() if admin else None,
        )

    @app.get("/api/traces")
    def traces(
        request: Request,
        q: str = Query("", max_length=300),
        status: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        """Saved investigations with their trace figures (duration, model calls, tokens)."""
        page = service.store.search(q=q, status=status, offset=offset, limit=limit, owner_id=None)
        ids = [item["run_id"] for item in page["items"]]
        overview = observatory.overview(ids)
        facts = service.store.run_facts(ids)
        items = []
        for item in page["items"]:
            traced = overview.get(item["run_id"])
            digest = (traced or {}).get("summary") or {}
            fact = facts.get(item["run_id"], {})
            llm = digest.get("llm") or {}
            items.append(
                item
                | {
                    "trace_source": (traced or {}).get("source"),
                    "started_at": digest.get("started_at"),
                    "duration_ms": digest.get("duration_ms"),
                    "llm_calls": llm.get("calls"),
                    "tokens": (llm.get("tokens") or {}).get("total"),
                    "errors": len(digest.get("errors") or []),
                    "origin": digest.get("origin"),
                    "mode": fact.get("mode"),
                    "agent_mode": fact.get("agent_mode"),
                    "validation_passed": None
                    if fact.get("validation_passed") is None
                    else bool(fact["validation_passed"]),
                    "judge_status": fact.get("judge_status"),
                    "judge_passed": None
                    if fact.get("judge_passed") is None
                    else bool(fact["judge_passed"]),
                    "judge_score": fact.get("judge_score"),
                }
            )
        return page | {"items": items}

    @app.get("/api/observability/summary")
    def observability_summary(
        window: str = Query("7d", pattern="^(24h|7d|30d|all)$"),
        origin: str = Query("all", pattern="^(all|user|evaluation)$"),
    ):
        """System-wide figures over a time window; administrators only (not a user path)."""
        return observatory.summary(window, origin)

    @app.get("/api/observability/evaluations")
    def observability_evaluations(limit: int = Query(20, ge=1, le=100)):
        """Recent evaluation-suite runs with their judge results; administrators only."""
        return observatory.evaluations(limit)

    @app.get("/api/investigations")
    def list_runs(
        request: Request,
        q: str = Query("", max_length=300),
        status: str = "",
        claim_type: str = "",
        state: str = Query("", max_length=2),
        date_from: date | None = None,
        date_to: date | None = None,
        min_amount: float | None = Query(None, ge=0, le=1_000_000_000),
        max_amount: float | None = Query(None, ge=0, le=1_000_000_000),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
        sort: str = Query("recent", pattern="^(recent|priority)$"),
        tier: str = Query("", pattern="^(|critical|high|medium|low)$"),
    ):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "Start date must be on or before end date")
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            raise HTTPException(422, "Minimum amount must not exceed maximum amount")
        return service.store.search(
            q=q,
            status=status,
            claim_type=claim_type,
            state=state,
            date_from=date_from.isoformat() if date_from else "",
            date_to=date_to.isoformat() if date_to else "",
            min_amount=min_amount,
            max_amount=max_amount,
            offset=offset,
            limit=limit,
            owner_id=owner(request),
            sort=sort,
            tier=tier,
        )

    @app.get("/api/queue")
    def queue(
        request: Request,
        tier: str = Query("", pattern="^(|critical|high|medium|low)$"),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        """Investigations still awaiting a handler, highest priority score first."""
        return service.store.search(
            sort="priority",
            tier=tier,
            open_only=True,
            offset=offset,
            limit=limit,
            owner_id=owner(request),
        )

    @app.get("/api/case-suggestions")
    def case_suggestions(
        request: Request, q: str = Query("", max_length=300), limit: int = Query(8, ge=1, le=20)
    ):
        return case_search.suggest(q, limit, owner_id=owner(request))

    @app.post("/api/investigations/{run_id}/review")
    def review(request: Request, run_id: str, body: ReviewDecision):
        require_case(request, run_id)
        try:
            result = service.submit_review(run_id, body)
            service.store.event(run_id, "reviewed_by", request.state.actor)
            return result
        except KeyError:
            raise HTTPException(404, "Investigation not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/investigations/{run_id}/feedback")
    def feedback(request: Request, run_id: str, body: FeedbackRequest):
        require_case(request, run_id)
        result = service.store.add_feedback(run_id, body.rating, body.note)
        service.store.event(run_id, "handler_feedback", result | body.model_dump())
        return result

    @app.get("/api/feedback/lessons")
    def lessons():
        return {
            "candidate_lessons": service.store.lessons(),
            "promotion": "An administrator promotes a reviewed lesson. Promoted lessons are cited as "
            "evidence in later investigations of the same claim type and, in live mode, ingested "
            "into the Synapt provider. Nothing is promoted automatically and no ground truth changes.",
        }

    @app.post("/api/feedback/lessons/{lesson_id}/promote")
    def promote_lesson(request: Request, lesson_id: int):
        try:
            return service.promote_lesson(lesson_id, request.state.actor["id"])
        except KeyError:
            raise HTTPException(404, "Lesson not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:  # noqa: BLE001 - never echo provider details
            raise HTTPException(
                502, "Synapt ingestion failed; the lesson was not promoted. Check Activity."
            ) from None

    @app.get("/api/models/status")
    def models_status():
        return analytics.status()

    @app.post("/api/predictions")
    def predictions(body: ClaimInput):
        return analytics.predict(body)

    @app.post("/api/search")
    def search(body: InvestigationRequest):
        try:
            with service.lock:
                context = service.retrieve_context(
                    body.claim, body.filters, with_cohort=False, with_graph=False, with_query=False
                )
        except Exception:  # noqa: BLE001 - provider errors must not disclose credentials
            raise HTTPException(
                503, "Retrieval unavailable; check Synapt integration configuration."
            ) from None
        context.pop("cohort", None)
        context.pop("graph", None)
        context.pop("query_agent", None)
        return context | {
            "semantic_case_matches": sum(
                c.get("semantic_match", False) for c in context["similar_cases"]
            ),
            "semantic": context["semantic"],
            "similar_flagged_count": sum(
                bool(c.get("dataset_fraud_flag")) for c in context["similar_cases"]
            ),
            "limitation": "Semantic ranking comes from the past claims in Synapt's ticket store and applies only to claims that were uploaded there.",
        }

    @app.post("/api/models/train")
    def train():
        try:
            with service.lock:
                report = analytics.train()
                service.retriever.reload()
                return report
        except (ValueError, FileNotFoundError):
            raise HTTPException(
                409,
                "Training data unavailable or insufficient. Run the documented dataset fetch first.",
            ) from None

    @app.get("/api/evaluations/status")
    def eval_status():
        return evaluation.status()

    @app.post("/api/evaluations/run")
    def evaluate(body: EvaluationRequest | None = None):
        judge = body.judge if body else False
        try:
            if body and body.background:
                return evaluation.start(judge)
            return evaluation.run(judge)
        except EvaluationBusy:
            raise HTTPException(
                409, "An evaluation is already running. Its progress is shown on the Quality page."
            ) from None

    @app.get("/api/integration/synapt-stats")
    def integration_synapt_stats(refresh: bool = False):
        """What the Synapt provider holds now (documents, passages, graph by kind, procedures, steps, episodes); administrators only."""
        return synapt_stats.get(refresh=refresh)

    @app.get("/api/integration/status")
    def integration():
        return {
            "mode": settings.synapt_mode,
            "provider_configured": bool(settings.synapt_provider_id),
            "credentials_configured": bool(
                settings.synapt_username and settings.synapt_password.get_secret_value()
            ),
            "live_verified": bool(getattr(service.adapter, "live_verified", False)),
            "mcp_url": settings.synapt_mcp_url,
            "auth_contract": f"Configured {settings.synapt_auth_encoding} / {settings.synapt_auth_username_field}; see docs/SYNAPT_CONTRACT.md",
            "local_history_origin": service.retriever.origin,
            "history_rows": service.retriever.store.row_count() if service.retriever.store else None,
            "judge_mode": settings.judge_mode,
            "last_retrieval": service.last_retrieval,
            "fallback": fallback.status() if fallback else None,
        }

    return app


app = create_app()
