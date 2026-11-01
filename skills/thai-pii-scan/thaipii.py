#!/usr/bin/env python3
"""thai-pii-scan: find real Thai personal data in code, test fixtures, logs and commits before it leaks.

    python3 thaipii.py                       scan the git repo you're in (tracked and untracked files)
    python3 thaipii.py src/ fixtures/users.csv
    python3 thaipii.py --staged              only lines you're about to commit (pre-commit)
    python3 thaipii.py --diff origin/main    only lines added since a ref (CI)
    kubectl logs api | python3 thaipii.py -  scan stdin
    python3 thaipii.py --test

Finds Thai national ID numbers (checksum and province code must be valid, so random 13-digit numbers
and test numbers from area 9999 don't count), Thai mobile numbers, ID card laser codes and bank account
numbers. Output is always masked, so the scan itself never leaks what it finds. Exit code 1 if anything
is found. Lines containing `thaipii:ignore` are skipped; paths in `.thaipii-ignore` (globs) too.

With --hook it reads a Claude Code PreToolUse event on stdin and asks before the agent writes any of this into a file.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

PROVINCES = {*range(10, 28), *range(30, 50), *range(50, 59), *range(60, 68), *range(70, 78), *range(80, 87), *range(90, 97)}
SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "dist", "build", ".next", "coverage", "__pycache__", "target"}
SKIP_FILES = re.compile(r"(\.lock|-lock\.json|-lock\.yaml|\.min\.js|\.map|\.svg|\.png|\.jpe?g|\.gif|\.pdf|\.woff2?|\.ttf|\.ico|\.zip|\.gz)$", re.I)
SEP = r"[ \t-]?"

NATIONAL_ID = re.compile(rf"(?<![\d.,])(\d){SEP}(\d{{4}}){SEP}(\d{{5}}){SEP}(\d{{2}}){SEP}(\d)(?![\d.,])")
MOBILE = re.compile(r"(?<![\d+])(?:\+66|66|0)[ \t-]?([689]\d)[ \t-]?(\d{3})[ \t-]?(\d{4})(?!\d)")
LASER = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2}\d)(-?)(\d{7})(-?)(\d{2})(?![A-Za-z0-9])")
BANK_FORMATTED = re.compile(r"(?<![\d-])(\d{3})-(\d)-(\d{5})-(\d)(?![\d-])")
BANK_LABELLED = re.compile(r"(?i)(บัญชี|account[\s_-]*(?:no|number|num)?|acct|bank[\s_-]*account)\D{0,20}?(?<!\d)(\d{10,12})(?!\d)")
TIME_CONTEXT = re.compile(r"(?i)(time|timestamp|_at\b|_ts\b|\bts\b|epoch|date|millis|created|updated|expires?)\W{0,4}$")
LASER_CONTEXT = re.compile(r"(?i)laser|เลเซอร์|หลังบัตร|back[\s_-]*of[\s_-]*card")


def thai_id_ok(d):
    """13 digits: personal category 1-8, real province code, valid check digit."""
    if len(d) != 13 or d[0] not in "12345678" or int(d[1:3]) not in PROVINCES:
        return False
    return (11 - sum(int(x) * (13 - i) for i, x in enumerate(d[:12])) % 11) % 10 == int(d[12])


RUNS = ("12345678", "23456789", "34567890", "01234567", "98765432", "87654321", "76543210")


def placeholder(digits):
    """Textbook examples like 1234567890121 or 0812345678: a long straight run, or barely any distinct digits."""
    return len(set(digits)) <= 2 or any(r in digits for r in RUNS)


def scan_line(line):
    """-> [(column, kind, masked)]"""
    if "thaipii:ignore" in line:
        return []
    out, taken = [], []

    def add(m, kind, masked):
        if any(a < m.end() and m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        out.append((m.start() + 1, kind, masked))

    for m in NATIONAL_ID.finditer(line):
        d = "".join(m.groups())
        if thai_id_ok(d) and not placeholder(d[:12]) and not TIME_CONTEXT.search(line[:m.start()]):
            add(m, "national ID", f"{d[0]}-xxxx-xxxxx-xx-{d[12]}")
    for m in LASER.finditer(line):
        if ((m.group(2) and m.group(4)) or LASER_CONTEXT.search(line)) and not placeholder(m.group(1)[2] + m.group(3) + m.group(5)):
            add(m, "ID card laser code", f"{m.group(1)[:2]}x-xxxxxxx-xx")
    for m in MOBILE.finditer(line):
        rest = m.group(1)[1] + m.group(2) + m.group(3)
        if not placeholder(rest):
            add(m, "mobile number", f"0{m.group(1)[0]}x-xxx-x{m.group(3)[-3:]}")
    for m in BANK_FORMATTED.finditer(line):
        if not placeholder("".join(m.groups())):
            add(m, "bank account", f"xxx-x-xxxx{m.group(3)[-1]}-{m.group(4)}")
    for m in BANK_LABELLED.finditer(line):
        num = m.group(2)
        start = m.start(2)
        if not placeholder(num) and not any(a < start + len(num) and start < b for a, b in taken):
            taken.append((start, start + len(num)))
            out.append((start + 1, "bank account", "x" * (len(num) - 4) + num[-4:]))
    return sorted(out)


def scan_text(text, name):
    return [(name, n, col, kind, masked) for n, line in enumerate(text.splitlines(), 1) for col, kind, masked in scan_line(line)]


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else None


def ignored_globs(root):
    try:
        with open(os.path.join(root, ".thaipii-ignore"), encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def skip(path, globs):
    parts = set(path.replace("\\", "/").split("/"))
    return bool(parts & SKIP_DIRS) or bool(SKIP_FILES.search(path)) or any(fnmatch.fnmatch(path, g) for g in globs)


def read(path):
    try:
        if os.path.getsize(path) > 2_000_000:
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace")


def files_under(paths, root):
    if not paths:
        listed = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if listed is not None:
            yield from (p for p in listed.split("\0") if p)
            return
        paths = ["."]
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for dirpath, dirs, names in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            yield from (os.path.join(dirpath, n) for n in names)


def added_lines(diff):
    """Unified diff -> {path: [(line_no, text)]} for added lines."""
    files, cur, line_no = {}, None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            line_no = int(m.group(1)) if m else 0
        elif cur and line.startswith("+"):
            files.setdefault(cur, []).append((line_no, line[1:]))
            line_no += 1
    return files


def scan_diff(root, *diff_args):
    diff = git(root, "diff", "--no-color", "--no-ext-diff", "-U0", *diff_args)
    if diff is None:
        raise SystemExit("thaipii: git diff failed (is this a git repository, and does the ref exist?)")
    globs = ignored_globs(root)
    return [(path, n, col, kind, masked) for path, lines in added_lines(diff).items() if not skip(path, globs)
            for n, text in lines for col, kind, masked in scan_line(text)]


def report(findings):
    for path, n, col, kind, masked in findings:
        print(f"{path}:{n}:{col}  {kind}  {masked}")
    if findings:
        kinds = sorted({f[3] for f in findings})
        print(f"\nthaipii: {len(findings)} finding(s) ({', '.join(kinds)}). Replace them with test data, or mark a line "
              f"`thaipii:ignore` if it really is fake.", file=sys.stderr)
    return 1 if findings else 0


ASK = """thai-pii-scan: this would write what looks like real Thai personal data into {path}:

{items}

Real ID numbers, phone numbers and bank accounts don't belong in code, fixtures, docs or logs (PDPA). Use test data instead: Thai ID numbers from area 9999 with a valid checksum (they can't belong to anyone), phone numbers like 0812345678, made-up accounts. If this data really is fake, add `thaipii:ignore` to the line."""


def hook(data):
    if data.get("hook_event_name") != "PreToolUse":
        return
    ti = data.get("tool_input") or {}
    texts = [ti.get("content"), ti.get("new_string"), ti.get("new_source")] + [e.get("new_string") for e in ti.get("edits") or [] if isinstance(e, dict)]
    findings = [f for t in texts if isinstance(t, str) for f in scan_text(t, "")]
    if findings:
        path = ti.get("file_path") or ti.get("notebook_path") or "a file"
        items = "\n".join(f"- line {n}: {kind} {masked}" for _, n, _, kind, masked in findings[:10])
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                 "permissionDecisionReason": ASK.format(path=path, items=items)}}))


def main(argv):
    if argv[:1] == ["--test"]:
        return test()
    if argv[:1] == ["--hook"]:
        try:
            hook(json.load(sys.stdin))
        except Exception as e:  # a broken hook must never break the session
            print(f"thai-pii-scan: {e}", file=sys.stderr)
        return 0
    root = (git(os.getcwd(), "rev-parse", "--show-toplevel") or os.getcwd()).strip()
    if argv[:1] == ["-"]:
        return report(scan_text(sys.stdin.read(), "stdin"))
    if argv[:1] == ["--staged"]:
        return report(scan_diff(root, "--cached"))
    if argv[:1] == ["--diff"]:
        if len(argv) < 2:
            raise SystemExit("usage: thaipii.py --diff REF")
        return report(scan_diff(root, f"{argv[1]}...HEAD") + scan_diff(root))
    globs = ignored_globs(root)
    findings = []
    base = root if not argv else ""
    for path in files_under(argv, root):
        full = os.path.join(base, path) if base else path
        path = os.path.normpath(path)
        if skip(path, globs):
            continue
        text = read(full)
        if text is not None:
            findings += scan_text(text, path)
    return report(findings)


def make_id(first12):
    return first12 + str((11 - sum(int(x) * (13 - i) for i, x in enumerate(first12)) % 11) % 10)


def test():
    import contextlib
    import io
    import tempfile

    real = make_id("110370012345")             # category 1, Bangkok (10)
    fmt = f"{real[0]}-{real[1:5]}-{real[5:10]}-{real[10:12]}-{real[12]}"
    test_area = make_id("199990012345")        # area 9999: never a real person
    bad_sum = real[:12] + str((int(real[12]) + 1) % 10)
    no_province = make_id("199000012345")      # province 99 doesn't exist
    company = make_id("010553611201")          # category 0: juristic person tax ID, public

    def kinds(line):
        return [k for _, k, _ in scan_line(line)]

    assert kinds(f"citizen_id: {real}") == ["national ID"]
    assert kinds(f"เลขบัตร {fmt}") == ["national ID"]
    assert scan_line(f"id={real}")[0][2] == f"{real[0]}-xxxx-xxxxx-xx-{real[12]}", "masked"
    for clean in (test_area, bad_sum, no_province, company, real + "1", "1" + real, f"{real}.5",
                  f'"created_at": {real}', "price 1,234,567,890,123"):
        assert kinds(f"value {clean}") == [], clean
    assert kinds(f"{real} thaipii:ignore") == []

    assert kinds("โทร 089-123-4567") == ["mobile number"]
    assert kinds("phone: +66 89 123 4567") == ["mobile number"]
    assert kinds('"tel": "0891234567"') == ["mobile number"]
    assert scan_line("call 0891234567")[0][2] == "08x-xxx-x567"
    for fake in ("0812345678", "0800000000", "0899999999", "021234567", "1089123456789"):
        assert kinds(f"x {fake}") == [], fake

    assert kinds("laser: JT1-2093847-56") == ["ID card laser code"]
    assert kinds("เลขหลังบัตร JT1209384756") == ["ID card laser code"]
    assert kinds("laser: JT0-1234567-89") == [], "textbook example"
    assert kinds("example 1-2345-67890-12-1 and 1234567890121") == [], "textbook example"
    assert kinds("order AB1209384756") == []

    assert kinds("โอนเข้า 502-7-31948-6") == ["bank account"]
    assert kinds("account_number: 5027319486") == ["bank account"]
    assert kinds("เลขบัญชี 5027319486") == ["bank account"]
    assert kinds("เลขบัญชี 123-4-56789-0") == [], "textbook example"
    assert kinds("order 5027319486") == []

    with tempfile.TemporaryDirectory() as d:
        g = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, check=True)  # noqa: E731
        g("init", "-q")
        g("config", "user.email", "t@t")
        g("config", "user.name", "t")
        os.makedirs(os.path.join(d, "fixtures"))
        os.makedirs(os.path.join(d, "node_modules", "x"))
        with open(os.path.join(d, "fixtures", "users.json"), "w") as fh:
            fh.write(f'[{{"name": "สมชาย", "cid": "{real}", "phone": "0891234567"}}]\n')
        with open(os.path.join(d, "fixtures", "fake.json"), "w") as fh:
            fh.write(f'[{{"cid": "{test_area}", "phone": "0812345678"}}]\n')
        with open(os.path.join(d, "node_modules", "x", "data.js"), "w") as fh:
            fh.write(f"const id = '{real}'\n")
        with open(os.path.join(d, ".thaipii-ignore"), "w") as fh:
            fh.write("docs/*\n")
        os.makedirs(os.path.join(d, "docs"))
        with open(os.path.join(d, "docs", "example.md"), "w") as fh:
            fh.write(f"{real}\n")
        old = os.getcwd()
        os.chdir(d)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main([])
            text = out.getvalue()
            assert code == 1 and "fixtures/users.json:1:" in text and text.count("\n") == 2, text
            assert real not in text and "fake.json" not in text and "node_modules" not in text and "docs/" not in text, text

            g("add", "fixtures/fake.json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                assert main(["--staged"]) == 0, out.getvalue()
            g("add", "fixtures/users.json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                assert main(["--staged"]) == 1
            assert "fixtures/users.json:1:" in out.getvalue()
        finally:
            os.chdir(old)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        hook({"hook_event_name": "PreToolUse", "tool_name": "Write",
              "tool_input": {"file_path": "seed.sql", "content": f"insert into users values ('{real}', '0891234567');"}})
    assert '"permissionDecision": "ask"' in out.getvalue() and real not in out.getvalue(), out.getvalue()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        hook({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "a.py", "new_string": f"X = '{test_area}'"}})
    assert out.getvalue() == ""
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
