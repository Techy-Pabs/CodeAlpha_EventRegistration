# CodeAlpha Event Registration System

## Secret check

A pre-commit hook in `.githooks/pre-commit` blocks any commit that stages a
`.env` file, a generated Django "insecure" secret key, or a value copied from your local
`.env`. It also blocks the commit if the check itself fails.

Git does not enable repository hooks automatically, so after cloning run
this once:

```bash
git config core.hooksPath .githooks
```
