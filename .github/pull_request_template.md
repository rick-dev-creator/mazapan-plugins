<!-- Listing a plugin, or a new version of one. The whole way:
     https://github.com/rick-dev-creator/mazapan/blob/main/docs/publishing-plugins.md -->

**Plugin:** <!-- its id, and one line on what it does -->

- [ ] `mazapan plugins check` passes on the tag
- [ ] The repository is public, with README.md and LICENSE
- [ ] plugin.toml has `author`, `license` and a `[gallery]` icon
- [ ] The tag is `v` + plugin.toml's `version`, and `commit` is `git rev-parse <tag>^{commit}`
- [ ] The entry has only `id`, `source`, `ref`, `commit`, in order by id
- [ ] What it can do (this pull request's check lists it) is what it needs, and its README says why
