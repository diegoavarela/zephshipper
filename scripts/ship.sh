#!/bin/bash
# ZephShipper ship.sh — Full app shipping pipeline
# Usage: ship.sh <project_path> [--resume-from <step>] [--version <x.y.z>] [--whats-new "text"] [--dry-run]

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VALIDATE="$SCRIPT_DIR/validate.sh"
BUMP_BUILD="$SCRIPT_DIR/bump-build.sh"
ASC_META="$SCRIPT_DIR/asc-metadata.py"

KEY_ID="AA5UCQU456"
ISSUER_ID="638c67e6-9365-4b3f-8250-474197f6f1a1"
KEY_PATH="$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8"
TEAM_ID="LFAGCRNVLW"

TEMP_DIR="/tmp/zephshipper"
MAX_RETRIES=3

STEPS=(detect validate iap bump archive upload metadata optimize submit)
STEP_LABELS=("🔍 Detect Project" "✅ Validate" "💰 IAP Check" "🔢 Bump Build" "📦 Archive" "☁️  Upload" "📝 Metadata Check" "🔑 ASO Optimize" "🚀 Submit")

# ── Parse Args ──────────────────────────────────────────────────────
PROJECT_PATH=""
RESUME_FROM=""
VERSION=""
WHATS_NEW=""
DRY_RUN=false
OPTIMIZE_ASO=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --resume-from) RESUME_FROM="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --whats-new) WHATS_NEW="$2"; shift 2 ;;
        --optimize-aso) OPTIMIZE_ASO=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help)
            echo "Usage: ship.sh <project_path> [--resume-from <step>] [--version <x.y.z>] [--whats-new \"text\"] [--dry-run]"
            echo "Steps: ${STEPS[*]}"
            exit 0 ;;
        *) PROJECT_PATH="$1"; shift ;;
    esac
done

if [[ -z "$PROJECT_PATH" ]]; then
    echo "❌ Usage: ship.sh <project_path> [options]"
    exit 1
fi

PROJECT_PATH="$(cd "$PROJECT_PATH" && pwd)"
mkdir -p "$TEMP_DIR"

# ── State ───────────────────────────────────────────────────────────
XCPROJECT=""
XCWORKSPACE=""
PROJECT_FLAG=""  # -project or -workspace + path
SCHEME=""
PLATFORMS=()     # ios, macos
BUNDLE_ID=""
APP_ID=""
ARCHIVE_PATHS=()
STEP_RESULTS=()  # pass/fail/skip per step

# ── Helpers ─────────────────────────────────────────────────────────
log()  { echo ""; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "  $1"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
ok()   { echo "  ✅ $1"; }
warn() { echo "  ⚠️  $1"; }
fail() { echo "  ❌ $1"; }
info() { echo "  ℹ️  $1"; }

should_skip() {
    local step="$1"
    if [[ -n "$RESUME_FROM" ]]; then
        for s in "${STEPS[@]}"; do
            [[ "$s" == "$RESUME_FROM" ]] && RESUME_FROM="" && return 1
            [[ "$s" == "$step" ]] && return 0
        done
    fi
    return 1
}

retry() {
    local max=$1; shift
    local attempt=1
    while [[ $attempt -le $max ]]; do
        if "$@"; then return 0; fi
        warn "Attempt $attempt/$max failed, retrying..."
        attempt=$((attempt + 1))
    done
    return 1
}

# ── Step 1: Detect ──────────────────────────────────────────────────
step_detect() {
    log "${STEP_LABELS[0]}"
    info "Project: $PROJECT_PATH"
    cd "$PROJECT_PATH"

    # Find xcodeproj
    XCPROJECT=$(find . -maxdepth 1 -name "*.xcodeproj" -type d | head -1)
    if [[ -z "$XCPROJECT" ]]; then
        fail "No .xcodeproj found"; return 1
    fi
    XCPROJECT="$(pwd)/$XCPROJECT"

    # Check for workspace (prefer if CocoaPods)
    local ws=$(find . -maxdepth 1 -name "*.xcworkspace" -type d | head -1)
    if [[ -n "$ws" && -d "Pods" ]]; then
        XCWORKSPACE="$(pwd)/$ws"
        PROJECT_FLAG="-workspace $XCWORKSPACE"
        info "Workspace: $XCWORKSPACE (CocoaPods detected)"
    else
        PROJECT_FLAG="-project $XCPROJECT"
        info "Project: $XCPROJECT"
    fi

    # Detect scheme
    SCHEME=$(xcodebuild -list $PROJECT_FLAG 2>/dev/null | awk '/Schemes:/{f=1;next} f && NF{print; exit}' | xargs)
    if [[ -z "$SCHEME" ]]; then
        fail "No scheme found"; return 1
    fi
    ok "Scheme: $SCHEME"

    # Detect platform from pbxproj
    local pbx="$XCPROJECT/project.pbxproj"
    local has_ios=false has_mac=false

    if grep -q "SUPPORTED_PLATFORMS.*iphone" "$pbx" 2>/dev/null || grep -q "SDKROOT.*iphoneos" "$pbx" 2>/dev/null; then
        has_ios=true
    fi
    if grep -q "SUPPORTED_PLATFORMS.*macosx" "$pbx" 2>/dev/null || grep -q "SDKROOT.*macosx" "$pbx" 2>/dev/null; then
        has_mac=true
    fi

    if $has_ios && $has_mac; then
        PLATFORMS=(ios macos)
    elif $has_mac; then
        PLATFORMS=(macos)
    elif $has_ios; then
        PLATFORMS=(ios)
    else
        # Fallback: try build settings
        local sdk=$(xcodebuild $PROJECT_FLAG -scheme "$SCHEME" -showBuildSettings 2>/dev/null | grep "SDKROOT " | head -1 | awk '{print $NF}')
        if [[ "$sdk" == *"macos"* ]]; then
            PLATFORMS=(macos)
        else
            PLATFORMS=(ios)
        fi
    fi
    ok "Platforms: ${PLATFORMS[*]}"

    # Get bundle ID
    BUNDLE_ID=$(xcodebuild $PROJECT_FLAG -scheme "$SCHEME" -showBuildSettings 2>/dev/null | grep "PRODUCT_BUNDLE_IDENTIFIER" | head -1 | awk '{print $NF}')
    if [[ -z "$BUNDLE_ID" ]]; then
        fail "Could not detect bundle ID"; return 1
    fi
    ok "Bundle ID: $BUNDLE_ID"

    # Get ASC App ID
    if $DRY_RUN; then
        info "[DRY-RUN] Skipping ASC app ID lookup"
        APP_ID="DRY_RUN_APP_ID"
    else
        APP_ID=$(python3 "$ASC_META" apps 2>/dev/null | grep "$BUNDLE_ID" | awk -F' \\| ' '{print $1}' | xargs)
        if [[ -z "$APP_ID" ]]; then
            warn "Could not find ASC app for $BUNDLE_ID (new app?)"
        else
            ok "ASC App ID: $APP_ID"
        fi
    fi

    return 0
}

# ── Step 2: Validate ────────────────────────────────────────────────
step_validate() {
    log "${STEP_LABELS[1]}"

    if $DRY_RUN; then
        info "[DRY-RUN] Would run: validate.sh $PROJECT_PATH"; return 0
    fi

    local output
    output=$("$VALIDATE" "$PROJECT_PATH" 2>&1) || {
        fail "Validation failed (blocker issues found)"
        echo "$output" | grep -E "❌|error:" | head -10
        return 1
    }
    ok "Validation passed"
    return 0
}

# ── Step 2.5: IAP Check ─────────────────────────────────────────────
step_iap() {
    log "${STEP_LABELS[2]}"

    if [[ -z "$APP_ID" || "$APP_ID" == "DRY_RUN_APP_ID" ]]; then
        if $DRY_RUN; then
            info "[DRY-RUN] Would check IAPs"; return 0
        fi
        info "No ASC App ID yet — skipping IAP check (new app?)"
        return 0
    fi

    if $DRY_RUN; then
        info "[DRY-RUN] Would check IAPs for $APP_ID"; return 0
    fi

    # Check if app references IAP/subscription in code
    local has_iap_code=false
    if grep -rq "RevenueCat\|StoreKit\|Purchases\|Product\.\|\.purchase\|paywall\|PRO\|premium\|subscription" "$PROJECT_PATH" --include="*.swift" 2>/dev/null; then
        has_iap_code=true
    fi

    if ! $has_iap_code; then
        ok "No IAP/subscription references found in code — skipping"
        return 0
    fi

    info "IAP/subscription references detected in code — checking ASC..."

    # List IAPs for this app
    local iap_json
    iap_json=$(asc iap list --app "$APP_ID" --output json 2>/dev/null || echo "[]")

    local iap_count
    iap_count=$(echo "$iap_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")

    if [[ "$iap_count" == "0" ]]; then
        # Also check subscriptions
        local sub_json
        sub_json=$(asc subscriptions list --app "$APP_ID" --output json 2>/dev/null || echo "[]")
        local sub_count
        sub_count=$(echo "$sub_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")

        if [[ "$sub_count" == "0" ]]; then
            fail "Code references IAP/subscriptions but NONE found in App Store Connect!"
            info "Create your IAPs/subscriptions in ASC before shipping."
            info "Use: asc iap create --app $APP_ID --type <TYPE> --ref-name <NAME> --product-id <ID>"
            return 1
        fi
    fi

    ok "Found $iap_count IAP(s) in App Store Connect"

    # Check each IAP has a review screenshot
    local missing_screenshots=()
    local iap_ids
    iap_ids=$(echo "$iap_json" | python3 -c "
import json,sys
data=json.load(sys.stdin)
for iap in (data if isinstance(data,list) else []):
    iap_id = iap.get('id','')
    name = iap.get('attributes',{}).get('referenceName','') or iap.get('attributes',{}).get('name','')
    state = iap.get('attributes',{}).get('state','')
    print(f'{iap_id}|{name}|{state}')
" 2>/dev/null)

    local needs_submit=()
    while IFS='|' read -r iap_id iap_name iap_state; do
        [[ -z "$iap_id" ]] && continue

        # Check review screenshot
        local screenshot
        screenshot=$(asc iap review-screenshots get --iap-id "$iap_id" --output json 2>/dev/null || echo "{}")
        local has_screenshot
        has_screenshot=$(echo "$screenshot" | python3 -c "
import json,sys
d=json.load(sys.stdin)
# If it's a dict with 'id' or a non-empty list, screenshot exists
if isinstance(d, list): print('yes' if len(d)>0 else 'no')
elif isinstance(d, dict) and d.get('id'): print('yes')
else: print('no')
" 2>/dev/null || echo "no")

        if [[ "$has_screenshot" == "no" ]]; then
            missing_screenshots+=("$iap_name ($iap_id)")
            warn "IAP '$iap_name' missing review screenshot!"
        else
            ok "IAP '$iap_name' has review screenshot"
        fi

        # Check if IAP needs to be submitted for review
        if [[ "$iap_state" != "APPROVED" && "$iap_state" != "WAITING_FOR_REVIEW" ]]; then
            needs_submit+=("$iap_id|$iap_name")
        fi
    done <<< "$iap_ids"

    # Block if screenshots missing
    if [[ ${#missing_screenshots[@]} -gt 0 ]]; then
        fail "IAPs missing review screenshots: ${missing_screenshots[*]}"
        info "Upload screenshots: asc iap review-screenshots create --iap-id <ID> --file ./screenshot.png"
        info "Apple REQUIRES review screenshots for IAP submission."
        return 1
    fi

    # Auto-submit IAPs that need review
    if [[ ${#needs_submit[@]} -gt 0 ]]; then
        for entry in "${needs_submit[@]}"; do
            IFS='|' read -r iap_id iap_name <<< "$entry"
            info "Submitting IAP '$iap_name' for review..."
            if asc iap submit --iap-id "$iap_id" --confirm 2>&1; then
                ok "IAP '$iap_name' submitted for review"
            else
                warn "Could not submit IAP '$iap_name' — may need manual action"
            fi
        done
    fi

    ok "IAP validation complete"
    return 0
}

# ── Step 3: Bump Build ──────────────────────────────────────────────
step_bump() {
    log "${STEP_LABELS[2]}"

    if $DRY_RUN; then
        info "[DRY-RUN] Would run: bump-build.sh $PROJECT_PATH"
        [[ -n "$VERSION" ]] && info "[DRY-RUN] Would set MARKETING_VERSION=$VERSION"
        return 0
    fi

    "$BUMP_BUILD" "$PROJECT_PATH" || { fail "Build bump failed"; return 1; }

    # Set marketing version if requested
    if [[ -n "$VERSION" ]]; then
        local pbx="$XCPROJECT/project.pbxproj"
        # Replace MARKETING_VERSION in pbxproj
        if grep -q "MARKETING_VERSION" "$pbx"; then
            sed -i '' "s/MARKETING_VERSION = [^;]*;/MARKETING_VERSION = $VERSION;/g" "$pbx"
            ok "Marketing version set to $VERSION"
        else
            # Try Info.plist
            local plist
            plist=$(xcodebuild $PROJECT_FLAG -scheme "$SCHEME" -showBuildSettings 2>/dev/null | grep "INFOPLIST_FILE" | head -1 | awk '{print $NF}')
            if [[ -n "$plist" && -f "$PROJECT_PATH/$plist" ]]; then
                /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PROJECT_PATH/$plist" 2>/dev/null && \
                    ok "Marketing version set to $VERSION (Info.plist)" || \
                    warn "Could not set version in Info.plist"
            fi
        fi
    fi

    return 0
}

# ── Step 4: Archive ─────────────────────────────────────────────────
do_archive() {
    local platform="$1"
    local dest archive_path

    if [[ "$platform" == "ios" ]]; then
        dest="generic/platform=iOS"
        archive_path="$TEMP_DIR/${SCHEME}-iOS.xcarchive"
    else
        dest="generic/platform=macOS"
        archive_path="$TEMP_DIR/${SCHEME}-macOS.xcarchive"
    fi

    info "Archiving for $platform → $archive_path"

    local cmd=(xcodebuild archive
        $PROJECT_FLAG
        -scheme "$SCHEME"
        -destination "$dest"
        -archivePath "$archive_path"
        -configuration Release
        DEVELOPMENT_TEAM="$TEAM_ID"
        CODE_SIGN_STYLE=Automatic
    )

    local output attempt=0
    while [[ $attempt -lt $MAX_RETRIES ]]; do
        output=$("${cmd[@]}" 2>&1) && {
            ARCHIVE_PATHS+=("$archive_path")
            ok "Archive succeeded: $platform"
            return 0
        }

        # Auto-fix: signing
        if echo "$output" | grep -qi "signing\|provisioning\|code sign"; then
            warn "Signing issue detected, retrying with -allowProvisioningUpdates"
            cmd+=(-allowProvisioningUpdates)
        fi

        # Auto-fix: destination
        if echo "$output" | grep -qi "Unable to find a destination"; then
            if [[ "$platform" == "ios" ]]; then
                warn "Trying alternate iOS destination"
                dest="generic/platform=iOS Simulator"
                # Actually for archive we need device, try without destination specificity
                dest="generic/platform=iOS"
            else
                dest="generic/platform=macOS,variant=Mac Catalyst"
            fi
            cmd=("${cmd[@]/generic\/platform=*/}")
            cmd=(xcodebuild archive $PROJECT_FLAG -scheme "$SCHEME" -destination "$dest" -archivePath "$archive_path" -configuration Release DEVELOPMENT_TEAM="$TEAM_ID" CODE_SIGN_STYLE=Automatic -allowProvisioningUpdates)
        fi

        attempt=$((attempt + 1))
        warn "Archive attempt $attempt/$MAX_RETRIES failed"
    done

    fail "Archive failed for $platform after $MAX_RETRIES attempts"
    echo "$output" | grep -E "error:" | head -10
    return 1
}

step_archive() {
    log "${STEP_LABELS[3]}"

    if $DRY_RUN; then
        for p in "${PLATFORMS[@]}"; do
            info "[DRY-RUN] Would archive for $p"
            ARCHIVE_PATHS+=("$TEMP_DIR/${SCHEME}-${p}.xcarchive")
        done
        return 0
    fi

    for p in "${PLATFORMS[@]}"; do
        do_archive "$p" || return 1
    done
    return 0
}

# ── Step 5: Upload ──────────────────────────────────────────────────
do_upload() {
    local archive_path="$1"
    local platform="$2"
    local export_path="$TEMP_DIR/export-${platform}"
    mkdir -p "$export_path"

    # Create export options plist
    local plist="$TEMP_DIR/export-options-${platform}.plist"
    local method="app-store"
    local dest="upload"

    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>${method}</string>
    <key>destination</key>
    <string>${dest}</string>
    <key>teamID</key>
    <string>${TEAM_ID}</string>
    <key>uploadSymbols</key>
    <true/>
    <key>signingStyle</key>
    <string>automatic</string>
</dict>
</plist>
PLIST

    local attempt=0
    while [[ $attempt -lt $MAX_RETRIES ]]; do
        local output
        output=$(xcodebuild -exportArchive \
            -archivePath "$archive_path" \
            -exportOptionsPlist "$plist" \
            -exportPath "$export_path" \
            -authenticationKeyPath "$KEY_PATH" \
            -authenticationKeyID "$KEY_ID" \
            -authenticationKeyIssuerID "$ISSUER_ID" \
            -allowProvisioningUpdates 2>&1) && {
            ok "Upload succeeded: $platform"
            return 0
        }

        # Auto-fix: duplicate build number
        if echo "$output" | grep -qi "duplicate\|already exists\|redundant binary"; then
            warn "Duplicate build number — bumping and re-archiving"
            "$BUMP_BUILD" "$PROJECT_PATH"
            do_archive "$platform" || return 1
            # Update archive_path to new one
            attempt=$((attempt + 1))
            continue
        fi

        # Auto-fix: payload directory
        if echo "$output" | grep -qi "Payload directory\|not a valid archive"; then
            warn "Invalid archive format — re-exporting with proper plist"
            attempt=$((attempt + 1))
            continue
        fi

        attempt=$((attempt + 1))
        warn "Upload attempt $attempt/$MAX_RETRIES failed"
    done

    fail "Upload failed for $platform after $MAX_RETRIES attempts"
    echo "$output" | grep -E "error:|ERROR" | head -10
    return 1
}

step_upload() {
    log "${STEP_LABELS[4]}"

    if $DRY_RUN; then
        for p in "${PLATFORMS[@]}"; do
            info "[DRY-RUN] Would upload archive for $p"
        done
        return 0
    fi

    local i=0
    for p in "${PLATFORMS[@]}"; do
        do_upload "${ARCHIVE_PATHS[$i]}" "$p" || return 1
        i=$((i + 1))
    done
    return 0
}

# ── Step 6: Metadata Check ──────────────────────────────────────────
step_metadata() {
    log "${STEP_LABELS[5]}"

    if [[ -z "$APP_ID" || "$APP_ID" == "DRY_RUN_APP_ID" ]]; then
        if $DRY_RUN; then
            info "[DRY-RUN] Would check metadata for app"; return 0
        fi
        fail "No ASC App ID — cannot check metadata"; return 1
    fi

    if $DRY_RUN; then
        info "[DRY-RUN] Would run: asc-metadata.py status $APP_ID"; return 0
    fi

    local output
    output=$(python3 "$ASC_META" status "$APP_ID" 2>&1) || true
    echo "$output" | sed 's/^/  /'

    local fixed=false

    # Auto-fix: whatsNew
    if echo "$output" | grep -qi "whatsNew.*EMPTY\|whatsNew.*Missing"; then
        local wn="${WHATS_NEW:-Bug fixes and improvements.}"
        info "Setting whatsNew: $wn"
        # Get version loc ID and patch it
        local tmpjson="$TEMP_DIR/meta-fix.json"
        echo "{\"locale\":\"en-US\",\"whatsNew\":\"$wn\"}" > "$tmpjson"
        python3 "$ASC_META" set "$APP_ID" "$tmpjson" --force 2>&1 | sed 's/^/  /'
        fixed=true
    fi

    # Auto-fix: review notes
    if echo "$output" | grep -qi "Review notes.*Missing\|Review notes.*❌"; then
        info "Setting review notes with contact info"
        local contact='{"firstName":"Diego","lastName":"Varela","email":"varelad@gmail.com","phone":"+14154654712"}'
        python3 "$ASC_META" review-notes "$APP_ID" "No demo account needed. Standard app functionality." "$contact" 2>&1 | sed 's/^/  /'
        fixed=true
    fi

    if $fixed; then
        ok "Metadata auto-fixed"
    else
        ok "Metadata looks good"
    fi
    return 0
}

# ── Step 7: ASO Optimize ────────────────────────────────────────────
step_optimize() {
    log "${STEP_LABELS[6]}"

    if ! $OPTIMIZE_ASO; then
        info "Skipping ASO optimization (use --optimize-aso to enable)"
        return 0
    fi

    if [[ -z "$APP_ID" || "$APP_ID" == "DRY_RUN_APP_ID" ]]; then
        if $DRY_RUN; then
            info "[DRY-RUN] Would optimize ASO metadata"; return 0
        fi
        fail "No ASC App ID — cannot optimize"; return 1
    fi

    if $DRY_RUN; then
        info "[DRY-RUN] Would run: asc-metadata.py optimize $APP_ID $PROJECT_PATH --apply"
        return 0
    fi

    local output
    output=$(python3 "$ASC_META" optimize "$APP_ID" "$PROJECT_PATH" --apply 2>&1) || {
        fail "ASO optimization failed"
        echo "$output" | tail -10 | sed 's/^/  /'
        return 1
    }
    echo "$output" | sed 's/^/  /'
    ok "ASO metadata optimized and applied"
    return 0
}

# ── Step 8: Submit ──────────────────────────────────────────────────
step_submit() {
    log "${STEP_LABELS[8]}"

    if [[ -z "$APP_ID" || "$APP_ID" == "DRY_RUN_APP_ID" ]]; then
        if $DRY_RUN; then
            info "[DRY-RUN] Would submit app for review"; return 0
        fi
        fail "No ASC App ID"; return 1
    fi

    if $DRY_RUN; then
        info "[DRY-RUN] Would run: asc-metadata.py submit $APP_ID"; return 0
    fi

    # Wait for build to be VALID (up to 5 min)
    local waited=0 max_wait=300 interval=30
    info "Waiting for build to be processed..."
    while [[ $waited -lt $max_wait ]]; do
        local status_out
        status_out=$(python3 "$ASC_META" status "$APP_ID" 2>&1) || true
        if echo "$status_out" | grep -q "Build:.*✅"; then
            ok "Build is ready"
            break
        fi
        if [[ $waited -ge $max_wait ]]; then
            fail "Build not ready after ${max_wait}s"
            return 1
        fi
        info "Build processing... waiting ${interval}s ($waited/${max_wait}s)"
        sleep "$interval"
        waited=$((waited + interval))
    done

    # Submit
    local attempt=0 output
    while [[ $attempt -lt $MAX_RETRIES ]]; do
        output=$(python3 "$ASC_META" submit "$APP_ID" 2>&1) || true

        if echo "$output" | grep -qi "submitted for review\|🚀"; then
            ok "App submitted for review! 🎉"
            return 0
        fi

        # Auto-fix: already in another submission
        if echo "$output" | grep -qi "already added to another reviewSubmission"; then
            warn "Existing review submission found — this version may already be submitted"
            ok "Submission exists"
            return 0
        fi

        # Auto-fix: unresolved issues
        if echo "$output" | grep -qi "UNRESOLVED_ISSUES\|resolve"; then
            warn "Unresolved issues — running metadata fixes"
            step_metadata
            attempt=$((attempt + 1))
            continue
        fi

        # App Privacy missing — can't auto-fix
        if echo "$output" | grep -qi "app privacy\|privacy"; then
            fail "App Privacy (Data Usage) must be set in App Store Connect web UI"
            info "Go to: https://appstoreconnect.apple.com/apps/$APP_ID/distribution/privacy"
            info "Then resume: ship.sh $PROJECT_PATH --resume-from submit"
            return 1
        fi

        attempt=$((attempt + 1))
        warn "Submit attempt $attempt/$MAX_RETRIES"
        echo "$output" | grep -E "ERROR|error" | head -5 | sed 's/^/  /'
    done

    fail "Submission failed after $MAX_RETRIES attempts"
    return 1
}

# ── Main Pipeline ───────────────────────────────────────────────────
echo ""
echo "🚢 ZephShipper — App Shipping Pipeline"
echo "======================================="
echo "  Project: $PROJECT_PATH"
echo "  Version: ${VERSION:-auto}"
echo "  Dry run: $DRY_RUN"
[[ -n "$RESUME_FROM" ]] && echo "  Resume:  $RESUME_FROM"
echo ""

passed=0 failed=0 skipped=0

for i in "${!STEPS[@]}"; do
    step="${STEPS[$i]}"

    if should_skip "$step"; then
        STEP_RESULTS+=("skip")
        skipped=$((skipped + 1))
        info "⏭️  Skipping ${STEP_LABELS[$i]}"
        continue
    fi

    if "step_$step"; then
        STEP_RESULTS+=("pass")
        passed=$((passed + 1))
    else
        STEP_RESULTS+=("fail")
        failed=$((failed + 1))
        fail "Pipeline stopped at: $step"
        echo ""
        info "Resume with: ship.sh $PROJECT_PATH --resume-from $step"
        break
    fi
done

# ── Summary ─────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📊 SHIPPING SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for i in "${!STEPS[@]}"; do
    result="${STEP_RESULTS[$i]:-pending}"
    icon="⬜"
    [[ "$result" == "pass" ]] && icon="✅"
    [[ "$result" == "fail" ]] && icon="❌"
    [[ "$result" == "skip" ]] && icon="⏭️"
    echo "  $icon ${STEP_LABELS[$i]}"
done
echo ""
echo "  Passed: $passed | Failed: $failed | Skipped: $skipped"

if [[ $failed -eq 0 ]]; then
    # Cleanup on full success
    if ! $DRY_RUN && [[ $skipped -eq 0 ]]; then
        rm -rf "$TEMP_DIR"
        info "Temp files cleaned up"
    fi
    echo ""
    echo "  🎉 Ship complete!"
else
    echo ""
    echo "  ⚠️  Pipeline incomplete — fix issues and resume"
fi
echo ""
