#!/bin/bash
# ZephShipper - Build Number Incrementer
# Bumps CURRENT_PROJECT_VERSION in Xcode project

set -e

PROJECT_DIR="${1:-.}"
INCREMENT="${2:-1}"

# Find project file
PROJ_FILE=$(find "$PROJECT_DIR" -maxdepth 2 -name "*.xcodeproj" -type d | head -1)
if [[ -z "$PROJ_FILE" ]]; then
    echo "❌ No .xcodeproj found in $PROJECT_DIR"
    exit 1
fi

PBXPROJ="$PROJ_FILE/project.pbxproj"
if [[ ! -f "$PBXPROJ" ]]; then
    echo "❌ project.pbxproj not found"
    exit 1
fi

# Get current build number
CURRENT=$(grep -m1 "CURRENT_PROJECT_VERSION = " "$PBXPROJ" | sed 's/.*= //' | tr -d ';' | tr -d ' ')

if [[ -z "$CURRENT" ]]; then
    echo "❌ Could not find CURRENT_PROJECT_VERSION"
    exit 1
fi

# Calculate new build number
if [[ "$INCREMENT" == "set:"* ]]; then
    NEW="${INCREMENT#set:}"
else
    NEW=$((CURRENT + INCREMENT))
fi

# Replace all occurrences
sed -i '' "s/CURRENT_PROJECT_VERSION = $CURRENT;/CURRENT_PROJECT_VERSION = $NEW;/g" "$PBXPROJ"

# Verify
VERIFY=$(grep -m1 "CURRENT_PROJECT_VERSION = " "$PBXPROJ" | sed 's/.*= //' | tr -d ';' | tr -d ' ')

if [[ "$VERIFY" == "$NEW" ]]; then
    echo "✅ Build bumped: $CURRENT → $NEW"
else
    echo "❌ Failed to bump build"
    exit 1
fi
