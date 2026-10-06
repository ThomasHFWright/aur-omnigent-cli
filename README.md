# omnigent-cli for Arch Linux and CachyOS

AUR recipe for Omnigent's CLI, server and agent host. Installs `omni` and
`omnigent`; the desktop client is the separate `omnigent-desktop` package.
Currently supports x86_64.

## Packaging

The three first-party projects are built from upstream's unmodified, versioned
PyPI source distributions. Those distributions already include the web assets.
Upstream's Python dependency bounds do not currently match Arch's packages, so
this package installs a private environment under `/opt/omnigent-cli`, owned
entirely by pacman. It uses system Python, not a downloaded interpreter.

Runtime dependencies use pinned upstream wheels. Every download is in
PKGBUILD's `source` array with a SHA-256 checksum; the dependency manifest is
`requirements.txt`. Build/install commands use offline mode. Dependency licenses
remain in their distributions. This is a deliberate compromise: bundled wheels
are not Arch-built libraries and do not all use Arch's hardening flags. Namcap
also reports private-environment Python imports and `/opt` ELF locations.
They are not a reason to install duplicate system Python dependencies.

`openai-codex` and `claude-code` are optional provider executables. The Claude SDK's
bundled executable is removed so its normal system CLI discovery is used.
SQLite, Git, tmux and Bubblewrap support the core database and host functionality.

## Updates

Install and upgrade through an AUR helper such as Shelly. Omnigent's self-upgrade
is disabled through its installer metadata. Do not run pip/uv against this
pacman-owned environment. Optional Python extras (such as Copilot/Cursor SDKs)
are not included; upstream's extras-install prompts cannot modify it as a normal
user. Request packaging support for extras instead of running those prompts as
root. Native Codex and Claude need only their optional executable packages.

GitHub Actions checks every six hours for stable releases and compatible
runtime dependency updates. Third-party releases have a seven-day waiting
period. Changes publish to AUR automatically only after an unprivileged build,
full Python dependency validation, relocated CLI startup, and database,
password hashing, CEL, WebSocket and isolated server authentication checks pass. Publication uses a
separate job; the AUR key is never supplied to the build job. Installation on
your machine remains a manual package-manager action.

The package pins the system Python minor version. When Arch advances Python,
the workflow resolves matching wheels and rebuilds before publishing matching
bounds. If that build fails, publication stops: do not bypass pacman's dependency
checks. A new compatible package is required before upgrading Python.

## Maintainer checks

Run `.github/scripts/update-release.py --self-test`, then run the script without
arguments using current Arch system Python with `uv` and `python-packaging`.
Review the generated sources, hashes and `.SRCINFO`. Build with
`makechrootpkg -c -r /path/to/chroot -- --check`, and inspect the resulting package
with `namcap`. Keep provider packages optional and test on a clean Arch base,
not only a developer workstation.
