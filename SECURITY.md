# Security Policy

## Supported Versions

`smt-mcp-server-poc` is a proof-of-concept project.

Only the latest version of the default branch is actively maintained. Older commits and snapshots may not receive security fixes.

This project is not intended to provide production-grade security guarantees.

## Reporting a Vulnerability

Please report suspected security vulnerabilities privately using GitHub's **Report a vulnerability** feature for this repository.

Do not open a public GitHub issue containing vulnerability details, credentials, API keys, access tokens, tunnel IDs, or sensitive workspace contents.

When possible, include:

* The affected commit or version
* A description of the issue and its potential impact
* Steps to reproduce the issue
* Relevant configuration details with secrets removed
* Any suggested mitigation or fix

Security-relevant issues may include, for example:

* Access to files that should be blocked by `.mcpignore` or the built-in deny policy
* Path traversal or access outside the configured workspace
* Authentication or authorization bypasses
* Exposure of API keys, access tokens, or other credentials
* Sensitive data leakage through logs
* Unexpected file modification or command execution in functionality intended to be read-only

Issues that affect `tunnel-client` or the OpenAI Secure MCP Tunnel service independently of this repository may also need to be reported to the upstream project or service provider.

Non-security bugs and feature requests should be reported through normal GitHub issues.

## Disclosure

Please allow reasonable time to investigate and address a reported vulnerability before publicly disclosing technical details.

As this is a small proof-of-concept project, no guaranteed response or remediation time is provided.
