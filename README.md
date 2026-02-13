# ZephShipper 🚀

One command to validate and ship iOS/macOS apps to the App Store.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Validate** - Build test, SwiftLint (zero tolerance), memory leak patterns
- **Ship** - Bump version, archive, upload, submit for review
- **Screenshots** - AI-powered intelligent screenshot capture (agent task)

## Requirements

- macOS with Xcode
- Node.js 18+
- [SwiftLint](https://github.com/realm/SwiftLint) (`brew install swiftlint`)
- App Store Connect API key

## Installation

```bash
# Clone into your OpenClaw skills directory
git clone https://github.com/yourusername/zephshipper ~/.openclaw/workspace/skills/zephshipper

# Or install as OpenClaw skill
openclaw skill install zephshipper
```

## Setup

### App Store Connect API Key

1. Go to [App Store Connect → Users and Access → Keys](https://appstoreconnect.apple.com/access/api)
2. Generate a new API key
3. Download the `.p8` file
4. Place it in `~/.appstoreconnect/private_keys/AuthKey_KEYID.p8`
5. Set environment variables:

```bash
export ASC_KEY_ID="YOUR_KEY_ID"
export ASC_ISSUER_ID="YOUR_ISSUER_ID"
```

## Usage

### Validate

Check if an app is ready to ship:

```bash
./scripts/validate.sh ~/Projects/MyApp
```

### Ship

Full pipeline: validate → bump → archive → upload → submit:

```bash
./scripts/ship.sh ~/Projects/MyApp "Bug fixes and improvements"
```

### Screenshots (Agent Task)

Screenshots are captured by the AI agent, not a script. When using with OpenClaw or Claude Code:

```
User: screenshots MyApp
Agent: [analyzes project, captures screenshots intelligently]
```

## How It Works

### Validation Pipeline

1. **Build Test** - `xcodebuild clean build`
2. **Code Quality** - SwiftLint with zero tolerance (auto-fix first)
3. **Memory Leak Patterns** - Detects common leaks (NotificationCenter, Timers, SystemSoundID)

### Ship Pipeline

1. **Validate** - Runs full validation (blocks if fails)
2. **Version Bump** - Increments build number
3. **Archive** - Creates release archive for each platform
4. **Upload** - Uploads to App Store Connect via API
5. **Submit** - Creates version, sets release notes, submits for review

## Configuration

### .swiftlint.yml

Create a `.swiftlint.yml` in your project to customize SwiftLint rules:

```yaml
disabled_rules:
  - line_length
  - file_length

excluded:
  - Pods
  - .build
```

## Contributing

Pull requests welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## License

MIT © Diego Varela
