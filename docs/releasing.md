# Releasing OFTI

OFTI releases are immutable Git tags. PyPI publication is intentionally not
part of the current process.

`ofti.__version__` is the single authoritative version. Setuptools derives
wheel and source-distribution metadata from it, and `ofti version` prints the
same value.

## Release checklist

1. Change only `ofti.__version__` and update release notes when appropriate.
2. Sync and run the mandatory gate:

   ```bash
   uv sync --locked --group dev
   ./scripts/quality.sh
   ```

3. Run the relevant opt-in real OpenFOAM scenarios described in
   [testing.md](testing.md).
4. Build into a clean directory and inspect both metadata files:

   ```bash
   rm -rf dist
   uv build
   uv run python scripts/verify_distribution.py dist
   ```

   Verification requires the wheel and source distribution to carry the same
   version as `ofti.__version__` and the SPDX expression
   `GPL-3.0-or-later`.

5. Install the wheel into a clean environment and verify the public entry
   point:

   ```bash
   tmpenv="$(mktemp -d)"
   uv venv "$tmpenv"
   uv pip install --python "$tmpenv/bin/python" dist/ofti-*.whl
   "$tmpenv/bin/ofti" version
   "$tmpenv/bin/ofti" --help
   ```

6. Commit and push a clean tree.
7. Read the version once, create an annotated tag on that commit, and push it:

   ```bash
   version="$(uv run python -c 'import ofti; print(ofti.__version__)')"
   git tag -a "v${version}" -m "OFTI ${version}"
   git push origin "v${version}"
   ```

8. Optionally create a GitHub Release and attach `dist/*.whl` and
   `dist/*.tar.gz`. This does not publish to PyPI.

Install any tagged release directly from GitHub:

```bash
uv tool install "git+https://github.com/CKPEIIKA/ofti.git@vX.Y.Z"
```
