---
name: zephshipper
description: iOS/macOS app validation, shipping, and screenshot automation. Validates code quality, ships to App Store, and captures intelligent screenshots.
---

# ZephShipper 🚀

One command to validate, ship, and screenshot iOS/macOS apps.

## Commands

### validate <path>

```bash
~/.openclaw/workspace/skills/zephshipper/scripts/validate.sh ~/Projects/App
```

Validates app is ready to ship: build, SwiftLint, memory leak patterns.

### bump-build <path> [increment]

```bash
~/.openclaw/workspace/skills/zephshipper/scripts/bump-build.sh ~/Projects/App
~/.openclaw/workspace/skills/zephshipper/scripts/bump-build.sh ~/Projects/App 1      # +1 (default)
~/.openclaw/workspace/skills/zephshipper/scripts/bump-build.sh ~/Projects/App set:5  # set to 5
```

Increments CURRENT_PROJECT_VERSION in Xcode project. Use before uploading new builds.

### asc-metadata

```bash
python3 ~/.openclaw/workspace/skills/zephshipper/scripts/asc-metadata.py apps
python3 ~/.openclaw/workspace/skills/zephshipper/scripts/asc-metadata.py get <app_id>
python3 ~/.openclaw/workspace/skills/zephshipper/scripts/asc-metadata.py set <app_id> metadata.json
python3 ~/.openclaw/workspace/skills/zephshipper/scripts/asc-metadata.py subtitle <app_id> "text"
python3 ~/.openclaw/workspace/skills/zephshipper/scripts/asc-metadata.py categories <app_id> PRIMARY [SECONDARY]
```

Manage App Store Connect metadata via API. Upload descriptions, keywords, subtitles, categories.
Metadata JSON supports: description, keywords, promotionalText, whatsNew, subtitle, primaryCategory, secondaryCategory.

**Requires:** `~/.appstoreconnect/private_keys/AuthKey_*.p8` + PyJWT (`pip3 install pyjwt[crypto]`)

### ship <path> [release_notes]

```bash
~/.openclaw/workspace/skills/zephshipper/scripts/ship.sh ~/Projects/App "Bug fixes"
```

Full pipeline: validate → bump version → archive → upload → submit for review.

**Requirements:**
- App Store Connect API key at `~/.appstoreconnect/private_keys/AuthKey_*.p8`
- Environment: `ASC_KEY_ID`, `ASC_ISSUER_ID` (or defaults in script)

### screenshots <path>

**This is an AGENT TASK, not a script.** The AI agent performs intelligent screenshot capture.

## Screenshots: Agent Instructions

When user requests screenshots, follow this process:

### Step 1: Analyze Project

Read and understand the app:

```bash
# Find documentation
cat PROJECT/CLAUDE.md PROJECT/README.md PROJECT/docs/*.md 2>/dev/null

# Detect platforms
grep -l "iphoneos\|macosx" PROJECT/*.xcodeproj/project.pbxproj

# Find views/screens
grep -rh "struct.*View.*:" PROJECT --include="*.swift" | grep -v Preview

# Detect integrations
grep -r "RevenueCat\|StoreKit\|Purchases" PROJECT --include="*.swift"  # Paywall
grep -r "ASAuthorizationAppleIDProvider" PROJECT --include="*.swift"   # Apple Sign In
grep -r "FirebaseAuth" PROJECT --include="*.swift"                      # Firebase Auth

# Find tabs
grep -r "tabItem\|TabView" PROJECT --include="*.swift"

# Get bundle ID
grep "PRODUCT_BUNDLE_IDENTIFIER" PROJECT/*.xcodeproj/project.pbxproj | head -1
```

### Step 2: Plan Captures

Based on analysis, decide what screens to capture:

**Required screenshots:**
1. **Main screen** - The primary value proposition
2. **Key features** - 2-3 screens showing main functionality
3. **Paywall** (if RevenueCat/StoreKit detected) - Apple requires this

**Resolution requirements:**
- **iPhone**: 1320×2868 (6.9") - use iPhone 16 Pro Max simulator
- **iPad**: 2064×2752 (13") - use iPad Pro 13" simulator (if app supports iPad)
- **Mac**: 2880×1800 - use screencapture on host (if macOS app)

### Step 3: Setup Simulator

```bash
# List available simulators
xcrun simctl list devices available | grep -E "iPhone|iPad"

# Find best device (6.9" display)
DEVICE_ID=$(xcrun simctl list devices available | grep "iPhone 16 Pro Max" | head -1 | grep -oE "[A-F0-9-]{36}")

# Boot simulator
xcrun simctl boot "$DEVICE_ID"

# Open Simulator app (optional, for visibility)
open -a Simulator
```

### Step 4: Build & Install App

```bash
# Find project
PROJ=$(find PROJECT -name "*.xcodeproj" | head -1)
SCHEME=$(xcodebuild -list -project "$PROJ" 2>/dev/null | awk '/Schemes:/{f=1;next} f{print;exit}' | xargs)

# Build for simulator
xcodebuild -project "$PROJ" -scheme "$SCHEME" \
  -destination "id=$DEVICE_ID" \
  -configuration Debug build

# Find built app
APP=$(find ~/Library/Developer/Xcode/DerivedData -name "*.app" -path "*Debug-iphonesimulator*" | head -1)

# Install
xcrun simctl install "$DEVICE_ID" "$APP"

# Get bundle ID
BUNDLE_ID=$(defaults read "$APP/Info.plist" CFBundleIdentifier)
```

### Step 5: Capture Screenshots

```bash
# Create output directory
mkdir -p PROJECT/screenshots/ios

# Launch app
xcrun simctl launch "$DEVICE_ID" "$BUNDLE_ID"
sleep 3

# Capture main screen
xcrun simctl io "$DEVICE_ID" screenshot PROJECT/screenshots/ios/01-main.png

# Navigate and capture more screens
# Use deep links if supported:
xcrun simctl openurl "$DEVICE_ID" "myapp://settings"
sleep 2
xcrun simctl io "$DEVICE_ID" screenshot PROJECT/screenshots/ios/02-settings.png

# Or use simctl UI automation (limited):
# For complex navigation, guide user to manually navigate, then capture
```

### Step 6: macOS Screenshots (if applicable)

```bash
# Build and run macOS app
xcodebuild -project "$PROJ" -scheme "$SCHEME" \
  -destination "platform=macOS" \
  -configuration Debug build

# Run the app
open ~/Library/Developer/Xcode/DerivedData/*/Build/Products/Debug/*.app

# Capture with screencapture
screencapture -w PROJECT/screenshots/macos/01-main.png
```

### Navigation Strategies

**If app has tabs:**
- Identify tab bar items from code
- Navigate by tapping tab coordinates (bottom of screen)

**If app has deep links:**
```bash
xcrun simctl openurl "$DEVICE_ID" "appscheme://screen/settings"
```

**If app needs manual navigation:**
1. Tell user: "Navigate to [screen name] and press Enter"
2. Wait for confirmation
3. Capture screenshot

**For onboarding/paywall:**
- May need to trigger via deep link or code modification
- Or guide user through the flow

### Output Format

```
PROJECT/screenshots/
├── ios/
│   ├── 01-main.png        # 1320×2868
│   ├── 02-feature.png
│   ├── 03-settings.png
│   └── 04-paywall.png     # If applicable
└── macos/
    └── 01-main.png        # 2880×1800
```

### Pro Tips

1. **Wait for animations** - `sleep 2` after navigation before capture
2. **Hide status bar clock** - Screenshots look cleaner with consistent time
3. **Use demo data** - Populate app with good-looking sample data
4. **Check dark mode** - May want both light and dark screenshots

## Metadata Guardrails

**NEVER hallucinate contact info.** The asc-metadata.py script enforces these checks automatically:

1. **No unverified emails** — Don't invent support@whatever.com. If no email exists, don't include one.
2. **No unverified URLs** — Only use URLs that actually exist and are controlled by the developer.
3. **No fake phone numbers or social handles** — Only include verified, real contact info.
4. **Character limits enforced** — Title 30, Subtitle 30, Keywords 100, Description 4000, Promo Text 170.
5. **Keyword hygiene** — No spaces after commas, no duplicates, no plurals (iOS indexes both).

The script will **block uploads** with errors (char limits) and **warn** on suspicious content (emails, URLs, handles). Use `--force` to override warnings only after manual verification.

**Rule for the agent:** When generating metadata, ONLY include contact information that the developer has explicitly provided or that exists in the project files. When in doubt, leave it out.

## App Store Connect Credentials

Store in `~/.appstoreconnect/private_keys/AuthKey_KEYID.p8`

Environment variables:
```bash
export ASC_KEY_ID="AA5UCQU456"
export ASC_ISSUER_ID="638c67e6-9365-4b3f-8250-474197f6f1a1"
```

## Known Apps

Diego's apps in ~/Projects/:
- Making Miles (iOS)
- InkMark (iOS + macOS)
- TaskLancer (iOS + macOS)
- TunePulse (iOS)
- ZephTicker (macOS only)
- Civics 100 (iOS)
- Purpura (iOS)
- HeartStrong (iOS)
