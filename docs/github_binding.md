# GitHub Binding Status

Checked on 2026-06-19 Asia/Shanghai.

- Local git repository: initialized.
- Local commit identity: `zhangta <zhangta@local.invalid>`.
- GitHub remote: `origin https://github.com/slnmkr/us-market-sim-monitor.git`.
- GitHub CLI: no usable `gh` executable or authenticated status was available from the shell.
- Edge browser check: `https://github.com/new` opened, but the page stayed blank in the accessible browser view, so no remote repository was created.
- Push check at `2026-06-19T09:50:03+0800`: `git push -u origin main` failed with `fatal: could not read Username for 'https://github.com': Device not configured`.

The repository is currently auditable locally and has a configured remote. Publishing to GitHub still needs a real authenticated GitHub session or a secure credential flow; do not commit or paste GitHub passwords, cookies, or tokens into this repository.

## Safe local setup path

After the user creates a GitHub repository and provides its URL, run:

```bash
python3 scripts/setup_github_remote.py https://github.com/USER/REPO.git --git-email USER_VERIFIED_EMAIL --refresh-live-gate 2026-06-19
```

The helper only changes local git config and refreshes the local live gate. It rejects token-like URLs and does not accept passwords, cookies, API keys, or GitHub tokens. Pushing still requires a real authenticated GitHub session:

```bash
git push -u origin main
```
