# thai-pii-scan

[ภาษาไทย](README.md) · From the maker of [thai-id-card-kit](https://github.com/nuttakulsv/thai-id-card-kit) and [thaiproof](https://github.com/nuttakulsv/thaiproof)

Real customers' Thai national ID numbers end up in repos more often than anyone admits: a seed file exported from production, a fixture copied from a bug report, a log that prints whole requests, an agent that queried the real database while debugging and wrote the result into test data. Once committed, it's in git history forever, and under Thailand's PDPA that's a data leak.

thai-pii-scan finds Thai personal data in code, fixtures, logs and commits before it gets out.

```
$ python3 thaipii.py
fixtures/users.json:14:22  national ID  1-xxxx-xxxxx-xx-3
fixtures/users.json:14:51  mobile number  08x-xxx-x567
scripts/import.log:203:9  ID card laser code  JTx-xxxxxxx-xx
docs/refund.md:31:18  bank account  xxx-x-xxxx1-6
```

Output is always masked, so the scan never leaks what it finds into CI logs.

## What it finds

| Data | How it avoids false alarms |
|---|---|
| **Thai national ID** (13 digits, with or without dashes) | valid check digit, personal category 1 to 8, and a real province code in digits 2 and 3. Random 13-digit numbers, area-9999 test numbers, company tax IDs (starting with 0) and timestamps don't match |
| **Mobile numbers** (06/08/09, local or +66) | skips placeholders like 0812345678 |
| **ID card laser codes** | dashed form, or undashed with "laser"/"หลังบัตร" on the same line |
| **Bank accounts** | `xxx-x-xxxxx-x`, or 10 to 12 digits right after "account"/"บัญชี" |

Textbook examples like `1-2345-67890-12-1` and `JT0-1234567-89` are ignored.

## Use it

`python3` only (plus `git` to scan a repo). One file, no dependencies.

```
curl -O https://raw.githubusercontent.com/nuttakulsv/thai-pii-scan/main/skills/thai-pii-scan/thaipii.py
python3 thaipii.py                       # the repo
python3 thaipii.py --staged              # lines about to be committed
python3 thaipii.py --diff origin/main    # lines added on this branch (CI)
kubectl logs deploy/api | python3 thaipii.py -
```

Exit code 1 on findings. `thaipii:ignore` on a line skips it; globs in `.thaipii-ignore` skip files.

**pre-commit:**

```yaml
repos:
  - repo: https://github.com/nuttakulsv/thai-pii-scan
    rev: main
    hooks:
      - id: thai-pii-scan
```

**Coding agents:** a Claude Code hook asks before the agent writes real-looking Thai personal data into any file, and a skill (for any agent that reads SKILL.md) covers PDPA-minded handling: test data instead of real data, no personal data in logs or third-party tools, scan before committing.

```
/plugin marketplace add nuttakulsv/thai-pii-scan
/plugin install thai-pii-scan@thai-pii-scan
npx skills add nuttakulsv/thai-pii-scan
```

## Already committed?

Fixing the file isn't enough; it's still in history. Rewrite history with [git filter-repo](https://github.com/newren/git-filter-repo) and force-push, and if the repo was ever public or cloned, treat it as a leak and involve your DPO. See the [PDPC](https://www.pdpc.or.th/).

## Limits

- A safety net, not a PDPA compliance guarantee.
- Names, addresses, emails and birth dates aren't detected: real and fake look the same.
- Some unrelated 13-digit numbers will pass the checksum and province check by chance. Mark them `thaipii:ignore`.
- IDs starting with 0 are skipped because they overlap with public company tax IDs.

## Tests

```
python3 skills/thai-pii-scan/thaipii.py --test
```

## License

MIT
