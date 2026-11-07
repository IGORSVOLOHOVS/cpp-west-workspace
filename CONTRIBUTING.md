# Contributing

1. Open an issue: what is wanted, why, and numbered acceptance criteria.
2. Branch from `test`: `<code>-<issue>/<type>/<slug>`,
   e.g. `cww-7/feat/short-slug`.
3. Work. Run `.\recipe.ps1 test` until it is green; commit what the
   formatter leaves behind.
4. Commit as `<type>(<scope>): <what changed>`, with `git commit -s`.
5. Push and open a pull request with base `test`, first line
   `Issue: #<issue>`. The gate runs by itself; merge it once it is green.
6. `test` into `release` is the lab's move, not yours: manual tests on the
   cell, a confirmation, and the release makes itself.

The whole of it: BEST_REQUIREMENTS.md.
