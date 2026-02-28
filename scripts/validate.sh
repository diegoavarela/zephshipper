#!/bin/bash
# ZephShipper validate.sh - Validate iOS/macOS app for shipping
# Usage: validate.sh <project_path>

set -e

PROJECT_PATH="${1:-.}"
cd "$PROJECT_PATH"

echo "🚀 ZephShipper Validate"
echo "======================="
echo "Project: $(pwd)"
echo ""

# Find Xcode project
XCODEPROJ=$(find . -maxdepth 1 -name "*.xcodeproj" | head -1)
if [ -z "$XCODEPROJ" ]; then
    echo "❌ No .xcodeproj found"
    exit 1
fi
echo "📦 Project: $XCODEPROJ"

# Get scheme
SCHEME=$(xcodebuild -list -project "$XCODEPROJ" 2>/dev/null | awk '/Schemes:/{f=1;next} f{print;exit}' | xargs)
echo "🎯 Scheme: $SCHEME"
echo ""

# ========================================
# Level 1: Build Check (BLOCKER)
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📱 Level 1: Build Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Detect platform (macOS vs iOS)
if grep -q "SUPPORTED_PLATFORMS.*macosx" "$XCODEPROJ/project.pbxproj" 2>/dev/null && \
   ! grep -q "SUPPORTED_PLATFORMS.*iphone" "$XCODEPROJ/project.pbxproj" 2>/dev/null; then
    BUILD_DEST="generic/platform=macOS"
elif grep -q "SDKROOT.*macosx" "$XCODEPROJ/project.pbxproj" 2>/dev/null && \
     ! grep -q "SDKROOT.*iphoneos" "$XCODEPROJ/project.pbxproj" 2>/dev/null; then
    BUILD_DEST="generic/platform=macOS"
else
    BUILD_DEST="generic/platform=iOS Simulator"
fi

BUILD_OUTPUT=$(xcodebuild -project "$XCODEPROJ" -scheme "$SCHEME" \
    -destination "$BUILD_DEST" \
    -configuration Debug build 2>&1) || true

if echo "$BUILD_OUTPUT" | grep -q "BUILD SUCCEEDED"; then
    echo "✅ Build: PASSED"
else
    echo "❌ Build: FAILED"
    echo "$BUILD_OUTPUT" | grep -E "error:" | head -10
    exit 1
fi
echo ""

# ========================================
# Level 2: SwiftLint (BLOCKER after auto-fix)
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧹 Level 2: SwiftLint"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if command -v swiftlint &> /dev/null; then
    # Auto-fix what we can
    swiftlint lint --fix --quiet 2>/dev/null || true
    
    # Check remaining issues
    LINT_OUTPUT=$(swiftlint lint --quiet 2>/dev/null) || true
    LINT_ERRORS=$(echo "$LINT_OUTPUT" | grep -c "error:" 2>/dev/null) || LINT_ERRORS=0
    LINT_WARNINGS=$(echo "$LINT_OUTPUT" | grep -c "warning:" 2>/dev/null) || LINT_WARNINGS=0
    
    if [ "$LINT_ERRORS" -gt 0 ]; then
        echo "❌ SwiftLint: $LINT_ERRORS errors (BLOCKER)"
        echo "$LINT_OUTPUT" | grep "error:" | head -10
        exit 1
    elif [ "$LINT_WARNINGS" -gt 0 ]; then
        echo "⚠️  SwiftLint: $LINT_WARNINGS warnings (non-blocking)"
    else
        echo "✅ SwiftLint: PASSED (0 issues)"
    fi
else
    echo "⚠️  SwiftLint not installed, skipping"
fi
echo ""

# ========================================
# Level 2b: Memory Leak Patterns (WARNING)
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Level 2b: Memory Leak Patterns"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

LEAK_PATTERNS=0

# Check for [weak self] missing in closures with self
STRONG_SELF=$(grep -rn "{ self\." --include="*.swift" 2>/dev/null | grep -v "\[weak self\]" | grep -v "\[unowned self\]" | wc -l | xargs)
if [ "$STRONG_SELF" -gt 0 ]; then
    echo "⚠️  Potential retain cycles: $STRONG_SELF (closures using self without [weak self])"
    LEAK_PATTERNS=$((LEAK_PATTERNS + STRONG_SELF))
fi

# Check for delegate properties not marked weak
STRONG_DELEGATES=$(grep -rn "var.*delegate.*:" --include="*.swift" 2>/dev/null | grep -v "weak" | wc -l | xargs)
if [ "$STRONG_DELEGATES" -gt 0 ]; then
    echo "⚠️  Strong delegate references: $STRONG_DELEGATES"
    LEAK_PATTERNS=$((LEAK_PATTERNS + STRONG_DELEGATES))
fi

if [ "$LEAK_PATTERNS" -eq 0 ]; then
    echo "✅ Memory patterns: PASSED"
else
    echo "⚠️  Memory patterns: $LEAK_PATTERNS potential issues (review recommended)"
fi
echo ""

# ========================================
# Level 3: App Store Guidelines Compliance
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Level 3: App Store Guidelines Compliance"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

L3_PASS=0
L3_FAIL=0
L3_WARN=0

l3_pass() { echo "  ✅ PASS: $1"; L3_PASS=$((L3_PASS + 1)); }
l3_fail() { echo "  ❌ FAIL: $1"; L3_FAIL=$((L3_FAIL + 1)); }
l3_warn() { echo "  ⚠️  WARN: $1"; L3_WARN=$((L3_WARN + 1)); }

# --- Detect capabilities ---
ASC_AVAILABLE=false
APP_ID=""
BUNDLE_ID=""

if command -v asc &>/dev/null; then
    ASC_AVAILABLE=true
    BUNDLE_ID=$(xcodebuild -project "$XCODEPROJ" -scheme "$SCHEME" -showBuildSettings 2>/dev/null | grep "PRODUCT_BUNDLE_IDENTIFIER" | head -1 | awk '{print $NF}')
    if [ -n "$BUNDLE_ID" ]; then
        APP_ID=$(asc apps list --output json 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
for app in (data if isinstance(data,list) else []):
    bid = app.get('attributes',{}).get('bundleId','')
    if bid == '$BUNDLE_ID':
        print(app['id']); break
" 2>/dev/null || echo "")
    fi
fi

HAS_IAP=false
if grep -rq "RevenueCat\|StoreKit\|Purchases\|\.purchase\|SubscriptionStoreView\|Product\.products" --include="*.swift" 2>/dev/null; then
    HAS_IAP=true
fi

HAS_LOGIN=false
if grep -rq "signIn\|SignIn\|login\|Login\|ASAuthorizationAppleIDProvider\|FirebaseAuth\|Auth0\|authenticate" --include="*.swift" 2>/dev/null; then
    HAS_LOGIN=true
fi

# Find Info.plist
INFO_PLIST=""
PLIST_BUILD=$(xcodebuild -project "$XCODEPROJ" -scheme "$SCHEME" -showBuildSettings 2>/dev/null | grep "INFOPLIST_FILE" | head -1 | awk '{print $NF}')
if [ -n "$PLIST_BUILD" ] && [ -f "$PLIST_BUILD" ]; then
    INFO_PLIST="$PLIST_BUILD"
elif [ -f "Info.plist" ]; then
    INFO_PLIST="Info.plist"
else
    INFO_PLIST=$(find . -maxdepth 3 -name "Info.plist" -not -path "*/Pods/*" -not -path "*/DerivedData/*" -not -path "*Test*" | head -1)
fi

# Fetch ASC metadata once if available
META_JSON="{}"
VER_JSON="[]"
if $ASC_AVAILABLE && [ -n "$APP_ID" ]; then
    META_JSON=$(asc app-info get --app "$APP_ID" --output json 2>/dev/null || echo "{}")
    VER_JSON=$(asc versions list --app "$APP_ID" --output json 2>/dev/null || echo "[]")
fi

# ── 3.1: Subscription Compliance (Guideline 3.1.2) ──
echo ""
echo "  ── Subscription Compliance (Guideline 3.1.2) ──"

if $HAS_IAP; then
    # 1. Terms of Use / EULA link
    if grep -rq "terms.*of.*use\|termsOfUse\|terms-of-use\|EULA\|eula\|TermsURL\|termsURL\|terms_url" --include="*.swift" 2>/dev/null; then
        l3_pass "Terms of Use / EULA link found in app code"
    else
        l3_fail "No Terms of Use / EULA link found (required for subscriptions - 3.1.2)"
    fi

    # 2. Privacy Policy link in app
    if grep -rq "privacy.*policy\|privacyPolicy\|privacy-policy\|PrivacyURL\|privacyURL\|privacy_url" --include="*.swift" 2>/dev/null; then
        l3_pass "Privacy Policy link found in app code"
    else
        l3_fail "No Privacy Policy link found in app code (required for subscriptions - 3.1.2)"
    fi

    # 3. Pricing hierarchy check
    PAYWALL_FILES=$(grep -rl "paywall\|Paywall\|PayWall\|SubscriptionView\|PurchaseView\|SubscriptionStoreView" --include="*.swift" 2>/dev/null || echo "")
    if [ -n "$PAYWALL_FILES" ]; then
        PROMINENCE_BAD=false
        for f in $PAYWALL_FILES; do
            if grep -q "perMonth\|perWeek\|per month\|per week\|\/mo\|\/wk" "$f" 2>/dev/null; then
                if grep -A2 "perMonth\|perWeek\|per month\|per week" "$f" 2>/dev/null | grep -q "\.title\|\.largeTitle\|\.headline" 2>/dev/null; then
                    PROMINENCE_BAD=true
                fi
            fi
        done
        if $PROMINENCE_BAD; then
            l3_warn "Calculated per-period price may be more prominent than billed amount (3.1.2)"
        else
            l3_pass "Pricing hierarchy appears correct"
        fi
    fi

    # 4. Required subscription info in paywall
    if [ -n "$PAYWALL_FILES" ]; then
        MISSING_INFO=()
        if ! grep -rq "displayPrice\|localizedPrice\|price\|Price\|\.products" $PAYWALL_FILES 2>/dev/null; then
            MISSING_INFO+=("price")
        fi
        if ! grep -rq "period\|duration\|monthly\|yearly\|annual\|weekly\|SubscriptionPeriod" $PAYWALL_FILES 2>/dev/null; then
            MISSING_INFO+=("period")
        fi
        if [ ${#MISSING_INFO[@]} -eq 0 ]; then
            l3_pass "Paywall displays required subscription info (price, period)"
        else
            l3_fail "Paywall missing: ${MISSING_INFO[*]} (required - 3.1.2)"
        fi
    else
        l3_warn "No paywall view found — ensure subscription UI shows required info"
    fi

    # 5. Auto-renewal disclosure
    if grep -rq "auto.renew\|auto-renew\|automatically renew\|cancel.*anytime\|cancel.*any.*time\|subscription.*renews\|renews.*automatically" --include="*.swift" 2>/dev/null; then
        l3_pass "Auto-renewal disclosure text found"
    else
        l3_fail "No auto-renewal disclosure text ('subscription auto-renews' / 'cancel anytime')"
    fi

    # 6. Restore Purchases button
    if grep -rq "restorePurchases\|restore.*purchases\|Restore Purchases\|restoreCompletedTransactions\|AppStore\.sync\|\.restorePurchases" --include="*.swift" 2>/dev/null; then
        l3_pass "Restore Purchases functionality found"
    else
        l3_fail "No Restore Purchases button/action found (required - 3.1.2)"
    fi
else
    echo "  ℹ️  No IAP/subscription code detected — subscription checks skipped"
fi

# ── 3.2: IAP Completeness (Guideline 2.1b) ──
echo ""
echo "  ── IAP Completeness (Guideline 2.1b) ──"

if $HAS_IAP && $ASC_AVAILABLE && [ -n "$APP_ID" ]; then
    # 7. IAPs configured in ASC
    IAP_JSON=$(asc iap list --app "$APP_ID" --output json 2>/dev/null || echo "[]")
    IAP_COUNT=$(echo "$IAP_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")

    if [ "$IAP_COUNT" -gt 0 ]; then
        l3_pass "Found $IAP_COUNT IAP(s) configured in App Store Connect"
    else
        l3_fail "Code references IAP but none found in ASC (Guideline 2.1b)"
    fi

    # 8 & 9. IAP screenshots and state
    if [ "$IAP_COUNT" -gt 0 ]; then
        IAP_IDS=$(echo "$IAP_JSON" | python3 -c "
import json,sys
data=json.load(sys.stdin)
for iap in (data if isinstance(data,list) else []):
    print(iap.get('id','') + '|' + (iap.get('attributes',{}).get('referenceName','') or '') + '|' + (iap.get('attributes',{}).get('state','') or ''))
" 2>/dev/null)

        SS_MISSING=0
        STATE_BAD=0
        while IFS='|' read -r iap_id iap_name iap_state; do
            [ -z "$iap_id" ] && continue
            SS=$(asc iap review-screenshots get --iap-id "$iap_id" --output json 2>/dev/null || echo "{}")
            HAS_SS=$(echo "$SS" | python3 -c "
import json,sys; d=json.load(sys.stdin)
if isinstance(d,list): print('yes' if len(d)>0 else 'no')
elif isinstance(d,dict) and d.get('id'): print('yes')
else: print('no')" 2>/dev/null || echo "no")
            [ "$HAS_SS" = "no" ] && SS_MISSING=$((SS_MISSING + 1))
            if [ "$iap_state" != "APPROVED" ] && [ "$iap_state" != "READY_TO_SUBMIT" ] && [ "$iap_state" != "WAITING_FOR_REVIEW" ]; then
                STATE_BAD=$((STATE_BAD + 1))
            fi
        done <<< "$IAP_IDS"

        if [ "$SS_MISSING" -eq 0 ]; then
            l3_pass "All IAPs have review screenshots"
        else
            l3_fail "$SS_MISSING IAP(s) missing review screenshots (required for submission)"
        fi
        if [ "$STATE_BAD" -eq 0 ]; then
            l3_pass "All IAPs in submittable state"
        else
            l3_warn "$STATE_BAD IAP(s) not in Ready/Approved state"
        fi
    fi
elif $HAS_IAP; then
    l3_warn "ASC not available — cannot verify IAP completeness (install asc CLI)"
else
    echo "  ℹ️  No IAP code detected — IAP checks skipped"
fi

# ── 3.3: Metadata Completeness (Guideline 2.3) ──
echo ""
echo "  ── Metadata Completeness (Guideline 2.3) ──"

if $ASC_AVAILABLE && [ -n "$APP_ID" ]; then
    # 10. Placeholder text in description
    DESC=$(echo "$VER_JSON" | python3 -c "
import json,sys
data=json.load(sys.stdin)
for v in (data if isinstance(data,list) else []):
    print(v.get('attributes',{}).get('description','') or ''); break
" 2>/dev/null || echo "")

    if [ -n "$DESC" ]; then
        if echo "$DESC" | grep -iq "lorem ipsum\|placeholder\|TODO\|FIXME\|insert.*here\|your.*description\|description.*here"; then
            l3_fail "App description contains placeholder text (Guideline 2.3)"
        else
            l3_pass "App description — no placeholder text"
        fi
    else
        l3_warn "Could not retrieve app description from ASC"
    fi

    # 11. Screenshots exist
    SS_OUTPUT=$(asc screenshots list --app "$APP_ID" --output json 2>/dev/null || echo "[]")
    SS_COUNT=$(echo "$SS_OUTPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")
    if [ "$SS_COUNT" -gt 0 ]; then
        l3_pass "Screenshots uploaded: $SS_COUNT found in ASC"
    else
        l3_fail "No screenshots found in App Store Connect (required - Guideline 2.3)"
    fi

    # 12. Support URL functional
    SUPPORT_URL=$(echo "$META_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('supportUrl','') or '')" 2>/dev/null)
    if [ -n "$SUPPORT_URL" ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$SUPPORT_URL" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
            l3_pass "Support URL reachable: $SUPPORT_URL"
        else
            l3_fail "Support URL returns HTTP $HTTP_CODE: $SUPPORT_URL"
        fi
    else
        l3_fail "No Support URL set in ASC (required - Guideline 2.3)"
    fi

    # 13. What's New text
    WHATS_NEW=$(echo "$VER_JSON" | python3 -c "
import json,sys
data=json.load(sys.stdin)
for v in (data if isinstance(data,list) else []):
    st = v.get('attributes',{}).get('appStoreState','')
    if st in ('PREPARE_FOR_SUBMISSION','DEVELOPER_REJECTED'):
        print(v.get('attributes',{}).get('whatsNew','') or ''); break
" 2>/dev/null || echo "")
    if [ -n "$WHATS_NEW" ] && [ ${#WHATS_NEW} -gt 2 ]; then
        l3_pass "What's New text present (${#WHATS_NEW} chars)"
    else
        l3_warn "What's New text is empty — should describe changes"
    fi

    # 14. App category
    CATEGORY=$(echo "$META_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('primaryCategory','') or d.get('category','') or '')" 2>/dev/null)
    if [ -n "$CATEGORY" ]; then
        l3_pass "App category set: $CATEGORY"
    else
        l3_warn "Could not verify app category from ASC"
    fi
else
    l3_warn "ASC not available — cannot verify metadata completeness"
fi

# ── 3.4: App Completeness (Guideline 2.1a) ──
echo ""
echo "  ── App Completeness (Guideline 2.1a) ──"

# 15. TODO/FIXME/HACK in production code
TODO_COUNT=$(grep -rn "TODO\|FIXME\|HACK\|XXX" --include="*.swift" 2>/dev/null | grep -v "Test\|test\|Spec\|spec\|Mock\|mock\|Preview" | wc -l | xargs)
if [ "$TODO_COUNT" -eq 0 ]; then
    l3_pass "No TODO/FIXME/HACK comments in production code"
else
    l3_warn "$TODO_COUNT TODO/FIXME/HACK comment(s) in production code"
fi

# 16. Placeholder text in UI strings
PLACEHOLDER_UI=$(grep -rn '"Lorem ipsum\|"Placeholder\|"Sample text\|"Test text\|"Insert.*here' --include="*.swift" 2>/dev/null | grep -v "Test\|test\|Preview\|placeholder:\|will appear here\|response here" | wc -l | xargs)
if [ "$PLACEHOLDER_UI" -eq 0 ]; then
    l3_pass "No placeholder text in UI strings"
else
    l3_fail "$PLACEHOLDER_UI placeholder string(s) in UI code (Guideline 2.1)"
fi

PLACEHOLDER_STRINGS=$(grep -rn "Lorem ipsum\|TODO\|FIXME" --include="*.strings" --include="*.xcstrings" 2>/dev/null | wc -l | xargs)
if [ "$PLACEHOLDER_STRINGS" -gt 0 ]; then
    l3_warn "$PLACEHOLDER_STRINGS potential placeholder(s) in localization files"
fi

# 17. Debug/test screens in production
DEBUG_SCREENS=$(grep -rn "DebugView\|DebugScreen\|TestView\|TestScreen" --include="*.swift" 2>/dev/null | grep -v "Test\|test\|Spec\|#if DEBUG" | wc -l | xargs)
if [ "$DEBUG_SCREENS" -eq 0 ]; then
    l3_pass "No debug/test screens in production code paths"
else
    l3_warn "$DEBUG_SCREENS debug/test screen reference(s) — verify gated behind #if DEBUG"
fi

# 18. Demo account in review notes if login
if $HAS_LOGIN && $ASC_AVAILABLE && [ -n "$APP_ID" ]; then
    REVIEW_NOTES=$(echo "$META_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('reviewNotes','') or d.get('notes','') or '')" 2>/dev/null || echo "")
    if [ -n "$REVIEW_NOTES" ] && echo "$REVIEW_NOTES" | grep -iq "demo\|test.*account\|login\|password\|credential"; then
        l3_pass "Review notes contain demo account info"
    else
        l3_warn "App has login but review notes may lack demo account info (Guideline 2.1)"
    fi
elif $HAS_LOGIN; then
    l3_warn "App has login — ensure demo account info is in ASC review notes"
fi

# ── 3.5: Privacy (Guideline 5.1) ──
echo ""
echo "  ── Privacy (Guideline 5.1) ──"

# 19. Camera usage description
if grep -rq "AVCaptureSession\|UIImagePickerController.*camera\|\.camera\|CameraView" --include="*.swift" 2>/dev/null; then
    if [ -n "$INFO_PLIST" ] && grep -q "NSCameraUsageDescription" "$INFO_PLIST" 2>/dev/null; then
        l3_pass "NSCameraUsageDescription present (camera detected)"
    elif grep -rq "NSCameraUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "NSCameraUsageDescription present"
    else
        l3_fail "Camera usage detected but NSCameraUsageDescription missing (5.1)"
    fi
fi

# 20. Photo library usage description
if grep -rq "PHPhotoLibrary\|UIImagePickerController\|PHPickerViewController\|PhotosUI\|\.photoLibrary" --include="*.swift" 2>/dev/null; then
    if [ -n "$INFO_PLIST" ] && grep -q "NSPhotoLibraryUsageDescription" "$INFO_PLIST" 2>/dev/null; then
        l3_pass "NSPhotoLibraryUsageDescription present (photo access detected)"
    elif grep -rq "NSPhotoLibraryUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "NSPhotoLibraryUsageDescription present"
    else
        l3_fail "Photo library access detected but NSPhotoLibraryUsageDescription missing (5.1)"
    fi
fi

# 21. Other usage descriptions
# Microphone
if grep -rq "AVAudioSession\|AVAudioRecorder\|SFSpeechRecognizer\|\.microphone" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSMicrophoneUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "NSMicrophoneUsageDescription present"
    else
        l3_fail "Microphone usage detected but NSMicrophoneUsageDescription missing (5.1)"
    fi
fi
# Location
if grep -rq "CLLocationManager\|CoreLocation\|requestWhenInUseAuthorization\|requestAlwaysAuthorization" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSLocationWhenInUseUsageDescription\|NSLocationAlwaysUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "Location usage description present"
    else
        l3_fail "Location usage detected but usage description missing (5.1)"
    fi
fi
# Contacts
if grep -rq "CNContactStore\|AddressBook" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSContactsUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "NSContactsUsageDescription present"
    else
        l3_fail "Contacts access detected but NSContactsUsageDescription missing (5.1)"
    fi
fi
# Calendar
if grep -rq "EKEventStore\|EventKit" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSCalendarsUsageDescription\|NSCalendarsFullAccessUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "Calendar usage description present"
    else
        l3_fail "Calendar access detected but usage description missing (5.1)"
    fi
fi
# HealthKit
if grep -rq "HKHealthStore\|HealthKit" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSHealthShareUsageDescription\|NSHealthUpdateUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "HealthKit usage description present"
    else
        l3_fail "HealthKit usage detected but usage description missing (5.1)"
    fi
fi
# Bluetooth
if grep -rq "CBCentralManager\|CoreBluetooth" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSBluetoothAlwaysUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "Bluetooth usage description present"
    else
        l3_fail "Bluetooth usage detected but NSBluetoothAlwaysUsageDescription missing (5.1)"
    fi
fi
# Face ID
if grep -rq "LAContext\|evaluatePolicy\|biometricType" --include="*.swift" 2>/dev/null; then
    if grep -rq "NSFaceIDUsageDescription" --include="*.plist" 2>/dev/null; then
        l3_pass "NSFaceIDUsageDescription present"
    else
        l3_warn "Biometric auth detected but NSFaceIDUsageDescription may be missing"
    fi
fi

# 22. Privacy Policy URL in ASC
if $ASC_AVAILABLE && [ -n "$APP_ID" ]; then
    PRIVACY_URL=$(echo "$META_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('privacyUrl','') or d.get('privacyPolicyUrl','') or '')" 2>/dev/null)
    if [ -n "$PRIVACY_URL" ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$PRIVACY_URL" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
            l3_pass "Privacy Policy URL reachable in ASC: $PRIVACY_URL"
        else
            l3_fail "Privacy Policy URL returns HTTP $HTTP_CODE: $PRIVACY_URL"
        fi
    else
        l3_fail "Privacy Policy URL not set in ASC (required - Guideline 5.1)"
    fi
fi

# ── 3.6: Security ──
echo ""
echo "  ── Security ──"

# 23. Hardcoded API keys/secrets
SECRETS_FOUND=$(grep -rn 'sk-[a-zA-Z0-9]\{20,\}\|sk_live_\|sk_test_\|Bearer [a-zA-Z0-9]\{20,\}\|PRIVATE_KEY.*=.*"[a-zA-Z0-9]' --include="*.swift" --include="*.plist" 2>/dev/null | grep -v "Test\|test\|Mock\|mock\|Example\|example\|TextField\|placeholder\|comment\|Secrets\.plist\|ProcessInfo\|UserDefaults\|@AppStorage" | wc -l | xargs)
if [ "$SECRETS_FOUND" -eq 0 ]; then
    l3_pass "No hardcoded API keys/secrets detected"
else
    l3_fail "$SECRETS_FOUND potential hardcoded secret(s) found (security risk)"
    grep -rn 'sk-[a-zA-Z0-9]\{20,\}\|sk_live_\|sk_test_\|API_KEY.*=.*"' --include="*.swift" 2>/dev/null | grep -v "Test\|Mock" | head -3 | sed 's/^/    /'
fi

# 24. .gitignore coverage
if [ -f ".gitignore" ]; then
    GI_MISSING=()
    grep -q "\.env" .gitignore 2>/dev/null || GI_MISSING+=(".env")
    grep -q "Pods" .gitignore 2>/dev/null || GI_MISSING+=("Pods/")
    grep -q "DerivedData" .gitignore 2>/dev/null || GI_MISSING+=("DerivedData/")
    grep -q "xcuserdata" .gitignore 2>/dev/null || GI_MISSING+=("xcuserdata")
    if [ ${#GI_MISSING[@]} -eq 0 ]; then
        l3_pass ".gitignore covers .env, Pods, DerivedData, xcuserdata"
    else
        l3_warn ".gitignore missing: ${GI_MISSING[*]}"
    fi
else
    l3_fail "No .gitignore file found (may leak secrets/build artifacts)"
fi

# 25. Sensitive data in UserDefaults
UD_SENSITIVE=$(grep -rn "UserDefaults.*password\|UserDefaults.*token\|UserDefaults.*secret\|UserDefaults.*apiKey\|\.set.*password.*forKey\|\.set.*token.*forKey" --include="*.swift" 2>/dev/null | grep -iv "Test\|Mock\|keychain\|SecItem" | wc -l | xargs)
if [ "$UD_SENSITIVE" -eq 0 ]; then
    l3_pass "No sensitive data in UserDefaults (use Keychain for secrets)"
else
    l3_warn "$UD_SENSITIVE instance(s) of potentially sensitive data in UserDefaults"
fi

# 26. App Transport Security
ATS_DISABLED=false
if [ -n "$INFO_PLIST" ] && grep -q "NSAllowsArbitraryLoads" "$INFO_PLIST" 2>/dev/null; then
    if grep -A1 "NSAllowsArbitraryLoads" "$INFO_PLIST" 2>/dev/null | grep -q "true\|YES"; then
        ATS_DISABLED=true
    fi
elif grep -rq "NSAllowsArbitraryLoads" --include="*.plist" 2>/dev/null; then
    if grep -A1 "NSAllowsArbitraryLoads" --include="*.plist" 2>/dev/null | grep -q "true\|YES"; then
        ATS_DISABLED=true
    fi
fi
if $ATS_DISABLED; then
    l3_warn "App Transport Security globally disabled (NSAllowsArbitraryLoads=true) — Apple may reject"
else
    l3_pass "App Transport Security not globally disabled"
fi

# ── 3.7: Build Compliance ──
echo ""
echo "  ── Build Compliance ──"

# 27. Export compliance
EXPORT_SET=false
if [ -n "$INFO_PLIST" ] && grep -q "ITSAppUsesNonExemptEncryption" "$INFO_PLIST" 2>/dev/null; then
    EXPORT_SET=true
elif grep -rq "ITSAppUsesNonExemptEncryption" --include="*.plist" 2>/dev/null; then
    EXPORT_SET=true
fi
if $EXPORT_SET; then
    l3_pass "ITSAppUsesNonExemptEncryption set (avoids export compliance popup)"
else
    l3_warn "ITSAppUsesNonExemptEncryption not set — will show export compliance dialog on upload"
fi

# 28. Build version incremented
if $ASC_AVAILABLE && [ -n "$APP_ID" ]; then
    CURRENT_BUILD=$(grep "CURRENT_PROJECT_VERSION" "$XCODEPROJ/project.pbxproj" 2>/dev/null | head -1 | grep -o '[0-9]*' | head -1)
    LATEST_ASC_BUILD=$(asc builds list --app "$APP_ID" --limit 1 --output json 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
for b in (data if isinstance(data,list) else []):
    print(b.get('attributes',{}).get('version','0')); break
" 2>/dev/null || echo "0")
    if [ -n "$CURRENT_BUILD" ] && [ -n "$LATEST_ASC_BUILD" ]; then
        if [ "$CURRENT_BUILD" -gt "$LATEST_ASC_BUILD" ] 2>/dev/null; then
            l3_pass "Build version ($CURRENT_BUILD) ahead of latest ASC build ($LATEST_ASC_BUILD)"
        else
            l3_warn "Build version ($CURRENT_BUILD) not ahead of ASC ($LATEST_ASC_BUILD) — bump before upload"
        fi
    fi
fi

# 29. Deployment target
DEPLOY_TARGET=$(grep "IPHONEOS_DEPLOYMENT_TARGET\|MACOSX_DEPLOYMENT_TARGET" "$XCODEPROJ/project.pbxproj" 2>/dev/null | head -1 | grep -o '[0-9]*\.[0-9]*' | head -1)
if [ -n "$DEPLOY_TARGET" ]; then
    l3_pass "Deployment target: $DEPLOY_TARGET"
else
    l3_warn "Could not determine deployment target"
fi

# ── Level 3 Summary ──
echo ""
echo "  ── Level 3 Results ──"
echo "  ✅ PASS: $L3_PASS  |  ❌ FAIL: $L3_FAIL  |  ⚠️  WARN: $L3_WARN"
LEVEL3_BLOCKED=false
if [ "$L3_FAIL" -gt 0 ]; then
    echo "  ❌ Level 3: $L3_FAIL blocking issue(s) must be fixed before submission"
    LEVEL3_BLOCKED=true
else
    echo "  ✅ Level 3: PASSED (no blocking issues)"
fi
echo ""

# ========================================
# Summary
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 VALIDATION SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SWIFT_FILES=$(find . -name "*.swift" -not -path "*/.*" | wc -l | xargs)
echo "📁 Swift files: $SWIFT_FILES"
echo "📋 Level 3 compliance: $L3_PASS pass / $L3_FAIL fail / $L3_WARN warn"

if $LEVEL3_BLOCKED; then
    echo ""
    echo "❌ VALIDATION FAILED — $L3_FAIL App Store guideline violation(s) found"
    echo "   Fix FAIL items above before submitting for review."
    exit 1
fi

echo ""
echo "✅ VALIDATION PASSED - Ready to ship!"
echo ""
