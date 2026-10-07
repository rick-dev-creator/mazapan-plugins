#!/usr/bin/env python3
"""The Mazapan plugin registry.

plugins.toml lists the plugins others made: where each lives (its own git
repository), the tag of the version listed and its commit. Everything else
comes from the plugin's repository, at that commit.

  registry.py check [--entries ID,...]   every entry (or these) looked at, as a pull request is
  registry.py build                      generated/: index.toml (what Mazapan reads), plugins.json
                                         and media/ (what mazapan.dev shows)
  registry.py bump                       newer tags of each plugin: listed when they can do nothing
                                         more than the version listed; else a pull request to look at

It needs git, and a mazapan built from source: $MAZAPAN (the binary) and
$MAZAPAN_ROOT (its checkout: the built-in plugins and themes each plugin is
checked against).
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(HERE, "plugins.toml")
OUT = os.path.join(HERE, "generated")

ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}\Z")
COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SOURCE = re.compile(r"^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~-]+)+\Z")
KEYS = {"id", "source", "ref", "commit"}
CATEGORIES = ["bar", "panel", "theme", "window", "hardware", "tools", "agent"]
PICTURES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}


class Problem(Exception):
    """What's wrong with an entry, said to its author."""


# --- plugins.toml ---------------------------------------------------------------


def load(path=LIST):
    """The entries of plugins.toml, checked: each a pointer that must lead somewhere sane."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    unknown = set(data) - {"plugin"}
    if unknown:
        raise Problem(f"plugins.toml: unknown keys {sorted(unknown)}")
    entries, seen = [], set()
    for i, e in enumerate(data.get("plugin", [])):
        where = f"plugins.toml: [[plugin]] {e.get('id', i)}"
        if set(e) - KEYS:
            raise Problem(f"{where}: unknown keys {sorted(set(e) - KEYS)} (only {', '.join(sorted(KEYS))})")
        for k in KEYS:
            if not isinstance(e.get(k), str):
                raise Problem(f"{where}: {k} is needed, as a string")
        if not ID.match(e["id"]):
            raise Problem(f"{where}: id: lowercase letters, digits and dashes, as the plugin's own")
        if e["id"] in seen:
            raise Problem(f"{where}: listed twice")
        seen.add(e["id"])
        if not SOURCE.match(e["source"]) or e["source"].endswith(".git"):
            raise Problem(f"{where}: source: the repository's https address (https://github.com/you/mazapan-hello)")
        if not TAG.match(e["ref"]):
            raise Problem(f"{where}: ref: a version's tag, vX.Y.Z")
        if not COMMIT.match(e["commit"]):
            raise Problem(f"{where}: commit: the tag's full commit id (git rev-parse {e['ref']}^{{commit}})")
        entries.append(e)
    return entries


def version_of(tag):
    return tuple(int(x) for x in TAG.match(tag).groups())


def set_entry(text, id, ref, commit):
    """plugins.toml's text with the entry for id at ref and commit; the rest (comments too) as it was."""
    blocks = re.split(r"(?m)^(?=\[\[plugin\]\])", text)
    for i, b in enumerate(blocks):
        if re.search(rf'(?m)^id\s*=\s*"{re.escape(id)}"\s*$', b):
            b = re.sub(r'(?m)^ref\s*=\s*".*"\s*$', f'ref = "{ref}"', b)
            b = re.sub(r'(?m)^commit\s*=\s*".*"\s*$', f'commit = "{commit}"', b)
            blocks[i] = b
            return "".join(blocks)
    raise Problem(f"{id} isn't in plugins.toml")


# --- git ------------------------------------------------------------------------


def git(*args, cwd=None, check=True):
    """git, as mazapan runs it: no config of anyone's, no hooks, never asking."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1", LC_ALL="C")
    harden = ["-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false", "-c", "protocol.ext.allow=never"]
    r = subprocess.run(["git", *harden, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise Problem(f"git {args[0]}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def tags(source):
    """The version tags of a repository, with their commits: {"v1.2.0": commit}."""
    out = {}
    try:
        listing = git("ls-remote", "--tags", "--", source)
    except Problem as p:
        if "could not read Username" in str(p) or "not found" in str(p):
            raise Problem(f"{source} can't be read: is the repository public?")
        raise
    for line in listing.splitlines():
        commit, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        peeled = name.endswith("^{}")
        name = name.removesuffix("^{}")
        if TAG.match(name) and (peeled or name not in out):
            out[name] = commit
    return out


def fetch(e, dest):
    """The plugin at the entry's commit, in dest; refused with symlinks or submodules, as mazapan refuses them."""
    os.makedirs(dest)
    git("init", "--quiet", dest)
    git("-C", dest, "fetch", "--quiet", "--depth=1", "--", e["source"], e["commit"])
    git("-C", dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", e["commit"])
    for line in git("-C", dest, "ls-tree", "-r", "--full-tree", "HEAD").splitlines():
        mode, name = line.split(" ", 1)[0], line.split("\t", 1)[1]
        if mode == "120000":
            raise Problem(f"it has a symlink ({name}); plugins can't")
        if mode == "160000":
            raise Problem(f"it has a submodule ({name}); plugins can't")
    return dest


# --- mazapan ----------------------------------------------------------------------


def mazapan():
    exe, root = os.environ.get("MAZAPAN", ""), os.environ.get("MAZAPAN_ROOT", "")
    if not (exe and root and os.path.isdir(os.path.join(root, "plugins"))):
        raise SystemExit("set MAZAPAN (a mazapan binary) and MAZAPAN_ROOT (its checkout)")
    return exe, root


def builtins():
    _, root = mazapan()
    return {d for d in os.listdir(os.path.join(root, "plugins")) if os.path.isfile(os.path.join(root, "plugins", d, "plugin.toml"))}


def inspect(dir):
    """mazapan plugins check --json: everything a plugin's author should know, and what it says it is."""
    exe, root = mazapan()
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "HOME": home, "MAZAPAN_ROOT": root, "NO_COLOR": "1"}
        r = subprocess.run([exe, "plugins", "check", dir, "--json"], env=env, capture_output=True, text=True, timeout=600)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise Problem(f"mazapan plugins check didn't answer: {(r.stderr or r.stdout).strip()[:500]}")


def look(e, work, strict=True):
    """
    An entry looked at: its plugin fetched at the commit listed, and checked as
    the registry asks. strict: the tag must still be where the entry says (a
    pull request); a build only says so.
    Returns (what plugins check said, its folder, warnings).
    """
    warnings = []
    at = tags(e["source"]).get(e["ref"])
    if at is None:
        raise Problem(f"no tag {e['ref']} in {e['source']}")
    if at != e["commit"]:
        msg = f"the tag {e['ref']} is at {at[:10]} now, the entry says {e['commit'][:10]}"
        if strict:
            raise Problem(msg)
        warnings.append(msg)
    dir = fetch(e, os.path.join(work, e["id"]))
    info = inspect(dir)
    problems = list(info.get("errors", []))
    if info.get("ok") and info["id"] != e["id"]:
        problems.append(f"the repository's plugin is \"{info['id']}\", the entry says \"{e['id']}\"")
    if info.get("ok") and info["version"] != e["ref"][1:]:
        problems.append(f"its plugin.toml says version {info['version']}, its tag {e['ref']}: they must match")
    if e["id"] in builtins():
        problems.append(f"\"{e['id']}\" is a plugin Mazapan ships: pick another id")
    if not any(re.match(r"(?i)^(license|licence|copying)(\.|$)", f) for f in os.listdir(dir)):
        problems.append("no LICENSE file: say what others may do with it")
    if not os.path.isfile(os.path.join(dir, "README.md")):
        problems.append("no README.md: its page would be empty")
    if info.get("ok"):
        if not info.get("author"):
            problems.append("no author: [plugin] author = \"…\"")
        if not info.get("icon"):
            problems.append("no icon: [gallery] icon = \"media/icon.svg\"")
        for c in info.get("categories", []):
            if c not in CATEGORIES:
                problems.append(f"category {c}: one of {', '.join(CATEGORIES)}")
    if problems:
        raise Problem("\n".join(problems))
    warnings += [w for w in info.get("warnings", []) if not w.startswith("its folder is")]
    return info, dir, warnings


# --- check ------------------------------------------------------------------------


def cmd_check(args):
    entries = load()
    only = set(filter(None, (args.entries or "").split(",")))
    failed = 0
    with tempfile.TemporaryDirectory() as work:
        for e in entries:
            if only and e["id"] not in only:
                continue
            try:
                info, _, warnings = look(e, work)
                print(f"✓ {e['id']} {info['version']} ({e['commit'][:10]}): {len(info['capabilities'])} capabilities")
                for cap in info["capabilities"]:
                    print(f"    - {cap}")
                for w in warnings:
                    print(f"  ! {w}")
            except Problem as p:
                failed += 1
                print(f"✗ {e['id']}: " + str(p).replace("\n", "\n    "))
                if os.environ.get("GITHUB_ACTIONS"):
                    print(f"::error title={e['id']}::" + str(p).replace("\n", "%0A"))
    if only - {e["id"] for e in entries}:
        print(f"✗ not in plugins.toml: {', '.join(sorted(only - {e['id'] for e in entries}))}")
        failed += 1
    return 1 if failed else 0


# --- build ------------------------------------------------------------------------


def toml_str(s):
    """A TOML basic string (JSON's escapes are TOML's, but for DEL)."""
    return json.dumps(s, ensure_ascii=False).replace("\x7f", "\\u007F")


def index_toml(plugins, generated):
    lines = [
        "# The Mazapan plugin registry: plugins from others, each in its own",
        "# repository, at the commit the registry looked at. Generated from",
        "# https://github.com/rick-dev-creator/mazapan-plugins; don't edit.",
        f"# {generated}",
        "",
    ]
    for p in plugins:
        lines.append("[[plugin]]")
        for k in ["id", "name", "description", "author", "source", "ref", "commit", "version", "license", "homepage"]:
            if p.get(k):
                lines.append(f"{k} = {toml_str(p[k])}")
        lines.append("categories = [" + ", ".join(toml_str(c) for c in p["categories"]) + "]")
        for lang, t in sorted(p["translations"].items()):
            for k in ["name", "description"]:
                if t.get(k):
                    lines.append(f"translations.{lang}.{k} = {toml_str(t[k])}")
        lines.append("")
    return "\n".join(lines)


def cmd_build(args):
    entries = load()
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    before = {}
    try:
        with open(os.path.join(OUT, "plugins.json")) as f:
            before = {p["id"]: p for p in json.load(f)["plugins"]}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    plugins, failed = [], []
    media = os.path.join(OUT, "media.new")
    shutil.rmtree(media, ignore_errors=True)
    with tempfile.TemporaryDirectory() as work:
        for e in entries:
            try:
                info, dir, warnings = look(e, work, strict=False)
            except Problem as p:
                # One that can't be read now (its repository gone, offline): as
                # it was last time, said; never dropped by a hiccup.
                failed.append(f"{e['id']}: {p}")
                if e["id"] in before and before[e["id"]]["commit"] == e["commit"]:
                    old = before[e["id"]]
                    plugins.append(old)
                    keep = os.path.join(OUT, "media", e["id"])
                    if os.path.isdir(keep):
                        shutil.copytree(keep, os.path.join(media, e["id"]))
                continue
            for w in warnings:
                print(f"! {e['id']}: {w}")
            pics = os.path.join(media, e["id"])
            os.makedirs(pics)

            def picture(rel, name):
                ext = os.path.splitext(rel)[1].lower()
                shutil.copyfile(os.path.join(dir, rel), os.path.join(pics, name + ext))
                return f"media/{e['id']}/{name}{ext}"

            old = before.get(e["id"], {})
            with open(os.path.join(dir, "README.md"), encoding="utf-8", errors="replace") as f:
                readme = f.read()
            plugins.append({
                "id": e["id"],
                "name": info["name"],
                "description": info["description"],
                "version": info["version"],
                "author": info["author"],
                "homepage": info["homepage"] or e["source"],
                "license": info["license"],
                "source": e["source"],
                "ref": e["ref"],
                "commit": e["commit"],
                "categories": info["categories"],
                "requires": info["requires"],
                "capabilities": info["capabilities"],
                "settings": info["settings"],
                "languages": info["languages"],
                "translations": info["translations"],
                "icon": picture(info["icon"], "icon") if info["icon"] else "",
                "screenshots": [picture(s, f"screenshot-{i + 1}") for i, s in enumerate(info["screenshots"])],
                "readme": readme,
                # Where the gallery's pictures are in the repository: the README needn't show them again.
                "pictures": [x for x in [info["icon"], *info["screenshots"]] if x],
                "added": old.get("added", now.isoformat()),
                "updated": old.get("updated", now.isoformat()) if old.get("commit") == e["commit"] else now.isoformat(),
            })
    plugins.sort(key=lambda p: p["id"])
    generated = max([p["updated"] for p in plugins], default=now.isoformat())
    os.makedirs(OUT, exist_ok=True)
    shutil.rmtree(os.path.join(OUT, "media"), ignore_errors=True)
    os.rename(media, os.path.join(OUT, "media"))
    with open(os.path.join(OUT, "plugins.json"), "w") as f:
        json.dump({"generated": generated, "plugins": plugins}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with open(os.path.join(OUT, "index.toml"), "w") as f:
        f.write(index_toml(plugins, generated))
    print(f"{len(plugins)} plugins")
    for x in failed:
        print(f"✗ {x}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=build::{x}".replace("\n", "%0A"))
    return 0


# --- bump -------------------------------------------------------------------------


def cmd_bump(args):
    """
    Each plugin's newest version tag, when it's newer than the one listed and
    passes the checks: listed at once when it can do nothing the listed one
    couldn't (the same capabilities, or fewer); else a pull request that says
    what it would do more, for a person to look at.
    """
    entries = load()
    with open(LIST) as f:
        text = f.read()
    listed, proposals = [], []
    with tempfile.TemporaryDirectory() as work:
        for e in entries:
            try:
                found = tags(e["source"])
            except Problem as p:
                print(f"! {e['id']}: {p}")
                continue
            newer = sorted((t for t in found if version_of(t) > version_of(e["ref"])), key=version_of)
            if not newer:
                continue
            tag = newer[-1]
            n = {**e, "ref": tag, "commit": found[tag]}
            try:
                old_info, _, _ = look(e, os.path.join(work, "old"), strict=False)
                info, _, _ = look(n, os.path.join(work, "new"))
            except Problem as p:
                print(f"✗ {e['id']} {tag}: " + str(p).replace("\n", "\n    "))
                continue
            more = [c for c in info["capabilities"] if c not in old_info["capabilities"]]
            if more:
                proposals.append((n, more, info))
                print(f"? {e['id']} {e['ref']} → {tag}: wants more, a pull request")
            else:
                text = set_entry(text, e["id"], tag, n["commit"])
                listed.append(f"{e['id']} {tag}")
                print(f"✓ {e['id']} {e['ref']} → {tag}")
    if listed:
        with open(LIST, "w") as f:
            f.write(text)
    summary = {"listed": listed, "proposals": [
        {"id": n["id"], "ref": n["ref"], "commit": n["commit"], "more": more, "version": info["version"]} for n, more, info in proposals]}
    if args.summary:
        with open(args.summary, "w") as f:
            json.dump(summary, f, indent=1)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--entries", help="only these ids, comma-separated")
    sub.add_parser("build")
    b = sub.add_parser("bump")
    b.add_argument("--summary", help="write what was done here, as JSON")
    args = ap.parse_args()
    try:
        return {"check": cmd_check, "build": cmd_build, "bump": cmd_bump}[args.cmd](args)
    except Problem as p:
        print(f"✗ {p}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
