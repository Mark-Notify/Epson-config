# CLAUDE.md

## ค่าเริ่มต้นของหน้าตาโปรแกรม (UI default)

ถ้าผู้ใช้ขอทำโปรแกรมหรือหน้าจอใหม่ และ**ไม่ได้ระบุสไตล์** ให้ใช้เทมเพลต
สกิล **glass-ui** ([`.claude/skills/glass-ui/`](.claude/skills/glass-ui/SKILL.md)) เป็นค่าเริ่มต้นเสมอ:

- สไตล์ **Glassmorphism (Liquid Glass) Sidebar Dashboard**: การ์ดกระจกฝ้า พื้นหลังก้อนสีพาสเทลเบลอ
  ธีมสว่าง/มืดตามระบบ ไอคอนเส้น 24px ภาษาไทย
- เริ่มจากก๊อป `.claude/skills/glass-ui/template/` ทั้งโฟลเดอร์ แล้วแก้ชื่อ โลโก้ เมนู และสี `--accent` / `--blob-*`
- ใช้ class ที่มีอยู่ใน `style.css` ก่อนเขียน CSS ใหม่ (ดูตารางใน `.claude/skills/glass-ui/REFERENCE.md`)
- โปรแกรม Windows: ใช้ pywebview + หน้า HTML นี้ แบบเดียวกับ `app_web.py`

ถ้าผู้ใช้ระบุสไตล์อื่น ให้ทำตามที่ผู้ใช้สั่ง

## โปรเจกต์นี้

- `ui/` หน้าตาของ Epson Ink Pad Reset (HTML/CSS/JS), `app_web.py` สะพานไป `epson_reset_core.py`
- ทดสอบโดยไม่มีเครื่องพิมพ์: `EPSON_RESET_MOCK=1`
- ออกเวอร์ชัน: แก้ `APP_VERSION` ใน `epson_reset_core.py` ให้ตรงกับ tag
