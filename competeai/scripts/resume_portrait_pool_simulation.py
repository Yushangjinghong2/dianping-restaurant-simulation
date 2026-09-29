"""Resume five portrait-pool rounds from already-generated restaurant menus."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
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
BASE_PORT = 9330
ROUNDS = 5
DESIGN_STEPS = ["plan", "basic_info", "menu", "chef", "ads", "summary"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def free_port(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def split_messages(text: str):
    parts = re.split(r"\n\n(?=\[[^\]\r\n]+->)", text)
    messages = []
    for part in parts:
        match = re.match(r"^\[([^\]]+)->([^\]]+)\]:\s?", part)
        if match:
            messages.append({
                "sender": match.group(1),
                "recipient": match.group(2),
                "content": part[match.end():].strip(),
            })
    return messages


def parse_json_if_possible(content: str):
    start_candidates = [index for index in (content.find("{"), content.find("[")) if index >= 0]
    if not start_candidates:
        return None
    try:
        return json.loads(content[min(start_candidates):])
    except (json.JSONDecodeError, TypeError):
        return None


class ReplayBackend:
    """Return saved model responses in order, without making another API call."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.position = 0

    def query(self, agent_name, *args, **kwargs):
        if self.position >= len(self.outputs):
            raise RuntimeError(f"Saved response sequence exhausted for {agent_name}")
        response = self.outputs[self.position]
        self.position += 1
        return response


def load_replay_outputs(source_run: Path, customer_names: list[str]):
    results = {}
    for index, name in enumerate(customer_names):
        message_path = source_run / f"dine_{index}"
        if not message_path.exists():
            raise FileNotFoundError(f"Saved customer transcript is missing: {message_path}")
        messages = split_messages(message_path.read_text(encoding="utf-8", errors="replace"))
        responses = [
            message["content"]
            for message in messages
            if message["sender"] == name and message["recipient"] == "all"
        ]
        if len(responses) not in (2, 3):
            raise RuntimeError(f"Expected two model outputs and at most one retry for {name}, found {len(responses)}")
        results[name] = responses
    return results


def recover_initialization_trace(source_run: Path, run_dir: Path, profiles: dict, ports: list[int]):
    simulation_log = (source_run / "simulation.log").read_text(encoding="utf-8", errors="replace")
    retry_records = {}
    retry_pattern = re.compile(
        r"Attempt (\d+) failed with error: Send data to database: (\w+) (\d+) error: ([^\r\n]+)"
    )
    for attempt, process, port, error in retry_pattern.findall(simulation_log):
        retry_records.setdefault((int(port), process), []).append({
            "attempt": int(attempt),
            "status": "retry",
            "error": error,
            "raw_output": None,
            "raw_output_unavailable_in_original_run": True,
        })

    profile_rows = profiles["restaurants"]
    trace_path = run_dir / "restaurant_design_trace.jsonl"
    with trace_path.open("w", encoding="utf-8") as output:
        for index, port in enumerate(ports, 1):
            name = f"Restaurant-{index:02d}"
            message_path = source_run / f"restaurant_design_{port - 20}" / "message"
            if not message_path.exists():
                raise FileNotFoundError(f"Initialization transcript is missing: {message_path}")
            messages = split_messages(message_path.read_text(encoding="utf-8", errors="replace"))
            system_prompts = [m["content"] for m in messages if m["sender"] == "System"]
            model_responses = [m["content"] for m in messages if m["sender"] == name]
            if len(model_responses) != len(DESIGN_STEPS):
                raise RuntimeError(f"Expected six initialization outputs for {name}, found {len(model_responses)}")

            outputs = {}
            attempts = {}
            for step_name, prompt, raw in zip(DESIGN_STEPS, system_prompts, model_responses):
                outputs[step_name] = {
                    "prompt": prompt,
                    "raw": raw,
                    "parsed": parse_json_if_possible(raw),
                    "capture_source": "message_pool_transcript",
                }
                attempts[step_name] = retry_records.get((port - 20, step_name), []) + [{
                    "attempt": len(retry_records.get((port - 20, step_name), [])) + 1,
                    "status": "accepted",
                    "raw_output": raw,
                }]

            state = requests.get(f"http://127.0.0.1:{port}/show/", timeout=5).json()
            profile = profile_rows[name]
            record = {
                "schema_version": 2,
                "day": 1,
                "restaurant": name,
                "simulation_restaurant_instance_id": str(port),
                "source_restaurant_profile_id": profile.get("source_profile_id"),
                "starting_profile": {
                    key: profile.get(key)
                    for key in (
                        "category", "profile_family", "city", "average_cost",
                        "baseline_review_count", "baseline_rating", "price_tier",
                    )
                },
                "database_state_after_round": state,
                "model_outputs": outputs,
                "process_attempts": attempts,
                "recovered_from_prior_run": True,
                "capture_note": "Accepted prompts and outputs reconstructed from saved message logs. Failed-attempt raw output was not recorded by the original framework.",
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_group(scenes, data):
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(scene.run, data) for scene in scenes]
        return [future.result() for future in futures]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", required=True, help="Failed run with the completed restaurant setup")
    parser.add_argument("--replay-first-round-from", help="Use saved customer outputs to replay round 1 without API calls")
    args = parser.parse_args()
    source_run = Path(args.source_run).resolve()
    allowed_root = (PROJECT / "logs").resolve()
    if allowed_root not in source_run.parents or not source_run.is_dir():
        raise ValueError("--source-run must identify an existing run directory under competeai/logs")

    key_path = ROOT / "api.txt"
    if not key_path.exists():
        raise FileNotFoundError("api.txt is missing; no model key was loaded")
    key = key_path.read_text(encoding="utf-8-sig").strip()
    if not key:
        raise ValueError("api.txt is empty; no model key was loaded")

    run_name = "portrait_pool_5rounds_resumed_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PROJECT / "logs" / run_name
    database_dir = run_dir / "databases"
    database_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "fig").mkdir()
    for index in range(1, 21):
        source_db = source_run / "databases" / f"restaurant_{index:02d}.sqlite3"
        if not source_db.exists():
            raise FileNotFoundError(f"Saved restaurant database is missing: {source_db}")
        shutil.copy2(source_db, database_dir / source_db.name)
    shutil.copy2(source_run / "profiles_used.json", run_dir / "profiles_used.json")
    profiles = read_json(run_dir / "profiles_used.json")
    config = yaml.safe_load((source_run / "simulation.yaml").read_text(encoding="utf-8"))
    config["exp_name"] = run_name
    config["database_port_base"] = BASE_PORT
    config["max_days"] = ROUNDS
    config["profile_file"] = str((run_dir / "profiles_used.json").resolve())
    config["relationship"] = yaml.safe_load((PROJECT / "competeai" / "relationship.yaml").read_text(encoding="utf-8"))
    config_path = run_dir / "simulation.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    ports = list(range(BASE_PORT, BASE_PORT + 20))
    occupied = [port for port in ports if not free_port(port)]
    if occupied:
        raise RuntimeError(f"Simulation port range is occupied: {occupied}")

    manifest = {
        "schema_version": 1,
        "run_name": run_name,
        "status": "starting",
        "started_at_utc": utc_now(),
        "resumed_from_run": str(source_run.relative_to(PROJECT)),
        "reused_restaurant_setup": True,
        "counts": {"restaurants": 20, "customers": 120, "rounds": ROUNDS},
        "database_ports": ports,
        "scope": "Round 1 uses the saved restaurant setup; rounds 2-5 run the original restaurant-design and dine stages.",
        "first_round_replay_from": args.replay_first_round_from,
    }
    manifest_path = run_dir / "run_manifest.json"
    write_json(manifest_path, manifest)

    env = os.environ.copy()
    env["OPENAI_KEY"] = key
    env["OPENAI_BASE_URL"] = "https://api.ai-gaochao.cn/v1"
    env["PYTHONIOENCODING"] = "utf-8"
    os.environ["OPENAI_KEY"] = key
    os.environ["OPENAI_BASE_URL"] = env["OPENAI_BASE_URL"]
    key = ""

    processes = []
    log_files = []
    try:
        for index, port in enumerate(ports, 1):
            process_env = env.copy()
            process_env["COMPETEAI_DB_PATH"] = str(database_dir / f"restaurant_{index:02d}.sqlite3")
            log_file = (run_dir / f"database_{index:02d}.log").open("w", encoding="utf-8")
            log_files.append(log_file)
            process = subprocess.Popen(
                [str(PYTHON), "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload", "--settings=restaurant_sys.settings.portrait_pool"],
                cwd=PROJECT / "database" / "restaurant_sys",
                env=process_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            processes.append(process)

        deadline = time.time() + 60
        pending = set(ports)
        while pending and time.time() < deadline:
            for port in list(pending):
                try:
                    response = requests.get(f"http://127.0.0.1:{port}/show/", timeout=1)
                    if response.status_code == 200 and response.json().get("name"):
                        pending.remove(port)
                except requests.RequestException:
                    pass
            if pending:
                time.sleep(0.5)
        if pending:
            raise RuntimeError(f"Restaurant services did not become ready: {sorted(pending)}")

        initialization_trace = source_run / "restaurant_design_trace.jsonl"
        if initialization_trace.exists():
            shutil.copy2(initialization_trace, run_dir / "restaurant_design_trace.jsonl")
            recovered = [
                json.loads(line)
                for line in (run_dir / "restaurant_design_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for index, record in enumerate(recovered):
                record["initialization_source_instance_id"] = record.get("simulation_restaurant_instance_id")
                record["simulation_restaurant_instance_id"] = str(BASE_PORT + index)
                record["reused_restaurant_setup"] = True
            with (run_dir / "restaurant_design_trace.jsonl").open("w", encoding="utf-8") as output:
                for record in recovered:
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            recover_initialization_trace(source_run, run_dir, profiles, ports)
        manifest["status"] = "running"
        manifest["services_ready_at_utc"] = utc_now()
        write_json(manifest_path, manifest)

        # Import after setting OPENAI_KEY because the backend checks it at import time.
        sys.path.insert(0, str(PROJECT))
        from competeai.globals import NAME2PORT, PORT2NAME
        from competeai.scene.restaurant_design import RestaurantDesign
        from competeai.simul import Simulation

        simulation = Simulation.from_config(config)
        design_scenes, dine_scenes = simulation.scenes
        for restaurant_name, port in NAME2PORT.items():
            PORT2NAME[port] = restaurant_name
        for scene in design_scenes:
            scene.day = 1  # first design stage uses the completed first-round daybook

        previous_data = RestaurantDesign.action_for_next_scene(None)
        if args.replay_first_round_from:
            replay_source = Path(args.replay_first_round_from).resolve()
            if allowed_root not in replay_source.parents or not replay_source.is_dir():
                raise ValueError("--replay-first-round-from must identify a run directory under competeai/logs")
            customer_names = [scene.players[0].name for scene in dine_scenes]
            saved_outputs = load_replay_outputs(replay_source, customer_names)
            original_backends = {}
            for scene in dine_scenes:
                player = scene.players[0]
                original_backends[player.name] = player.backend
                player.backend = ReplayBackend(saved_outputs[player.name])
            try:
                round1_results = run_group(dine_scenes, previous_data)
            finally:
                for scene in dine_scenes:
                    player = scene.players[0]
                    player.backend = original_backends[player.name]
        else:
            round1_results = run_group(dine_scenes, previous_data)
        dine_scenes[0].action_for_next_scene(round1_results)

        for round_number in range(2, ROUNDS + 1):
            run_group(design_scenes, None)
            previous_data = RestaurantDesign.action_for_next_scene(None)
            round_results = run_group(dine_scenes, previous_data)
            dine_scenes[0].action_for_next_scene(round_results)

        trace_path = run_dir / "dining_trace.jsonl"
        summary_path = run_dir / "round_summary.jsonl"
        design_trace_path = run_dir / "restaurant_design_trace.jsonl"
        traces = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        summaries = [json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        design_traces = [json.loads(line) for line in design_trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(traces) != 600 or len(summaries) != ROUNDS or len(design_traces) != 100:
            raise RuntimeError(
                f"Trace count mismatch: dining={len(traces)}, summaries={len(summaries)}, restaurant_design={len(design_traces)}"
            )
        report = {
            "run_name": run_name,
            "rounds": ROUNDS,
            "restaurant_count": 20,
            "customer_agent_count": 120,
            "trace_record_count": len(traces),
            "restaurant_design_trace_count": len(design_traces),
            "rounds_recorded": [item.get("day") for item in summaries],
            "completed_visits_by_round": {str(item.get("day")): item.get("completed_visits") for item in summaries},
            "restaurant_review_counts_after_round_5": {
                name: state.get("platform_review_count_after_round")
                for name, state in summaries[-1]["restaurant_state_after_round"].items()
            },
            "trace_validation": "passed",
            "trace_file": str(trace_path.relative_to(PROJECT)),
            "restaurant_design_trace_file": str(design_trace_path.relative_to(PROJECT)),
            "round_summary_file": str(summary_path.relative_to(PROJECT)),
            "initialization_trace_recovered_from": str((source_run / "restaurant_design_trace.jsonl").relative_to(PROJECT)),
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
        for log_file in log_files:
            log_file.close()


if __name__ == "__main__":
    main()
