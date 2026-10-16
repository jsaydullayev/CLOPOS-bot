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
| `ADMIN_IDS` | ha | Asosiy adminlar ID si, vergul bilan: `111,222`. Boshqa adminlarni ular botning o‘zida qo‘shadi: `/admin` → «👥 Adminlar». Asosiy adminni paneldan olib tashlab bo‘lmaydi |
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
- Salomlashuv (rasm, video yoki GIF bilan ham), «katalog bo‘sh» matni va «📞 Bog‘lanish va yordam» — `/admin` → «✏️ Salomlashuv va matnlar» → matnni tanlang. Bot uni mijoz ko‘radigandek ko‘rsatadi, tagida «✏️ Matnni o‘zgartirish», «🖼 Rasm yoki video qo‘yish», «🗑 Rasm yoki videoni olib tashlash», «↩️ Standart holatga qaytarish» tugmalari bo‘ladi. «↩️ Standart holatga qaytarish» faqat matnni tiklaydi, rasm yoki video joyida qoladi.
- Bog‘lanish va yordam — bosh menyu pastidagi yashil tugma. Ichida telefon va @username (standart: +998 55 513 11 77, @CloposYordam; admin o‘zgartira oladi) va «✍️ Muammoni yozib qoldirish»: mijoz muammosini matn, rasm, video yoki ovozli xabar bilan yozadi, bot uni barcha adminlarga mijozning ismi, @username’i va profil havolasi bilan yuboradi. Bir mijoz daqiqasiga bitta murojaat yubora oladi. Murojaat faqat botga /start bosgan adminlarga yetadi.
- Bo‘lim emojisi — `/admin` → «📂 Bo‘limlar» → bo‘lim → «😀 Emoji». Tanlanmasa, 📂 (ichida bo‘limlar) yoki 🎬 (ichida videolar).
- Salomlashuv videosi GIF bo‘lib (ovozsiz, o‘zi takrorlanib) tursin desangiz, uni Telegram’da ovozini o‘chirib (🔇) yuboring — Telegram ovozsiz videoni GIF qiladi.
- Bo‘lim matni (mijoz bo‘limga kirganda ko‘radi) — `/admin` → «📂 Bo‘limlar» → bo‘lim → «✏️ Bo‘lim matni».

Matnni oddiy xabar qilib yuboring: qalin, kursiv, havola saqlanadi. Rasm yoki videoni (yoki GIF) «🖼 Rasm yoki video qo‘yish»dan keyin yuboring: izoh (caption) yozsangiz, u yangi salomlashuv matni bo‘ladi, yozmasangiz, faqat rasm yoki video almashadi. Salomlashuv rasmi botning «kartochkasi» bo‘ladi: bo‘limlar ro‘yxati ham uning ostida chiqadi. Video yoki GIF esa faqat bosh menyuda o‘ynaydi — bo‘limlarda uning o‘rnida standart ko‘k muqova turadi. Bot almashsa (yangi token), rasm yoki videoni qayta yuklang.

**Standart matnlar va tugma nomlari** — [locales/uz.toml](locales/uz.toml) (dasturchi uchun). `{nom}` ko‘rinishidagi joylarni o‘chirmang. Serverda o‘zgartirgandan keyin: `docker compose up -d --build`.

## 6. Kanal orqali video qo‘shish

Videoni video kanalga shunday caption bilan tashlang:

```
Бек офис › Финансы        ← 1-qator: bo‘lim yo‘li (› yoki > bilan)
Отчёты                    ← 2-qator: video nomi
Oylik hisobotni ko‘rish   ← 3-qatordan: tavsif (ixtiyoriy)
```

Adminlar uchun to‘liq shablon botning o‘zida: `/admin` → «📢 Kanal shabloni».

- **Bo‘lim kodi** — eng ishonchli usul: 1-qatorga `#12` yozing (kodlar: «📢 Kanal shabloni» → «📋 Bo‘lim kodlari»). `#12 › +Ombor` — 12-bo‘lim ichida yangi bo‘lim.
- **Yangi bo‘lim** faqat nomi oldida `+` bo‘lsa ochiladi: `Videodarsliklar › +Ombor`. `+` dan keyingi bo‘limlar ham, topilmasa, yangi ochiladi.
- **Nom bilan** yozilganda bot kechiradi: katta-kichik harf, bo‘sh joy va tinish belgilari, `o‘ o' oʻ` farqi, kirill/lotin o‘xshash harflar (а/a, о/o, с/c…) va 1–2 harf xatosi («Finas» → «Finans»; 5 harfdan qisqa nomlarda xato kechirilmaydi, raqamlar har doim aniq bo‘lishi kerak). Xato tuzatilsa, bot adminlarga nimani nimaga tuzatganini yozadi.
- `+` siz va topilmagan bo‘lim ochilmaydi: postga 👎, adminlarga o‘xshash nomlar yuboriladi. Ikki bo‘limga bir xil yaqin xato ham taxmin qilinmaydi.
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
  handlers/          mijoz, bog‘lanish va murojaatlar, admin (bo‘limlar, videolar, matnlar, adminlar),
                     video kanal postlari, qolgan xabarlar
  services/          bo‘limlar daraxti va qoidalar, kanal postlari, admin matnlari, adminlar ro‘yxati,
                     murojaatlar, kanalga nusxa, baza zaxirasi
  ui/                ekranlar, tugmalar, bitta faol xabar (display.py)
assets/cover.png     bo‘lim ekranlari uchun standart muqova
locales/uz.toml      barcha matnlar
migrations/          Alembic migratsiyalari
scripts/             arxivdan tiklash
tests/               testlar
```
