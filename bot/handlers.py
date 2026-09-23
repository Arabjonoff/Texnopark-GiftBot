import asyncio
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
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes
from telegram.helpers import escape_markdown

from app_main.services import (
    check_user_spin_status,
    get_pending_winning,
    process_referral,
    referrals_per_spin,
)
from app_main.messaging import register_bot_user
from app_main.subscription import MEMBER_STATUSES, get_required_channels
from bot.utils import get_webapp_url
from bot.worker import outbox_loop

logger = logging.getLogger(__name__)


# Django ORM sinxron ishlaydi — async handler ichidan to'g'ridan-to'g'ri
# chaqirilsa SynchronousOnlyOperation xatosi chiqadi. Shu sabab barcha
# baza bilan ishlovchi funksiyalar sync_to_async orqali o'raladi.
process_referral_async = sync_to_async(process_referral, thread_sensitive=True)
register_bot_user_async = sync_to_async(register_bot_user, thread_sensitive=True)
referrals_per_spin_async = sync_to_async(referrals_per_spin, thread_sensitive=True)
get_required_channels_async = sync_to_async(get_required_channels, thread_sensitive=True)


async def unjoined_channel_buttons(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Foydalanuvchi hali obuna bo'lmagan majburiy kanallar uchun tugmalar.
    Tekshirib bo'lmagan kanal (bot admin emas) ko'rsatilmaydi — MiniApp ham
    uni talab qilmaydi.
    """
    rows = []
    for channel in await get_required_channels_async():
        try:
            member = await context.bot.get_chat_member(channel.chat_id, user_id)
        except TelegramError as e:
            logger.warning("Kanalni tekshirib bo'lmadi (%s): %s", channel.chat_id, e)
            continue
        joined = member.status in MEMBER_STATUSES or getattr(member, 'is_member', False)
        if not joined and channel.link:
            rows.append([InlineKeyboardButton(f"📢 {channel.title}", url=channel.link)])
    return rows


@sync_to_async(thread_sensitive=True)
def get_user_winnings(telegram_id: int):
    """
    Foydalanuvchining yutuqlari va qolgan spinlari.

    Manzil sovg'aning o'zidan olinadi (admin panelda kiritiladi), shuning
    uchun natija shablonga tayyor dict ko'rinishida qaytariladi.
    """
    available_spins, lead, winnings = check_user_spin_status(telegram_id)
    pending = get_pending_winning(lead)
    pending_title = pending.prize.title if pending else None

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

    return available_spins, rows, pending_title


async def notify_referrer(context: ContextTypes.DEFAULT_TYPE, referrer_tg_id: int, friend_name: str):
    """
    Taklif qiluvchiga do'sti havola orqali kirgani haqida xabar. Bonus
    do'st birinchi yutug'ini rasmiylashtirgandan keyin hisoblanadi.
    """
    name = escape_markdown(friend_name or "Do'stingiz", version=1)
    per_spin = await referrals_per_spin_async()
    text = (
        f"👥 *{name}* havolangiz orqali botga kirdi!\n\n"
        f"U barabanni aylantirib, yutug'ini rasmiylashtirgach hisobingizga "
        f"qo'shiladi. Har {per_spin} ta do'st uchun *+1 aylantirish*."
    )

    reply_markup, _ = _webapp_keyboard()
    try:
        await context.bot.send_message(
            chat_id=referrer_tg_id, text=text,
            reply_markup=reply_markup, parse_mode="Markdown"
        )
    except Exception as e:
        # Foydalanuvchi botni bloklagan yoki hali /start bosmagan bo'lishi mumkin
        logger.warning("Could not notify referrer %s: %s", referrer_tg_id, e)


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
                friend_name = new_user.first_name if new_user else ''
                success, _referrer_lead = await process_referral_async(
                    referrer_tg_id, new_user_id, friend_name
                )
                if success:
                    logger.info("Referral linked: %s invited %s", referrer_tg_id, new_user_id)
                    await notify_referrer(context, referrer_tg_id, friend_name)
            except Exception as e:
                logger.error("Failed to process referral: %s", e)

    # Referaldan keyin — aks holda process_referral uni "eski foydalanuvchi" deb o'ylardi.
    # Yozuv bo'lsa ommaviy xabarlar hali aylantirmagan foydalanuvchiga ham yetadi.
    if new_user:
        try:
            await register_bot_user_async(new_user.id, new_user.first_name, new_user.last_name)
        except Exception as e:
            logger.error("Failed to register bot user %s: %s", new_user.id, e)

    channel_rows = await unjoined_channel_buttons(context, new_user_id) if new_user else []
    reply_markup, webapp_url = _webapp_keyboard(extra_rows=channel_rows)
    user_first_name = escape_markdown(new_user.first_name if new_user else "Foydalanuvchi", version=1)

    if webapp_url.startswith("https://"):
        text = (
            f"👋 **Salom, {user_first_name}!**\n\n"
            f"Yoshlar Texnoparki Gift Box barabaniga xush kelibsiz! 🚀\n\n"
            f"Tugmani bosing va barabanni aylantiring — yutuq chiqsa, faqat "
            f"**ism va telefon raqamingizni** kiritasiz, xolos.\n\n"
            f"🎁 Yutuqlaringizni va ularni qayerdan olishni ko'rish uchun "
            f"/yutuqlarim buyrug'ini yuboring."
        )
        if channel_rows:
            text += (
                "\n\n📢 **Barabanni aylantirish uchun quyidagi kanallarga obuna bo'ling**, "
                "so'ng «Ochish» tugmasini bosing."
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

    available_spins, rows, pending_title = await get_user_winnings(user.id)

    if pending_title:
        reply_markup, _ = _webapp_keyboard()
        await update.message.reply_text(
            f"🎁 Sizga **{pending_title}** tushgan, lekin hali rasmiylashtirilmagan.\n\n"
            f"MiniApp'ni oching va ism-telefoningizni yuboring — shundan keyin "
            f"QR-kod beriladi.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        if not rows:
            return

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
    per_spin = await referrals_per_spin_async()
    await update.message.reply_text(
        "ℹ️ **Qanday ishlaydi?**\n\n"
        "1️⃣ Tugmani bosib MiniApp'ni oching va barabanni aylantiring.\n"
        "2️⃣ Yutuq chiqsa, ism va telefon raqamingizni kiriting.\n"
        "3️⃣ «Yutuqlarim» bo'limidan QR-kodni oching — uning ostida "
        "sovg'ani olish manzili ko'rsatiladi.\n"
        "4️⃣ Texnopark xodimiga QR-kodni ko'rsating.\n\n"
        f"Har {per_spin} ta taklif qilgan do'stingiz uchun **+1 aylantirish** olasiz "
        "(do'st birinchi yutug'ini rasmiylashtirgach hisoblanadi).\n\n"
        "Buyruqlar:\n"
        "/start — barabanni ochish\n"
        "/yutuqlarim — yutuqlar va manzillar\n"
        "/yordam — shu qo'llanma",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


def _webapp_markup():
    return _webapp_keyboard()[0]


async def post_init(application):
    """Telegram menyusidagi buyruqlar va xabarlar navbatini yuboruvchi fon sikli."""
    await application.bot.set_my_commands([
        BotCommand("start", "Barabanni ochish"),
        BotCommand("yutuqlarim", "Yutuqlarim va manzillar"),
        BotCommand("yordam", "Qanday ishlaydi?"),
    ])
    application.bot_data['outbox_task'] = asyncio.create_task(
        outbox_loop(application, _webapp_markup)
    )


async def post_shutdown(application):
    task = application.bot_data.get('outbox_task')
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def setup_handlers(application):
    """
    Bot buyruqlarini ro'yxatdan o'tkazadi.
    """
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler(["yutuqlarim", "myprizes"], my_prizes_command))
    application.add_handler(CommandHandler(["yordam", "help"], help_command))
