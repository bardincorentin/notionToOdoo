# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main`  | ✅ Yes     |

## Reporting a Vulnerability

Please **do not open a public GitHub issue** for security vulnerabilities.

1. Send a report to the repository owner via GitHub's private **Security Advisory** feature:
   `Security → Advisories → New draft security advisory`
2. Include as much detail as possible: steps to reproduce, impact, and potential fix.
3. You will receive an acknowledgement within 48 hours and a resolution plan within 7 days.

## Credentials & Secrets

- This project uses API tokens for Notion and Odoo — store them **only** in `.env` (never commit).
- Rotate any exposed token immediately and open a private advisory.
- The `.gitignore` in this repo blocks `.env` from being committed.

## Dependency Scanning

Dependabot is configured to scan Python dependencies weekly. Security alerts are
reviewed and patched within 14 days of disclosure.
