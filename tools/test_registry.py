#!/usr/bin/env python3
"""
The registry's tool against real git and a real mazapan, with plugins in
repositories made for the test: python tools/test_registry.py (MAZAPAN and
MAZAPAN_ROOT set, as for registry.py).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    r = subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
                        "-c", "tag.gpgsign=false", "-c", "init.defaultBranch=main", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def manifest(id, version, reload="", author="Ana", icon=True):
    return (f'[plugin]\nid = "{id}"\nname = "{id.title()}"\nversion = "{version}"\napi = 1\n'
            f'description = "What {id} does"\ncategories = ["tools"]\nauthor = "{author}"\nlicense = "MIT"\n'
            + ('\n[gallery]\nicon = "icon.svg"\nscreenshots = ["shot.png"]\n' if icon else "")
            + f'\n[[targets]]\ntemplate = "a.tmpl"\noutput = "~/.config/{id}/a"\n'
            + (f'reload = "{reload}"\n' if reload else ""))


def read(path):
    with open(path) as f:
        return f.read()


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="registry-test-")
        self.list = os.path.join(self.tmp, "plugins.toml")
        self.out = os.path.join(self.tmp, "generated")
        self.env = {**os.environ, "REGISTRY_LIST": self.list, "REGISTRY_OUT": self.out, "REGISTRY_LOCAL_SOURCES": "1"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plugin(self, id, version="1.0.0", **kw):
        """A plugin's repository, tagged at its version: (its folder, the tag's commit)."""
        d = os.path.join(self.tmp, "src", id)
        os.makedirs(d)
        git(d, "init", "--quiet")
        self.write(d, id, version, **kw)
        return d, self.release(d, version)

    def write(self, d, id, version, **kw):
        files = {"plugin.toml": manifest(id, version, **kw), "a.tmpl": "x\n", "README.md": f"# {id}\n\nIt does things.\n",
                 "LICENSE": "MIT\n", "icon.svg": "<svg/>", "shot.png": "png"}
        for k, v in files.items():
            with open(os.path.join(d, k), "w") as f:
                f.write(v)

    def release(self, d, version):
        git(d, "add", "-A")
        git(d, "commit", "--quiet", "--allow-empty", "-m", version)
        git(d, "tag", f"v{version}")
        return git(d, "rev-parse", "HEAD")

    def listing(self, *entries):
        with open(self.list, "w") as f:
            f.write("# the registry\n\n" + "\n".join(
                f'[[plugin]]\nid = "{id}"\nsource = "{src}"\nref = "{ref}"\ncommit = "{commit}"\n' for id, src, ref, commit in entries))

    def run_tool(self, *args, env=None, cwd=None):
        r = subprocess.run([sys.executable, os.path.join(HERE, "registry.py"), *args], env=env or self.env, cwd=cwd,
                           capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout + r.stderr

    # --- check ---

    def test_a_good_entry_passes_and_says_what_it_can_do(self):
        src, c = self.plugin("hello")
        self.listing(("hello", src, "v1.0.0", c))
        code, out = self.run_tool("check")
        self.assertEqual(code, 0, out)
        self.assertIn("✓ hello 1.0.0", out)
        self.assertIn("    - full access, a config that can run commands: ~/.config/hello/a", out)

    def test_what_the_registry_refuses(self):
        src, c = self.plugin("hello")
        cases = [
            (("hello", src, "v1.0.0", "0" * 40), "the tag v1.0.0 is at"),
            (("other", src, "v1.0.0", c), 'the repository\'s plugin is "hello"'),
            (("palette", src, "v1.0.0", c), "a plugin Mazapan ships"),
            (("hello", src, "v2.0.0", c), "no tag v2.0.0"),
        ]
        for entry, says in cases:
            self.listing(entry)
            code, out = self.run_tool("check")
            self.assertEqual(code, 1, out)
            self.assertIn(says, out)
        # The tag isn't the version.
        git(src, "tag", "v1.0.1")
        self.listing(("hello", src, "v1.0.1", c))
        self.assertIn("they must match", self.run_tool("check")[1])
        # No author, icon, license or README.
        d, c2 = self.plugin("bare", author="", icon=False)
        os.remove(os.path.join(d, "LICENSE"))
        os.remove(os.path.join(d, "README.md"))
        git(d, "add", "-A")
        git(d, "commit", "--quiet", "-m", "bare")
        git(d, "tag", "-f", "v1.0.0")
        self.listing(("bare", d, "v1.0.0", git(d, "rev-parse", "HEAD")))
        out = self.run_tool("check")[1]
        for says in ["no LICENSE", "no README.md", "no author", "no icon"]:
            self.assertIn(says, out)
        # A symlink.
        os.symlink("/etc/hostname", os.path.join(d, "link"))
        git(d, "add", "-A")
        git(d, "commit", "--quiet", "-m", "link")
        git(d, "tag", "-f", "v1.0.0")
        self.listing(("bare", d, "v1.0.0", git(d, "rev-parse", "HEAD")))
        self.assertIn("symlink", self.run_tool("check")[1])

    def test_bad_lists_are_refused(self):
        src, c = self.plugin("hello")
        for text, says in [
            (f'[[plugin]]\nid = "hello"\nsource = "{src}"\nref = "v1.0.0"\ncommit = "{c}"\nname = "x"\n', "unknown keys"),
            (f'[[plugin]]\nid = "hello"\nsource = "{src}"\nref = "main"\ncommit = "{c}"\n', "vX.Y.Z"),
            (f'[[plugin]]\nid = "hello"\nsource = "{src}"\nref = "v1.0.0"\ncommit = "{c[:10]}"\n', "full commit"),
            (f'[[plugin]]\nid = "Hello"\nsource = "{src}"\nref = "v1.0.0"\ncommit = "{c}"\n', "lowercase"),
            (f'[[plugin]]\nid = "hello"\nsource = "http://example.com/x"\nref = "v1.0.0"\ncommit = "{c}"\n', "https address"),
            (f'[[plugin]]\nid = "hello"\nsource = "{src}"\nref = "v1.0.0"\ncommit = "{c}"\n' * 2, "listed twice"),
        ]:
            with open(self.list, "w") as f:
                f.write(text)
            code, out = self.run_tool("check")
            self.assertEqual(code, 1, out)
            self.assertIn(says, out)

    def test_only_the_entries_asked_for(self):
        a, ca = self.plugin("aaa")
        self.listing(("aaa", a, "v1.0.0", ca), ("bbb", a, "v1.0.0", ca))
        code, out = self.run_tool("check", "--entries", "aaa")
        self.assertEqual(code, 0, out)
        self.assertNotIn("bbb", out)

    # --- build ---

    def test_build_makes_what_mazapan_and_the_site_read(self):
        src, c = self.plugin("hello")
        self.listing(("hello", src, "v1.0.0", c))
        code, out = self.run_tool("build")
        self.assertEqual(code, 0, out)
        data = json.loads(read(os.path.join(self.out, "plugins.json")))
        p = data["plugins"][0]
        self.assertEqual((p["id"], p["version"], p["commit"], p["author"], p["icon"]), ("hello", "1.0.0", c, "Ana", "media/hello/icon.svg"))
        self.assertEqual(p["screenshots"], ["media/hello/screenshot-1.png"])
        self.assertEqual(p["pictures"], ["icon.svg", "shot.png"])
        self.assertTrue(os.path.isfile(os.path.join(self.out, "media", "hello", "screenshot-1.png")))
        # Mazapan reads index.toml: its own catalog, in a home of its own.
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        r = subprocess.run([os.environ["MAZAPAN"], "plugins", "search", "hello"], capture_output=True, text=True,
                           env={**os.environ, "HOME": home, "MAZAPAN_PLUGIN_CATALOG": os.path.join(self.out, "index.toml")})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("What hello does", r.stdout)
        added = p["added"]

        # Built again: nothing changes (dates included).
        before = read(os.path.join(self.out, "plugins.json"))
        self.run_tool("build")
        self.assertEqual(before, read(os.path.join(self.out, "plugins.json")))

        # A new version: updated now, listed when it was.
        self.write(src, "hello", "1.1.0")
        c2 = self.release(src, "1.1.0")
        self.listing(("hello", src, "v1.1.0", c2))
        self.run_tool("build")
        p = json.loads(read(os.path.join(self.out, "plugins.json")))["plugins"][0]
        self.assertEqual((p["version"], p["added"]), ("1.1.0", added))

        # Its repository gone for now: kept as it was, never dropped by a hiccup.
        shutil.move(src, src + "-away")
        code, out = self.run_tool("build")
        self.assertEqual(code, 0, out)
        self.assertIn("✗ hello", out)
        p = json.loads(read(os.path.join(self.out, "plugins.json")))["plugins"][0]
        self.assertEqual(p["version"], "1.1.0")
        self.assertTrue(os.path.isfile(os.path.join(self.out, "media", "hello", "icon.svg")))

    # --- bump ---

    def test_bump_lists_what_can_do_no_more_and_proposes_the_rest(self):
        same, cs = self.plugin("same")
        more, cm = self.plugin("more")
        self.listing(("more", more, "v1.0.0", cm), ("same", same, "v1.0.0", cs))
        before = read(self.list)
        # Nothing newer: nothing done.
        summary = os.path.join(self.tmp, "bump.json")
        self.assertEqual(self.run_tool("bump", "--summary", summary)[0], 0)
        self.assertEqual(read(self.list), before)

        self.write(same, "same", "1.1.0")
        cs2 = self.release(same, "1.1.0")
        self.write(same, "same", "1.2.0")
        cs3 = self.release(same, "1.2.0")  # the newest is the one taken
        self.write(more, "more", "2.0.0", reload="pkill -USR1 more")
        cm2 = self.release(more, "2.0.0")
        git(same, "tag", "v1.10.0-rc1")  # not a version tag: ignored
        code, out = self.run_tool("bump", "--summary", summary)
        self.assertEqual(code, 0, out)
        s = json.loads(read(summary))
        self.assertEqual(s["listed"], ["same v1.2.0"])
        self.assertEqual([(p["id"], p["ref"], p["commit"]) for p in s["proposals"]], [("more", "v2.0.0", cm2)])
        self.assertIn("runs after writing: pkill -USR1 more", s["proposals"][0]["more"])
        text = read(self.list)
        self.assertIn(f'ref = "v1.2.0"\ncommit = "{cs3}"', text)
        self.assertIn(f'ref = "v1.0.0"\ncommit = "{cm}"', text)  # left for a person
        self.assertTrue(text.startswith("# the registry\n"))  # the rest as it was

        # A newer tag that doesn't pass: not listed.
        self.write(same, "same", "1.3.0")
        with open(os.path.join(same, "plugin.toml"), "a") as f:
            f.write("nonsense = 1\n")
        self.release(same, "1.3.0")
        code, out = self.run_tool("bump", "--summary", summary)
        self.assertIn("✗ same v1.3.0", out)
        self.assertIn(f'commit = "{cs3}"', read(self.list))

    def test_propose_opens_one_pull_request_per_version(self):
        more, cm = self.plugin("more")
        self.write(more, "more", "2.0.0", reload="pkill -USR1 more")
        cm2 = self.release(more, "2.0.0")
        # The registry's own repository, with an origin, and a gh that writes down what it's asked.
        origin = os.path.join(self.tmp, "origin.git")
        git(self.tmp, "init", "--quiet", "--bare", origin)
        reg = os.path.join(self.tmp, "registry")
        git(self.tmp, "clone", "--quiet", origin, reg)
        lst = os.path.join(reg, "plugins.toml")
        with open(lst, "w") as f:
            f.write(f'[[plugin]]\nid = "more"\nsource = "{more}"\nref = "v1.0.0"\ncommit = "{cm}"\n')
        git(reg, "add", "-A")
        git(reg, "commit", "--quiet", "-m", "list")
        git(reg, "push", "--quiet", "origin", "HEAD:main")
        bin = os.path.join(self.tmp, "bin")
        os.makedirs(bin)
        log = os.path.join(self.tmp, "gh.log")
        with open(os.path.join(bin, "gh"), "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {log}\n')
        os.chmod(os.path.join(bin, "gh"), 0o755)
        env = {**self.env, "REGISTRY_LIST": lst, "PATH": bin + ":" + os.environ["PATH"],
               "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "bot",
               "GIT_CONFIG_KEY_1": "user.email", "GIT_CONFIG_VALUE_1": "bot@example.com"}
        summary = os.path.join(self.tmp, "bump.json")
        self.assertEqual(self.run_tool("bump", "--summary", summary, env=env, cwd=reg)[0], 0)
        code, out = self.run_tool("propose", summary, env=env, cwd=reg)
        self.assertEqual(code, 0, out)
        asked = read(log)
        self.assertIn("more v2.0.0: wants to do more", asked)
        self.assertIn("pkill -USR1 more", asked)
        self.assertIn(cm2, git(reg, "show", "origin/bump/more-v2.0.0:plugins.toml"))
        self.assertIn(cm, read(lst))  # main as it was
        # Once: again, it's there already.
        code, out = self.run_tool("propose", summary, env=env, cwd=reg)
        self.assertIn("already proposed", out)
        self.assertEqual(read(log), asked)


if __name__ == "__main__":
    if not os.environ.get("MAZAPAN"):
        sys.exit("set MAZAPAN and MAZAPAN_ROOT")
    unittest.main(verbosity=2)
