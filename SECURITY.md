# Security Policy

## Reporting Security Issues

Do not open a public GitHub issue for secrets, account compromise, wallet problems, or vulnerabilities that include private data.

Contact the maintainer by email:

igor.ignatenko.10@mail.ru

Include only the minimum technical details needed to reproduce the issue. Do not send wallet mnemonics, Fragment cookies, private keys, PyPI tokens, or production API keys.

## Secret Handling

This project must never store or log:

- TON wallet mnemonics.
- Fragment cookies.
- TonCenter API keys.
- PyPI tokens.
- Local database files.

If any of these values are accidentally exposed, revoke or rotate them immediately.
