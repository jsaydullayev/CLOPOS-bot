# Telegram video-bot

Videolar katalogi: admin videoni yopiq video kanalga caption bilan tashlaydi, bot uni kerakli bo‘limga o‘zi qo‘shadi; mijoz bo‘limlarni tanlab videoni bot ichida ko‘radi. Talablar — [TZ.md](TZ.md) (MVP, 2.3-versiya).

- **Mijoz:** bosh menyu → bo‘lim → ichki bo‘lim → video, «Oldingi / Keyingi», «Orqaga», «Bosh menyu». Chatda doim bitta bot xabari turadi.
- **Video kanal:** kanalga tashlangan video botga qo‘shiladi, post captionini tahrirlash videoni tahrirlaydi (6-bo‘lim).
- **Admin** (`/admin`): bo‘lim va ichki bo‘lim yaratish va o‘chirish, video qo‘shish va o‘chirish, salomlashuv va bo‘lim matnlarini yozish.
- **Zaxira:** botdagi har bir videoning posti video kanalda turadi, baza har kuni shu kanalga yuboriladi.

Texnologiyalar: Python 3.12, aiogram 3, PostgreSQL 15, SQLAlchemy 2 + Alembic, Docker Compose; webhook rejimida Caddy (HTTPS).

## 1. Tayyorgarlik

1. **Bot.** [@BotFather](https://t.me/BotFather) → `/newbot` → tokenni saqlang.
2. **Adminlar ID si.** Har bir admin [@userinfobot](https://t.me/userinfobot)ga yozadi va `Id` raqamini beradi.
3. **Video kanal.**
   - Yopiq (private) kanal yarating va botni unga admin qiling («Post messages» huquqi bilan).
   - Kanal sozlamalarida «Restrict saving content» **o‘chiq** tursin — aks holda kanaldan tiklab bo‘lmaydi.
   - Kanalga post yoza oladigan har kim botga video qo‘sha oladi — kanal adminlarini shunga qarab tanlang.
   - Kanal ID si: [web.telegram.org/a](https://web.telegram.org/a)da kanalni oching, manzil satridagi `#` dan keyingi `-100…` raqam.
4. **Server.** 1 vCPU / 1 GB RAM li VPS, Docker va Docker Compose o‘rnatilgan. Domen shart emas: bot polling rejimida ishlaydi va hech qanday port ochmaydi. Webhook kerak bo‘lsa — domen (A-yozuvi server IP siga qaragan) va ochiq 80, 443 portlar.

## 2. Sozlamalar (`.env`)

```bash
cp .env.example .env
```

| O‘zgaruvchi | Majburiy | Izoh |
| --- | --- | --- |
| `BOT_TOKEN` | ha | @BotFather bergan token |
| `ADMIN_IDS` | ha | Adminlar ID si, vergul bilan: `111,222` |
| `BACKUP_CHANNEL_ID` | ha | Video kanal ID si (`-100…`) |
| `WEBHOOK_URL` | webhookda | `https://DOMEN/webhook`. Bo‘sh bo‘lsa bot polling rejimida ishlaydi |
| `WEBHOOK_SECRET` | webhookda | Tasodifiy satr: lotin harflari, raqamlar, `_` va `-` |
| `DOMAIN` | webhookda | Caddy HTTPS sertifikat oladigan domen |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | ha | Baza; parol faqat harf va raqamlardan |
| `DATABASE_URL` | Docker’siz | Docker Compose uni yuqoridagilardan o‘zi yig‘adi |
| `PROTECT_CONTENT` | yo‘q | `true` — mijoz videoni forward qila olmaydi va saqlay olmaydi. Standart: `false` |
| `MAX_DEPTH` | yo‘q | Bo‘limlar necha darajagacha ichma-ich bo‘ladi. Standart: `5` |
| `DB_BACKUP_ENABLED`, `DB_BACKUP_HOUR`, `TIMEZONE` | yo‘q | Kunlik baza zaxirasi: yoqilgan, soat `3` da, `Asia/Tashkent` vaqti bilan |
| `LOG_LEVEL` | yo‘q | `INFO` |

## 3. Serverda ishga tushirish

Kod serverda `/opt/videobot` papkasida turadi.

```bash
cd /opt/videobot
cp .env.example .env   # va to‘ldiring (WEBHOOK_URL bo‘sh — polling)
docker compose up -d --build
docker compose logs -f bot
```

Bot ishga tushganda baza jadvallarini o‘zi yaratadi (`alembic upgrade head`). Tekshirish: botga `/start` yozing, admin hisobidan `/admin`.

**Webhook rejimi** (domen bilan): `.env` da `WEBHOOK_URL`, `WEBHOOK_SECRET`, `DOMAIN` ni to‘ldiring va HTTPS uchun Caddy bilan ishga tushiring: `docker compose --profile webhook up -d --build`. Bot webhookni Telegramga o‘zi ro‘yxatdan o‘tkazadi.

**Yangilash:** yangi kodni `/opt/videobot` ga ko‘chiring (`.env` ga tegmang — undagi baza paroli o‘zgarmasligi kerak), keyin `docker compose up -d --build`.

**Foydali buyruqlar:** `docker compose ps` — holat, `docker compose logs --tail 100 bot` — loglar, `docker compose restart bot` — qayta ishga tushirish.

## 4. Lokal sinov (webhooksiz)

> Lokal sinov uchun **alohida test bot** oching. Polling rejimi ishga tushganda webhook o‘chiriladi, shuning uchun serverdagi bot tokeni bilan sinab bo‘lmaydi.

```bash
# PostgreSQL (Docker orqali)
docker run -d --name videobot-db -p 5432:5432 \
  -e POSTGRES_DB=videobot -e POSTGRES_USER=videobot -e POSTGRES_PASSWORD=KuchliParol123 postgres:15-alpine

python -m venv .venv
.venv\Scripts\activate        # Windows;  Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m bot
```

`.env` da: `WEBHOOK_URL` bo‘sh, `DATABASE_URL=postgresql+asyncpg://videobot:KuchliParol123@localhost:5432/videobot`, `DB_BACKUP_ENABLED=false` (kompyuterda `pg_dump` bo‘lmasligi mumkin).

## 5. Matnlarni tahrirlash

**Admin bot ichida o‘zi o‘zgartiradi:**
- Salomlashuv (rasm bilan ham) va «katalog bo‘sh» matni — `/admin` → «✏️ Salomlashuv va matnlar» → matnni tanlang. Bot uni mijoz ko‘radigandek ko‘rsatadi, tagida «✏️ Matnni o‘zgartirish», «🖼 Rasm qo‘yish», «🗑 Rasmni olib tashlash», «↩️ Standart holatga qaytarish» tugmalari bo‘ladi.
- Bo‘lim matni (mijoz bo‘limga kirganda ko‘radi) — `/admin` → «📂 Bo‘limlar» → bo‘lim → «✏️ Bo‘lim matni».

Matnni oddiy xabar qilib yuboring: qalin, kursiv, havola saqlanadi. Rasmni «🖼 Rasm qo‘yish»dan keyin yuboring: izoh (caption) yozsangiz, u yangi salomlashuv matni bo‘ladi, yozmasangiz, faqat rasm almashadi. Bot almashsa (yangi token), rasmni qayta yuklang.

**Standart matnlar va tugma nomlari** — [locales/uz.toml](locales/uz.toml) (dasturchi uchun). `{nom}` ko‘rinishidagi joylarni o‘chirmang. Serverda o‘zgartirgandan keyin: `docker compose up -d --build`.

## 6. Kanal orqali video qo‘shish

Videoni video kanalga shunday caption bilan tashlang:

```
Бек офис › Финансы        ← 1-qator: bo‘lim yo‘li (› yoki > bilan)
Отчёты                    ← 2-qator: video nomi
Oylik hisobotni ko‘rish   ← 3-qatordan: tavsif (ixtiyoriy)
```

- Bo‘lim topilmasa, bot uni yaratadi va adminlarga xabar beradi. Katta-kichik harf farq qilmaydi.
- Qo‘shilgan postga bot 👍 qo‘yadi. Qo‘shilmagan postga 👎 qo‘yadi va adminlarga sababini yozadi — captionni tahrirlang, bot qayta ko‘rib chiqadi.
- Captionni tahrirlash — videoni tahrirlash: nom, tavsif va bo‘lim yangilanadi.
- Videolarni bittadan tashlang: albomda caption faqat birinchi videoga tushadi.
- Kanaldan post o‘chirilsa, video botda qoladi — uni `/admin` orqali o‘chiring.
- Bot admin bo‘lishidan oldingi postlarni ko‘rmaydi — ularni kanalga qayta forward qiling.

## 7. Zaxira va tiklash

**Videolar** Telegram serverida turadi, bazada faqat `file_id`. Botdagi har bir videoning posti video kanalda turadi: kanalga tashlangani o‘zi, admin panelda qo‘shilgani esa bot yuborgan nusxa.

**Baza** har kuni `DB_BACKUP_HOUR` da `backup-YYYY-MM-DD.dump` fayli bo‘lib video kanalga keladi. Bazani tiklash:

```bash
docker compose cp backup-2026-09-27.dump db:/tmp/backup.dump
docker compose exec db pg_restore -U videobot -d videobot --clean --if-exists /tmp/backup.dump
```

**Bot almashsa** (yangi token): `file_id` faqat eski botga tegishli, shuning uchun videolar kanaldan qayta olinadi.

1. `.env` da `BOT_TOKEN` ni yangilang.
2. Yangi botni video kanalga admin qiling.
3. Birinchi admin hisobidan yangi botga `/start` yozing — nusxalar vaqtincha shu chatga keladi va darhol o‘chiriladi.
4. Tiklash skriptini ishga tushiring:

```bash
docker compose run --rm bot python -m scripts.restore_from_archive
docker compose up -d --build
```

## 8. Testlar

```bash
pip install -r requirements-dev.txt
pytest
```

Testlar Telegramga ulanmaydi: bot so‘rovlari soxta server orqali tekshiriladi. Standart holatda SQLite ishlatiladi. PostgreSQL’da sinash uchun **bo‘sh test bazasi**ni bering (jadvallar o‘chirib qayta yaratiladi):

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/videobot_test pytest
```

## 9. Loyiha tuzilishi

```
bot/
  __main__.py        ishga tushirish: webhook yoki polling
  app.py             dispatcher, middleware va routerlar
  config.py          .env sozlamalari
  db/                modellar, so‘rovlar, ulanish
  handlers/          mijoz, admin (bo‘limlar, videolar, matnlar), video kanal postlari, qolgan xabarlar
  services/          bo‘limlar daraxti va qoidalar, kanal postlari, admin matnlari, kanalga nusxa, baza zaxirasi
  ui/                ekranlar, tugmalar, bitta faol xabar (display.py)
locales/uz.toml      barcha matnlar
migrations/          Alembic migratsiyalari
scripts/             arxivdan tiklash
tests/               testlar
```
