# Epson-config

โปรแกรมหน้าต่างภาษาไทย (ธีมสว่าง/มืดตาม Windows) สำหรับเช็กสถานะและ **รีเซ็ตตัวนับซับหมึก (waste ink pad counter)** ของเครื่องพิมพ์ Epson ผ่านสาย USB กดใช้ได้เลย ไม่ต้องพิมพ์คำสั่ง

ทดสอบกับเครื่องจริงแล้ว: **Epson L4260** (เฟิร์มแวร์ XJ05Q2) รุ่นอื่นที่อยู่ในฐานข้อมูลของ ReInkPy น่าจะใช้ได้ แต่ยังไม่ได้ทดสอบ

## ดาวน์โหลด

**[⬇ EpsonInkPadReset.exe (เวอร์ชันล่าสุด)](https://github.com/Mark-Notify/Epson-config/releases/latest/download/EpsonInkPadReset.exe)** · Windows 10/11 64-bit · ไม่ต้องลง Python

ดูทุกเวอร์ชันและ SHA-256 ได้ที่หน้า [Releases](https://github.com/Mark-Notify/Epson-config/releases)

โปรแกรมเช็กอัปเดตเองตอนเปิด ถ้ามีเวอร์ชันใหม่จะขึ้นแถบสีน้ำเงินด้านบน กด **อัปเดตเลย** แล้วโปรแกรมจะโหลด ตรวจ SHA-256 ปิดตัวเอง และเปิดเวอร์ชันใหม่ให้ (กด **ตรวจหาอัปเดต** ที่มุมล่างซ้ายเพื่อเช็กเองก็ได้)

ไฟล์ไม่ได้เซ็นชื่อดิจิทัล ตอนเปิดครั้งแรก Windows อาจขึ้น "Windows protected your PC" ให้กด **More info** แล้ว **Run anyway**

## วิธีใช้ (ผู้ใช้ทั่วไป)

1. เสียบสาย USB ระหว่างคอมกับเครื่องพิมพ์ แล้วเปิดเครื่องพิมพ์
2. ดับเบิลคลิก `EpsonInkPadReset.exe`
3. กด **ตรวจสอบเครื่องพิมพ์** โปรแกรมจะบอกรุ่น สถานะ ซับหมึกเต็มหรือยัง และระดับหมึกแต่ละสี
4. ถ้าซับหมึกเต็ม ปุ่มจะเปลี่ยนเป็นสีแดง **รีเซ็ตซับหมึก** กดแล้วติ๊ก "ฉันเข้าใจ" แล้วกด **รีเซ็ตเลย**
5. ปิดเครื่องพิมพ์ด้วยปุ่ม Power รอไฟดับ แล้วเปิดใหม่ จากนั้นกด **ตรวจสอบเครื่องพิมพ์** อีกครั้งเพื่อยืนยัน

ก่อนรีเซ็ต โปรแกรมจะสำรองข้อมูล EEPROM ของเครื่องพิมพ์ไว้ที่ `Documents\EpsonResetBackups` อัตโนมัติ ถ้าสำรองไม่สำเร็จจะไม่รีเซ็ต

## ข้อควรรู้

- **แผ่นซับหมึกจริงยังเต็มอยู่** การรีเซ็ตแค่ทำให้ตัวนับกลับเป็นศูนย์ ควรล้างหรือเปลี่ยนแผ่นซับ หรือต่อถังหมึกทิ้งภายนอก ไม่งั้นหมึกจะล้นออกใต้เครื่อง
- ห้ามปิดเครื่องพิมพ์หรือถอดสายระหว่างรีเซ็ต
- การแก้ EEPROM อาจทำให้เสียสิทธิ์ประกันจาก Epson ถ้าเครื่องยังอยู่ในประกัน ส่งศูนย์ดีกว่า
- ใช้ได้เฉพาะสาย USB รุ่นใหม่หลายรุ่น (รวม L4260) ปิดการเข้าถึง EEPROM ผ่าน Wi-Fi
- ปิดโปรแกรมอื่นที่คุยกับเครื่องพิมพ์ (เช่น Epson Status Monitor, WIC Reset) ก่อนใช้

## Build เป็น .exe (สำหรับนักพัฒนา)

ต้องมี Python 3.10+ (คำสั่ง `py`), git และ curl (มากับ Windows 10/11)

```bat
build.bat
```

สคริปต์จะ:

1. โหลด [epson_print_conf](https://github.com/Ircama/epson_print_conf) เวอร์ชันที่ล็อกไว้ลง `vendor\`
2. สร้าง venv และติดตั้ง dependency กับ PyInstaller
3. โหลด `epson.toml` ของ [ReInkPy](https://codeberg.org/atufi/reinkpy) แล้วแปลงเป็น `printers.pickle`
4. Build ได้ไฟล์ `dist\EpsonInkPadReset.exe` (ไฟล์เดียว ไม่ต้องลง Python บนเครื่องที่ใช้)

รันจากซอร์สโดยไม่ build (หลังรัน `build.bat` ครั้งแรกแล้ว):

```bat
venv\Scripts\python epson_reset_gui.py
```

ทดสอบโดยไม่มีเครื่องพิมพ์ (เครื่องพิมพ์จำลอง L4260):

```bat
set EPSON_RESET_MOCK=1
venv\Scripts\python epson_reset_gui.py
```

## ออกเวอร์ชันใหม่

GitHub Actions ([build.yml](.github/workflows/build.yml)) build .exe บน Windows ให้ทุกครั้งที่ push ขึ้น `main` (โหลดได้จากแท็บ Actions) ถ้าจะปล่อยให้ผู้ใช้อัปเดต:

1. แก้ `APP_VERSION` ใน `epson_reset_core.py` เช่น `"2.2.0"`
2. commit แล้วติด tag ให้ตรงกัน: `git tag v2.2.0` แล้ว `git push origin main v2.2.0`
3. Actions จะ build และสร้าง Release พร้อม `EpsonInkPadReset.exe` กับ `.sha256` ผู้ใช้ทุกคนจะเห็นแถบอัปเดตตอนเปิดโปรแกรมครั้งถัดไป

ถ้าเลข tag ไม่ตรงกับ `APP_VERSION` Actions จะหยุดและไม่สร้าง Release

## เครดิตและสัญญาอนุญาต

- UI สร้างด้วย [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (MIT)
- [epson_print_conf](https://github.com/Ircama/epson_print_conf) โดย Ircama, สัญญาอนุญาต EUPL-1.2 ใช้คุยกับเครื่องพิมพ์ผ่าน USB และเขียน EEPROM
- ข้อมูลรุ่นเครื่องพิมพ์จาก `epson.toml` ของ [ReInkPy](https://codeberg.org/atufi/reinkpy)

repo นี้ไม่ได้รวมซอร์สของสองโปรเจกต์ข้างต้นไว้ `build.bat` โหลดมาตอน build แต่ไฟล์ .exe ในหน้า Releases มีโค้ดของ epson_print_conf (EUPL-1.2) อยู่ข้างใน build จาก commit `2dc3bebacf314f22bd6484acdb2a7434c7cc00ad` ซอร์สฉบับเต็มดูได้ที่ https://github.com/Ircama/epson_print_conf/tree/2dc3bebacf314f22bd6484acdb2a7434c7cc00ad
