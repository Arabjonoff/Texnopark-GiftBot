# Yoshlar Texnoparki — Production Deployment Guide

Ushbu hujjat **Texnopark Telegram Mini App (CS2 Skin Roulette)** loyihasini Ubuntu Linux serveriga va `gift.yoshlar-texnoparki.uz` domeniga production rejimida joylashtirish bo'yicha to'liq ko'rsatmalarni o'z ichiga oladi.

---

## 📋 Server Ma'lumotlari & Arxitektura

- **Server IP:** `5.104.108.235`
- **Operatsion Sistema:** Ubuntu Linux 22.04 LTS
- **Domen Manzili:** `https://gift.yoshlar-texnoparki.uz`
- **Loyiha Joylashuvi:** `/var/www/texnopark-miniapp-bot`
- **WSGI Server:** Gunicorn (Systemd service: `texnopark-web.service`)
- **Telegram Bot Worker:** Systemd service (`texnopark-bot.service`)
- **Web Server:** Nginx (Reverse Proxy & Static Files)
- **SSL Sertifikati:** Let's Encrypt / Certbot

---

## 🛠 Step-by-Step Deployment Qo'llanmasi

### 1. Tizim paketlarini yangilash va zaruriy instrumentlarni o'rnatish

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git -y
```

---

### 2. Loyiha papkasini yaratish va virtual muhitni sozlash

```bash
sudo mkdir -p /var/www/texnopark-miniapp-bot
sudo chown -R root:root /var/www/texnopark-miniapp-bot
cd /var/www/texnopark-miniapp-bot

# Virtualenv yaratish
python3 -m venv venv
source venv/bin/activate
```

---

### 3. Loyiha fayllarini yuklash va kutubxonalarni o'rnatish

Loyiha kodlari nusxalanib `/var/www/texnopark-miniapp-bot` papkasiga joylanadi:

```bash
pip install --upgrade pip setuptools wheel
pip install django djangorestframework python-telegram-bot python-dotenv gunicorn pillow requests sqlparse asgiref
```

---

### 4. Production `.env` Faylini Sozlash

`/var/www/texnopark-miniapp-bot/.env` fayli yaratiladi:

```env
DJANGO_SECRET_KEY=<uzun tasodifiy kalit>
DEBUG=False
ALLOWED_HOSTS=gift.yoshlar-texnoparki.uz,5.104.108.235,127.0.0.1,localhost
TELEGRAM_BOT_TOKEN=<BotFather bergan token>
TELEGRAM_WEBAPP_URL=https://gift.yoshlar-texnoparki.uz
```

---

### 5. Migratsiyalar va Static Assetlarni Yig'ish

```bash
cd /var/www/texnopark-miniapp-bot
source venv/bin/activate

# Database migratsiyalarini o'tkazish
python manage.py makemigrations app_main
python manage.py migrate

# Sovg'alarni bazaga seed qilish
python manage.py seed_prizes

# Static fayllarni to'plash
python manage.py collectstatic --noinput
```

---

### 6. Gunicorn Web Service Sozlanishi (`/etc/systemd/system/texnopark-web.service`)

Fayl yaratiladi: `/etc/systemd/system/texnopark-web.service`

```ini
[Unit]
Description=Texnopark MiniApp Gunicorn Web Daemon
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/var/www/texnopark-miniapp-bot
ExecStart=/var/www/texnopark-miniapp-bot/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 core.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Servisni yoqish va ishga tushirish:
```bash
sudo systemctl daemon-reload
sudo systemctl start texnopark-web
sudo systemctl enable texnopark-web
```

---

### 7. Telegram Bot Worker Service Sozlanishi (`/etc/systemd/system/texnopark-bot.service`)

Fayl yaratiladi: `/etc/systemd/system/texnopark-bot.service`

```ini
[Unit]
Description=Texnopark Telegram Bot Worker Daemon
After=network.target texnopark-web.service

[Service]
User=root
Group=root
WorkingDirectory=/var/www/texnopark-miniapp-bot
ExecStart=/var/www/texnopark-miniapp-bot/venv/bin/python manage.py run_bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Servisni yoqish va ishga tushirish:
```bash
sudo systemctl daemon-reload
sudo systemctl start texnopark-bot
sudo systemctl enable texnopark-bot
```

---

### 8. Nginx Web Server Sozlanishi (`/etc/nginx/sites-available/gift.yoshlar-texnoparki.uz`)

Fayl yaratiladi: `/etc/nginx/sites-available/gift.yoshlar-texnoparki.uz`

```nginx
server {
    listen 80;
    server_name gift.yoshlar-texnoparki.uz 5.104.108.235;

    client_max_body_size 20M;

    location /static/ {
        alias /var/www/texnopark-miniapp-bot/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Nginx konfiguratsiyasini faollashtirish va tekshirish:
```bash
sudo ln -sf /etc/nginx/sites-available/gift.yoshlar-texnoparki.uz /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### 9. SSL Certbot HTTPS Sertifikati

Domen A record IP-ga yo'naltirilgach, HTTPS o'rnatish:

```bash
sudo certbot --nginx -d gift.yoshlar-texnoparki.uz
```

---

## 🔍 Servislar Holatini Tekshirish (Status & Logs)

- **Web Server statusi:** `systemctl status texnopark-web`
- **Bot Worker statusi:** `systemctl status texnopark-bot`
- **Nginx statusi:** `systemctl status nginx`
- **Bot loglarini ko'rish:** `journalctl -u texnopark-bot -f`
- **Web loglarini ko'rish:** `journalctl -u texnopark-web -f`
