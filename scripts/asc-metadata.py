#!/usr/bin/env python3
"""
ZephShipper - App Store Connect Metadata Manager
Upload and manage app metadata via ASC API.

Usage:
  python3 asc-metadata.py apps                              # List all apps
  python3 asc-metadata.py versions <app_id>                  # List versions
  python3 asc-metadata.py get <app_id>                       # Get current metadata
  python3 asc-metadata.py set <app_id> <metadata.json>       # Upload metadata from JSON
  python3 asc-metadata.py subtitle <app_id> <text>           # Set subtitle
  python3 asc-metadata.py categories <app_id> <primary> [secondary]
  python3 asc-metadata.py price <app_id> free                # Set app price to Free
  python3 asc-metadata.py review-notes <app_id> <text>       # Set review notes + contact info
  python3 asc-metadata.py review-screenshot <sub_id> <file>  # Upload subscription review screenshot
  python3 asc-metadata.py subs <app_id>                      # List subscriptions + status
  python3 asc-metadata.py submit <app_id>                    # Submit for App Store review
  python3 asc-metadata.py status <app_id>                    # Full submission readiness check

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

import jwt, time, json, urllib.request, sys, os, re, requests as _requests

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


def _rapi(method, path, payload=None):
    """requests-based API call (for uploads etc)."""
    headers = {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}
    url = f"{BASE}{path}"
    r = _requests.request(method, url, headers=headers, json=payload)
    return r


def cmd_price_free(app_id):
    """Set app price to Free."""
    # Find FREE price point for USA
    resp = api("GET", f"/apps/{app_id}/appPricePoints?filter[territory]=USA&limit=1")
    if not resp or not resp["data"]:
        print("Could not find price points")
        return
    free_pp = resp["data"][0]["id"]  # First one is always $0.00

    payload = {
        "data": {
            "type": "appPriceSchedules",
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}},
                "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
                "manualPrices": {"data": [{"type": "appPrices", "id": "${price1}"}]}
            }
        },
        "included": [{
            "type": "appPrices", "id": "${price1}",
            "attributes": {"startDate": None},
            "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": free_pp}}}
        }]
    }
    r = _rapi("POST", "/appPriceSchedules", payload)
    if r.status_code in (200, 201):
        print("✅ Price set to FREE")
    else:
        for err in r.json().get("errors", []):
            print(f"ERROR: {err.get('detail', '')}")


def cmd_review_notes(app_id, notes, contact=None):
    """Set review notes and contact info. contact = dict with firstName, lastName, email, phone."""
    # Get version ID (PREPARE_FOR_SUBMISSION)
    versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString,appStoreState")
    if not versions or not versions["data"]:
        print("No versions found")
        return
    ver_id = versions["data"][0]["id"]

    # Check if review detail exists
    r = _rapi("GET", f"/appStoreVersions/{ver_id}/appStoreReviewDetail")
    existing = r.json().get("data")

    attrs = {"notes": notes, "demoAccountRequired": False}
    if contact:
        attrs.update({
            "contactFirstName": contact.get("firstName", ""),
            "contactLastName": contact.get("lastName", ""),
            "contactEmail": contact.get("email", ""),
            "contactPhone": contact.get("phone", ""),
        })

    if existing:
        # Update
        r2 = _rapi("PATCH", f"/appStoreReviewDetails/{existing['id']}", {
            "data": {"type": "appStoreReviewDetails", "id": existing["id"], "attributes": attrs}
        })
    else:
        # Create
        r2 = _rapi("POST", "/appStoreReviewDetails", {
            "data": {
                "type": "appStoreReviewDetails", "attributes": attrs,
                "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": ver_id}}}
            }
        })

    if r2.status_code in (200, 201):
        print(f"✅ Review notes set ({len(notes)} chars)")
    else:
        for err in r2.json().get("errors", []):
            print(f"ERROR: {err.get('detail', '')}")


def cmd_review_screenshot(sub_id, file_path):
    """Upload a review screenshot for a subscription."""
    file_path = os.path.expanduser(file_path)
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)

    # Create reservation
    r = _rapi("POST", "/subscriptionAppStoreReviewScreenshots", {
        "data": {
            "type": "subscriptionAppStoreReviewScreenshots",
            "attributes": {"fileName": filename, "fileSize": file_size},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sub_id}}}
        }
    })
    if r.status_code != 201:
        for err in r.json().get("errors", []):
            print(f"ERROR: {err.get('detail', '')}")
        return

    rdata = r.json()["data"]
    ss_id = rdata["id"]

    # Upload chunks
    with open(file_path, "rb") as f:
        file_data = f.read()
    for op in rdata["attributes"]["uploadOperations"]:
        hdrs = {h["name"]: h["value"] for h in op["requestHeaders"]}
        chunk = file_data[op["offset"]:op["offset"]+op["length"]]
        _requests.put(op["url"], headers=hdrs, data=chunk)

    # Commit
    r2 = _rapi("PATCH", f"/subscriptionAppStoreReviewScreenshots/{ss_id}", {
        "data": {
            "type": "subscriptionAppStoreReviewScreenshots", "id": ss_id,
            "attributes": {"uploaded": True, "sourceFileChecksum": rdata["attributes"]["sourceFileChecksum"]}
        }
    })
    if r2.status_code == 200:
        print(f"✅ Review screenshot uploaded for subscription {sub_id}")
    else:
        for err in r2.json().get("errors", []):
            print(f"ERROR: {err.get('detail', '')}")


def cmd_subs(app_id):
    """List subscription groups and subscriptions with status."""
    resp = api("GET", f"/apps/{app_id}/subscriptionGroups")
    if not resp or not resp["data"]:
        print("No subscription groups")
        return
    for g in resp["data"]:
        print(f"\nGroup: {g['attributes']['referenceName']} ({g['id']})")
        subs = api("GET", f"/subscriptionGroups/{g['id']}/subscriptions")
        if subs:
            for s in subs["data"]:
                a = s["attributes"]
                print(f"  {a['name']} | {a['productId']} | {a['state']} | {a.get('subscriptionPeriod', '?')}")
                # Check review screenshot
                r = _rapi("GET", f"/subscriptions/{s['id']}/appStoreReviewScreenshot")
                has_ss = r.status_code == 200 and r.json().get("data")
                print(f"    Review screenshot: {'✅' if has_ss else '❌ Missing'}")


def cmd_submit(app_id):
    """Submit app for App Store review."""
    # Create review submission
    r = _rapi("POST", "/reviewSubmissions", {
        "data": {
            "type": "reviewSubmissions",
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}
        }
    })
    if r.status_code != 201:
        for err in r.json().get("errors", []):
            print(f"ERROR: {err.get('detail', '')}")
        return

    sub_id = r.json()["data"]["id"]

    # Get latest version
    versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString,appStoreState")
    if not versions or not versions["data"]:
        print("No versions found")
        return
    ver_id = versions["data"][0]["id"]

    # Add version as submission item
    r2 = _rapi("POST", "/reviewSubmissionItems", {
        "data": {
            "type": "reviewSubmissionItems",
            "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub_id}},
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": ver_id}}
            }
        }
    })
    if r2.status_code not in (200, 201):
        errors = r2.json().get("errors", [])
        for err in errors:
            print(f"ERROR: {err.get('detail', '')}")
            # Show associated errors if any
            meta = err.get("meta", {})
            for path, errs in meta.get("associatedErrors", {}).items():
                for ae in errs:
                    print(f"  → {ae.get('detail', '')}")
        return

    # Confirm submission
    r3 = _rapi("PATCH", f"/reviewSubmissions/{sub_id}", {
        "data": {
            "type": "reviewSubmissions", "id": sub_id,
            "attributes": {"submitted": True}
        }
    })
    if r3.status_code == 200:
        print(f"🚀 App submitted for review!")
    else:
        for err in r3.json().get("errors", []):
            print(f"ERROR: {err.get('detail', '')}")


def cmd_status(app_id):
    """Full submission readiness check."""
    print("=== SUBMISSION READINESS CHECK ===\n")

    # Version state
    versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString,appStoreState")
    if versions and versions["data"]:
        v = versions["data"][0]
        state = v["attributes"]["appStoreState"]
        print(f"Version: {v['attributes']['versionString']} → {state}")
        ver_id = v["id"]
    else:
        print("❌ No version found")
        return

    # Build linked?
    build = api("GET", f"/appStoreVersions/{ver_id}/build?fields[builds]=version,processingState")
    if build and build.get("data"):
        b = build["data"]["attributes"]
        print(f"Build: {b['version']} ({b['processingState']}) ✅")
    else:
        print("Build: ❌ No build linked")

    # Screenshots
    locs = api("GET", f"/appStoreVersions/{ver_id}/appStoreVersionLocalizations")
    if locs:
        for loc in locs["data"]:
            locale = loc["attributes"]["locale"]
            ss = api("GET", f"/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets")
            count = 0
            if ss:
                for s in ss["data"]:
                    shots = api("GET", f"/appScreenshotSets/{s['id']}/appScreenshots")
                    if shots:
                        count += len(shots["data"])
            print(f"Screenshots ({locale}): {count} {'✅' if count >= 1 else '❌'}")

    # Review notes
    r = _rapi("GET", f"/appStoreVersions/{ver_id}/appStoreReviewDetail")
    rd = r.json().get("data")
    if rd:
        print(f"Review notes: ✅ ({len(rd['attributes'].get('notes') or '')} chars)")
        print(f"Demo account required: {rd['attributes'].get('demoAccountRequired', '?')}")
    else:
        print("Review notes: ❌ Missing")

    # Price
    r2 = _rapi("GET", f"/appPriceSchedules/{app_id}/manualPrices")
    if r2.status_code == 200 and r2.json().get("data"):
        print("Pricing: ✅")
    else:
        print("Pricing: ❌ Not set")

    # Subscriptions
    resp = api("GET", f"/apps/{app_id}/subscriptionGroups")
    if resp and resp["data"]:
        for g in resp["data"]:
            subs = api("GET", f"/subscriptionGroups/{g['id']}/subscriptions")
            if subs:
                for s in subs["data"]:
                    a = s["attributes"]
                    icon = "✅" if a["state"] == "READY_TO_SUBMIT" else "⚠️"
                    print(f"Sub {a['name']}: {a['state']} {icon}")

    print("\n⚠️  App Privacy (Data Usage) must be set via ASC web UI — no API available.")


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
    elif cmd == "price" and len(sys.argv) > 3 and sys.argv[3] == "free":
        cmd_price_free(sys.argv[2])
    elif cmd == "review-notes" and len(sys.argv) > 3:
        contact = None
        if len(sys.argv) > 4:
            # Optional: pass contact as JSON string
            try:
                contact = json.loads(sys.argv[4])
            except json.JSONDecodeError:
                pass
        cmd_review_notes(sys.argv[2], sys.argv[3], contact)
    elif cmd == "review-screenshot" and len(sys.argv) > 3:
        cmd_review_screenshot(sys.argv[2], sys.argv[3])
    elif cmd == "subs" and len(sys.argv) > 2:
        cmd_subs(sys.argv[2])
    elif cmd == "submit" and len(sys.argv) > 2:
        cmd_submit(sys.argv[2])
    elif cmd == "status" and len(sys.argv) > 2:
        cmd_status(sys.argv[2])
    else:
        print(__doc__)
