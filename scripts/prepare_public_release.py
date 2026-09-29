"""Prepare sanitized public-release trees for GitHub and Hugging Face.

Run from the workspace root. The HMAC key is generated in memory and never saved.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import hmac
import json
import re
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public_release"
GH = OUT / "github"
HF = OUT / "huggingface"
MERGED = ROOT / "datasets" / "Dianping_Three_Source_Merged"
PORTRAITS = ROOT / "datasets" / "Dianping_Beijing_Subset" / "sampled_portrait_pool"
KEY = secrets.token_bytes(32)

PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
LANDLINE = re.compile(r"(?<!\d)(?:0\d{2,3}[- ]?)\d{7,8}(?!\d)")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
CNID = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
COUNTS = {"mobile": 0, "landline": 0, "email": 0, "cn_id": 0}


def stable_id(namespace: str, value: object) -> str:
    digest = hmac.new(KEY, f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    return f"{namespace}_{digest}"


def scrub(text: str) -> str:
    global COUNTS
    for name, pattern in (("email", EMAIL), ("mobile", PHONE), ("landline", LANDLINE), ("cn_id", CNID)):
        text, n = pattern.subn(f"[REDACTED_{name.upper()}]", text)
        COUNTS[name] += n
    return text


def clean_tree(src: Path, dst: Path) -> None:
    excluded_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "logs", ".venv", "venv", "node_modules"}
    excluded_suffixes = {".sqlite", ".sqlite3", ".db", ".log", ".pyc", ".pyo"}
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part in excluded_dirs for part in rel.parts):
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() in excluded_suffixes or path.name.lower() in {"api.txt", ".env"}:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    GH.mkdir(parents=True)
    HF.mkdir(parents=True)

    # Code release: only the current implementation and the small initial portrait pool.
    clean_tree(ROOT / "competeai", GH / "competeai")
    clean_tree(ROOT / "scripts", GH / "scripts")
    shutil.copy2(ROOT / "PROJECT_PROGRESS.md", GH / "PROJECT_PROGRESS.md")
    portrait_dir = GH / "data" / "initial_portraits"
    portrait_dir.mkdir(parents=True)
    profiles = json.loads((PORTRAITS / "customers.json").read_text(encoding="utf-8"))
    for customer in profiles:
        if customer.get("user_id") is not None:
            customer["user_id"] = stable_id("user", customer["user_id"])
    (portrait_dir / "customers.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    restaurants = json.loads((PORTRAITS / "restaurants.json").read_text(encoding="utf-8"))
    (portrait_dir / "restaurants.json").write_text(json.dumps(restaurants, ensure_ascii=False, indent=2), encoding="utf-8")
    (portrait_dir / "sampling_summary.json").write_bytes((PORTRAITS / "sampling_summary.json").read_bytes())

    github_readme = """# Dianping Restaurant Simulation\n\nA prototype for simulating restaurant choice, dining, and review participation with customer and restaurant agents. The repository contains the simulation code and a small, anonymized initial portrait pool (20 restaurant profiles and 120 customer profiles).\n\n## Data and privacy\n\nThe portrait files are derived from a merged research dataset. Customer identifiers are pseudonymized consistently within this release. Raw review text and raw source datasets are not included here. Restaurant identifiers are retained where needed for joins. See [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md) for the current project status and [data/initial_portraits](data/initial_portraits) for the profiles.\n\n## Upstream code\n\nThe simulation builds on Microsoft's CompeteAI. See the included upstream license and preserve its attribution.\n"""
    (GH / "README.md").write_text(github_readme, encoding="utf-8")

    # Hugging Face release: pseudonymous customer/review identifiers and contact scrubbing.
    for filename in ("restaurants.jsonl.gz", "restaurant_mapping.jsonl.gz"):
        shutil.copy2(MERGED / filename, HF / filename)
    shutil.copy2(MERGED / "merge_statistics.json", HF / "merge_statistics.json")
    input_reviews = MERGED / "reviews.jsonl.gz"
    with gzip.open(input_reviews, "rt", encoding="utf-8", errors="replace") as inp, gzip.open(HF / "reviews.jsonl.gz", "wt", encoding="utf-8", newline="\n", compresslevel=6) as out:
        for i, line in enumerate(inp):
            row = json.loads(line)
            if row.get("user_id") is not None:
                row["user_id"] = stable_id("user", row["user_id"])
            rid = row.get("review_id")
            row["review_id"] = stable_id("review", rid if rid is not None else f"missing-row-{i}")
            for field in ("content", "segmented_content"):
                if isinstance(row.get(field), str):
                    row[field] = scrub(row[field])
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Keep provenance and make the transforms auditable without publishing the key or ID map.
    summary = {
        "source": "Dianping_Three_Source_Merged local research dataset",
        "privacy_transform": "Customer and review identifiers replaced by release-specific HMAC pseudonyms; missing review IDs synthesized; contact-like strings redacted from review text.",
        "redaction_counts": COUNTS,
        "identifier_key_or_mapping_published": False,
    }
    (HF / "public_release_transform.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (HF / "README.md").write_text("""---\ntask_categories:\n- text-classification\nlanguage:\n- zh\nsize_categories:\n- 1M<n<10M\n---\n\n# Dianping Three-Source Merged Restaurant Reviews\n\nThis dataset combines the local three-source merged Dianping research corpus. It contains restaurant records, review records, a restaurant crosswalk, and merge statistics. See the source project documentation for detailed field descriptions and merge provenance.\n\n## Release privacy processing\n\nCustomer and review IDs have been replaced with release-specific pseudonymous identifiers, preserving joins within this release. Missing review IDs were synthesized. Review text was scanned for email addresses, mainland China mobile and landline phone patterns, and 18-character Chinese ID-number patterns; matches were replaced with redaction markers. The pseudonymization key and any mapping are not included. Restaurant IDs remain to support analysis and joins. See `public_release_transform.json` for transformation counts.\n\n## Sources and use\n\nThis is a research-oriented merged dataset derived from the Stanford Dianping corpus, the PKU Guangzhou restaurant review data, and a Yongfeng high-confidence restaurant subset. Consult the source-specific documentation and terms before redistribution or downstream use; this dataset card does not grant additional rights over source material.\n""", encoding="utf-8")
    print(json.dumps({"github_files": sum(1 for p in GH.rglob("*") if p.is_file()), "hf_files": [(p.name, p.stat().st_size) for p in HF.iterdir() if p.is_file()], "redactions": COUNTS}, ensure_ascii=False))


if __name__ == "__main__":
    main()
