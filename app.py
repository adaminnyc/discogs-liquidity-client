import os
import time
import math
import csv
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv

# -----------------------------
# Load .env
# -----------------------------
load_dotenv()

# -----------------------------
# Config
# -----------------------------
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
if not DISCOGS_TOKEN:
    raise RuntimeError("Missing DISCOGS_TOKEN. Create a .env file with DISCOGS_TOKEN=your_token_here")

USER_AGENT = "AdamRecordValuer/1.0 (contact: users@gmail.com)"
CURRENCY = "USD"
BASE = "https://api.discogs.com"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
}

session = requests.Session()
session.headers.update(HEADERS)

# -----------------------------
# Rate limiting (<= 60 req/min)
# -----------------------------
MIN_SECONDS_PER_REQUEST = 1.05  # ~57 req/min buffer under 60
_last_request_ts = 0.0


def _rate_limit_sleep():
    global _last_request_ts
    now = time.time()
    elapsed = now - _last_request_ts
    if elapsed < MIN_SECONDS_PER_REQUEST:
        time.sleep(MIN_SECONDS_PER_REQUEST - elapsed)
    _last_request_ts = time.time()


# -----------------------------
# Simple JSON cache (Option A)
# -----------------------------
DEFAULT_CACHE_PATH = "discogs_cache.json"
DEFAULT_MARKETPLACE_TTL = 24 * 60 * 60          # 24 hours
DEFAULT_RELEASE_DETAILS_TTL = 14 * 24 * 60 * 60 # 14 days


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def load_cache(cache_path: str) -> dict:
    if not os.path.exists(cache_path):
        return {"version": 1, "updated_at": _utc_now_iso(), "releases": {}}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Cache root is not a dict")
        data.setdefault("version", 1)
        data.setdefault("updated_at", _utc_now_iso())
        data.setdefault("releases", {})
        if not isinstance(data["releases"], dict):
            data["releases"] = {}
        return data
    except Exception:
        return {"version": 1, "updated_at": _utc_now_iso(), "releases": {}}


def save_cache(cache_path: str, cache: dict) -> None:
    cache["updated_at"] = _utc_now_iso()
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, cache_path)


def cache_get_release(cache: dict, release_id: int) -> dict:
    return cache["releases"].get(str(release_id), {})


def cache_put_release(cache: dict, release_id: int, entry: dict) -> None:
    cache["releases"][str(release_id)] = entry


def is_fresh(entry: dict, field: str, ttl_seconds: int) -> bool:
    meta = entry.get(field, {})
    fetched_at = meta.get("fetched_at")
    if not fetched_at:
        return False
    age = time.time() - _parse_iso(fetched_at)
    return age >= 0 and age < ttl_seconds


def today_mmddyyyy() -> str:
    return datetime.now().strftime("%m%d%Y")


# -----------------------------
# HTTP helper
# -----------------------------
def get_json(url, params=None, retries=5, allow_404=False):
    last_status = None
    last_text = None

    for attempt in range(1, retries + 1):
        try:
            _rate_limit_sleep()

            r = session.get(url, params=params, timeout=30)
            last_status = r.status_code
            last_text = r.text[:300]

            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "60"))
                time.sleep(wait)
                continue

            if allow_404 and r.status_code == 404:
                return None

            if r.status_code in (500, 502, 503, 504):
                time.sleep(1.0 * attempt)
                continue

            r.raise_for_status()
            return r.json()

        except requests.exceptions.RequestException as e:
            last_text = str(e)
            time.sleep(1.0 * attempt)

    raise RuntimeError(f"Failed after retries: {url} (last_status={last_status}, last_response={last_text})")


def safe_num(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


# -----------------------------
# Discogs fetchers (collection + enrichment)
# -----------------------------
def fetch_collection_folders(username: str) -> Dict[str, int]:
    data = get_json(f"{BASE}/users/{username}/collection/folders")
    folders = data.get("folders", []) if data else []
    mapping: Dict[str, int] = {}
    for f in folders:
        name = (f.get("name") or "").strip()
        fid = f.get("id")
        if name and isinstance(fid, int):
            mapping[name.lower()] = fid
    return mapping


def fetch_folder_releases(username: str, folder_id: int, per_page: int = 100) -> List[dict]:
    page = 1
    out: List[dict] = []
    while True:
        data = get_json(
            f"{BASE}/users/{username}/collection/folders/{folder_id}/releases",
            params={"page": page, "per_page": per_page},
            allow_404=True,
        )
        if not data:
            break
        releases = data.get("releases", []) or []
        out.extend(releases)

        pagination = data.get("pagination", {}) or {}
        pages = pagination.get("pages")
        if not pages or page >= pages:
            break
        page += 1
    return out


def collection_to_dataframe(username: str, category: str) -> pd.DataFrame:
    folders = fetch_collection_folders(username)
    if not folders:
        raise RuntimeError(f"No folders found (user may not exist or collection may be private): {username}")

    category_norm = category.lower().strip()
    items: List[dict] = []

    if category_norm == "all":
        folder_ids: List[Tuple[str, int]] = []
        for name_lower, fid in folders.items():
            if fid == 0:
                continue
            folder_ids.append((name_lower, fid))

        if not folder_ids:
            raise RuntimeError(f"No public folders found for user: {username}")

        for name_lower, fid in sorted(folder_ids, key=lambda x: x[0]):
            rels = fetch_folder_releases(username, fid)
            for r in rels:
                r["_collection_folder_name"] = name_lower
            items.extend(rels)

    else:
        if category_norm not in folders:
            available = ", ".join(sorted(folders.keys()))
            raise RuntimeError(
                f"Folder '{category}' not found for user '{username}'. "
                f"Available (public) folders: {available}"
            )
        fid = folders[category_norm]
        rels = fetch_folder_releases(username, fid)
        for r in rels:
            r["_collection_folder_name"] = category_norm
        items = rels

    rows = []
    for it in items:
        bi = it.get("basic_information") or {}
        artists = bi.get("artists") or []
        artist_name = artists[0].get("name") if artists else None

        labels = bi.get("labels") or []
        label_name = labels[0].get("name") if labels else None

        formats = bi.get("formats") or []
        format_str = None
        if formats:
            f0 = formats[0]
            name = f0.get("name")
            desc = f0.get("descriptions") or []
            format_str = name if not desc else f"{name} ({', '.join(desc)})"

        catalog_no = labels[0].get("catno") if labels else None
        year = bi.get("year")
        title = bi.get("title")
        rid = bi.get("id")

        rows.append({
            "CollectionFolder": it.get("_collection_folder_name"),
            "Artist": artist_name,
            "Title": title,
            "Label": label_name,
            "Format": format_str,
            "Released": year,
            "Catalog#": catalog_no,
            "release_id": rid,
        })

    return pd.DataFrame(rows)


def fetch_marketplace_stats_cached(release_id: int, cache: dict, marketplace_ttl: int):
    entry = cache_get_release(cache, release_id)

    if is_fresh(entry, "marketplace_stats", marketplace_ttl):
        return entry["marketplace_stats"]["data"], True

    data = get_json(
        f"{BASE}/marketplace/stats/{release_id}",
        params={"curr_abbr": CURRENCY},
        allow_404=True,
    )

    if not data:
        stats = {"num_for_sale": None, "blocked_from_sale": None, "lowest_price": None}
    else:
        lowest = data.get("lowest_price")
        stats = {
            "num_for_sale": data.get("num_for_sale"),
            "blocked_from_sale": data.get("blocked_from_sale"),
            "lowest_price": None if lowest is None else float(lowest.get("value")),
        }

    entry["marketplace_stats"] = {"fetched_at": _utc_now_iso(), "data": stats}
    cache_put_release(cache, release_id, entry)
    return stats, False


def fetch_release_details_cached(release_id: int, cache: dict, release_details_ttl: int):
    entry = cache_get_release(cache, release_id)

    if is_fresh(entry, "release_details", release_details_ttl):
        return entry["release_details"]["data"], True

    data = get_json(f"{BASE}/releases/{release_id}")
    comm = (data.get("community") or {})
    details = {"want_count": comm.get("want"), "have_count": comm.get("have")}

    entry["release_details"] = {"fetched_at": _utc_now_iso(), "data": details}
    cache_put_release(cache, release_id, entry)
    return details, False


# -----------------------------
# Liquidity model (API-truthful)
# -----------------------------
def liquidity_score(row: dict):
    if row.get("blocked_from_sale") is True:
        return -1e9

    num_for_sale = safe_num(row.get("num_for_sale"))
    want = safe_num(row.get("want_count"))
    have = safe_num(row.get("have_count"))

    demand_ratio = (want + 1) / (have + 10)

    score = 0.0
    score += 2.2 * math.log1p(want)
    score += 1.2 * math.log1p(num_for_sale)
    score += 3.0 * math.log(demand_ratio)

    if num_for_sale == 0:
        score -= 2.0

    return round(score, 4)


# -----------------------------
# Input loaders
# -----------------------------
def csv_to_dataframe(path: str, category: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "CollectionFolder" not in df.columns:
        raise ValueError("CSV input is missing required column: CollectionFolder")
    if "release_id" not in df.columns:
        raise ValueError("CSV input is missing required column: release_id")

    category_norm = category.lower().strip()
    if category_norm == "all":
        subset = df.copy()
    else:
        subset = df[df["CollectionFolder"].fillna("").str.lower().eq(category_norm)].copy()

    subset["release_id"] = subset["release_id"].astype("Int64")
    return subset


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Discogs liquidity analysis (API-first collection fetch OR CSV import)",
        epilog="""Examples:

  # Print usage (no args)
  python3 app.py

  # API mode: fetch your (or another user's public) collection folder
  python3 app.py --user adaminnyc --category selling

  # API mode: fetch ALL folders (public) and keep CollectionFolder labels
  python3 app.py --user adaminnyc --category all

  # CSV mode: read an export (still supports selling/all)
  python3 app.py --source csv --input my_export.csv --category selling

  # Cache + TTL overrides (seconds)
  python3 app.py --user adaminnyc --category selling --marketplace-ttl 3600 --release-ttl 2592000
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )

    parser.add_argument("--source", choices=["api", "csv"], default="api",
                        help="Input source: api (fetch collection) or csv (read export). Default: api")
    parser.add_argument("--user", default=None,
                        help="Discogs username to fetch (API mode). Required for --source api.")
    parser.add_argument("--input", default=None,
                        help="Path to CSV export (CSV mode). Required for --source csv.")
    parser.add_argument("--category", default="selling",
                        help="Folder name (e.g. selling) or 'all'. Default: selling")
    parser.add_argument("--output", default=None,
                        help="Output CSV path (optional). If omitted, uses collection-output-MMDDYYYY.csv")
    parser.add_argument("--cache", default=DEFAULT_CACHE_PATH,
                        help=f"JSON cache file path (default: {DEFAULT_CACHE_PATH})")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable cache reads/writes for this run")
    parser.add_argument("--marketplace-ttl", type=int, default=DEFAULT_MARKETPLACE_TTL,
                        help="TTL in seconds for marketplace stats cache (default: 86400 / 24h)")
    parser.add_argument("--release-ttl", type=int, default=DEFAULT_RELEASE_DETAILS_TTL,
                        help="TTL in seconds for release details cache (default: 1209600 / 14d)")

    import sys
    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()

    category = (args.category or "selling").strip()
    marketplace_ttl = max(0, int(args.marketplace_ttl))
    release_details_ttl = max(0, int(args.release_ttl))

    print(
        f"TTL settings: marketplace_stats={marketplace_ttl/3600:.2f} hours | "
        f"release_details={release_details_ttl/3600:.2f} hours"
    )
    print(f"Rate limit: ~{60/MIN_SECONDS_PER_REQUEST:.1f} requests/min (target <= 60)")

    cache = {"version": 1, "updated_at": _utc_now_iso(), "releases": {}}
    if not args.no_cache:
        cache = load_cache(args.cache)
        print(f"Cache enabled: {args.cache}")
    else:
        print("Cache disabled (--no-cache)")

    if args.source == "api":
        if not args.user:
            raise RuntimeError("--user is required when --source api")
        print(f"Source: api | user={args.user} | category={category}")
        base_df = collection_to_dataframe(args.user, category)
    else:
        if not args.input:
            raise RuntimeError("--input is required when --source csv")
        print(f"Source: csv | input={args.input} | category={category}")
        base_df = csv_to_dataframe(args.input, category)

    if base_df.empty:
        print("No rows found after source load/filter. Exiting.")
        return

    base_df["release_id"] = pd.to_numeric(base_df["release_id"], errors="coerce").astype("Int64")

    if args.output:
        out_path = args.output
    else:
        out_path = f"collection-output-{today_mmddyyyy()}.csv"

    release_ids = base_df["release_id"].dropna().astype(int).unique()
    print(f"Rows loaded: {len(base_df)} | Unique release_ids: {len(release_ids)}")

    rows = []
    cache_hits_stats = 0
    cache_hits_rel = 0

    for i, rid in enumerate(release_ids, start=1):
        if args.no_cache:
            stats_data = get_json(
                f"{BASE}/marketplace/stats/{rid}",
                params={"curr_abbr": CURRENCY},
                allow_404=True,
            )
            if not stats_data:
                stats = {"num_for_sale": None, "blocked_from_sale": None, "lowest_price": None}
            else:
                lowest = stats_data.get("lowest_price")
                stats = {
                    "num_for_sale": stats_data.get("num_for_sale"),
                    "blocked_from_sale": stats_data.get("blocked_from_sale"),
                    "lowest_price": None if lowest is None else float(lowest.get("value")),
                }

            rel_data = get_json(f"{BASE}/releases/{rid}")
            comm = (rel_data.get("community") or {})
            rel = {"want_count": comm.get("want"), "have_count": comm.get("have")}
        else:
            stats, hit_s = fetch_marketplace_stats_cached(rid, cache, marketplace_ttl)
            rel, hit_r = fetch_release_details_cached(rid, cache, release_details_ttl)
            cache_hits_stats += int(hit_s)
            cache_hits_rel += int(hit_r)

        merged = {"release_id": rid, **stats, **rel}
        merged["liquidity_score"] = liquidity_score(merged)
        rows.append(merged)

        if i % 25 == 0 or i == len(release_ids):
            print(f"Fetched {i}/{len(release_ids)}")

    if not args.no_cache:
        save_cache(args.cache, cache)
        print(f"Cache hits: marketplace_stats={cache_hits_stats}, release_details={cache_hits_rel}")

    market = pd.DataFrame(rows)
    out = base_df.merge(market, on="release_id", how="left")

    out["Release URL"] = out["release_id"].apply(
        lambda x: f"https://www.discogs.com/release/{int(x)}" if pd.notna(x) else ""
    )

    out = out.sort_values(
        ["liquidity_score", "want_count", "num_for_sale"],
        ascending=[False, False, False],
    )
    out.insert(0, "Sell Order", range(1, len(out) + 1))

    out_cols = [
        "Sell Order",
        "CollectionFolder",
        "Artist", "Title", "Label", "Format", "Released", "Catalog#",
        "release_id", "Release URL",
        "want_count", "have_count",
        "num_for_sale", "lowest_price",
        "liquidity_score",
    ]

    out[out_cols].to_csv(out_path, index=False, quoting=csv.QUOTE_ALL)
    print(f"Wrote: {out_path} ({len(out)} rows)")


if __name__ == "__main__":
    main()

