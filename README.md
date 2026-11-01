# thai-pii-scan

[English](README.en.md) · จากคนทำ [thai-id-card-kit](https://github.com/nuttakulsv/thai-id-card-kit) และ [thaiproof](https://github.com/nuttakulsv/thaiproof)

เลขบัตรประชาชนของลูกค้าจริงหลุดเข้า repo ได้ง่ายกว่าที่คิด ไฟล์ seed ที่ export มาจาก production, fixture ที่ copy มาจากตั๋วบั๊ก, log ที่ print request ทั้งก้อน หรือ agent ที่ไป query ฐานข้อมูลแล้วเอาผลมาเขียนเป็นข้อมูลทดสอบ พอ commit ไปแล้วก็อยู่ในประวัติ git ตลอดไป และตาม PDPA นั่นคือข้อมูลรั่ว

thai-pii-scan หาข้อมูลส่วนบุคคลของคนไทยในโค้ด ไฟล์ทดสอบ log และ commit ก่อนที่จะหลุดออกไป

```
$ python3 thaipii.py

fixtures/users.json:14:22  national ID  1-xxxx-xxxxx-xx-3
fixtures/users.json:14:51  mobile number  08x-xxx-x567
scripts/import.log:203:9  ID card laser code  JTx-xxxxxxx-xx
docs/refund.md:31:18  bank account  xxx-x-xxxx1-6

thaipii: 4 finding(s) (ID card laser code, bank account, mobile number, national ID).
```

ผลลัพธ์ปิดเลขไว้เสมอ ตัวสแกนเองจึงไม่ทำข้อมูลหลุดซ้ำใน log ของ CI

## หาอะไรบ้าง

| ข้อมูล | จับยังไงไม่ให้ทักมั่ว |
|---|---|
| **เลขบัตรประชาชน 13 หลัก** มีหรือไม่มีขีดก็ได้ | check digit ต้องถูก, หลักแรกต้องเป็น 1 ถึง 8 (บุคคล), หลักที่ 2-3 ต้องเป็นรหัสจังหวัดที่มีจริง ตัวเลข 13 หลักมั่วๆ, เลขทดสอบ area 9999, เลขนิติบุคคล (ขึ้นต้นด้วย 0) และ timestamp จึงไม่โดน |
| **เบอร์มือถือ** 06/08/09 ทั้งแบบ 0xx และ +66 | ข้ามเบอร์ตัวอย่างอย่าง 0812345678, 0800000000 |
| **เลขหลังบัตร (laser code)** เช่น `XX0-0000000-00` | แบบมีขีด หรือแบบไม่มีขีดที่มีคำว่า laser/หลังบัตร อยู่ในบรรทัดเดียวกัน |
| **เลขบัญชีธนาคาร** | แบบ `xxx-x-xxxxx-x` หรือตัวเลข 10-12 หลักที่อยู่หลังคำว่า บัญชี/account |

เลขตัวอย่างในตำรา เช่น `1-2345-67890-12-1` หรือ `JT0-1234567-89` ก็ไม่โดนทัก

## ใช้งาน

ต้องมีแค่ `python3` (และ `git` ถ้าจะสแกน repo) ไฟล์เดียว ไม่มี dependency

```
curl -O https://raw.githubusercontent.com/nuttakulsv/thai-pii-scan/main/skills/thai-pii-scan/thaipii.py

python3 thaipii.py                        # ทั้ง repo (ไฟล์ที่ git track และไฟล์ใหม่ที่ยังไม่ ignore)
python3 thaipii.py fixtures/ seed.sql     # เฉพาะไฟล์หรือโฟลเดอร์
python3 thaipii.py --staged               # เฉพาะบรรทัดที่กำลังจะ commit
python3 thaipii.py --diff origin/main     # เฉพาะบรรทัดที่เพิ่มใน branch นี้ (ใช้ใน CI)
kubectl logs deploy/api | python3 thaipii.py -    # สแกน log จาก stdin
```

เจออะไรจะจบด้วย exit code 1

- **ข้ามบรรทัด:** ใส่ `thaipii:ignore` ไว้ในบรรทัดนั้น
- **ข้ามไฟล์:** เขียน glob ลงไฟล์ `.thaipii-ignore` ที่ root ของ repo เช่น `docs/legal/*`
- `node_modules`, `vendor`, `dist`, lockfile และไฟล์ binary ข้ามให้อยู่แล้ว

### pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/nuttakulsv/thai-pii-scan
    rev: main
    hooks:
      - id: thai-pii-scan
```

ไม่ได้ใช้ pre-commit framework ก็ใส่เป็น git hook ตรงๆ ได้

```sh
printf '#!/bin/sh\nexec python3 path/to/thaipii.py --staged\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

### GitHub Actions

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: curl -sO https://raw.githubusercontent.com/nuttakulsv/thai-pii-scan/main/skills/thai-pii-scan/thaipii.py
- run: python3 thaipii.py --diff origin/${{ github.base_ref }}
```

## สำหรับ coding agent

agent ชอบ query ฐานข้อมูลจริงตอน debug แล้วเอาผลนั้นมาเขียนเป็น fixture ต่อทันที ปลั๊กอินนี้มีสองส่วน

- **hook** (Claude Code): ก่อน agent จะเขียนไฟล์ ถ้าเนื้อหามีเลขบัตร เบอร์โทร laser code หรือเลขบัญชีที่ดูเหมือนของจริง จะหยุดถามเราก่อน พร้อมบอกให้ใช้ข้อมูลทดสอบแทน
- **skill**: กฎการจัดการข้อมูลส่วนบุคคลสำหรับ agent เช่น ห้ามเอาข้อมูลจริงลง repo, ใช้เลขทดสอบ area 9999, ไม่ log ข้อมูลส่วนบุคคล, ไม่ส่งไปให้ error tracker หรือ LLM โดยไม่ตั้งใจ และให้สแกนก่อน commit

Claude Code

```
/plugin marketplace add nuttakulsv/thai-pii-scan
/plugin install thai-pii-scan@thai-pii-scan
```

Codex, Cursor หรือ agent อื่นที่อ่าน SKILL.md ได้ (ได้แค่ skill ไม่มี hook)

```
npx skills add nuttakulsv/thai-pii-scan
```

## ถ้าเจอข้อมูลที่ commit ไปแล้ว

แก้ไฟล์แล้ว commit ใหม่ยังไม่พอ เพราะข้อมูลยังอยู่ในประวัติ git ต้องลบออกจากประวัติด้วย [git filter-repo](https://github.com/newren/git-filter-repo) แล้ว force push และถ้า repo เคยเป็น public หรือมีคน clone ไปแล้ว ให้ถือว่าข้อมูลรั่วไปแล้ว ปรึกษาเจ้าหน้าที่คุ้มครองข้อมูลส่วนบุคคล (DPO) ขององค์กร เพราะ PDPA มีเรื่องที่ต้องทำเมื่อข้อมูลรั่ว ดูได้ที่ [สำนักงานคณะกรรมการคุ้มครองข้อมูลส่วนบุคคล (สคส.)](https://www.pdpc.or.th/)

## ข้อจำกัด

- เครื่องมือนี้ช่วยกันพลาด ไม่ได้รับรองว่าระบบทำตาม PDPA ครบ
- ยังไม่จับชื่อ-นามสกุล ที่อยู่ อีเมล และวันเกิด เพราะแยกของจริงกับของปลอมไม่ได้โดยไม่ทักผิดเยอะ
- ตัวเลข 13 หลักอื่นๆ ที่หลักแรกเป็น 1 ถึง 8 และหลักที่ 2-3 บังเอิญเป็นรหัสจังหวัด จะผ่าน check digit ได้ประมาณ 1 ใน 10 เลยอาจโดนทักบ้าง ถ้าเจอให้ใส่ `thaipii:ignore`
- เลขขึ้นต้นด้วย 0 ไม่ได้ตรวจ เพราะซ้ำกับเลขผู้เสียภาษีของนิติบุคคลซึ่งเป็นข้อมูลสาธารณะ

## รันเทสต์

```
python3 skills/thai-pii-scan/thaipii.py --test
```

## License

MIT
