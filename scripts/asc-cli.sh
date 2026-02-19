#!/bin/bash
# ZephShipper ASC CLI wrapper
# Uses `asc` (App Store Connect CLI) as backend with ZephShipper guardrails
# Replaces asc-metadata.py

set -euo pipefail

# --- Guardrails ---
APPLE_TRADEMARKS=(
  "apple" "iphone" "ipad" "mac" "macbook" "imac" "airpods" "apple watch"
  "ios" "macos" "ipados" "watchos" "tvos" "visionos" "siri" "safari"
  "app store" "testflight" "xcode" "swift" "swiftui" "itunes"
)

check_trademark() {
  local text
  text=$(echo "$1" | tr '[:upper:]' '[:lower:]')
  for tm in "${APPLE_TRADEMARKS[@]}"; do
    if [[ "$text" == *"$tm"* ]]; then
      echo "BLOCKED: Subtitle contains Apple trademark '$tm'"
      exit 1
    fi
  done
}

check_url() {
  local url="$1"
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
  if [[ "$status" != "200" && "$status" != "301" && "$status" != "302" ]]; then
    echo "WARNING: URL $url returned HTTP $status"
    return 1
  fi
  return 0
}

CMD="${1:-help}"
shift || true

case "$CMD" in
  # --- App listing ---
  apps)
    asc apps list --output "${1:-table}"
    ;;

  # --- Version management ---
  versions)
    APP_ID="${1:?Usage: asc-cli.sh versions <app-id>}"
    asc versions list --app "$APP_ID" --output table
    ;;

  # --- Build listing ---
  builds)
    APP_ID="${1:?Usage: asc-cli.sh builds <app-id> [limit]}"
    LIMIT="${2:-5}"
    asc builds list --app "$APP_ID" --limit "$LIMIT" --output table
    ;;

  # --- Get metadata ---
  get)
    APP_ID="${1:?Usage: asc-cli.sh get <app-id>}"
    asc app-info get --app "$APP_ID" --output json
    ;;

  # --- Set description ---
  description)
    APP_ID="${1:?Usage: asc-cli.sh description <app-id> <text>}"
    TEXT="${2:?Missing description text}"
    if [ ${#TEXT} -gt 4000 ]; then
      echo "BLOCKED: Description exceeds 4000 chars (${#TEXT})"
      exit 1
    fi
    # Get latest version localization and update
    VER_ID=$(asc versions list --app "$APP_ID" --output json | python3 -c "
import json,sys
data=json.load(sys.stdin)
for v in data:
    if v['attributes']['appStoreState'] in ('PREPARE_FOR_SUBMISSION','DEVELOPER_REJECTED'):
        print(v['id']); break
" 2>/dev/null)
    if [ -z "$VER_ID" ]; then
      echo "ERROR: No editable version found"
      exit 1
    fi
    asc localizations update --version "$VER_ID" --locale "en-US" --description "$TEXT"
    echo "Description updated (${#TEXT} chars)"
    ;;

  # --- Set subtitle (with trademark check) ---
  subtitle)
    APP_ID="${1:?Usage: asc-cli.sh subtitle <app-id> <text>}"
    TEXT="${2:?Missing subtitle text}"
    if [ ${#TEXT} -gt 30 ]; then
      echo "BLOCKED: Subtitle exceeds 30 chars (${#TEXT})"
      exit 1
    fi
    check_trademark "$TEXT"
    asc app-info update --app "$APP_ID" --subtitle "$TEXT" --locale "en-US"
    echo "Subtitle set: '$TEXT' (${#TEXT}/30 chars)"
    ;;

  # --- Set keywords ---
  keywords)
    APP_ID="${1:?Usage: asc-cli.sh keywords <app-id> <keywords>}"
    TEXT="${2:?Missing keywords}"
    if [ ${#TEXT} -gt 100 ]; then
      echo "BLOCKED: Keywords exceed 100 chars (${#TEXT})"
      exit 1
    fi
    # Check for spaces after commas
    if [[ "$TEXT" == *", "* ]]; then
      echo "WARNING: Keywords have spaces after commas — wastes chars. Fixing..."
      TEXT=$(echo "$TEXT" | sed 's/, /,/g')
    fi
    VER_ID=$(asc versions list --app "$APP_ID" --output json | python3 -c "
import json,sys
data=json.load(sys.stdin)
for v in data:
    if v['attributes']['appStoreState'] in ('PREPARE_FOR_SUBMISSION','DEVELOPER_REJECTED'):
        print(v['id']); break
" 2>/dev/null)
    asc localizations update --version "$VER_ID" --locale "en-US" --keywords "$TEXT"
    echo "Keywords set (${#TEXT}/100 chars)"
    ;;

  # --- TestFlight ---
  testflight)
    SUBCMD="${1:?Usage: asc-cli.sh testflight <groups|testers|builds> <app-id>}"
    APP_ID="${2:?Missing app-id}"
    case "$SUBCMD" in
      groups) asc testflight beta-groups list --app "$APP_ID" --output table ;;
      testers) asc testflight beta-testers list --app "$APP_ID" --output table ;;
      builds) asc builds list --app "$APP_ID" --limit 10 --output table ;;
      *) echo "Unknown testflight subcommand: $SUBCMD" ;;
    esac
    ;;

  # --- Review submission ---
  submit)
    APP_ID="${1:?Usage: asc-cli.sh submit <app-id> [platform]}"
    PLATFORM="${2:-IOS}"
    asc review submit --app "$APP_ID" --platform "$PLATFORM"
    echo "Submitted for review ($PLATFORM)"
    ;;

  # --- Status check with URL validation ---
  status)
    APP_ID="${1:?Usage: asc-cli.sh status <app-id>}"
    echo "=== APP STATUS ==="
    asc versions list --app "$APP_ID" --output table
    echo ""
    echo "=== BUILDS ==="
    asc builds list --app "$APP_ID" --limit 3 --output table
    echo ""
    # Check URLs
    echo "=== URL CHECKS ==="
    INFO=$(asc app-info get --app "$APP_ID" --output json 2>/dev/null || echo "{}")
    for field in supportUrl marketingUrl privacyUrl; do
      URL=$(echo "$INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$field',''))" 2>/dev/null)
      if [ -n "$URL" ]; then
        if check_url "$URL"; then
          echo "  $field: $URL ✅"
        else
          echo "  $field: $URL ⚠️"
        fi
      fi
    done
    ;;

  # --- Screenshots ---
  screenshots)
    SUBCMD="${1:?Usage: asc-cli.sh screenshots <list|upload> <app-id> [files...]}"
    APP_ID="${2:?Missing app-id}"
    case "$SUBCMD" in
      list) asc screenshots list --app "$APP_ID" --output table ;;
      upload)
        shift 2
        for f in "$@"; do
          echo "Uploading $f..."
          asc screenshots upload --app "$APP_ID" --file "$f"
        done
        ;;
    esac
    ;;

  # --- Phased release ---
  phased)
    SUBCMD="${1:?Usage: asc-cli.sh phased <start|pause|resume|complete> <version-id>}"
    VER_ID="${2:?Missing version-id}"
    case "$SUBCMD" in
      start) asc versions phased-release create --version "$VER_ID" ;;
      pause) asc versions phased-release pause --version "$VER_ID" ;;
      resume) asc versions phased-release resume --version "$VER_ID" ;;
      complete) asc versions phased-release complete --version "$VER_ID" ;;
    esac
    ;;

  # --- Customer reviews ---
  reviews)
    APP_ID="${1:?Usage: asc-cli.sh reviews <app-id>}"
    asc reviews list --app "$APP_ID" --output table
    ;;

  # --- Raw passthrough to asc ---
  raw)
    asc "$@"
    ;;

  help|--help|-h)
    cat << 'EOF'
ZephShipper ASC CLI (powered by asc)

COMMANDS:
  apps                          List all apps
  versions <app-id>             List versions
  builds <app-id> [limit]       List builds
  get <app-id>                  Get app metadata (JSON)
  description <app-id> <text>   Set description (4000 char limit)
  subtitle <app-id> <text>      Set subtitle (30 char, trademark check)
  keywords <app-id> <text>      Set keywords (100 char, auto-fix spaces)
  testflight <sub> <app-id>     TestFlight: groups|testers|builds
  submit <app-id> [platform]    Submit for review
  status <app-id>               Full status check with URL validation
  screenshots <sub> <app-id>    Screenshots: list|upload
  phased <sub> <version-id>     Phased release: start|pause|resume|complete
  reviews <app-id>              Customer reviews
  raw <args...>                 Pass-through to asc CLI

GUARDRAILS:
  - Apple trademark blocking in subtitles
  - Character limit enforcement
  - Keyword space-after-comma auto-fix
  - URL liveness checks
EOF
    ;;

  *)
    echo "Unknown command: $CMD (try: asc-cli.sh help)"
    exit 1
    ;;
esac
