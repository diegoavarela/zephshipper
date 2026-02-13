# Contributing to ZephShipper

Thanks for your interest in contributing! 🎉

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests locally
5. Commit with a clear message (`git commit -m 'Add amazing feature'`)
6. Push to your fork (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

```bash
git clone https://github.com/yourusername/zephshipper
cd zephshipper
```

## Code Style

- Shell scripts: Use `shellcheck` for linting
- Keep scripts POSIX-compatible where possible
- Add comments for non-obvious logic

## Testing

Test against real iOS/macOS projects before submitting PRs:

```bash
./scripts/validate.sh /path/to/test/project
```

## Reporting Issues

- Use GitHub Issues
- Include macOS version, Xcode version
- Include full error output
- Minimal reproduction steps

## Feature Requests

Open an issue with the `enhancement` label. Describe:
- What problem it solves
- Proposed solution
- Alternatives considered

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
