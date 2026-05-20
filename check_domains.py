#!/usr/bin/env python3
"""Check domain availability via RDAP (IANA's free, key-less protocol).

Usage:
    python3 check_domains.py
    python3 check_domains.py --name "personalspace" --tlds com io game
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import error, request

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
USER_AGENT = "domain-availability-checker/1.0"
TIMEOUT = 8

DEFAULT_NAMES = [
    "personalspace",
    "personal-space",
    "playpersonalspace",
    "getpersonalspace",
    "personalspacegame",
]

DEFAULT_TLDS = [
    "com", "net", "org", "io", "co", "app", "dev", "ai",
    "game", "games", "gg", "fun", "space", "xyz", "online",
    "club", "studio", "world", "live", "rocks",
]


def fetch_bootstrap():
    req = request.Request(BOOTSTRAP_URL, headers={"User-Agent": USER_AGENT})
    with request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def build_tld_map(bootstrap):
    tld_to_server = {}
    for entry in bootstrap.get("services", []):
        tlds, servers = entry[0], entry[1]
        if not servers:
            continue
        base = servers[0].rstrip("/")
        for tld in tlds:
            tld_to_server[tld.lower()] = base
    return tld_to_server


def check_domain(domain, rdap_base):
    """Return ('available'|'taken'|'unknown', detail)."""
    url = f"{rdap_base}/domain/{domain}"
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json"})
    try:
        with request.urlopen(req, timeout=TIMEOUT) as r:
            r.read()
            return "taken", f"HTTP {r.status}"
    except error.HTTPError as e:
        if e.code == 404:
            return "available", "RDAP 404"
        if e.code == 429:
            return "unknown", "rate limited"
        return "unknown", f"HTTP {e.code}"
    except error.URLError as e:
        return "unknown", f"network: {e.reason}"
    except Exception as e:
        return "unknown", f"error: {e}"


def main():
    parser = argparse.ArgumentParser(description="Check domain availability via RDAP.")
    parser.add_argument("--name", action="append", help="Base name (repeatable). Defaults to a preset list.")
    parser.add_argument("--tlds", nargs="+", help="TLDs to check (no dot). Defaults to a preset list.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel requests.")
    args = parser.parse_args()

    names = args.name or DEFAULT_NAMES
    tlds = [t.lower().lstrip(".") for t in (args.tlds or DEFAULT_TLDS)]

    print(f"Fetching IANA RDAP bootstrap from {BOOTSTRAP_URL} ...", file=sys.stderr)
    try:
        tld_map = build_tld_map(fetch_bootstrap())
    except Exception as e:
        print(f"Failed to load bootstrap: {e}", file=sys.stderr)
        sys.exit(1)

    candidates = []
    skipped = []
    for name in names:
        for tld in tlds:
            server = tld_map.get(tld)
            if server:
                candidates.append((f"{name}.{tld}", server))
            else:
                skipped.append(f"{name}.{tld}")

    if skipped:
        print(f"Skipping {len(skipped)} domains with no RDAP server (e.g. {skipped[0]})", file=sys.stderr)

    results = {}
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_domain, d, s): d for d, s in candidates}
        for fut in as_completed(futures):
            domain = futures[fut]
            results[domain] = fut.result()

    available = sorted(d for d, (status, _) in results.items() if status == "available")
    taken = sorted(d for d, (status, _) in results.items() if status == "taken")
    unknown = sorted((d, detail) for d, (status, detail) in results.items() if status == "unknown")

    print(f"\nChecked {len(results)} domains in {time.time() - start:.1f}s\n")
    print(f"AVAILABLE ({len(available)}):")
    for d in available:
        print(f"  + {d}")
    print(f"\nTAKEN ({len(taken)}):")
    for d in taken:
        print(f"  - {d}")
    if unknown:
        print(f"\nUNKNOWN ({len(unknown)}):")
        for d, detail in unknown:
            print(f"  ? {d}  ({detail})")

    print("\nNote: RDAP 404 strongly suggests available, but always confirm at a registrar before buying.")


if __name__ == "__main__":
    main()
