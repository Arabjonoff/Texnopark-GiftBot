# Yoshlar Texnoparki — Loyihaning Hozirgi Holati va O'zgarishlar Jurnali (Changelog)

Ushbu fayl loyihaning yaratilishidan boshlab hozirgacha bajarilgan barcha ishlarni va kelgusida kiritiladigan yangilanishlar hamda o'zgarishlarni qayd etib borish uchun mo'ljallangan.

---

## 📌 Hozirgi Holat (Current Project Status)

**Versiya:** `v1.3.0`  
**Server IP:** `5.104.108.235`  
**Domen:** `gift.yoshlar-texnoparki.uz`  
**Telegram Bot:** `@texnogiftbot`  

---

## 🛠 Bajarilgan Ishlar Ro'yxati

### 1. Backend & Arxitektura (Django + DRF)
- [x] **Monolitik Django arxitekturasi:** Core va App app-lariga ajratilgan to'liq ishlab turgan production loyiha.
- [x] **Database Modellari (`app_main/models.py`):**
  - `Prize`: Sovg'a nomi, kamyoblik darajasi (`COMMON`, `RARE`, `EPIC`, `LEGENDARY`), ehtimollik og'irligi (`probability`), `valid_days` va status.
  - `StudentLead`: O'quvchi ma'lumotlari, `extra_spins` (qo'shimcha spinlar) va `referrer` (taklif qiluvchi o'quvchi).
  - `WinningResult`: Yutuqlar jurnali (`lead`, `prize`, `promo_code`, `status`: ACTIVE/USED/EXPIRED, `expires_at`, `used_at`).
- [x] **Initial Data Seed (`seed_prizes`):** Bazaga 5 xil CS2 skin rarity sovg'alari avtomatik kiritildi.
- [x] **Django Admin & CSV Export (`app_main/admin.py`):** O'quvchilar va yutuqlar ro'yxatini filtrlash, qidirish va CSV/Excel faylga eksport qilish.

### 2. Xavfsizlik & Anti-Cheat Logic (`app_main/services.py`)
- [x] **Telegram `initData` Verification:** HMAC-SHA256 hash orqali soxta so'rovlar taqiqlandi.
- [x] **Server-Side Probability Engine:** Yutuq backend serverda weighted random algoritmi orqali hal qilinadi.
- [x] **Referral System & Dynamic Spin Counter:** Do'stlarni taklif qilish orqali +1 ta qo'shimcha baraban aylantirish imkoniyati.

### 3. REST API Endpoints (`app_main/views.py`)
- [x] `POST /api/validate-init/` — InitData tekshiruvi, mavjud spinlar soni (`available_spins`), yutuqlar va referral link.
- [x] `GET /api/prizes/` — Baraban lentasi uchun sovg'alar va ularning rarity ranglari.
- [x] `POST /api/spin/` — Yutuqni backend serverda oldindan aniqlash hamda 65-stop index qaytarish.
- [x] `POST /api/claim-prize/` — StudentLead va WinningResult ma'lumotlarini saqlash.
- [x] `GET /api/my-prize/` — Aktiv yutuqlar statusi va QR-kod ma'lumotlari.
- [x] `POST /api/admin/verify-code/` — Admin QR/Promokodni skanerlab yutuqni aktivlashtirish (`USED`).

### 4. Frontend UX & Grand Victory Modal (`static/` & `templates/`)
- [x] **Grand Victory Celebration Modal (`#victory-modal`):** Spin to'xtagach darhol forma emas, balki katta CS2 glowing yutuq kartasi va **"🎁 Yutuqni Qabul Qilish"** tugmasi ko'rinadi.
- [x] **Lead Form Modal (`#lead-modal`):** "Yutuqni Qabul Qilish" bosilganda forma ochiladi.
- [x] **Asosiy Sahifaga Qaytish & Referral Hub:** Forma to'ldirilgach foydalanuvchi baraban sahifasiga qaytadi. Baraban ostida:
  - **Aktiv Yutuqlar & QR-kodlar kartasi** ("📱 QR-kodni Ko'rish" modal oynasi bilan).
  - **Do'stlarni Taklif Qilish Bo'limi**: Taklif havolasi, 1-click **"📋 Nusxalash"** va **"🚀 Telegram'da Ulashish"** knopkalari.
- [x] **Admin QR Skaner (`templates/admin_panel/scan.html`):** Mobil brauzer kamerasi orqali `html5-qrcode` bilan QR-kodni skanerlash va yutuqni aktivlashtirish.

### 5. Telegram Bot Integratsiyasi (`bot/`)
- [x] `/start ref_123456789` referral argumentini avtomatik tanib, taklif qiluvchiga **+1 extra spin** berish logic.
- [x] Inline WebApp / HTTPS havolali tugma.

---

## 📝 Kelgusidagi O'zgarishlar va Yangilanishlar Jurnali (Change Log)

### 2026-09-23 - Versiya: v1.3.0
- **Turi:** Majburiy obuna, bot xabarlari, aksiya muddati, sovg'a qoldig'i va xavfsizlik
- **A. Xavfsizlik va ishonchlilik:**
  1. `initData` muddati tekshiriladi (`auth_date`, standart 24 soat — `INIT_DATA_MAX_AGE_SECONDS`).
  2. Sovg'a **qoldig'i** (`Prize.stock`): har yutuqda 1 ta kamayadi, 0 bo'lsa barabandan chiqadi.
     Bo'sh — cheksiz. Oxirgi donaga bir vaqtda ikki kishi tushsa, faqat bittasiga beriladi.
  3. **Referal endi do'st yutug'ini rasmiylashtirgach hisoblanadi** (soxta akkauntlarga qarshi).
     Eski referallar migratsiyada tasdiqlangan deb belgilandi — balanslar o'zgarmadi.
  4. Sovg'ani **qaysi xodim bergani** saqlanadi (`WinningResult.used_by`).
  5. Promokod `TX-XXXXXX` (6 belgi, 887 mln variant, o'xshash belgilarsiz), tasodif `secrets` orqali.
  6. Statistikada "O'quvchilar" = forma to'ldirganlar; botdagi jami alohida ko'rsatiladi.
- **B. Bot xabarlari:**
  1. `BotMessage` navbati + bot jarayonidagi fon sikli (`bot/worker.py`) — sekundiga ~20 xabar,
     flood-limit, bloklaganlar avtomatik belgilanadi. Qo'shimcha kutubxona kerak emas.
  2. Dashboard → **Xabarlar**: auditoriya tanlab ommaviy xabar, progress, to'xtatish.
  3. Muddat tugashidan 24 soat oldin avtomatik **eslatma**; EXPIRED holati har 10 daqiqada yangilanadi.
  4. Referal tasdiqlanganda taklif qiluvchiga progress xabari. `/start` bosgan har kim bazaga yoziladi.
- **C. MiniApp:**
  1. **Majburiy obuna**: kanallarga a'zo bo'lmaguncha yangi spin berilmaydi (server tekshiradi,
     `getChatMember`). MiniApp'da kanallar kartasi va «Obunani tekshirish»; bot `/start` da ham tugmalar.
     Bot kanalda admin bo'lmasa, o'sha kanal tekshirilmaydi (aksiya to'xtab qolmaydi).
  2. **Aksiya muddati**: boshlanish/tugash vaqti, yopiq paytda banner; rasmiylashtirish davom etadi.
  3. **Kunlik bonus** (+1 aylantirish, kuniga bir marta) — dashboarddan yoqiladi.
  4. G'oliblar bo'limida **Top taklifchilar** reytingi.
- **D. Dashboard:** **Sozlamalar** sahifasi (kanallar + «Botni tekshirish», aksiya, bonus,
  necha do'st = +1 spin), **konversiya voronkasi**, **xodimlar faoliyati**, qoldiq ustuni.
- **Yangi API:** `POST /api/check-subscription/`, `POST /api/daily-bonus/`, `GET /api/top-referrers/`.
- **Migratsiyalar:** `0009`–`0011`. **Deploydan keyin `texnopark-bot` servisini qayta ishga tushirish shart**
  (xabarlar navbatini u yuboradi).

---

### 2026-09-15 - Versiya: v1.2.1
- **Turi:** Parolni O'zgartirish Sahifasi va Yetim Rasm Fayllarini Tozalash
- **Tavsif:**
  1. **`/dashboard/account/password/`** — dashboard ichida parol almashtirish sahifasi.
     Django'ning `PasswordChangeForm`i ishlatiladi: eski parol so'raladi, yangisi
     `AUTH_PASSWORD_VALIDATORS` bo'yicha tekshiriladi, `update_session_auth_hash` tufayli
     parol o'zgargach foydalanuvchi tizimdan chiqib ketmaydi. Maslahat matni o'zbekchaga o'girildi.
  2. **`app_main/signals.py`** — `post_delete` va `pre_save` signallari orqali yuklangan rasm
     fayllari avtomatik tozalanadi: yozuv o'chirilganda yoki rasm almashtirilganda eski fayl
     `media/` dan o'chiriladi. Ilgari fayllar diskda yetim qolib ketardi.
- **Tuzatish:** `app.js` baraban bo'limining sarlavhasini endi `index.html` dan o'qiydi —
  ilgari u qattiq yozilgan matn bilan almashtirib yuborardi.
- **Fayllar:** `signals.py`, `apps.py`, `dashboard_views.py`, `dashboard_urls.py`,
  `templates/dashboard/account_password.html`, `base.html`, `static/js/app.js`.

---

### 2026-09-15 - Versiya: v1.2.0
- **Turi:** Admin Dashboard, Sovg'a Kategoriyalari, 3 Bo'limli MiniApp UI va Xavfsizlik Tuzatishlari
- **Tavsif:**
  1. **Alohida Admin Dashboard (`/dashboard/`)** — Django admin'dan mustaqil, staff login bilan himoyalangan:
     Statistika (14 kunlik grafik, rarity taqsimoti, maktablar reytingi, sovg'a samaradorligi),
     Sovg'alar CRUD, Kategoriyalar CRUD, O'quvchilar (filtr + CSV), Yutuqlar jurnali, QR Skaner.
  2. **Sovg'a rasmi** — `Prize.image` (ImageField) qo'shildi, dashboarddan yuklanadi (`/media/prizes/`).
     Tekshiruvlar: PNG/JPG/WEBP/GIF, 5 MB gacha. Rasm yo'q bo'lsa rarity emoji ishlatiladi.
  3. **Sovg'a kategoriyalari** — yangi `PrizeCategory` modeli (nom, tavsif, rasm/ikonka, tartib, aktivlik).
     Kategoriya o'chirilsa sovg'alar o'chmaydi (`SET_NULL`), noaktiv kategoriya sovg'alari barabandan chiqmaydi.
  4. **MiniApp pastki appbar** — 3 bo'lim: Baraban / Yutuqlarim (QR + holat) / G'oliblar ro'yxati.
     Yangi ochiq endpoint `GET /api/winners/` — maxfiylik uchun familiya bosh harfga qisqartiriladi,
     telefon va Telegram ID umuman qaytarilmaydi.
- **Tuzatilgan nosozliklar:**
  - Baraban va Victory modalda **rasmlar hech qachon ko'rinmagan** — `roulette.js`/`app.js` faqat
    `http` bilan boshlanadigan yo'lni qabul qilardi, seed esa mavjud bo'lmagan `/static/images/...` yozardi.
  - **QR skaner sovg'ani darhol `USED` qilardi** — endi ikki bosqichli: avval ma'lumot, keyin tasdiqlash.
  - **`/admin-scan/` va `POST /api/admin/verify-code/` himoyasiz edi** — istalgan odam promokodlarni
    bekor qila olardi. Endi ikkalasi staff huquqini talab qiladi.
  - **`DEBUG = True` kodga qattiq yozilgan edi** — endi `.env` dan o'qiladi, productionda `False`.
- **Fayllar:** `models.py`, `forms.py`, `views.py`, `urls.py`, `serializers.py`, `services.py`, `admin.py`,
  `dashboard_views.py`, `dashboard_urls.py`, `dashboard_services.py`, `settings.py`, `core/urls.py`,
  `web_views.py`, `web_urls.py`, `templates/dashboard/*`, `templates/miniapp/index.html`,
  `static/css/dashboard.css`, `static/css/style.css`, `static/js/app.js`, `static/js/roulette.js`,
  migratsiyalar `0003`–`0005`.

---

### 2026-09-14 - Versiya: v1.1.0
- **Turi:** UX Redesign & Referral System (+1 Spin per Friend)
- **Tavsif:**
  1. Spin to'xtagach ochiluvchi **Grand Victory Celebration Modal** yaratildi.
  2. "🎁 Yutuqni Qabul Qilish" bosilgach forma to'ldirilishi va foydalanuvchi Asosiy Baraban sahifasiga qaytishi yo'lga qo'yildi.
  3. Baraban ostiga **Aktiv Yutuqlar & QR Viewer Modal** hamda **Do'stlarni Taklif Qilish Bo'limi (Referral Hub)** qo'shildi.
  4. Telegram botda `/start ref_123456` orqali do'stlarni taklif qilganda **+1 ta qo'shimcha spin** berish tizimi integratsiya qilindi.
- **Fayllar:** `models.py`, `services.py`, `handlers.py`, `views.py`, `style.css`, `index.html`, `app.js`, `tests.py`.

---

### 2026-09-14 - Versiya: v1.0.0
- **Turi:** Initial Release & Production Deployment
- **Tavsif:** Loyiha to'liq yaratildi va serverga (5.104.108.235) joylashtirildi.
- **Fayllar:** Barcha dastlabki loyiha fayllari.
