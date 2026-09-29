"""Run a reproducible 20-restaurant / 120-customer portrait-pool simulation."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "competeai"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
POOL = ROOT / "datasets" / "Dianping_Beijing_Subset" / "sampled_portrait_pool"
BASE_PORT = 9310
ROUNDS = 5


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def free_port(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def customer_profile(customer: dict) -> dict:
    detail = dict(customer.get("detailed_behavior_profile") or {})
    detail.pop("user_id", None)
    top_categories = [
        item.get("category")
        for item in detail.get("top_restaurant_categories", [])
        if isinstance(item, dict) and item.get("category")
    ]
    if not top_categories and customer.get("observed_top_family"):
        top_categories = [customer["observed_top_family"]]
    if not top_categories and customer.get("preferred_family"):
        top_categories = [customer["preferred_family"]]

    spend = detail.get("spend_profile") or {}
    rating = detail.get("rating_profile") or {}
    spend_reference = customer.get("median_spend_rmb")
    if spend_reference is None:
        spend_reference = spend.get("typical_per_review_spend_median_rmb")

    family = str(customer.get("preferred_family") or customer.get("observed_top_family") or "")
    spice = "high" if any(term in family for term in ("火锅", "麻辣")) else "medium"
    rating_style = str(rating.get("rating_style", ""))
    directness = 0.8 if "严苛" in rating_style else 0.35 if "宽容" in rating_style else 0.55
    evidence = customer.get("portrait_evidence_tier") or detail.get("evidence_tier")

    return {
        "preferred_categories": top_categories[:5],
        "taste_keywords": list(dict.fromkeys(
            [family] if family else []
        )),
        "price_reference": spend_reference,
        "price_basis": "historical_personal_median" if spend_reference is not None else "unavailable",
        "history_review_count": int(customer.get("history_count", 0) or 0),
        "distinct_restaurants": int(customer.get("distinct_restaurants", 0) or 0),
        "spice_preference": spice,
        "expression_directness": directness,
        "expression_style": "直接、符合个人评分习惯" if directness >= 0.7 else "自然、克制但不刻意客气",
        "profile_confidence": customer.get("portrait_confidence") or evidence,
        "archetype": customer.get("archetype"),
        "profile_type": customer.get("profile_type"),
        "embedding_cluster_id": customer.get("embedding_cluster_id"),
        "embedding_cluster": customer.get("embedding_cluster"),
        "portrait_evidence_tier": evidence,
        "portrait_note": customer.get("portrait_note"),
        "preferred_family": customer.get("preferred_family") or customer.get("observed_top_family"),
        "family_review_distribution": customer.get("family_review_distribution", {}),
        "dominant_family_share": customer.get("dominant_family_share"),
        "detailed_behavior_profile": detail,
    }


def build_inputs(run_dir: Path):
    restaurants = read_json(POOL / "restaurants.json")
    customers = read_json(POOL / "customers.json")
    if len(restaurants) != 20 or len(customers) != 120:
        raise ValueError(f"Expected 20 restaurants and 120 customers, got {len(restaurants)} and {len(customers)}")

    restaurant_profiles = {}
    restaurant_names = []
    for index, restaurant in enumerate(restaurants, 1):
        name = f"Restaurant-{index:02d}"
        restaurant_names.append(name)
        restaurant_profiles[name] = {
            "source_profile_id": str(restaurant.get("restaurant_id", "")),
            "category": restaurant.get("category"),
            "profile_family": restaurant.get("profile_family"),
            "city": "北京",
            "average_cost": restaurant.get("average_cost_rmb"),
            "baseline_review_count": int(restaurant.get("review_count", 0) or 0),
            "baseline_rating": float(restaurant.get("mean_rating", 0) or 0) * 2,
            "negative_review_share": restaurant.get("negative_review_share"),
            "price_tier": restaurant.get("price_tier"),
        }

    customer_preferences = {}
    source_customer_ids = {}
    customer_names = []
    for index, customer in enumerate(customers, 1):
        name = f"Customer-{index:03d}"
        customer_names.append(name)
        customer_preferences[name] = customer_profile(customer)
        source_customer_ids[name] = str(customer.get("user_id", ""))

    profiles_path = run_dir / "profiles_used.json"
    write_json(profiles_path, {
        "source_dataset": "Dianping_Beijing_Subset/sampled_portrait_pool",
        "restaurants": restaurant_profiles,
        "customers": customer_preferences,
        "trace_only_source_customer_ids": source_customer_ids,
    })

    backend = {
        "temperature": 0.7,
        "max_tokens": 1024,
        "model": "gpt-4o-2024-08-06",
        "backend_type": "openai-chat",
    }
    config = {
        "backends": {
            "default_backend": backend,
        },
        "global_prompt": {
            "boss": "You operate a fictional restaurant in a research simulation. Use prior simulated results to adapt your restaurant.",
            "customer": (
                "You are an independent simulated customer. The simulation chooses your restaurant with a fixed probability rule. "
                "Follow that choice, order dishes, and describe only your own simulated visit. Do not assume unsupported demographics."
            ),
        },
        "database_port_base": BASE_PORT,
        "max_days": ROUNDS,
        "profile_file": str(profiles_path.resolve()),
        "choice_model": {
            "seed": 2026,
            "epsilon": 0.05,
            "exploration_floor": 0.20,
            "recommendation_strength": 1.0,
            "preference_strength": 0.5,
            "repeat_penalty": 0.8,
            "price_penalty": 0.5,
            "recommendation_weights": {"review_count": 0.35, "recent_diners": 0.35, "rating": 0.30},
            "trace_customer_sources": source_customer_ids,
        },
        "players": [],
        "scenes": [
            {"name": "restaurant_design", "scene_type": "restaurant_design", "players": restaurant_names},
            {"name": "dine", "scene_type": "dine", "players": customer_names},
        ],
    }
    for name in restaurant_names:
        config["players"].append({
            "name": name,
            "agent_type": "boss",
            "role_desc": (
                "You manage a fictional simulated restaurant. Preserve the broad cuisine and price positioning from its anonymized starting profile. "
                "Do not claim this is the original source business."
            ),
            "backend": dict(backend),
        })
    for name in customer_names:
        config["players"].append({
            "name": name,
            "agent_type": "customer",
            "role_desc": (
                "You are a simulated customer. Follow your review-derived taste, spending, and rating profile. "
                "Do not invent age, income, gender, or other unsupported demographics."
            ),
            "backend": dict(backend),
        })
    config_path = run_dir / "simulation.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return profiles_path, config_path, restaurant_names, customer_names


def main():
    if not PYTHON.exists():
        raise FileNotFoundError("Project virtual environment is missing")
    key_path = ROOT / "api.txt"
    if not key_path.exists() or not key_path.read_text(encoding="utf-8-sig").strip():
        raise FileNotFoundError("api.txt is missing or empty; no model key was loaded")
    key = key_path.read_text(encoding="utf-8-sig").strip()

    run_name = "portrait_pool_5rounds_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PROJECT / "logs" / run_name
    database_dir = run_dir / "databases"
    database_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "fig").mkdir()
    logs_dir = PROJECT / "logs"

    ports = list(range(BASE_PORT, BASE_PORT + 20))
    occupied = [port for port in ports if not free_port(port)]
    if occupied:
        raise RuntimeError(f"Simulation port range is occupied: {occupied}")

    profiles_path, config_path, restaurant_names, customer_names = build_inputs(run_dir)
    input_restaurants = POOL / "restaurants.json"
    input_customers = POOL / "customers.json"
    manifest = {
        "schema_version": 1,
        "run_name": run_name,
        "status": "starting",
        "started_at_utc": utc_now(),
        "source_files": {
            "restaurants.json": str(input_restaurants.relative_to(ROOT)),
            "customers.json": str(input_customers.relative_to(ROOT)),
        },
        "source_sha256": {
            "restaurants.json": sha256(input_restaurants),
            "customers.json": sha256(input_customers),
        },
        "counts": {"restaurants": len(restaurant_names), "customers": len(customer_names), "rounds": ROUNDS},
        "database_ports": ports,
        "profile_snapshot": str(profiles_path.relative_to(PROJECT)),
        "config_snapshot": str(config_path.relative_to(PROJECT)),
    }
    manifest_path = run_dir / "run_manifest.json"
    write_json(manifest_path, manifest)

    base_env = os.environ.copy()
    base_env["OPENAI_KEY"] = key
    base_env["OPENAI_BASE_URL"] = "https://api.ai-gaochao.cn/v1"
    base_env["PYTHONIOENCODING"] = "utf-8"
    key = ""  # avoid keeping an unnecessary second reference to the secret

    def migrate(index_port):
        index, port = index_port
        database_path = database_dir / f"restaurant_{index:02d}.sqlite3"
        env = base_env.copy()
        env["COMPETEAI_DB_PATH"] = str(database_path)
        log_path = run_dir / f"migrate_{index:02d}.log"
        with log_path.open("w", encoding="utf-8") as output:
            result = subprocess.run(
                [str(PYTHON), "manage.py", "migrate", "--noinput", "--settings=restaurant_sys.settings.portrait_pool"],
                cwd=PROJECT / "database" / "restaurant_sys",
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(f"Database migration failed; see {log_path}")
        return index, port, database_path

    processes = []
    server_logs = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            migrated = list(executor.map(migrate, enumerate(ports, 1)))

        for index, port, database_path in migrated:
            env = base_env.copy()
            env["COMPETEAI_DB_PATH"] = str(database_path)
            log_file = (run_dir / f"database_{index:02d}.log").open("w", encoding="utf-8")
            server_logs.append(log_file)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                [str(PYTHON), "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload", "--settings=restaurant_sys.settings.portrait_pool"],
                cwd=PROJECT / "database" / "restaurant_sys",
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            processes.append(process)

        deadline = time.time() + 60
        pending = set(ports)
        while pending and time.time() < deadline:
            for port in list(pending):
                try:
                    response = requests.get(f"http://127.0.0.1:{port}/show/", timeout=1)
                    if response.status_code == 200:
                        pending.remove(port)
                except requests.RequestException:
                    pass
            if pending:
                time.sleep(0.5)
        if pending:
            raise RuntimeError(f"Restaurant services did not become ready on ports: {sorted(pending)}")

        manifest["status"] = "running"
        manifest["services_ready_at_utc"] = utc_now()
        write_json(manifest_path, manifest)
        simulation_log_path = run_dir / "simulation.log"
        with simulation_log_path.open("w", encoding="utf-8") as output:
            result = subprocess.run(
                [str(PYTHON), "run.py", run_name, "--config", str(config_path.resolve())],
                cwd=PROJECT,
                env=base_env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(f"Simulation exited with code {result.returncode}; see {simulation_log_path}")

        trace_path = run_dir / "dining_trace.jsonl"
        summary_path = run_dir / "round_summary.jsonl"
        traces = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        summaries = [json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(summaries) != ROUNDS:
            raise RuntimeError(f"Expected {ROUNDS} round summaries; found {len(summaries)}")
        expected_records = len(customer_names) * ROUNDS
        if len(traces) != expected_records:
            raise RuntimeError(f"Expected {expected_records} dining trace records; found {len(traces)}")
        required = {
            "source_customer_profile_id", "source_restaurant_profile_id", "choice_trace",
            "choice_state_before", "choice_state_after", "customer_profile_signals",
            "customer_portrait_snapshot", "candidate_restaurant_state", "selected_dishes", "experience", "review",
            "model_outputs", "process_attempts", "review_persisted",
        }
        incomplete = [
            (record.get("day"), record.get("customer"), sorted(required - record.keys()))
            for record in traces if required - record.keys()
        ]
        if incomplete:
            raise RuntimeError(f"Incomplete trace records detected: {incomplete[:3]}")

        report = {
            "run_name": run_name,
            "rounds": ROUNDS,
            "restaurant_count": len(restaurant_names),
            "customer_agent_count": len(customer_names),
            "trace_record_count": len(traces),
            "rounds_recorded": [item.get("day") for item in summaries],
            "completed_visits_by_round": {str(item.get("day")): item.get("completed_visits") for item in summaries},
            "restaurant_review_counts_after_round_5": {
                name: state.get("platform_review_count_after_round")
                for name, state in summaries[-1]["restaurant_state_after_round"].items()
            },
            "trace_validation": "passed",
            "trace_file": str(trace_path.relative_to(PROJECT)),
            "round_summary_file": str(summary_path.relative_to(PROJECT)),
        }
        write_json(run_dir / "run_report.json", report)
        manifest["status"] = "completed"
        manifest["completed_at_utc"] = utc_now()
        manifest["trace_record_count"] = len(traces)
        write_json(manifest_path, manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as error:
        manifest["status"] = "failed"
        manifest["failed_at_utc"] = utc_now()
        manifest["failure"] = str(error)
        write_json(manifest_path, manifest)
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log_file in server_logs:
            log_file.close()


if __name__ == "__main__":
    main()
