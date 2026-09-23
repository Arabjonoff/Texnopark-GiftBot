"""
Bot orqali yuboriladigan xabarlar: ommaviy xabarlar, muddat eslatmalari va
referal bildirishnomalari.

Web jarayoni xabarni faqat BotMessage navbatiga yozadi. Yuborish bot
jarayonidagi fon siklida (bot/worker.py) bajariladi — shu tufayli dashboard
so'rovi minglab xabar yuborilishini kutib qolmaydi va Telegram limitlari
bir joyda boshqariladi.
"""
from datetime import timedelta
from html import escape

from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from app_main.models import Broadcast, BotMessage, StudentLead, WinningResult

# Bir xabar necha marta qayta urinib ko'riladi (tarmoq xatolarida)
MAX_ATTEMPTS = 3

# Muddat tugashidan necha soat oldin eslatma yuboriladi
REMINDER_HOURS_BEFORE = 24


# ---------------------------------------------------------------- Navbatga yozish

def queue_message(chat_id, text, kind, parse_mode='HTML', with_button=True):
    return BotMessage.objects.create(
        chat_id=chat_id,
        text=text,
        kind=kind,
        parse_mode=parse_mode,
        with_button=with_button,
    )


def notify_referral_confirmed(referrer: StudentLead, friend: StudentLead, spin_awarded: bool, per_spin: int):
    """Taklif qilingan do'st yutug'ini rasmiylashtirdi — taklif qiluvchiga xabar."""
    name = escape(friend.first_name or "Do'stingiz")
    if spin_awarded:
        text = (
            f"🎉 <b>{name}</b> yutug'ini rasmiylashtirdi va siz {per_spin} ta do'st "
            f"to'pladingiz!\n\nSizga barabanni aylantirish uchun <b>+1 imkoniyat</b> "
            f"berildi. Omadingizni sinab ko'ring!"
        )
    else:
        confirmed = referrer.referrals.filter(referral_confirmed_at__isnull=False).count()
        progress = confirmed % per_spin
        text = (
            f"👥 <b>{name}</b> yutug'ini rasmiylashtirdi — u hisobingizga qo'shildi!\n\n"
            f"Progress: <b>{progress}/{per_spin}</b> — yana {per_spin - progress} ta do'st "
            f"va <b>+1 aylantirish</b> sizniki."
        )
    if referrer.bot_blocked:
        return None
    return queue_message(referrer.telegram_id, text, BotMessage.Kind.REFERRAL)


# ---------------------------------------------------------------- Ommaviy xabarlar

def audience_queryset(audience):
    """Tanlangan auditoriyadagi, botni bloklamagan foydalanuvchilar."""
    qs = StudentLead.objects.filter(bot_blocked=False)
    A = Broadcast.Audience

    if audience == A.REGISTERED:
        return qs.exclude(phone_number='')
    if audience == A.ACTIVE_PRIZE:
        return qs.filter(winnings__status=WinningResult.Status.ACTIVE).distinct()
    if audience == A.NO_SPIN:
        return qs.annotate(spin_count=Count('winnings')).filter(spin_count=0)
    if audience == A.HAS_SPINS:
        return (
            qs.annotate(spin_count=Count('winnings'))
            .filter(spin_count__lt=F('extra_spins') + 1)
        )
    return qs


def audience_counts():
    """Dashboard formasida har bir variant yonida ko'rsatiladigan son."""
    return {value: audience_queryset(value).count() for value in Broadcast.Audience.values}


def create_broadcast(text, audience, with_button, created_by=None):
    """Ommaviy xabarni yaratib, har bir qabul qiluvchi uchun navbatga yozadi."""
    with transaction.atomic():
        broadcast = Broadcast.objects.create(
            text=text,
            audience=audience,
            with_button=with_button,
            created_by=created_by if created_by and created_by.is_authenticated else None,
        )
        chat_ids = list(audience_queryset(audience).values_list('telegram_id', flat=True))
        BotMessage.objects.bulk_create(
            [
                BotMessage(
                    chat_id=chat_id,
                    text=text,
                    parse_mode='',  # xodim yozgan matn — oddiy matn sifatida
                    with_button=with_button,
                    kind=BotMessage.Kind.BROADCAST,
                    broadcast=broadcast,
                )
                for chat_id in chat_ids
            ],
            batch_size=500,
        )
        broadcast.total = len(chat_ids)
        if not chat_ids:
            broadcast.status = Broadcast.Status.DONE
            broadcast.finished_at = timezone.now()
        broadcast.save(update_fields=['total', 'status', 'finished_at'])
    return broadcast


def cancel_broadcast(broadcast):
    """Hali yuborilmagan xabarlarni navbatdan olib tashlaydi."""
    if broadcast.status != Broadcast.Status.SENDING:
        return 0
    with transaction.atomic():
        removed, _ = broadcast.messages.filter(status=BotMessage.Status.PENDING).delete()
        broadcast.status = Broadcast.Status.CANCELLED
        broadcast.finished_at = timezone.now()
        broadcast.save(update_fields=['status', 'finished_at'])
    return removed


# ---------------------------------------------------------------- Muddatlar

def expire_winnings():
    """Muddati o'tgan, lekin hali ACTIVE turgan yutuqlarni EXPIRED ga o'tkazadi."""
    return WinningResult.objects.filter(
        status=WinningResult.Status.ACTIVE,
        expires_at__lt=timezone.now(),
    ).update(status=WinningResult.Status.EXPIRED)


def queue_expiry_reminders(hours_before=REMINDER_HOURS_BEFORE):
    """
    Muddati yaqinlashgan, hali olib ketilmagan sovg'alar egalariga eslatma.
    Har bir yutuq uchun faqat bir marta yuboriladi.
    """
    now = timezone.now()
    due = (
        WinningResult.objects
        .filter(
            status=WinningResult.Status.ACTIVE,
            reminder_sent_at__isnull=True,
            expires_at__gt=now,
            expires_at__lte=now + timedelta(hours=hours_before),
        )
        .select_related('lead', 'prize')
    )

    queued = 0
    for winning in due:
        with transaction.atomic():
            # Ikki jarayon bir vaqtda ishlasa ham eslatma bir marta ketadi
            claimed = WinningResult.objects.filter(
                pk=winning.pk, reminder_sent_at__isnull=True
            ).update(reminder_sent_at=now)
            if not claimed or winning.lead.bot_blocked:
                continue

            expires = timezone.localtime(winning.expires_at).strftime('%d.%m.%Y %H:%M')
            lines = [
                "⏰ <b>Sovg'angiz muddati tugayapti!</b>",
                "",
                f"🎁 {escape(winning.prize.title)}",
                f"🔑 Promokod: <code>{escape(winning.promo_code)}</code>",
                f"⌛ Amal qiladi: <b>{expires}</b> gacha",
            ]
            if winning.prize.pickup_address:
                lines.append(f"📍 {escape(winning.prize.pickup_address)}")
            lines += ["", "QR-kodni MiniApp'dagi «Yutuqlarim» bo'limidan oching."]

            queue_message(winning.lead.telegram_id, "\n".join(lines), BotMessage.Kind.REMINDER)
            queued += 1
    return queued


# ---------------------------------------------------------------- Bot worker uchun

def next_pending_batch(limit=25):
    return list(
        BotMessage.objects.filter(status=BotMessage.Status.PENDING)
        .order_by('created_at')[:limit]
    )


def mark_sent(message: BotMessage):
    message.status = BotMessage.Status.SENT
    message.sent_at = timezone.now()
    message.attempts += 1
    message.error = ''
    message.save(update_fields=['status', 'sent_at', 'attempts', 'error'])
    if message.broadcast_id:
        Broadcast.objects.filter(pk=message.broadcast_id).update(sent_count=F('sent_count') + 1)


def mark_failed(message: BotMessage, error: str, permanent: bool, user_blocked: bool = False):
    """
    permanent=False — tarmoq xatosi: MAX_ATTEMPTS gacha qayta urinib ko'riladi.
    user_blocked=True — foydalanuvchi botni bloklagan, keyingi ommaviy
    xabarlar unga navbatga qo'yilmaydi.
    """
    message.attempts += 1
    message.error = (error or '')[:255]
    if permanent or message.attempts >= MAX_ATTEMPTS:
        message.status = BotMessage.Status.FAILED
        if message.broadcast_id:
            Broadcast.objects.filter(pk=message.broadcast_id).update(failed_count=F('failed_count') + 1)
    message.save(update_fields=['status', 'attempts', 'error'])

    if user_blocked:
        StudentLead.objects.filter(telegram_id=message.chat_id).update(bot_blocked=True)


def finish_broadcasts():
    """Navbatda xabari qolmagan ommaviy xabarlarni yakunlangan deb belgilaydi."""
    return (
        Broadcast.objects
        .filter(status=Broadcast.Status.SENDING)
        .exclude(messages__status=BotMessage.Status.PENDING)
        .update(status=Broadcast.Status.DONE, finished_at=timezone.now())
    )


def register_bot_user(telegram_id, first_name='', last_name=''):
    """
    /start bosgan foydalanuvchini bazaga yozadi — shunda u hali barabanni
    aylantirmagan bo'lsa ham ommaviy xabarlarni oladi. Botni qayta ishga
    tushirgan foydalanuvchining "bloklagan" belgisi olib tashlanadi.
    """
    lead, created = StudentLead.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            'first_name': first_name or "Foydalanuvchi",
            'last_name': last_name or '',
            'phone_number': '',
        },
    )
    if not created and lead.bot_blocked:
        lead.bot_blocked = False
        lead.save(update_fields=['bot_blocked'])
    return lead


def pending_counts_by_kind():
    """Dashboard uchun: navbatdagi xabarlar soni."""
    rows = (
        BotMessage.objects.filter(status=BotMessage.Status.PENDING)
        .values('kind').annotate(total=Count('id'))
    )
    return {row['kind']: row['total'] for row in rows}

