---
name: thai-pii-scan
description: Use when working with Thai users' personal data - national ID numbers (เลขบัตรประชาชน), phone numbers, ID card laser codes, bank accounts, addresses - in code, seed data, test fixtures, logs, analytics, error reports or docs; when copying data out of a database or log; and before committing. Keeps real personal data out of the repo and out of logs, in line with Thailand's PDPA.
---

# Thai personal data in code

Real people's ID numbers and phone numbers end up in repos all the time: a seed file built from a production export, a test fixture copied from a bug report, a log line that prints the whole request. Once committed, they're in git history for good. Under Thailand's Personal Data Protection Act (PDPA, พ.ร.บ.คุ้มครองข้อมูลส่วนบุคคล พ.ศ. 2562) that's a leak.

## Rules

- **Never copy real personal data into the repo.** Not into fixtures, seeds, tests, docs, examples, issues or commit messages. That includes data you just read from a database, a log or an API response while debugging.
- **Use test data that can't belong to anyone:**
  - Thai ID numbers: area code 9999 (digits 2 to 5) with a valid check digit. Province codes stop at 96, so these never match a real person. [thai-id-card-kit](https://github.com/nuttakulsv/thai-id-card-kit) generates them: `python3 tools/thai_id.py generate`.
  - Phone numbers: obvious placeholders like `0812345678`.
  - Names: clearly made up (สมชาย ทดสอบ), never a customer's.
  - Bank accounts, laser codes: placeholders like `123-4-56789-0`, `JT0-1234567-89`.
- **Don't log personal data.** Log a user id or a masked value (`1-xxxx-xxxxx-xx-3`, last four digits of a phone number). Never log full request bodies from signup, KYC or payment endpoints.
- **Don't send it to third parties by accident:** error trackers, analytics events, LLM prompts, support tools. Scrub before sending.
- **Store only what you need**, and encrypt ID numbers at rest if you must keep them. If a field is only used to check identity once, don't keep it.
- **Copies of ID cards** (สำเนาบัตรประชาชน) contain more than people expect, such as date of birth and address. Treat uploaded card images as highly sensitive: separate storage, restricted access, a retention period.

## Check before you commit

```
python3 <this skill's folder>/thaipii.py            # the whole repo
python3 <this skill's folder>/thaipii.py --staged   # what you're about to commit
```

It finds Thai national ID numbers (with valid checksum and a real province code), mobile numbers, ID card laser codes and bank account numbers, and prints them masked. If it finds something:

1. Replace it with test data (above).
2. If it was already committed, tell the user. Removing it from history needs `git filter-repo` or similar and a force push, which is the user's decision.
3. If it really is fake and the tool is wrong, add `thaipii:ignore` to the line.

When you're unsure whether some data is real, treat it as real and ask the user.
