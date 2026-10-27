"""Read-only dashboard API backed by the simulation run's JSON/JSONL artifacts."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator

from django.http import Http404, HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNS_ROOT = Path(os.environ.get("COMPETEAI_RUNS_DIR", PROJECT_ROOT / "logs")).resolve()
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PUBLIC_PROFILE_EXCLUDED_FIELDS = {
    "id", "user_id", "source_user_key", "source_customer_profile_id",
    "city", "province", "occupation", "career",
}


def _run_dir(run_id: str) -> Path:
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise Http404("Simulation run not found")
    run_dir = (RUNS_ROOT / run_id).resolve()
    if run_dir.parent != RUNS_ROOT or not run_dir.is_dir():
        raise Http404("Simulation run not found")
    return run_dir


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # A running process can be observed while it is writing the last line.
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        pass
    return records


def _load_run(run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    manifest = _read_json(run_dir / "run_manifest.json", {})
    profiles = _read_json(run_dir / "profiles_used.json", {})
    if not isinstance(manifest, dict) or not isinstance(profiles, dict):
        raise Http404("Simulation run data is unavailable")
    restaurants = profiles.get("restaurants", {})
    customers = profiles.get("customers", {})
    if not isinstance(restaurants, dict):
        restaurants = {}
    if not isinstance(customers, dict):
        customers = {}
    return {
        "run_dir": run_dir,
        "manifest": manifest,
        "profiles": profiles,
        "restaurants": restaurants,
        "customers": customers,
        "traces": _read_jsonl(run_dir / "dining_trace.jsonl"),
        "summaries": _read_jsonl(run_dir / "round_summary.jsonl"),
    }


def _restaurant_profile(run: dict[str, Any], restaurant_id: str) -> dict[str, Any]:
    profile = run["restaurants"].get(restaurant_id)
    if not isinstance(profile, dict):
        raise Http404("Restaurant not found in this simulation run")
    return profile


def _round_state(run: dict[str, Any], restaurant_id: str) -> list[dict[str, Any]]:
    states = []
    for summary in run["summaries"]:
        restaurant_states = summary.get("restaurant_state_after_round", {})
        state = restaurant_states.get(restaurant_id) if isinstance(restaurant_states, dict) else None
        if isinstance(state, dict):
            states.append({"round": summary.get("day"), **state})
    return states


def _selected_visits(
    run: dict[str, Any], restaurant_id: str, round_number: int | None = None
) -> list[dict[str, Any]]:
    visits = []
    for trace in run["traces"]:
        if trace.get("selected_restaurant") != restaurant_id:
            continue
        day = trace.get("day")
        try:
            trace_round = int(day)
        except (TypeError, ValueError):
            continue
        if round_number is not None and trace_round != round_number:
            continue
        customer_name = str(trace.get("customer") or "")
        raw_profile = trace.get("customer_portrait_snapshot")
        if not isinstance(raw_profile, dict):
            raw_profile = run["customers"].get(customer_name, {})
        if not isinstance(raw_profile, dict):
            raw_profile = {}
        profile = raw_profile.get("xhs_profile")
        if not isinstance(profile, dict):
            # Support older snapshots that stored the portrait fields at the top level.
            profile = {
                key: value
                for key, value in raw_profile.items()
                if key not in {
                    "profile_field_status", "source_profile_confidence", "profile_source",
                    "preferred_categories", "taste_keywords", "price_reference",
                    "history_review_count", "distinct_restaurants", "spice_preference",
                    "expression_directness", "expression_style", "profile_confidence",
                    "archetype", "profile_type", "embedding_cluster_id",
                    "embedding_cluster", "portrait_evidence_tier", "portrait_note",
                    "preferred_family", "family_review_distribution", "dominant_family_share",
                    "detailed_behavior_profile",
                }
            }
        profile = {
            key: value for key, value in profile.items()
            if key not in PUBLIC_PROFILE_EXCLUDED_FIELDS
        }
        review = trace.get("review")
        if not isinstance(review, dict):
            review = {}
        visits.append({
            "visit_id": f"{customer_name}-round-{trace_round}",
            "round": trace_round,
            "customer": {
                "customer_id": customer_name,
                "profile": profile,
            },
            "review": {
                "rating": review.get("score"),
                "comment": review.get("comment"),
            },
        })
    return visits


def _rating_stats(visits: list[dict[str, Any]]) -> tuple[float | None, dict[str, int]]:
    ratings = []
    distribution: dict[str, int] = {}
    for visit in visits:
        rating = visit["review"].get("rating")
        if isinstance(rating, (int, float)) and not isinstance(rating, bool):
            ratings.append(float(rating))
            key = str(rating).rstrip("0").rstrip(".") if isinstance(rating, float) else str(rating)
            distribution[key] = distribution.get(key, 0) + 1
    average = round(sum(ratings) / len(ratings), 3) if ratings else None
    return average, distribution


def _round_payload(
    run: dict[str, Any], restaurant_id: str, state: dict[str, Any],
    visits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    round_number = state.get("round")
    try:
        round_number = int(round_number)
    except (TypeError, ValueError):
        round_number = None
    if visits is None:
        visits = _selected_visits(run, restaurant_id, round_number)
    average, distribution = _rating_stats(visits)
    return {
        "round": round_number,
        "visits": len(visits),
        "review_count": sum(visit["review"].get("comment") is not None for visit in visits),
        "average_rating": average,
        "rating_distribution": distribution,
        "platform_rating_after_round": state.get("platform_rating_after_round"),
        "platform_review_count_after_round": state.get("platform_review_count_after_round"),
    }


def _json_error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@require_GET
def list_runs(request: HttpRequest) -> JsonResponse:
    runs = []
    if RUNS_ROOT.is_dir():
        for run_dir in sorted(RUNS_ROOT.iterdir(), key=lambda item: item.name, reverse=True):
            if not run_dir.is_dir() or not SAFE_RUN_ID.fullmatch(run_dir.name):
                continue
            manifest = _read_json(run_dir / "run_manifest.json", {})
            if not isinstance(manifest, dict) or not (run_dir / "profiles_used.json").is_file():
                continue
            counts = manifest.get("counts", {})
            runs.append({
                "run_id": run_dir.name,
                "status": manifest.get("status", "unknown"),
                "started_at": manifest.get("started_at_utc"),
                "completed_at": manifest.get("completed_at_utc"),
                "counts": counts if isinstance(counts, dict) else {},
            })
    return JsonResponse({"items": runs})


@require_GET
def list_restaurants(request: HttpRequest, run_id: str) -> JsonResponse:
    try:
        run = _load_run(run_id)
    except Http404:
        return _json_error("Simulation run not found", 404)
    items = []
    for restaurant_id, profile in run["restaurants"].items():
        if not isinstance(profile, dict):
            continue
        history = _round_state(run, restaurant_id)
        latest = history[-1] if history else {}
        selected_visits = _selected_visits(run, restaurant_id)
        items.append({
            "restaurant_id": restaurant_id,
            "name": profile.get("source_name") or profile.get("name") or restaurant_id,
            "category": profile.get("category"),
            "city": profile.get("city"),
            "environment": profile.get("tags") or profile.get("profile_family"),
            "average_cost_rmb": profile.get("average_cost"),
            "baseline_rating": profile.get("baseline_rating"),
            "baseline_review_count": profile.get("baseline_review_count"),
            "rating_scale": profile.get("rating_scale"),
            "current_round": latest.get("round"),
            "simulated_visit_count": len(selected_visits),
            "platform_rating": latest.get("platform_rating_after_round", profile.get("baseline_rating")),
        })
    return JsonResponse({
        "run_id": run_id,
        "status": run["manifest"].get("status", "unknown"),
        "items": items,
    })


@require_GET
def restaurant_snapshot(request: HttpRequest, run_id: str, restaurant_id: str) -> JsonResponse:
    try:
        run = _load_run(run_id)
        profile = _restaurant_profile(run, restaurant_id)
    except Http404:
        return _json_error("Simulation run or restaurant not found", 404)
    history = _round_state(run, restaurant_id)
    rounds = [_round_payload(run, restaurant_id, state) for state in history]
    latest = history[-1] if history else {}
    visits = _selected_visits(run, restaurant_id)
    latest_round_visits = _selected_visits(run, restaurant_id, int(latest["round"])) if latest.get("round") is not None else []
    latest_average, _ = _rating_stats(latest_round_visits)
    return JsonResponse({
        "run_id": run_id,
        "status": run["manifest"].get("status", "unknown"),
        "current_round": latest.get("round", 0),
        "restaurant": {
            "restaurant_id": restaurant_id,
            "source_restaurant_id": profile.get("source_profile_id"),
            "name": profile.get("source_name") or profile.get("name") or restaurant_id,
            "category": profile.get("category"),
            "city": profile.get("city"),
            "environment": profile.get("tags") or profile.get("profile_family"),
            "average_cost_rmb": profile.get("average_cost"),
            "price_tier": profile.get("price_tier"),
            "baseline_rating": profile.get("baseline_rating"),
            "baseline_review_count": profile.get("baseline_review_count"),
            "rating_scale": profile.get("rating_scale"),
        },
        "state": {
            "visits_this_round": len(latest_round_visits),
            "new_reviews_this_round": sum(v["review"].get("comment") is not None for v in latest_round_visits),
            "average_rating_this_round": latest_average,
            "platform_rating_after_round": latest.get("platform_rating_after_round", profile.get("baseline_rating")),
            "review_count_after_round": latest.get("platform_review_count_after_round", profile.get("baseline_review_count")),
            "simulated_rating_after_round": latest.get("simulated_rating_after_round"),
            "simulated_review_count_after_round": latest.get("simulated_review_count_after_round", 0),
        },
        "rating_history": rounds,
        "total_simulated_visits": len(visits),
    })


@require_GET
def round_visits(
    request: HttpRequest, run_id: str, restaurant_id: str, round_number: int
) -> JsonResponse:
    try:
        run = _load_run(run_id)
        _restaurant_profile(run, restaurant_id)
    except Http404:
        return _json_error("Simulation run or restaurant not found", 404)
    try:
        limit = min(max(int(request.GET.get("limit", "100")), 1), 500)
        offset = max(int(request.GET.get("offset", "0")), 0)
    except ValueError:
        return _json_error("limit and offset must be integers", 400)
    visits = _selected_visits(run, restaurant_id, round_number)
    return JsonResponse({
        "run_id": run_id,
        "restaurant_id": restaurant_id,
        "round": round_number,
        "total": len(visits),
        "limit": limit,
        "offset": offset,
        "items": visits[offset:offset + limit],
    })


def _event_records(run: dict[str, Any], restaurant_id: str) -> list[tuple[str, dict[str, Any]]]:
    visits_by_round: dict[int, list[dict[str, Any]]] = {}
    for visit in _selected_visits(run, restaurant_id):
        visits_by_round.setdefault(visit["round"], []).append(visit)
    completed_rounds = {}
    for state in _round_state(run, restaurant_id):
        try:
            completed_rounds[int(state["round"])] = state
        except (KeyError, TypeError, ValueError):
            continue
    records: list[tuple[str, dict[str, Any]]] = []
    for round_number in sorted(set(visits_by_round) | set(completed_rounds)):
        for visit in visits_by_round.get(round_number, []):
            records.append(("visit.completed", {"round": round_number, "visit": visit}))
        state = completed_rounds.get(round_number)
        if state is not None:
            round_summary = _round_payload(
                run,
                restaurant_id,
                {"round": round_number, **state},
                visits=visits_by_round.get(round_number, []),
            )
            records.append(("round.completed", round_summary))
    return records


@require_GET
def restaurant_events(request: HttpRequest, run_id: str, restaurant_id: str) -> StreamingHttpResponse | JsonResponse:
    try:
        initial = _load_run(run_id)
        _restaurant_profile(initial, restaurant_id)
    except Http404:
        return _json_error("Simulation run or restaurant not found", 404)
    try:
        after_seq = max(int(request.GET.get("after_seq", request.headers.get("Last-Event-ID", "0"))), 0)
    except ValueError:
        return _json_error("after_seq must be an integer", 400)

    def stream() -> Iterator[str]:
        last_seq = after_seq
        last_heartbeat = time.monotonic()
        while True:
            current = _load_run(run_id)
            events = _event_records(current, restaurant_id)
            for seq, (event_name, payload) in enumerate(events, start=1):
                if seq <= last_seq:
                    continue
                yield f"id: {seq}\nevent: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_seq = seq
                last_heartbeat = time.monotonic()
            status = current["manifest"].get("status")
            if status in {"completed", "failed", "stopped"} and last_seq >= len(events):
                break
            if time.monotonic() - last_heartbeat >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = time.monotonic()
            time.sleep(1)

    response = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
