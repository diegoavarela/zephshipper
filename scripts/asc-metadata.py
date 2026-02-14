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
  python3 asc-metadata.py optimize <app_id> <project_path>   # Generate ASO-optimized metadata
  python3 asc-metadata.py optimize <app_id> <project_path> --apply  # Generate and upload

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


# ── ASO Optimize ────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "HEALTH_AND_FITNESS": ["workout", "fitness", "health", "diet", "nutrition", "weight", "exercise", "gym", "wellness", "body", "calorie", "step", "activity", "training", "cardio"],
    "FOOD_AND_DRINK": ["recipe", "cook", "meal", "food", "diet", "nutrition", "restaurant", "kitchen", "ingredient", "grocery", "eat", "drink", "healthy", "plan", "prep"],
    "PRODUCTIVITY": ["task", "todo", "organize", "plan", "schedule", "reminder", "notes", "project", "manage", "workflow", "focus", "timer", "goal", "habit", "routine"],
    "FINANCE": ["stock", "invest", "portfolio", "market", "trade", "finance", "money", "budget", "wealth", "dividend", "ticker", "crypto", "savings", "expense", "bank"],
    "MUSIC": ["tuner", "metronome", "guitar", "piano", "music", "practice", "instrument", "pitch", "tempo", "rhythm", "chord", "song", "audio", "ear", "scale"],
    "TRAVEL": ["travel", "trip", "country", "map", "explore", "adventure", "journey", "vacation", "visit", "destination", "flight", "hotel", "guide", "passport", "bucket"],
    "EDUCATION": ["study", "learn", "quiz", "test", "exam", "practice", "flashcard", "education", "knowledge", "prep", "tutor", "course", "lesson", "review", "grade"],
    "UTILITIES": ["tool", "utility", "convert", "calculate", "scan", "widget", "shortcut", "clipboard", "backup", "file", "storage", "clean", "battery", "vpn", "qr"],
    "SOCIAL_NETWORKING": ["social", "chat", "message", "friend", "share", "connect", "community", "group", "profile", "follow", "feed", "post", "story", "network", "dating"],
    "ENTERTAINMENT": ["game", "fun", "watch", "stream", "video", "movie", "show", "meme", "trivia", "puzzle", "play", "comedy", "cartoon", "anime", "fan"],
    "LIFESTYLE": ["journal", "diary", "mood", "gratitude", "mindful", "meditation", "sleep", "relax", "self", "care", "style", "fashion", "home", "decor", "personal"],
    "WRITING": ["write", "editor", "note", "markdown", "journal", "blog", "publish", "text", "document", "draft", "story", "prose", "author", "outline", "creative"],
}

# Map framework/integration names to feature keywords
FRAMEWORK_KEYWORDS = {
    "RevenueCat": ["subscription", "premium", "pro"],
    "StoreKit": ["subscription", "premium", "purchase"],
    "HealthKit": ["health", "activity", "step", "heart", "workout"],
    "CloudKit": ["sync", "cloud", "backup"],
    "CoreLocation": ["location", "map", "nearby", "gps"],
    "MapKit": ["map", "location", "navigate", "direction"],
    "CoreML": ["ai", "smart", "intelligent", "predict"],
    "AVFoundation": ["audio", "video", "camera", "record"],
    "MusicKit": ["music", "playlist", "song", "album"],
    "WeatherKit": ["weather", "forecast", "temperature", "rain"],
    "WidgetKit": ["widget", "home", "glance"],
    "Charts": ["chart", "graph", "visual", "analytics"],
    "Firebase": ["sync", "cloud", "realtime"],
}


def analyze_project(project_path):
    """Analyze Swift project to extract features, integrations, and context."""
    import glob

    project_path = os.path.expanduser(project_path)
    result = {
        "features": [],
        "integrations": [],
        "view_names": [],
        "tab_names": [],
        "model_names": [],
        "readme": "",
        "has_subscription": False,
        "category_hints": set(),
    }

    # Read README/CLAUDE.md
    for doc in ["README.md", "CLAUDE.md", "docs/README.md"]:
        doc_path = os.path.join(project_path, doc)
        if os.path.exists(doc_path):
            with open(doc_path) as f:
                result["readme"] += f.read()[:2000] + "\n"

    # Find Swift files
    swift_files = glob.glob(os.path.join(project_path, "**/*.swift"), recursive=True)
    all_code = ""

    for sf in swift_files:
        try:
            with open(sf) as f:
                code = f.read()
            all_code += code + "\n"

            basename = os.path.basename(sf).replace(".swift", "")

            # Detect views
            if re.search(r'struct\s+\w+.*:\s*View\b', code):
                result["view_names"].append(basename)

            # Detect models
            if re.search(r'(class|struct)\s+\w+.*:\s*(Codable|Identifiable|ObservableObject)', code):
                result["model_names"].append(basename)

        except (UnicodeDecodeError, IOError):
            continue

    # Detect tab names
    tab_matches = re.findall(r'\.tabItem\s*\{[^}]*(?:Label|Text)\s*\(\s*"([^"]+)"', all_code)
    tab_matches += re.findall(r'Tab\s*\(\s*"([^"]+)"', all_code)
    result["tab_names"] = list(set(tab_matches))

    # Detect integrations/frameworks
    for framework, keywords in FRAMEWORK_KEYWORDS.items():
        if framework.lower() in all_code.lower() or f'import {framework}' in all_code:
            result["integrations"].append(framework)
            if framework in ("RevenueCat", "StoreKit"):
                result["has_subscription"] = True

    # Extract feature-like patterns
    feature_patterns = [
        r'NavigationTitle\s*\(\s*"([^"]+)"',
        r'navigationTitle\s*\(\s*"([^"]+)"',
        r'\.navigationBarTitle\s*\(\s*"([^"]+)"',
        r'Label\s*\(\s*"([^"]+)"',
    ]
    for pat in feature_patterns:
        matches = re.findall(pat, all_code)
        result["features"].extend(matches)

    result["features"] = list(set(result["features"]))[:20]

    # Category hints from frameworks
    if any(fw in result["integrations"] for fw in ["HealthKit"]):
        result["category_hints"].add("HEALTH_AND_FITNESS")
    if any(fw in result["integrations"] for fw in ["MusicKit"]):
        result["category_hints"].add("MUSIC")
    if any(fw in result["integrations"] for fw in ["MapKit", "CoreLocation"]):
        result["category_hints"].add("TRAVEL")

    # Hint from code content
    code_lower = all_code.lower()
    hint_map = {
        "FINANCE": ["stock", "ticker", "portfolio", "dividend", "market", "invest", "trading"],
        "HEALTH_AND_FITNESS": ["workout", "exercise", "calorie", "heart rate", "step count", "fitness"],
        "PRODUCTIVITY": ["task", "todo", "reminder", "schedule", "workflow"],
        "EDUCATION": ["quiz", "flashcard", "study", "exam", "lesson"],
        "MUSIC": ["tuner", "metronome", "chord", "guitar", "piano"],
        "WRITING": ["markdown", "editor", "document", "draft", "publish"],
    }
    for cat, hints in hint_map.items():
        if sum(1 for h in hints if h in code_lower) >= 2:
            result["category_hints"].add(cat)

    result["category_hints"] = list(result["category_hints"])
    return result


def extract_keywords_from_features(analysis):
    """Convert code features into user-facing search terms."""
    keywords = set()

    # From view names: split camelCase into words
    for name in analysis["view_names"] + analysis["model_names"]:
        words = re.findall(r'[A-Z][a-z]+|[a-z]+', name)
        for w in words:
            w = w.lower()
            if len(w) > 2 and w not in ("view", "model", "screen", "cell", "row", "item", "list", "detail", "main", "app", "content", "data", "helper", "manager", "service", "provider", "coordinator", "state", "type", "error", "loading", "frame", "button", "text", "image", "color", "font", "stack", "group", "section", "header", "footer", "body", "picker", "toggle", "sheet", "alert", "action", "handler", "delegate", "protocol", "extension", "private", "public", "static", "func", "enum", "case", "default", "return", "self", "super", "init", "class", "struct", "var", "let", "from", "with", "into", "over", "remove", "add", "update", "delete", "fetch", "load", "save", "set", "get", "new", "old", "info", "config", "setting", "option", "value", "result", "response", "request", "param", "arg", "sidebar", "tab", "bar", "nav", "navigation", "container", "wrapper", "overlay", "background", "foreground", "padding", "spacing", "toolbar", "menu", "popover", "modal", "scroll", "form", "field", "label", "icon", "badge", "progress", "indicator", "placeholder"):
                keywords.add(w)

    # Generic stop words for all keyword extraction
    stop_words = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our", "out", "has", "have", "from", "with", "into", "over", "your", "this", "that", "will", "each", "make", "like", "just", "them", "than", "been", "said", "its", "about", "other", "which", "their", "time", "very", "when", "come", "could", "made", "after", "remove", "add", "update", "delete", "new", "old", "set", "get", "show", "hide", "open", "close", "start", "stop", "save", "load", "edit", "create", "none", "some", "true", "false", "error", "success", "failed", "loading", "disclaimer", "yahoo", "google", "apple", "setting", "settings", "configure", "statistic", "statistics"}

    # From tab names
    for tab in analysis["tab_names"]:
        for word in tab.lower().split():
            if len(word) > 2 and word not in stop_words:
                keywords.add(word)

    # From features (navigation titles, labels)
    for feat in analysis["features"]:
        for word in feat.lower().split():
            if len(word) > 2 and word not in stop_words:
                keywords.add(word)

    # Remove stop words from all extracted keywords
    keywords = {kw for kw in keywords if kw not in stop_words}

    # From integration keywords
    for integration in analysis["integrations"]:
        if integration in FRAMEWORK_KEYWORDS:
            keywords.update(FRAMEWORK_KEYWORDS[integration])

    return keywords


def build_keyword_field(feature_keywords, category_keywords, title_words, subtitle_words, limit=100):
    """Build optimized keyword field, deduplicating against title and subtitle."""
    exclude = set(w.lower() for w in title_words) | set(w.lower() for w in subtitle_words)

    # Prioritize: feature keywords first, then category keywords
    ordered = []
    for kw in feature_keywords:
        kw = kw.lower().strip()
        if kw and kw not in exclude and kw not in ordered:
            # Remove plurals (but not words ending in 'ss', 'us', 'is', or common non-plural 's' words)
            no_deplural = {"news", "analysis", "stocks", "this", "plus", "focus", "canvas", "status", "virus", "bus", "gas", "atlas", "bias", "axis"}
            singular = kw
            if kw.endswith("s") and len(kw) > 3 and kw not in no_deplural and not kw.endswith(("ss", "us", "is")):
                singular = kw[:-1]
            if singular not in exclude and singular not in ordered:
                ordered.append(singular)

    for kw in category_keywords:
        kw = kw.lower().strip()
        if kw and kw not in exclude and kw not in ordered:
            singular = kw
            if kw.endswith("s") and len(kw) > 3 and kw not in no_deplural and not kw.endswith(("ss", "us", "is")):
                singular = kw[:-1]
            if singular not in exclude and singular not in ordered:
                ordered.append(singular)

    # Fill to limit
    result = []
    current_len = 0
    for kw in ordered:
        added_len = len(kw) + (1 if result else 0)  # +1 for comma
        if current_len + added_len <= limit:
            result.append(kw)
            current_len += added_len

    return ",".join(result)


def generate_subtitle(analysis, title_words, keyword_words, limit=30):
    """Generate benefit-focused subtitle using words NOT in title or keywords."""
    exclude = set(w.lower() for w in title_words) | set(w.lower() for w in keyword_words)

    # Build candidate subtitles based on detected category
    candidates = []
    cats = analysis.get("category_hints", [])

    if "FINANCE" in cats:
        candidates = ["Track Stocks & Markets", "Real-Time Market Data", "Smart Stock Tracker", "Portfolio & Dividends", "Live Market Watch", "Stock Alert & Tracker"]
    elif "HEALTH_AND_FITNESS" in cats:
        candidates = ["Track Your Fitness Goals", "Smart Health Companion", "Daily Workout Planner", "Your Fitness Journey", "Health & Activity Log"]
    elif "PRODUCTIVITY" in cats:
        candidates = ["Organize Your Day", "Smart Task Planner", "Get More Done Daily", "Plan & Focus Better", "Your Productivity Hub"]
    elif "MUSIC" in cats:
        candidates = ["Tune & Practice Better", "Your Music Companion", "Practice Made Simple", "Master Your Sound"]
    elif "EDUCATION" in cats:
        candidates = ["Study Smarter Daily", "Learn & Quiz Yourself", "Ace Every Test", "Your Study Companion"]
    elif "WRITING" in cats:
        candidates = ["Write Without Limits", "Your Writing Studio", "Draft & Publish Easy", "Distraction-Free Editor"]
    elif "TRAVEL" in cats:
        candidates = ["Explore & Plan Trips", "Your Travel Companion", "Discover New Places"]
    else:
        candidates = ["Simple & Powerful", "Smart & Fast", "Built for You"]

    # Pick first candidate that fits and has minimal overlap with excluded words
    for c in candidates:
        if len(c) <= limit:
            c_words = set(w.lower() for w in c.split())
            overlap = c_words & exclude
            if len(overlap) <= 1:  # Allow 1 word overlap
                return c

    return candidates[0][:limit] if candidates else ""


def generate_description(analysis, app_name, subtitle, keywords_str, limit=4000):
    """Generate ASO-optimized description from code analysis."""
    features = analysis["features"][:8]
    tabs = analysis["tab_names"]
    integrations = analysis["integrations"]
    has_sub = analysis["has_subscription"]
    cats = analysis.get("category_hints", [])

    # Build feature bullets from actual code analysis
    feature_bullets = []
    for feat in features:
        feature_bullets.append(f"- {feat}")
    for tab in tabs:
        if tab not in features:
            feature_bullets.append(f"- {tab}")

    # Integration-based features
    integration_features = []
    if "CloudKit" in integrations or "Firebase" in integrations:
        integration_features.append("- Seamless cloud sync across all your devices")
    if "WidgetKit" in integrations:
        integration_features.append("- Home screen widgets for quick access")
    if "HealthKit" in integrations:
        integration_features.append("- Apple Health integration for comprehensive tracking")
    if "Charts" in integrations:
        integration_features.append("- Beautiful charts and visual analytics")
    if "CoreML" in integrations:
        integration_features.append("- Smart, AI-powered insights")

    # Category-specific hook
    if "FINANCE" in cats:
        hook = f"Stay on top of your investments with {app_name}. Get the market data you need, exactly when you need it. Track stocks, monitor your portfolio, and never miss an important market move."
    elif "HEALTH_AND_FITNESS" in cats:
        hook = f"Take control of your health journey with {app_name}. Whether you are tracking workouts, monitoring nutrition, or building better habits, everything you need is in one place."
    elif "PRODUCTIVITY" in cats:
        hook = f"Stop letting tasks slip through the cracks. {app_name} helps you organize, plan, and execute with clarity. Spend less time managing and more time doing."
    elif "MUSIC" in cats:
        hook = f"Level up your musical skills with {app_name}. From practice sessions to performance prep, get the tools you need to sound your best."
    elif "EDUCATION" in cats:
        hook = f"Study smarter, not harder. {app_name} gives you the tools to master any subject with confidence and efficiency."
    else:
        hook = f"{app_name} is designed to make your life easier. Simple, fast, and focused on what matters most to you."

    # Build description
    sections = [hook, ""]

    if feature_bullets or integration_features:
        sections.append("KEY FEATURES")
        sections.extend(feature_bullets[:6])
        sections.extend(integration_features)
        sections.append("")

    # Perfect for section
    if "FINANCE" in cats:
        perfect = "Perfect for investors, day traders, financial advisors, and anyone who wants to stay informed about the markets."
    elif "HEALTH_AND_FITNESS" in cats:
        perfect = "Perfect for fitness enthusiasts, health-conscious individuals, and anyone starting their wellness journey."
    elif "PRODUCTIVITY" in cats:
        perfect = "Perfect for busy professionals, students, freelancers, and anyone who wants to get organized."
    elif "MUSIC" in cats:
        perfect = "Perfect for musicians, students, teachers, and anyone learning an instrument."
    else:
        perfect = f"Perfect for anyone looking for a reliable, well-designed app that just works."
    sections.append(perfect)
    sections.append("")

    # Subscription mention
    if has_sub:
        sections.append(f"{app_name} offers a free version with core features. Unlock the full experience with a subscription that gives you access to all premium features.")
        sections.append("")
        sections.append("Payment will be charged to your Apple ID account at confirmation of purchase. Subscription automatically renews unless it is canceled at least 24 hours before the end of the current period. Your account will be charged for renewal within 24 hours prior to the end of the current period. You can manage and cancel your subscriptions by going to your account settings on the App Store after purchase.")
        sections.append("")
        sections.append("Terms of Use: https://www.apple.com/legal/internet-services/itunes/dev/stdeula/")
        sections.append("")

    # CTA
    sections.append(f"Download {app_name} today and see the difference for yourself.")

    desc = "\n".join(sections)
    return desc[:limit]


def generate_promo_text(analysis, app_name, limit=170):
    """Generate promotional text with clear value prop + CTA."""
    cats = analysis.get("category_hints", [])

    if "FINANCE" in cats:
        text = f"Track stocks and markets in real time with {app_name}. Your investments, always at your fingertips. Try it now!"
    elif "HEALTH_AND_FITNESS" in cats:
        text = f"Reach your fitness goals faster with {app_name}. Track workouts, monitor progress, and stay motivated. Start today!"
    elif "PRODUCTIVITY" in cats:
        text = f"Get organized and stay productive with {app_name}. Plan your day, track your tasks, and achieve more. Try it free!"
    elif "MUSIC" in cats:
        text = f"Practice smarter with {app_name}. Tune, track tempo, and improve your skills every day. Download now!"
    elif "EDUCATION" in cats:
        text = f"Study smarter with {app_name}. Quiz yourself, track progress, and ace your exams. Get started today!"
    else:
        text = f"Discover {app_name} — simple, powerful, and designed for you. Download now and see the difference!"

    return text[:limit]


def get_current_metadata(app_id):
    """Fetch current metadata from ASC. Returns dict with title, subtitle, keywords, description, promoText."""
    result = {"title": "", "subtitle": "", "keywords": "", "description": "", "promotionalText": ""}

    # Get app name
    app_resp = api("GET", f"/apps/{app_id}?fields[apps]=name")
    if app_resp and app_resp.get("data"):
        result["title"] = app_resp["data"]["attributes"].get("name", "")

    # Get version localizations
    versions = api("GET", f"/apps/{app_id}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString,appStoreState")
    if versions and versions["data"]:
        ver_id = versions["data"][0]["id"]
        locs = api("GET", f"/appStoreVersions/{ver_id}/appStoreVersionLocalizations")
        if locs:
            for loc in locs["data"]:
                a = loc["attributes"]
                if a["locale"] == "en-US":
                    result["keywords"] = a.get("keywords") or ""
                    result["description"] = a.get("description") or ""
                    result["promotionalText"] = a.get("promotionalText") or ""
                    break

    # Get subtitle from app info
    infos = api("GET", f"/apps/{app_id}/appInfos")
    if infos and infos["data"]:
        info_id = infos["data"][0]["id"]
        # Try to get primary category too
        info_locs = api("GET", f"/appInfos/{info_id}/appInfoLocalizations")
        if info_locs:
            for loc in info_locs["data"]:
                if loc["attributes"]["locale"] == "en-US":
                    result["subtitle"] = loc["attributes"].get("subtitle") or ""
                    break

    return result


def cmd_optimize(app_id, project_path, apply=False):
    """Generate ASO-optimized metadata by analyzing app code and current ASC metadata."""
    print("🔍 Analyzing project...")
    analysis = analyze_project(project_path)

    print(f"  Views: {len(analysis['view_names'])}")
    print(f"  Models: {len(analysis['model_names'])}")
    print(f"  Tabs: {analysis['tab_names']}")
    print(f"  Integrations: {analysis['integrations']}")
    print(f"  Features: {analysis['features'][:5]}")
    print(f"  Category hints: {analysis['category_hints']}")
    print(f"  Has subscription: {analysis['has_subscription']}")

    print("\n📡 Fetching current metadata from ASC...")
    current = get_current_metadata(app_id)
    app_name = current["title"] or "App"
    print(f"  App: {app_name}")

    # Extract keywords from code
    feature_kws = extract_keywords_from_features(analysis)
    print(f"\n🔑 Extracted {len(feature_kws)} keywords from code: {sorted(feature_kws)[:15]}")

    # Get category keyword pool
    category_pool = []
    for cat in analysis["category_hints"]:
        category_pool.extend(CATEGORY_KEYWORDS.get(cat, []))
    if not category_pool:
        category_pool = CATEGORY_KEYWORDS.get("PRODUCTIVITY", [])  # fallback

    # Title words for dedup
    title_words = [w for w in re.split(r'[\s\-:]+', app_name) if len(w) > 2]

    # Generate optimized keywords
    new_keywords = build_keyword_field(
        list(feature_kws), category_pool, title_words, [], limit=100
    )

    # Generate subtitle (exclude keyword words too)
    kw_words = new_keywords.split(",")
    new_subtitle = generate_subtitle(analysis, title_words, kw_words)

    # Rebuild keywords deduplicating against subtitle too
    subtitle_words = [w for w in re.split(r'[\s\-:]+', new_subtitle) if len(w) > 2]
    new_keywords = build_keyword_field(
        list(feature_kws), category_pool, title_words, subtitle_words, limit=100
    )

    # Generate description and promo text
    new_description = generate_description(analysis, app_name, new_subtitle, new_keywords)
    new_promo = generate_promo_text(analysis, app_name)

    # Build optimized metadata
    optimized = {
        "locale": "en-US",
        "subtitle": new_subtitle,
        "keywords": new_keywords,
        "description": new_description,
        "promotionalText": new_promo,
    }

    # Print before/after comparison
    print("\n" + "=" * 60)
    print("📊 BEFORE / AFTER COMPARISON")
    print("=" * 60)

    print(f"\n🏷️  TITLE (unchanged): {app_name}")

    print(f"\n📌 SUBTITLE ({len(new_subtitle)} chars):")
    print(f"  Before: {current['subtitle'] or '(empty)'}")
    print(f"  After:  {new_subtitle}")

    print(f"\n🔑 KEYWORDS ({len(new_keywords)} chars):")
    print(f"  Before: {current['keywords'] or '(empty)'}")
    print(f"  After:  {new_keywords}")

    print(f"\n📝 DESCRIPTION ({len(new_description)} chars):")
    print(f"  Before: {(current['description'] or '(empty)')[:100]}...")
    print(f"  After:  {new_description[:100]}...")

    print(f"\n📣 PROMO TEXT ({len(new_promo)} chars):")
    print(f"  Before: {current['promotionalText'] or '(empty)'}")
    print(f"  After:  {new_promo}")

    # Run guardrails
    print("\n🛡️  Running guardrails...")
    warnings = validate_metadata(optimized)
    if warnings:
        for w in warnings:
            print(f"  {w}")
        if any(w.startswith("❌") for w in warnings):
            print("\n❌ Guardrail errors found — not saving.")
            return
    else:
        print("  ✅ All checks passed")

    # Save to file
    safe_name = re.sub(r'[^a-zA-Z0-9]', '-', app_name).strip('-').lower()
    output_path = f"/tmp/{safe_name}-aso-metadata.json"
    with open(output_path, "w") as f:
        json.dump(optimized, f, indent=2)
    print(f"\n💾 Saved to {output_path}")

    # Apply if requested
    if apply:
        print("\n☁️  Uploading optimized metadata to ASC...")
        cmd_set(app_id, output_path, force=True)
    else:
        print(f"\n💡 To apply: python3 asc-metadata.py optimize {app_id} {project_path} --apply")


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
    elif cmd == "optimize" and len(sys.argv) > 3:
        cmd_optimize(sys.argv[2], sys.argv[3], apply="--apply" in sys.argv)
    else:
        print(__doc__)
