# Security policy

MOODY BLUES is a v0.1.0 developer alpha. Read the [trust model](docs/security/trust-model.md) first: it is not intended to run
hostile code from strangers, and containers share the host kernel.

## Reporting a vulnerability

Please do not open a public issue. Report privately through
[GitHub security advisories](https://github.com/RaulMermans/moody-blues/security/advisories/new), with what you found, how to
reproduce it and what it affects.

This is a small project, with no guaranteed response time. Only the latest commit on `main` is supported.

## In scope

An escape from the sandbox settings as documented, an agent influencing a verdict, reaching state or the Oracle, secrets
reaching a sandbox, a browser or exported evidence, and anonymous access to anything beyond recorded investigations.

## Out of scope

Kernel or container-runtime exploits, which the trust model already excludes. Results from running an agent you chose to trust.
Anything that needs access to the Docker daemon, which is already root-equivalent.
