#!/usr/bin/env python3
"""
ZephShipper - App Store Connect Metadata Manager
Upload and manage app metadata via ASC API.

Usage:
  python3 asc-metadata.py apps                          # List all apps
  python3 asc-metadata.py versions <app_id>              # List versions
  python3 asc-metadata.py get <app_id>                   # Get current metadata
  python3 asc-metadata.py set <app_id> <metadata.json>   # Upload metadata from JSON
  python3 asc-metadata.py subtitle <app_id> <text>       # Set subtitle
  python3 asc-metadata.py categories <app_id> <primary> [secondary]

Metadata JSON format:
{
  "locale": "en-US",
  "description": "...",
  "keywords": "word1,word2,...",
  "promotionalText": "...",
  "whatsNew": "...",
  "subtitle": "...",
  "primaryCategory": "HEALTH_AND_FITNESS",
  "secondaryCategory": "FOOD_AND_DRINK"
}
"""

import jwt, time, json, urllib.request, sys, os, re

# Config - reads from env or defaults
KEY_ID = os.environ.get("ASC_KEY_ID", "AA5UCQU456")
ISSUER_ID = os.environ.get("ASC_ISSUER_ID", "638c67e6-9365-4b3f-8250-474197f6f1a1")
KEY_DIR = os.path.expanduser("~/.appstoreconnect/private_keys")
KEY_FILE = os.path.join(KEY_DIR, f"AuthKey_{KEY_ID}.p8")
BASE = "https://api.appstoreconnect.apple.com/v1"


def get_token():
    with open(KEY_FILE) as f:
        key = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER_ID, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        key, algorithm="ES256", headers={"kid": KEY_ID}
    )


def api(method, path, payload=None):
    headers = {"Authorization": f"Bearer {get_token()}"}
    data = None
    if payload:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        for err in body.get("errors", []):
            print(f"ERROR: {err.get('detail', err.get('title', 'Unknown'))}")
        return None


def cmd_apps():
    resp = api("GET", "/apps?limit=20&fields[apps]=name,bundleId,sku")
    if not resp:
        return
    for app in resp["data"]:
        a = app["attributes"]
        print(f"{app['id']} | {a['name']} | {a['bundleId']}")


def cmd_versions(app_id):
    resp = api("GET", f"/apps/{app_id}/appStoreVersions?limit=5&fields[appStoreVersions]=versionString,appStoreState,platform")
    if not resp:
        return
    for v in resp["data"]:
        a = v["attributes"]
        print(f"{v['id']} | v{a['versionString']} | {a['appStoreState']} | {a['platform']}")


def cmd_get(app_id):
    # Get version
    versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&filter[appStoreState]=PREPARE_FOR_SUBMISSION,READY_FOR_SALE&fields[appStoreVersions]=versionString,appStoreState")
    if not versions or not versions["data"]:
        # Try without filter
        versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString,appStoreState")
    if not versions or not versions["data"]:
        print("No versions found")
        return
    ver = versions["data"][0]
    ver_id = ver["id"]
    print(f"Version: {ver['attributes']['versionString']} ({ver['attributes']['appStoreState']})")

    # Get version localizations
    locs = api("GET", f"/appStoreVersions/{ver_id}/appStoreVersionLocalizations")
    if locs:
        for loc in locs["data"]:
            a = loc["attributes"]
            print(f"\n--- {a['locale']} (version loc: {loc['id']}) ---")
            print(f"Description: {(a.get('description') or 'EMPTY')[:100]}...")
            print(f"Keywords: {a.get('keywords') or 'EMPTY'}")
            print(f"WhatsNew: {(a.get('whatsNew') or 'EMPTY')[:80]}")
            print(f"PromoText: {(a.get('promotionalText') or 'EMPTY')[:80]}")

    # Get app info localizations (subtitle)
    infos = api("GET", f"/apps/{app_id}/appInfos")
    if infos and infos["data"]:
        info_id = infos["data"][0]["id"]
        info_locs = api("GET", f"/appInfos/{info_id}/appInfoLocalizations")
        if info_locs:
            for loc in info_locs["data"]:
                a = loc["attributes"]
                print(f"\n--- {a['locale']} (info loc: {loc['id']}) ---")
                print(f"Subtitle: {a.get('subtitle') or 'EMPTY'}")


def cmd_set(app_id, json_file, force=False):
    with open(json_file) as f:
        meta = json.load(f)

    if not enforce_guardrails(meta, force=force):
        sys.exit(1)

    locale = meta.get("locale", "en-US")

    # Get version
    versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString,appStoreState")
    if not versions or not versions["data"]:
        print("No versions found")
        return
    ver_id = versions["data"][0]["id"]
    ver_state = versions["data"][0]["attributes"]["appStoreState"]
    print(f"Version: {versions['data'][0]['attributes']['versionString']} ({ver_state})")

    # Find or create localization
    locs = api("GET", f"/appStoreVersions/{ver_id}/appStoreVersionLocalizations")
    loc_id = None
    if locs:
        for loc in locs["data"]:
            if loc["attributes"]["locale"] == locale:
                loc_id = loc["id"]
                break

    if not loc_id:
        print(f"No {locale} localization found")
        return

    # Build version loc attributes
    ver_attrs = {}
    for key in ["description", "keywords", "promotionalText", "whatsNew"]:
        if key in meta:
            ver_attrs[key] = meta[key]

    if ver_attrs:
        result = api("PATCH", f"/appStoreVersionLocalizations/{loc_id}", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "id": loc_id,
                "attributes": ver_attrs
            }
        })
        if result:
            print(f"✅ Version metadata updated ({', '.join(ver_attrs.keys())})")

    # Subtitle via appInfoLocalizations
    if "subtitle" in meta:
        infos = api("GET", f"/apps/{app_id}/appInfos")
        if infos and infos["data"]:
            info_id = infos["data"][0]["id"]
            info_locs = api("GET", f"/appInfos/{info_id}/appInfoLocalizations")
            if info_locs:
                for iloc in info_locs["data"]:
                    if iloc["attributes"]["locale"] == locale:
                        result = api("PATCH", f"/appInfoLocalizations/{iloc['id']}", {
                            "data": {
                                "type": "appInfoLocalizations",
                                "id": iloc["id"],
                                "attributes": {"subtitle": meta["subtitle"]}
                            }
                        })
                        if result:
                            print(f"✅ Subtitle set: {meta['subtitle']}")
                        break

    # Categories
    if "primaryCategory" in meta:
        infos = api("GET", f"/apps/{app_id}/appInfos")
        if infos and infos["data"]:
            info_id = infos["data"][0]["id"]
            rels = {
                "primaryCategory": {
                    "data": {"type": "appCategories", "id": meta["primaryCategory"]}
                }
            }
            if "secondaryCategory" in meta:
                rels["secondaryCategory"] = {
                    "data": {"type": "appCategories", "id": meta["secondaryCategory"]}
                }
            result = api("PATCH", f"/appInfos/{info_id}", {
                "data": {
                    "type": "appInfos",
                    "id": info_id,
                    "relationships": rels
                }
            })
            if result:
                cats = meta["primaryCategory"]
                if "secondaryCategory" in meta:
                    cats += f" + {meta['secondaryCategory']}"
                print(f"✅ Categories set: {cats}")


def cmd_subtitle(app_id, text):
    infos = api("GET", f"/apps/{app_id}/appInfos")
    if not infos or not infos["data"]:
        print("No app info found")
        return
    info_id = infos["data"][0]["id"]
    info_locs = api("GET", f"/appInfos/{info_id}/appInfoLocalizations")
    if not info_locs:
        return
    for loc in info_locs["data"]:
        result = api("PATCH", f"/appInfoLocalizations/{loc['id']}", {
            "data": {
                "type": "appInfoLocalizations",
                "id": loc["id"],
                "attributes": {"subtitle": text}
            }
        })
        if result:
            print(f"✅ Subtitle set for {loc['attributes']['locale']}: {text}")


def cmd_categories(app_id, primary, secondary=None):
    infos = api("GET", f"/apps/{app_id}/appInfos")
    if not infos or not infos["data"]:
        print("No app info found")
        return
    info_id = infos["data"][0]["id"]
    rels = {"primaryCategory": {"data": {"type": "appCategories", "id": primary}}}
    if secondary:
        rels["secondaryCategory"] = {"data": {"type": "appCategories", "id": secondary}}
    result = api("PATCH", f"/appInfos/{info_id}", {
        "data": {"type": "appInfos", "id": info_id, "relationships": rels}
    })
    if result:
        print(f"✅ Categories updated")


# ── Guardrails ──────────────────────────────────────────────────────
# Catch hallucinated or unverified content before it hits App Store Connect.

GUARDRAIL_PATTERNS = [
    # Emails that don't belong to verified domains
    (r'[\w.-]+@[\w.-]+\.\w+', "email address"),
    # URLs that aren't apple.com legal links
    (r'https?://(?!www\.apple\.com/legal)[\w.-]+\.\w+[/\w.-]*', "URL"),
    # Phone numbers
    (r'\+?\d[\d\s\-()]{7,}\d', "phone number"),
    # Social media handles
    (r'@[A-Za-z][\w]{2,}', "social media handle"),
]

# Known-safe patterns (won't trigger warnings)
SAFE_PATTERNS = [
    r'https?://www\.apple\.com/legal/',  # Apple EULA
]

def validate_metadata(meta: dict) -> list:
    """Check metadata for potentially hallucinated content. Returns list of warnings."""
    warnings = []
    text_fields = ["description", "promotionalText", "whatsNew", "subtitle"]

    for field in text_fields:
        text = meta.get(field, "")
        if not text:
            continue

        for pattern, label in GUARDRAIL_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                # Skip known-safe matches
                if any(re.match(sp, match) for sp in SAFE_PATTERNS):
                    continue
                warnings.append(f"⚠️  [{field}] contains {label}: \"{match}\"")

    # Character limit checks
    limits = {
        "subtitle": 30,
        "keywords": 100,
        "promotionalText": 170,
        "description": 4000,
        "whatsNew": 4000,
    }
    for field, limit in limits.items():
        text = meta.get(field, "")
        if text and len(text) > limit:
            warnings.append(f"❌ [{field}] exceeds {limit} char limit ({len(text)} chars)")

    # Keywords validation
    kw = meta.get("keywords", "")
    if kw:
        if " ," in kw or ", " in kw:
            warnings.append("⚠️  [keywords] has spaces around commas (wastes chars)")
        words = kw.split(",")
        dupes = [w for w in words if words.count(w) > 1]
        if dupes:
            warnings.append(f"⚠️  [keywords] duplicates: {set(dupes)}")

    return warnings


def enforce_guardrails(meta: dict, force: bool = False) -> bool:
    """Validate and block upload if issues found. Returns True if safe to proceed."""
    warnings = validate_metadata(meta)
    if not warnings:
        return True

    print("\n🛡️  GUARDRAIL CHECK:")
    for w in warnings:
        print(f"  {w}")
    print()

    has_blockers = any(w.startswith("❌") for w in warnings)
    if has_blockers:
        print("❌ Blocked: fix errors above before uploading.")
        return False

    if not force:
        print("⚠️  Warnings found. Use --force to upload anyway.")
        print("   Make sure all contact info, URLs, and handles are REAL and VERIFIED.")
        return False

    print("⚠️  Proceeding with warnings (--force)")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "apps":
        cmd_apps()
    elif cmd == "versions" and len(sys.argv) > 2:
        cmd_versions(sys.argv[2])
    elif cmd == "get" and len(sys.argv) > 2:
        cmd_get(sys.argv[2])
    elif cmd == "set" and len(sys.argv) > 3:
        cmd_set(sys.argv[2], sys.argv[3], force="--force" in sys.argv)
    elif cmd == "subtitle" and len(sys.argv) > 3:
        cmd_subtitle(sys.argv[2], sys.argv[3])
    elif cmd == "categories" and len(sys.argv) > 3:
        cmd_categories(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    else:
        print(__doc__)
