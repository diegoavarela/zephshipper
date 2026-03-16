#!/usr/bin/env python3
"""
ZephShipper Subscription Flow Manager
Handles: screenshot upload, first-time linking to version, submission
Usage: sub-flow.py <app_id> [--screenshot <path>] [--dry-run]
"""

import jwt, time, urllib.request, json, sys, os, hashlib, argparse

# ── Config ──────────────────────────────────────────────────────────
KEY_ID = "AA5UCQU456"
ISSUER_ID = "638c67e6-9365-4b3f-8250-474197f6f1a1"
KEY_PATH = os.path.expanduser("~/.appstoreconnect/private_keys/AuthKey_AA5UCQU456.p8")
BASE = "https://api.appstoreconnect.apple.com/v1"


def get_token():
    key = open(KEY_PATH).read()
    return jwt.encode(
        {"iss": ISSUER_ID, "iat": int(time.time()), "exp": int(time.time()) + 1200, "aud": "appstoreconnect-v1"},
        key, algorithm="ES256", headers={"kid": KEY_ID}
    )


def api(method, path, data=None, token=None):
    if token is None:
        token = get_token()
    url = f"{BASE}{path}" if path.startswith("/") else path
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        raw = resp.read()
        if not raw or len(raw) == 0:
            return {}
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            err_body = json.loads(raw)
            return {"error": True, "status": e.code, "errors": err_body.get("errors", [])}
        except:
            return {"error": True, "status": e.code, "errors": [{"detail": raw[:200]}]}


def ok(msg): print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️  {msg}")
def fail(msg): print(f"  ❌ {msg}")
def info(msg): print(f"  ℹ️  {msg}")


# ── Subscription Discovery ──────────────────────────────────────────
def get_subscriptions(app_id, token):
    """Get all subscriptions for an app with their states."""
    subs = []
    groups = api("GET", f"/apps/{app_id}/subscriptionGroups", token=token)
    if "error" in groups:
        return subs
    for g in groups.get("data", []):
        group_id = g["id"]
        group_name = g["attributes"].get("referenceName", "")
        group_subs = api("GET", f"/subscriptionGroups/{group_id}/subscriptions", token=token)
        for s in group_subs.get("data", []):
            a = s["attributes"]
            subs.append({
                "id": s["id"],
                "product_id": a.get("productId", ""),
                "name": a.get("name", a.get("productId", "")),
                "state": a.get("state", "UNKNOWN"),
                "group_id": group_id,
                "group_name": group_name,
            })
    return subs


def check_screenshot(sub_id, token):
    """Check if subscription has a valid review screenshot."""
    resp = api("GET", f"/subscriptions/{sub_id}/appStoreReviewScreenshot", token=token)
    if "error" in resp:
        return None
    data = resp.get("data")
    if not data:
        return None
    state = data.get("attributes", {}).get("assetDeliveryState", {}).get("state", "")
    return {"id": data["id"], "state": state}


def delete_screenshot(ss_id, token):
    """Delete a failed screenshot."""
    api("DELETE", f"/subscriptionAppStoreReviewScreenshots/{ss_id}", token=token)


def upload_screenshot(sub_id, img_path, token):
    """Upload a review screenshot for a subscription."""
    with open(img_path, "rb") as f:
        img_data = f.read()

    # Reserve
    reserve = api("POST", "/subscriptionAppStoreReviewScreenshots", {
        "data": {
            "type": "subscriptionAppStoreReviewScreenshots",
            "attributes": {"fileName": os.path.basename(img_path), "fileSize": len(img_data)},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sub_id}}}
        }
    }, token=token)

    if "error" in reserve:
        return False, reserve["errors"][0]["detail"] if reserve["errors"] else "Unknown error"

    ss_id = reserve["data"]["id"]
    ops = reserve["data"]["attributes"]["uploadOperations"]

    # Upload chunks
    for op in ops:
        headers = {h["name"]: h["value"] for h in op["requestHeaders"]}
        chunk = img_data[op["offset"]:op["offset"] + op["length"]]
        urllib.request.urlopen(urllib.request.Request(op["url"], data=chunk, method=op["method"], headers=headers))

    # Commit
    api("PATCH", f"/subscriptionAppStoreReviewScreenshots/{ss_id}", {
        "data": {
            "type": "subscriptionAppStoreReviewScreenshots",
            "id": ss_id,
            "attributes": {"uploaded": True, "sourceFileChecksum": None}
        }
    }, token=token)

    return True, ss_id


# ── Screenshot Generation ───────────────────────────────────────────
def generate_placeholder_screenshot(output_path, app_name="App"):
    """Generate a minimal placeholder paywall screenshot (640x920 PNG)."""
    import struct, zlib

    W, H = 640, 920

    def pixel(x, y):
        r, g, b = 20, 20, 20  # dark bg
        # Header area
        if 80 < y < 110 and 200 < x < 440:
            r, g, b = 240, 240, 240
        # Blue accent button
        if 550 < y < 590 and 60 < x < 580:
            t = (x - 60) / 520
            r, g, b = int(0 + t * 120), int(100 + t * 20), int(255 - t * 30)
        # Card outlines
        for cy, color in [(350, (0, 122, 255)), (440, (60, 60, 60))]:
            if cy - 35 < y < cy + 35 and 40 < x < 600:
                if y < cy - 33 or y > cy + 33 or x < 42 or x > 598:
                    r, g, b = color
                else:
                    r, g, b = 30, 30, 30
        # Feature dots
        for i in range(6):
            dy = 170 + i * 24
            if abs(y - dy) < 3 and abs(x - 55) < 3:
                r, g, b = 0, 122, 255
            if abs(y - dy) < 5 and 70 < x < 300:
                r, g, b = 140, 140, 140
        return struct.pack("BBBB", r, g, b, 255)

    def chunk(ct, data):
        c = ct + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b""
    for y in range(H):
        raw += b"\x00"
        for x in range(W):
            raw += pixel(x, y)

    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(raw)) +
           chunk(b"IEND", b""))

    with open(output_path, "wb") as f:
        f.write(png)
    return output_path


# ── Version & Submission Management ─────────────────────────────────
def get_inflight_versions(app_id, token):
    """Get PREPARE_FOR_SUBMISSION versions."""
    versions = []
    for platform in ["IOS", "MAC_OS"]:
        resp = api("GET", f"/apps/{app_id}/appStoreVersions?filter[appStoreState]=PREPARE_FOR_SUBMISSION,DEVELOPER_REJECTED,READY_FOR_REVIEW&filter[platform]={platform}", token=token)
        for v in resp.get("data", []):
            versions.append({
                "id": v["id"],
                "version": v["attributes"]["versionString"],
                "platform": platform,
                "state": v["attributes"]["appStoreState"],
            })
    return versions


def get_latest_build(app_id, token, limit=5):
    """Get latest builds sorted by upload date."""
    resp = api("GET", f"/builds?filter[app]={app_id}&sort=-uploadedDate&limit={limit}", token=token)
    builds = []
    for b in resp.get("data", []):
        a = b["attributes"]
        builds.append({
            "id": b["id"],
            "version": a.get("version", ""),
            "state": a.get("processingState", ""),
        })
    return builds


def attach_build_to_version(version_id, build_id, token):
    """Attach a build to a version."""
    resp = api("PATCH", f"/appStoreVersions/{version_id}", {
        "data": {
            "type": "appStoreVersions",
            "id": version_id,
            "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}
        }
    }, token=token)
    return "error" not in resp


def set_encryption(build_id, token):
    """Set usesNonExemptEncryption to false."""
    api("PATCH", f"/builds/{build_id}", {
        "data": {"type": "builds", "id": build_id, "attributes": {"usesNonExemptEncryption": False}}
    }, token=token)


def cleanup_submissions(app_id, token):
    """Cancel/resolve zombie submissions."""
    resp = api("GET", f"/reviewSubmissions?filter[app]={app_id}", token=token)
    cleaned = 0
    for s in resp.get("data", []):
        state = s["attributes"]["state"]
        sid = s["id"]

        if state == "UNRESOLVED_ISSUES":
            # Resolve items
            items = api("GET", f"/reviewSubmissions/{sid}/items", token=token)
            for item in items.get("data", []):
                api("PATCH", f"/reviewSubmissionItems/{item['id']}", {
                    "data": {"type": "reviewSubmissionItems", "id": item["id"], "attributes": {"resolved": True}}
                }, token=token)
            cleaned += 1

        elif state == "READY_FOR_REVIEW":
            # Check if empty
            items = api("GET", f"/reviewSubmissions/{sid}/items", token=token)
            if len(items.get("data", [])) == 0:
                # Cancel empty ones
                api("PATCH", f"/reviewSubmissions/{sid}", {
                    "data": {"type": "reviewSubmissions", "id": sid, "attributes": {"canceled": True}}
                }, token=token)
                cleaned += 1

    return cleaned


def submit_version(app_id, version_id, platform, token):
    """Create review submission and submit."""
    # Create submission
    resp = api("POST", "/reviewSubmissions", {
        "data": {
            "type": "reviewSubmissions",
            "attributes": {"platform": platform},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}
        }
    }, token=token)

    if "error" in resp:
        return False, resp["errors"][0]["detail"] if resp["errors"] else "Unknown"

    sub_id = resp["data"]["id"]

    # Add version item
    resp = api("POST", "/reviewSubmissionItems", {
        "data": {
            "type": "reviewSubmissionItems",
            "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub_id}},
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
            }
        }
    }, token=token)

    if "error" in resp:
        return False, resp["errors"][0]["detail"] if resp["errors"] else "Could not add version"

    # Submit
    resp = api("PATCH", f"/reviewSubmissions/{sub_id}", {
        "data": {"type": "reviewSubmissions", "id": sub_id, "attributes": {"submitted": True}}
    }, token=token)

    if "error" in resp:
        return False, resp["errors"][0]["detail"] if resp["errors"] else "Submit failed"

    return True, resp["data"]["attributes"]["state"]


def try_submit_subs_api(subs, token):
    """Try to submit subscriptions via API (works for non-first-time)."""
    results = {}
    for sub in subs:
        if sub["state"] not in ("READY_TO_SUBMIT",):
            results[sub["product_id"]] = {"ok": True, "state": sub["state"]}
            continue

        resp = api("POST", "/subscriptionSubmissions", {
            "data": {
                "type": "subscriptionSubmissions",
                "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sub["id"]}}}
            }
        }, token=token)

        if "error" in resp:
            detail = resp["errors"][0]["detail"] if resp["errors"] else ""
            results[sub["product_id"]] = {"ok": False, "error": detail}
        else:
            results[sub["product_id"]] = {"ok": True, "state": "SUBMITTED"}

    return results


# ── Main Flow ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ZephShipper Subscription Flow")
    parser.add_argument("app_id", help="App Store Connect App ID")
    parser.add_argument("--screenshot", help="Path to paywall screenshot (auto-generates if not provided)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--skip-submit", action="store_true", help="Only fix subs, don't submit version")
    args = parser.parse_args()

    print("\n💰 ZephShipper — Subscription Flow")
    print("=" * 40)

    token = get_token()

    # 1. Discover subscriptions
    info("Checking subscriptions...")
    subs = get_subscriptions(args.app_id, token)

    if not subs:
        ok("No subscriptions found — nothing to do")
        return 0

    print(f"\n  Found {len(subs)} subscription(s):")
    needs_work = False
    for s in subs:
        state_icon = "✅" if s["state"] == "APPROVED" else "⚠️" if s["state"] == "WAITING_FOR_REVIEW" else "❌"
        print(f"    {state_icon} {s['product_id']} — {s['state']}")
        if s["state"] not in ("APPROVED", "WAITING_FOR_REVIEW"):
            needs_work = True

    if not needs_work:
        ok("All subscriptions already approved or in review")
        return 0

    # 2. Check/fix screenshots
    print()
    info("Checking review screenshots...")
    screenshot_path = args.screenshot

    for s in subs:
        if s["state"] in ("APPROVED", "WAITING_FOR_REVIEW"):
            continue

        ss = check_screenshot(s["id"], token)

        if ss and ss["state"] == "COMPLETE":
            ok(f"{s['product_id']}: screenshot OK")
            continue

        if ss and ss["state"] == "FAILED":
            warn(f"{s['product_id']}: screenshot FAILED — deleting")
            if not args.dry_run:
                delete_screenshot(ss["id"], token)

        # Upload screenshot
        if not screenshot_path:
            screenshot_path = "/tmp/zephshipper-paywall.png"
            if not os.path.exists(screenshot_path):
                info("Generating placeholder screenshot...")
                generate_placeholder_screenshot(screenshot_path)

        info(f"Uploading screenshot for {s['product_id']}...")
        if args.dry_run:
            info(f"[DRY-RUN] Would upload {screenshot_path}")
            continue

        success, result = upload_screenshot(s["id"], screenshot_path, token)
        if success:
            ok(f"{s['product_id']}: screenshot uploaded")
        else:
            fail(f"{s['product_id']}: upload failed — {result}")
            return 1

    # Wait for screenshots to process
    if not args.dry_run:
        time.sleep(3)
        # Verify all screenshots are COMPLETE
        for s in subs:
            if s["state"] in ("APPROVED", "WAITING_FOR_REVIEW"):
                continue
            ss = check_screenshot(s["id"], token)
            if not ss or ss["state"] != "COMPLETE":
                fail(f"{s['product_id']}: screenshot not ready (state: {ss['state'] if ss else 'MISSING'})")
                return 1

    # 3. Try API submission first
    print()
    info("Attempting API submission...")

    if args.dry_run:
        info("[DRY-RUN] Would try API submission")
    else:
        results = try_submit_subs_api(subs, token)
        all_ok = all(r["ok"] for r in results.values())

        if all_ok:
            ok("Subscriptions submitted via API!")
            for pid, r in results.items():
                ok(f"  {pid}: {r.get('state', 'OK')}")
            print()
            print("  📝 RESULT: api_submitted")
            return 0

        # Check if it's a first-time issue
        first_time = any("cannot be reviewed" in r.get("error", "").lower() for r in results.values() if not r["ok"])

        if first_time:
            warn("First-time subscriptions — need to link via version page (web UI)")
            print()
            print("  📝 RESULT: needs_browser_flow")
            # Output sub IDs for the caller to handle
            for s in subs:
                if s["state"] in ("READY_TO_SUBMIT", "MISSING_METADATA"):
                    print(f"  SUB_ID: {s['id']} | {s['product_id']}")
            return 2  # Special exit code: needs browser
        else:
            for pid, r in results.items():
                if not r["ok"]:
                    fail(f"  {pid}: {r.get('error', 'unknown')}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
