# Releasing OFTI

OFTI releases are immutable Git tags. PyPI publication is intentionally not
part of the current release process.

## Release checklist

1. Set one version in `pyproject.toml` and update user-facing release notes.
2. Run `./scripts/quality.sh` and the relevant opt-in real OpenFOAM profiles.
3. Build locally with `uv build`; inspect the wheel and source archive.
4. Install the wheel into a clean environment and verify `ofti --version`.
5. Commit and push a clean tree.
6. Create an annotated `v<version>` tag on that commit and push the tag.
7. Optionally create a GitHub Release for the tag and attach the wheel and source
   archive from `dist/`. This does not publish to PyPI.

Install a tagged release directly from GitHub:

```bash
uv tool install "git+https://github.com/CKPEIIKA/ofti.git@v0.9.3"
```
