# Contributing

Thanks for improving `fragment-ton-api`.

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip build twine
python -m pip install -e .
```

## Before Opening a Pull Request

Run:

```bash
python -m build
python -m twine check dist\*
```

Keep examples free of real wallet mnemonics, Fragment cookies, API keys, tokens, and database files.

## Issues

Use GitHub Issues for bugs and feature requests:

https://github.com/igore4ick002/fragment-ton-api/issues
