# ZephShipper 🚀

One command to validate and ship iOS/macOS apps to the App Store.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What It Does

ZephShipper automates the entire iOS/macOS App Store submission pipeline — from code quality validation to build upload to review submission. Built for AI-assisted workflows (OpenClaw, Claude Code) but works standalone.

## Features

- **Validate** — Build test, SwiftLint (zero tolerance on errors), memory leak pattern detection, Apple Guidelines compliance checks
- **Ship** — Bump build number, archive, upload, link builds to versions, submit for review
- **IAP Validation** — Checks in-app purchases have review screenshots and are submitted before shipping
- **Subscription Flow** — Automated first-time subscription linking via ASC API, with browser fallback for API limitations
- **ASC CLI** — Full App Store Connect command-line interface: metadata, builds, versions, TestFlight, reviews, phased release, IAPs
- **Screenshots** — AI-powered intelligent screenshot capture (agent task)

## Requirements

- macOS with Xcode
- Node.js 18+
- [SwiftLint](https://github.com/realm/SwiftLint) (`brew install swiftlint`)
- App Store Connect API key (`.p8` file)
- Python 3 (for subscription flow and metadata scripts)

## Setup

### App Store Connect API Key

```bash
mkdir -p ~/.appstoreconnect/private_keys
# Place your AuthKey_XXXXXXXX.p8 file there
```

Set environment variables or the scripts auto-detect from `~/.appstoreconnect/`:

```bash
export ASC_KEY_ID="YOUR_KEY_ID"
export ASC_ISSUER_ID="YOUR_ISSUER_ID"
```

## Scripts

### `validate.sh <project-path>`

Pre-submission validation:
- Builds the project (xcodebuild)
- Runs SwiftLint with zero-error tolerance
- Detects memory leak patterns
- Checks Apple Review Guidelines compliance (font sizes, account deletion, iPad layout)

```bash
./scripts/validate.sh ~/Projects/MyApp
```

### `ship.sh <project-path>`

Full shipping pipeline:
1. Runs validation
2. Bumps build number
3. Archives for App Store
4. Uploads via `xcodebuild -exportArchive`
5. Links build to version
6. Validates IAP screenshots and submission status
7. Submits for App Store review

```bash
./scripts/ship.sh ~/Projects/MyApp
```

### `asc-cli.sh`

Comprehensive App Store Connect CLI:

```bash
ASC=./scripts/asc-cli.sh

# Apps & Status
$ASC apps                           # List all apps
$ASC versions <app-id>              # List versions with state
$ASC builds <app-id> [limit]        # List builds
$ASC status <app-id>                # Full status overview

# Metadata
$ASC description <app-id> "text"    # Set description (4000 char limit)
$ASC subtitle <app-id> "text"       # Set subtitle (30 char + trademark check)
$ASC keywords <app-id> "text"       # Set keywords (100 char + auto-fix)
$ASC get <app-id>                   # Get metadata (JSON)

# TestFlight
$ASC testflight groups <app-id>     # List beta groups
$ASC testflight testers <app-id>    # List beta testers
$ASC testflight builds <app-id>     # List TestFlight builds

# Review & Release
$ASC submit <app-id> [platform]     # Submit for review
$ASC phased start|pause|complete <version-id>

# In-App Purchases
$ASC iap list <app-id>              # List IAPs
$ASC iap get <iap-id>               # IAP details
$ASC iap submit <iap-id>            # Submit IAP for review
$ASC iap review-screenshots get <iap-id>  # Check review screenshots

# Customer Reviews
$ASC reviews <app-id>               # List reviews
```

### `sub-flow.py`

Automated subscription setup:
- Creates subscription groups, subscriptions, and pricing
- Links subscriptions to app versions
- Generates placeholder review screenshots
- Falls back to browser automation for first-time submissions (ASC API limitation)

Exit codes: `0` = success, `1` = error, `2` = needs browser flow

### `asc-metadata.py`

Metadata management via ASC API:
- Update app info, version details, localizations
- Submit versions for review
- Handle screenshot uploads

### `bump-build.sh <project-path> [increment]`

Increment or set build numbers:

```bash
./scripts/bump-build.sh ~/Projects/MyApp          # +1 (default)
./scripts/bump-build.sh ~/Projects/MyApp 5         # +5
./scripts/bump-build.sh ~/Projects/MyApp set:10    # set to 10
```

## Architecture

```
zephshipper/
├── SKILL.md              # OpenClaw skill definition
├── README.md             # This file
└── scripts/
    ├── validate.sh       # Pre-submission validation
    ├── ship.sh           # Full shipping pipeline
    ├── asc-cli.sh        # App Store Connect CLI
    ├── asc-metadata.py   # ASC metadata management
    ├── sub-flow.py       # Subscription setup automation
    ├── bump-build.sh     # Build number management
    └── sim-control.py    # Simulator control for screenshots
```

## Key Design Decisions

- **Level 1 checks are blockers** (Apple tools — build, SwiftLint), **Level 2 are warnings** (heuristics)
- **No git hooks** — validate on demand before shipping
- **Text-based scheme parsing** — Xcode JSON export is unreliable
- **Auto-fix code quality** where possible before failing
- **IAP validation step** checks review screenshots and submission status before shipping
- **First-time subscription submission requires ASC web UI** — API limitation confirmed, browser fallback handles it
- **Subscription descriptions max 55 characters** (ASC enforced)

## License

MIT
