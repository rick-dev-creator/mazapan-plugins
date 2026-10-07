# Mazapan plugin registry

The plugins others made for [Mazapan](https://github.com/rick-dev-creator/mazapan),
each in its own repository. This repository only says where each one lives
and which version is listed; Mazapan's Plugins panel, `mazapan plugins add`
and the gallery at [mazapan.dev/plugins](https://mazapan.dev/plugins/) all
read from it.

| Plugin | What it does |
|---|---|
| [Markets](https://github.com/rick-dev-creator/mazapan-markets) | Crypto and stock prices with trend charts, a watchlist, a ticker in the bar |
| [Pomodoro](https://github.com/rick-dev-creator/mazapan-pomodoro) | Focus sessions and breaks, a ring, today and the week, Do Not Disturb while you focus |

## How it works

- **The code stays yours.** Your plugin lives in your repository: its
  issues, its releases, its README. A version is a tag, `vX.Y.Z`, the same
  as `version` in its plugin.toml.
- **The registry lists a commit, not only a tag.** Each entry in
  [plugins.toml](plugins.toml) is the repository, the tag and that tag's
  commit. What was looked at is exactly what Mazapan installs, even if the
  tag is moved later.
- **Everything else comes from your plugin.** Its name, description,
  translations, author, license, icon and screenshots are read from its
  plugin.toml at that commit, into [generated/](generated): `index.toml`
  (what Mazapan reads), `plugins.json` and `media/` (what mazapan.dev
  shows). Nothing to keep in sync by hand.
- **New versions come by themselves.** Every six hours the registry looks
  for a newer `vX.Y.Z` tag in each plugin's repository. One that passes the
  checks and can do nothing the listed version couldn't is listed at once.
  One that would be able to do more becomes a pull request, for a person to
  look at. Either way, people who have it installed are asked again in
  Mazapan for anything new it would be able to do.

## Listing your plugin

**The whole way, step by step: [Publishing a plugin](https://github.com/rick-dev-creator/mazapan/blob/main/docs/publishing-plugins.md).**
In short:

1. Your plugin in a **public repository**, plugin.toml at its root, with
   a README.md and a LICENSE, `author`, `license` and a `[gallery]` icon
   in plugin.toml. `mazapan plugins new my-plugin --kind panel --dir .`
   gives one to start from.
2. **`mazapan plugins check .`** with no errors. Add the same check to
   your CI:

   ```yaml
   # .github/workflows/check.yml
   name: Check
   on: [push, pull_request, workflow_dispatch]
   jobs:
     check:
       uses: rick-dev-creator/mazapan-plugins/.github/workflows/check-plugin.yml@main
   ```

3. **Tag the version**, `v` + plugin.toml's version: `git tag v1.0.0 && git push origin v1.0.0`.
4. **A pull request** adding your entry to plugins.toml, in order by id:

   ```toml
   [[plugin]]
   id = "my-plugin"
   source = "https://github.com/you/mazapan-my-plugin"
   ref = "v1.0.0"
   commit = "…"   # git rev-parse v1.0.0^{commit}
   ```

The pull request's check fetches your plugin at that commit, checks it,
and says everything it would be able to do. A person then looks at it:
listing a plugin is the registry vouching that it's what it says it is.
After that, **new versions are only tags**: the registry finds them.

## What the registry asks

- The id is the plugin's own, isn't one of Mazapan's, and isn't listed yet.
- The tag is `vX.Y.Z`, it's plugin.toml's version, and it's at the commit listed.
- `mazapan plugins check` passes: it loads, renders with every theme and
  language, and doesn't take a key one of Mazapan's own plugins uses.
- A README.md, a LICENSE, an author and an icon.
- No symlinks or submodules (Mazapan refuses them anyway).

A plugin runs with your permissions: in the shell, in Hyprland, the
commands it says it runs. Mazapan shows all of it before anything is
installed and asks again when an update wants more; the registry's review
is one more pair of eyes, not a guarantee.

## Working on the registry

`tools/registry.py` does everything: `check` (a pull request's entries),
`build` (generated/), `bump` (new versions). It needs git and a mazapan
built from source: `MAZAPAN=…/bin/mazapan MAZAPAN_ROOT=…/mazapan`.
