import logging

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import CommandHandler, ContextTypes

from app_main.services import check_user_spin_status, process_referral
from bot.utils import get_webapp_url

logger = logging.getLogger(__name__)


# Django ORM sinxron ishlaydi — async handler ichidan to'g'ridan-to'g'ri
# chaqirilsa SynchronousOnlyOperation xatosi chiqadi. Shu sabab barcha
# baza bilan ishlovchi funksiyalar sync_to_async orqali o'raladi.
process_referral_async = sync_to_async(process_referral, thread_sensitive=True)


@sync_to_async(thread_sensitive=True)
def get_user_winnings(telegram_id: int):
    """
    Foydalanuvchining yutuqlari va qolgan spinlari.

    Manzil sovg'aning o'zidan olinadi (admin panelda kiritiladi), shuning
    uchun natija shablonga tayyor dict ko'rinishida qaytariladi.
    """
    available_spins, _lead, winnings = check_user_spin_status(telegram_id)

    rows = []
    for w in winnings:
        rows.append({
            'promo_code': w.promo_code,
            'prize_title': w.prize.title,
            'status': w.status,
            'status_label': w.get_status_display(),
            'expires_at': timezone.localtime(w.expires_at).strftime('%d.%m.%Y %H:%M'),
            'address': w.prize.pickup_address,
            'map_link': w.prize.map_link,
        })

    return available_spins, rows


def _webapp_keyboard(extra_rows=None):
    """
    Asosiy tugmalar. Telegram WebApp tugmasi faqat https:// manzil bilan
    ishlaydi; local dev (http://) holatida oddiy havola qo'yiladi.
    """
    webapp_url = get_webapp_url().strip()

    if webapp_url.startswith("https://"):
        rows = [[InlineKeyboardButton("🎰 Ochish", web_app=WebAppInfo(url=webapp_url))]]
    else:
        rows = [[InlineKeyboardButton("🌐 Brauzerda Ochish (HTTP)", url=webapp_url)]]

    if extra_rows:
        rows.extend(extra_rows)
    return InlineKeyboardMarkup(rows), webapp_url


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — referalni qayd qiladi va MiniApp tugmasini yuboradi.
    Havola ko'rinishi: /start ref_123456789
    """
    new_user = update.effective_user
    new_user_id = new_user.id if new_user else 0

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_tg_id = int(arg.split("ref_")[1])
                success, _referrer_lead = await process_referral_async(referrer_tg_id, new_user_id)
                if success:
                    logger.info(
                        "Referral processed: %s gained +1 extra spin from %s",
                        referrer_tg_id, new_user_id
                    )
            except Exception as e:
                logger.error("Failed to process referral: %s", e)

    reply_markup, webapp_url = _webapp_keyboard()
    user_first_name = new_user.first_name if new_user else "Foydalanuvchi"

    if webapp_url.startswith("https://"):
        text = (
            f"👋 **Salom, {user_first_name}!**\n\n"
            f"Yoshlar Texnoparki Gift Box barabaniga xush kelibsiz! 🚀\n\n"
            f"Tugmani bosing va barabanni aylantiring — yutuq chiqsa, faqat "
            f"**ism va telefon raqamingizni** kiritasiz, xolos.\n\n"
            f"🎁 Yutuqlaringizni va ularni qayerdan olishni ko'rish uchun "
            f"/yutuqlarim buyrug'ini yuboring."
        )
    else:
        text = (
            f"👋 **Salom, {user_first_name}!**\n\n"
            f"Yoshlar Texnoparki Gift Box loyihasiga xush kelibsiz! 🚀\n\n"
            f"⚠️ **Eslatma:** Telegram WebApp knopkasi uchun HTTPS manzili "
            f"(masalan `https://...`) talab qilinadi.\n"
            f"Hozirgi manzilingiz: `{webapp_url}`\n\n"
            f"Local dev muhitida ngrok ishlatib, `.env` fayliga "
            f"`TELEGRAM_WEBAPP_URL=https://...` qo'shing."
        )

    await update.message.reply_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def my_prizes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /yutuqlarim — foydalanuvchining yutuqlari: promokod, muddati va
    sovg'ani olish manzili (admin panelda kiritilgan Google Maps nuqtasi).
    """
    user = update.effective_user
    if not user:
        return

    available_spins, rows = await get_user_winnings(user.id)

    if not rows:
        reply_markup, _ = _webapp_keyboard()
        await update.message.reply_text(
            "📭 Hali yutug'ingiz yo'q.\n\n"
            f"Sizda **{available_spins}** ta aylantirish imkoniyati bor — "
            f"barabanni sinab ko'ring!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    status_icons = {'ACTIVE': '🟢', 'USED': '✅', 'EXPIRED': '⌛'}
    lines = ["🎁 **Sizning yutuqlaringiz:**", ""]
    map_buttons = []

    for row in rows:
        icon = status_icons.get(row['status'], '•')
        lines.append(f"{icon} **{row['prize_title']}**")
        lines.append(f"    Promokod: `{row['promo_code']}`")

        if row['status'] == 'ACTIVE':
            lines.append(f"    Amal qiladi: {row['expires_at']}")
        else:
            lines.append(f"    Holati: {row['status_label']}")

        if row['address']:
            lines.append(f"    📍 {row['address']}")

        if row['status'] == 'ACTIVE' and row['map_link']:
            map_buttons.append([InlineKeyboardButton(
                f"🗺️ {row['prize_title']} — manzil",
                url=row['map_link']
            )])

        lines.append("")

    lines.append(
        "QR-kodni ko'rsatish uchun MiniApp'dagi «Yutuqlarim» bo'limini oching."
    )

    reply_markup, _ = _webapp_keyboard(extra_rows=map_buttons)
    await update.message.reply_text(
        text="\n".join(lines),
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/yordam — qisqa qo'llanma."""
    reply_markup, _ = _webapp_keyboard()
    await update.message.reply_text(
        "ℹ️ **Qanday ishlaydi?**\n\n"
        "1️⃣ Tugmani bosib MiniApp'ni oching va barabanni aylantiring.\n"
        "2️⃣ Yutuq chiqsa, ism va telefon raqamingizni kiriting.\n"
        "3️⃣ «Yutuqlarim» bo'limidan QR-kodni oching — uning ostida "
        "sovg'ani olish manzili ko'rsatiladi.\n"
        "4️⃣ Texnopark xodimiga QR-kodni ko'rsating.\n\n"
        "Har bir taklif qilgan do'stingiz uchun **+1 aylantirish** olasiz.\n\n"
        "Buyruqlar:\n"
        "/start — barabanni ochish\n"
        "/yutuqlarim — yutuqlar va manzillar\n"
        "/yordam — shu qo'llanma",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def post_init(application):
    """Telegram menyusidagi buyruqlar ro'yxati."""
    await application.bot.set_my_commands([
        BotCommand("start", "Barabanni ochish"),
        BotCommand("yutuqlarim", "Yutuqlarim va manzillar"),
        BotCommand("yordam", "Qanday ishlaydi?"),
    ])


def setup_handlers(application):
    """
    Bot buyruqlarini ro'yxatdan o'tkazadi.
    """
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler(["yutuqlarim", "myprizes"], my_prizes_command))
    application.add_handler(CommandHandler(["yordam", "help"], help_command))
