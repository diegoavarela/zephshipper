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

BUILD_OUTPUT=$(xcodebuild -project "$XCODEPROJ" -scheme "$SCHEME" \
    -destination "generic/platform=iOS Simulator" \
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
# Level 3: Memory Leak Patterns (WARNING)
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Level 3: Memory Leak Patterns"
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
# Summary
# ========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 VALIDATION SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SWIFT_FILES=$(find . -name "*.swift" -not -path "*/.*" | wc -l | xargs)
echo "📁 Swift files: $SWIFT_FILES"

echo ""
echo "✅ VALIDATION PASSED - Ready to ship!"
echo ""
