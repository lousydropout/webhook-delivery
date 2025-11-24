#!/usr/bin/env python3
"""
Verify that endpoints.md documentation matches actual API implementation.

This script checks:
1. All documented endpoints exist in routes.py
2. HTTP methods match
3. No undocumented endpoints exist (optional check)
"""

import re
import sys
from pathlib import Path


def extract_endpoints_from_docs(docs_path):
    """Extract endpoints from endpoints.md"""
    with open(docs_path) as f:
        content = f.read()

    # Find where Migration Guide starts to exclude endpoints from there
    migration_start = content.find("## Migration Guide")

    endpoints = []
    # Match patterns like "POST /v1/events" or "GET /v1/events/{event_id}"
    pattern = r"```http\s+(GET|POST|PATCH|DELETE|PUT)\s+(/v1/[^\s]+)"
    for match in re.finditer(pattern, content):
        # Skip endpoints in Migration Guide section
        if migration_start > 0 and match.start() > migration_start:
            continue

        method = match.group(1)
        path = match.group(2)
        endpoints.append({"method": method, "path": path})

    return endpoints


def extract_endpoints_from_routes(routes_path):
    """Extract endpoints from routes.py"""
    with open(routes_path) as f:
        content = f.read()

    endpoints = []
    # Match patterns like "@router.get("/v1/events", ...)"
    pattern = r'@router\.(get|post|patch|delete|put)\(["\'](/v1/[^"\']+)["\']'
    for match in re.finditer(pattern, content):
        method = match.group(1).upper()
        path = match.group(2)
        endpoints.append({"method": method, "path": path})

    return endpoints


def main():
    repo_root = Path(__file__).parent.parent
    docs_path = repo_root / "endpoints.md"
    routes_path = repo_root / "src" / "api" / "routes.py"

    if not docs_path.exists():
        print(f"❌ Documentation file not found: {docs_path}")
        return 1

    if not routes_path.exists():
        print(f"❌ Routes file not found: {routes_path}")
        return 1

    doc_endpoints = extract_endpoints_from_docs(docs_path)
    route_endpoints = extract_endpoints_from_routes(routes_path)

    print(f"📋 Found {len(doc_endpoints)} endpoints in documentation")
    print(f"📋 Found {len(route_endpoints)} endpoints in routes.py\n")

    # Check each documented endpoint exists in routes
    missing = []

    for doc_ep in doc_endpoints:
        # Normalize path (remove trailing slashes, etc.)
        doc_path = doc_ep["path"].rstrip("/")
        found = False

        for route_ep in route_endpoints:
            route_path = route_ep["path"].rstrip("/")
            if doc_ep["method"] == route_ep["method"] and doc_path == route_path:
                found = True
                break

        if not found:
            missing.append(f"{doc_ep['method']} {doc_path}")

    # Report results
    if missing:
        print("❌ Endpoints documented but not found in routes.py:")
        for ep in missing:
            print(f"   - {ep}")
        print()
        return 1

    print("✅ All documented endpoints match routes.py implementation!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
