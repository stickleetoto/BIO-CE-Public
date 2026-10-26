<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Security Policy

## Supported versions

BIO CE is a pre-release project. Only the latest release candidate on the default branch receives security fixes.

| Version | Supported |
|---|---|
| 0.3.0-rc1 (current) | Yes |
| 0.2.0-rc1 and earlier previews | No; please update |

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability):
open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue, pull
request, or discussion for a security problem.

Please include the BIO CE version, Windows version, what you did, what you expected, and what happened. Use
synthetic data only. Never send real memories, host configuration files, connection tokens, or API keys.

This is a volunteer-maintained preview: reports are handled on a best-effort basis, without a guaranteed response
time. Please give a reasonable period for a fix before any public disclosure. There is no bug bounty.

## Scope

In scope, for example:

- An AI host doing more through BIO CE's MCP tools than its connection allows (writing while Read only or Paused,
  reading another project or namespace, using a revoked connection).
- Secrets, document content, or injected instructions being stored despite the memory policy in a way the
  documentation says is refused.
- The desktop app, installer, or uninstaller changing host settings or user data without the documented
  confirmation, or deleting user data unexpectedly.
- Memory content or tokens being written to logs or sent anywhere off the machine by BIO CE itself.

Out of scope, as documented in [Desktop Security](docs/desktop-security.md) and
[Known Limitations](docs/known-limitations.md):

- Attacks by other programs running as the same Windows user. They can read the SQLite files, backups, and host
  configuration (including connection tokens) directly. BIO CE does not encrypt data at rest.
- Retracted memories remaining recoverable from the database file. Retraction is not a secure erase.
- What a connected AI host or its model provider does with memories the host was allowed to read.
- Heuristic misses in the memory policy that the documentation already lists as limitations, unless they bypass
  a guarantee stated as absolute.
- Unsigned-installer or SmartScreen warnings.
