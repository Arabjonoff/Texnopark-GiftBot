"""
Bot jarayonidagi fon sikli.

  * BotMessage navbatidagi xabarlarni yuboradi (ommaviy xabarlar, eslatmalar,
    referal bildirishnomalari) — Telegram limitiga rioya qilib;
  * muddati o'tgan yutuqlarni EXPIRED holatiga o'tkazadi;
  * muddati tugayotgan sovg'alar egalariga eslatma navbatga qo'yadi.

Qo'shimcha kutubxona (Celery, APScheduler) talab qilinmaydi — sikl
python-telegram-bot'ning o'z event loop'ida ishlaydi.
"""
import asyncio
import logging
import time

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from app_main import messaging

logger = logging.getLogger(__name__)

# Navbat bo'sh bo'lganda necha soniyada bir tekshiriladi
IDLE_SLEEP_SECONDS = 5
# Telegram: bitta botdan sekundiga ~30 ta xabar. Zaxira bilan 20 ta.
SEND_INTERVAL_SECONDS = 0.05
# Muddatlarni tekshirish oralig'i
MAINTENANCE_INTERVAL_SECONDS = 10 * 60


def _db(func):
    """ORM chaqiruvi: uzilgan ulanishlarni yopib, alohida thread'da bajaradi."""
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()
    return sync_to_async(wrapper, thread_sensitive=True)


next_batch = _db(messaging.next_pending_batch)
mark_sent = _db(messaging.mark_sent)
mark_failed = _db(messaging.mark_failed)
finish_broadcasts = _db(messaging.finish_broadcasts)


@_db
def run_maintenance():
    expired = messaging.expire_winnings()
    reminders = messaging.queue_expiry_reminders()
    if expired or reminders:
        logger.info("Maintenance: %s expired, %s reminders queued", expired, reminders)


async def _send(bot, message, keyboard_factory):
    reply_markup = keyboard_factory() if message.with_button else None

    try:
        await bot.send_message(
            chat_id=message.chat_id,
            text=message.text,
            parse_mode=message.parse_mode or None,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except RetryAfter as exc:
        # Limitdan oshdik — xabar navbatda qoladi, kutib davom etamiz
        retry = exc.retry_after
        wait = retry.total_seconds() if hasattr(retry, 'total_seconds') else float(retry)
        logger.warning("Telegram flood limit, %.0fs kutamiz", wait)
        await asyncio.sleep(wait + 1)
        return
    except Forbidden as exc:
        # Foydalanuvchi botni bloklagan yoki akkaunti o'chirilgan
        await mark_failed(message, str(exc), permanent=True, user_blocked=True)
        return
    except BadRequest as exc:
        # Chat topilmadi, matn noto'g'ri va h.k. — qayta urinishdan foyda yo'q
        await mark_failed(message, str(exc), permanent=True)
        return
    except TelegramError as exc:
        await mark_failed(message, str(exc), permanent=False)
        return

    await mark_sent(message)


async def outbox_loop(application, keyboard_factory):
    """
    Bot ishlayotgan butun vaqt davomida aylanadigan sikl.
    keyboard_factory() — xabar ostidagi «Ochish» tugmasini qaytaradi.
    """
    bot = application.bot
    last_maintenance = 0.0
    logger.info("Outbox worker ishga tushdi")

    while True:
        try:
            if time.monotonic() - last_maintenance >= MAINTENANCE_INTERVAL_SECONDS:
                await run_maintenance()
                last_maintenance = time.monotonic()

            batch = await next_batch()
            if not batch:
                await finish_broadcasts()
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue

            for message in batch:
                await _send(bot, message, keyboard_factory)
                await asyncio.sleep(SEND_INTERVAL_SECONDS)

            await finish_broadcasts()
        except asyncio.CancelledError:
            logger.info("Outbox worker to'xtatildi")
            raise
        except Exception:
            # Sikl hech qachon butunlay to'xtab qolmasligi kerak
            logger.exception("Outbox worker xatosi")
            await asyncio.sleep(IDLE_SLEEP_SECONDS)
