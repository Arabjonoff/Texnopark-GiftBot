"""
Majburiy obuna: foydalanuvchi talab qilingan kanallarga a'zo ekanini
Telegram Bot API (getChatMember) orqali tekshiradi.

Muhim: bot har bir kanalda ADMIN bo'lishi kerak. Aks holda Telegram
"member list is inaccessible" xatosini qaytaradi — bunday kanal tekshirilmaydi
(foydalanuvchi bloklanmaydi), xato esa logga yoziladi va dashboardda ko'rinadi.
"""
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from app_main.models import RequiredChannel, SiteSettings

logger = logging.getLogger(__name__)

API_TIMEOUT_SECONDS = 5
# Obuna tasdiqlansa shuncha vaqt qayta so'ralmaydi. Obuna bo'lmaganlik
# keshlanmaydi — foydalanuvchi kanalga qo'shilib, darhol «Tekshirish»ni bosadi.
MEMBER_CACHE_SECONDS = 10 * 60

MEMBER_STATUSES = {'creator', 'administrator', 'member'}


class ChannelCheckError(Exception):
    """Kanalni tekshirib bo'lmadi (bot admin emas, kanal topilmadi, tarmoq xatosi)."""


def get_required_channels():
    if not SiteSettings.load().subscription_required:
        return []
    return list(RequiredChannel.objects.filter(is_active=True))


def _api_get_chat_member(chat_id, user_id):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise ChannelCheckError("TELEGRAM_BOT_TOKEN sozlanmagan")
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getChatMember",
            params={'chat_id': chat_id, 'user_id': user_id},
            timeout=API_TIMEOUT_SECONDS,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ChannelCheckError(f"Telegram API bilan aloqa yo'q: {exc}") from exc

    if data.get('ok'):
        return data['result']

    description = data.get('description', '')
    # Foydalanuvchi kanal bilan hech qachon aloqada bo'lmagan — demak a'zo emas
    if 'user not found' in description.lower() or 'PARTICIPANT_ID_INVALID' in description:
        return {'status': 'left'}
    raise ChannelCheckError(description or f"HTTP {resp.status_code}")


def is_member(channel: RequiredChannel, user_id: int) -> bool | None:
    """
    True — a'zo, False — a'zo emas, None — tekshirib bo'lmadi.
    """
    cache_key = f"sub-member:{channel.pk}:{channel.chat_id}:{user_id}"
    if cache.get(cache_key):
        return True

    try:
        member = _api_get_chat_member(channel.chat_id, user_id)
    except ChannelCheckError as exc:
        logger.error("Obunani tekshirib bo'lmadi (%s): %s", channel.chat_id, exc)
        return None

    status = member.get('status')
    joined = status in MEMBER_STATUSES or (status == 'restricted' and member.get('is_member'))
    if joined:
        cache.set(cache_key, True, MEMBER_CACHE_SECONDS)
    return bool(joined)


def subscription_status(user_id: int) -> dict:
    """
    MiniApp va API uchun: {'ok': bool, 'channels': [...]}.
    Tekshirib bo'lmagan kanal foydalanuvchini to'xtatmaydi — sozlash xatosi
    butun aksiyani yopib qo'ymasligi kerak.
    """
    channels = []
    ok = True
    for channel in get_required_channels():
        member = is_member(channel, user_id)
        subscribed = member is not False
        ok = ok and subscribed
        channels.append({
            'id': channel.pk,
            'title': channel.title,
            'link': channel.link,
            'subscribed': subscribed,
        })
    return {'ok': ok, 'channels': channels}


def diagnose_channel(channel: RequiredChannel) -> tuple[bool, str]:
    """
    Dashboard uchun: bot shu kanalda admin ekanini tekshiradi.
    Returns (ok, izoh).
    """
    bot_id = (settings.TELEGRAM_BOT_TOKEN or '').split(':')[0]
    if not bot_id.isdigit():
        return False, "TELEGRAM_BOT_TOKEN sozlanmagan"
    try:
        member = _api_get_chat_member(channel.chat_id, int(bot_id))
    except ChannelCheckError as exc:
        return False, str(exc)
    if member.get('status') in ('administrator', 'creator'):
        return True, "Bot admin — obuna tekshiriladi"
    return False, "Bot bu kanalda admin emas — kanal sozlamalaridan botni admin qiling"
