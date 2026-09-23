import hmac
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import parse_qsl, unquote
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from datetime import timedelta
from app_main.models import Prize, SiteSettings, SpinGrant, StudentLead, WinningResult

logger = logging.getLogger(__name__)

def verify_telegram_init_data(init_data_raw: str) -> tuple[bool, dict | None]:
    """
    Validates Telegram WebApp initData hash using HMAC-SHA256.
    Returns (is_valid, parsed_user_data_dict).
    """
    if not init_data_raw:
        return False, None

    # Dev/test uchun soxta foydalanuvchi: mock_<id>_<ism>. Productionda o'chiq —
    # aks holda istalgan odam istalgan Telegram ID nomidan so'rov yubora olardi.
    if init_data_raw.startswith('mock_'):
        if not settings.ALLOW_MOCK_INIT_DATA:
            return False, None
        parts = init_data_raw.split('_')
        tg_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 999888777
        first_name = parts[2] if len(parts) > 2 else "TestUser"
        return True, {
            'id': tg_id,
            'first_name': first_name,
            'last_name': 'Dev',
            'username': 'test_dev_user'
        }

    try:
        parsed_data = dict(parse_qsl(init_data_raw, keep_blank_values=True))
        if 'hash' not in parsed_data:
            return False, None

        received_hash = parsed_data.pop('hash')

        # Format key=value pairs sorted by key
        data_check_arr = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
        data_check_string = "\n".join(data_check_arr)

        # Telegram secret key generation
        bot_token = settings.TELEGRAM_BOT_TOKEN
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode('utf-8'),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        is_valid = hmac.compare_digest(calculated_hash, received_hash)

        # Imzo to'g'ri bo'lsa ham eskirgan initData qabul qilinmaydi —
        # aks holda bir marta ushlab olingan satr abadiy ishlayverardi
        if is_valid and not _is_fresh_auth_date(parsed_data.get('auth_date')):
            return False, None

        user_data = None
        if 'user' in parsed_data:
            try:
                user_str = parsed_data['user']
                try:
                    user_data = json.loads(user_str)
                except Exception:
                    user_data = json.loads(unquote(user_str))
            except Exception:
                pass

        return is_valid, user_data

    except Exception as e:
        return False, None


def _is_fresh_auth_date(auth_date_raw) -> bool:
    max_age = getattr(settings, 'INIT_DATA_MAX_AGE_SECONDS', 0)
    if not max_age:
        return True
    try:
        auth_date = int(auth_date_raw)
    except (TypeError, ValueError):
        return False
    # Soatlar biroz farq qilishi mumkin — kelajakdagi 5 daqiqagacha ruxsat
    age = time.time() - auth_date
    return -300 <= age <= max_age


def get_spinnable_prizes():
    """
    Barabanda qatnashadigan sovg'alar queryset'i.

    Sovg'a aktiv bo'lishi kerak; agar kategoriyasi bo'lsa, u ham aktiv bo'lishi
    shart. Kategoriyasi yo'q sovg'alar ham qatnashadi. Qoldig'i tugagan
    (stock=0) sovg'alar chiqarib tashlanadi, stock=NULL — cheksiz.

    Bu mantiq API va spin algoritmida bir xil bo'lishi uchun bitta joyda turadi.
    """
    return (
        Prize.objects
        .filter(is_active=True)
        .filter(Q(stock__isnull=True) | Q(stock__gt=0))
        .exclude(category__is_active=False)
        .select_related('category')
    )


def calculate_weighted_prize(exclude_ids=()) -> Prize:
    """
    Server-side weighted probability selection algorithm for the Gift Box roulette.
    Determines prize purely on server side according to Prize.probability weights.
    """
    active_prizes = list(get_spinnable_prizes().exclude(pk__in=exclude_ids))
    if not active_prizes:
        raise ValueError("Aktiv sovg'alar topilmadi. Baza bo'sh.")

    weights = [max(0, p.probability) for p in active_prizes]
    if sum(weights) == 0:
        weights = [1] * len(active_prizes)

    # secrets — kriptografik tasodifiy manba, natijani oldindan bashorat qilib bo'lmaydi
    point = secrets.randbelow(sum(weights))
    for prize, weight in zip(active_prizes, weights):
        if point < weight:
            return prize
        point -= weight
    return active_prizes[-1]


def _reserve_prize() -> Prize:
    """
    Sovg'ani tanlaydi va qoldig'idan 1 dona band qiladi.

    Qoldiqni UPDATE ... WHERE stock > 0 bilan kamaytiramiz — bir vaqtda ikki
    kishi oxirgi donani yutib olsa, faqat bittasiga tegadi, ikkinchisi uchun
    boshqa sovg'a tanlanadi.
    """
    tried = set()
    while True:
        prize = calculate_weighted_prize(exclude_ids=tried)
        if prize.stock is None:
            return prize
        taken = Prize.objects.filter(pk=prize.pk, stock__gt=0).update(stock=F('stock') - 1)
        if taken:
            prize.refresh_from_db(fields=['stock'])
            return prize
        tried.add(prize.pk)


def check_user_spin_status(telegram_id: int) -> tuple[int, StudentLead | None, list[WinningResult]]:
    """
    Calculates available spins for a user based on initial spin (1) + extra_spins - used spins.
    Returns (available_spins, student_lead, list_of_winnings).

    PENDING yutuqlar ham spin sifatida hisoblanadi, lekin ro'yxatga
    kirmaydi — ular hali rasmiylashtirilmagan (get_pending_winning'ga qarang).
    """
    lead = StudentLead.objects.filter(telegram_id=telegram_id).first()
    if not lead:
        return 1, None, []

    all_winnings = list(
        WinningResult.objects.filter(lead=lead).select_related('prize').order_by('-created_at')
    )
    allowed_total = 1 + lead.extra_spins
    available_spins = max(0, allowed_total - len(all_winnings))
    # Yutuq limitlari qo'shimcha spinlardan ustun turadi
    available_spins = min(available_spins, spins_left_by_limits(lead))
    winnings = [
        w for w in all_winnings
        if w.status not in (WinningResult.Status.PENDING, WinningResult.Status.CANCELLED)
    ]

    return available_spins, lead, winnings


def get_pending_winning(lead: StudentLead | None) -> WinningResult | None:
    """Aylantirilgan, lekin hali ism/telefon yuborilmagan yutuq."""
    if not lead:
        return None
    return (
        lead.winnings.filter(status=WinningResult.Status.PENDING)
        .select_related('prize')
        .order_by('-created_at')
        .first()
    )


class NoSpinsLeft(Exception):
    pass


class SpinBlocked(Exception):
    """Bloklangan yoki yutuq limitiga yetgan foydalanuvchi — yangi spin berilmaydi."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _limit_counted_winnings(lead):
    # Bekor qilingan yutuq limitga kirmaydi (xato bilan bekor qilingan bo'lsa, joy qaytadi)
    return lead.winnings.exclude(status=WinningResult.Status.CANCELLED)


def spin_block_reason(lead, site=None):
    """
    Yangi spin nima uchun berilmasligini qaytaradi: (code, matn) yoki None.
    Bu tekshiruv extra_spins'dan qat'i nazar ishlaydi — spin qayerdan kelgan
    bo'lmasin, bir odam limitdan ko'p sovg'a ololmaydi.
    """
    if not lead:
        return None
    if lead.is_banned:
        return 'banned', "Hisobingiz vaqtincha bloklangan. Savollar bo'lsa, Texnopark xodimlariga murojaat qiling."

    site = site or SiteSettings.load()
    counted = _limit_counted_winnings(lead)
    if site.max_wins_total and counted.count() >= site.max_wins_total:
        return 'total_limit', (
            f"Siz maksimal {site.max_wins_total} ta sovg'a yutib oldingiz. "
            f"Ishtirokingiz uchun rahmat!"
        )
    if site.max_wins_per_day and counted.filter(created_at__date=timezone.localdate()).count() >= site.max_wins_per_day:
        return 'daily_limit', "Bugungi limit tugadi. Ertaga yana urinib ko'ring!"
    return None


def spins_left_by_limits(lead, site=None) -> int:
    """Limitlar bo'yicha yana nechta spin mumkin (cheklanmagan bo'lsa — katta son)."""
    if lead.is_banned:
        return 0
    site = site or SiteSettings.load()
    left = 10 ** 6
    counted = _limit_counted_winnings(lead)
    if site.max_wins_total:
        left = min(left, site.max_wins_total - counted.count())
    if site.max_wins_per_day:
        left = min(left, site.max_wins_per_day - counted.filter(created_at__date=timezone.localdate()).count())
    return max(0, left)


def grant_spins(lead, amount, reason, note='', created_by=None) -> int:
    """
    extra_spins'ni o'zgartirishning YAGONA yo'li — har o'zgarish SpinGrant'ga
    yoziladi. Tranzaksiya ichida chaqirilishi kerak. Balans manfiy bo'lmaydi.
    Returns haqiqatda qo'llangan o'zgarish.
    """
    lead.refresh_from_db(fields=['extra_spins'])
    new_value = max(0, lead.extra_spins + amount)
    delta = new_value - lead.extra_spins
    if delta == 0:
        return 0
    lead.extra_spins = new_value
    lead.save(update_fields=['extra_spins'])
    SpinGrant.objects.create(
        lead=lead,
        amount=delta,
        reason=reason,
        note=note[:255],
        created_by=created_by if created_by and created_by.is_authenticated else None,
    )
    return delta


def phone_digits(phone) -> str:
    """Taqqoslash uchun raqamning oxirgi 9 ta raqami (+998 90 123 45 67 -> 901234567)."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return digits[-9:]


def normalize_phone(phone) -> str:
    """Yagona saqlash formati: +998XXXXXXXXX. 9 ta raqam chiqmasa — bo'sh satr."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if len(digits) == 12 and digits.startswith('998'):
        digits = digits[3:]
    return '+998' + digits if len(digits) == 9 else ''


def phone_used_by_other(lead, phone) -> bool:
    """Shu raqam bilan boshqa akkaunt allaqachon yutuq rasmiylashtirganmi."""
    digits = phone_digits(phone)
    if len(digits) != 9:
        return False
    return (
        StudentLead.objects
        .exclude(pk=lead.pk)
        .filter(phone_number__endswith=digits)
        .filter(winnings__status__in=[
            WinningResult.Status.ACTIVE, WinningResult.Status.USED, WinningResult.Status.EXPIRED,
        ])
        .exists()
    )


class CampaignClosed(Exception):
    """Aksiya hali boshlanmagan yoki tugagan — yangi spin berilmaydi."""

    def __init__(self, state):
        super().__init__(state)
        self.state = state


def campaign_info(site=None):
    """MiniApp uchun aksiya holati va (yopiq bo'lsa) ko'rsatiladigan matn."""
    site = site or SiteSettings.load()
    state = site.campaign_state()
    message = ''
    if state == 'not_started':
        start = timezone.localtime(site.campaign_start).strftime('%d.%m.%Y %H:%M')
        message = site.campaign_closed_message or f"Aksiya {start} da boshlanadi. Kutib qoling!"
    elif state == 'ended':
        message = site.campaign_closed_message or (
            "Aksiya yakunlandi. Ishtirokingiz uchun rahmat! Yutib olgan "
            "sovg'alaringizni «Yutuqlarim» bo'limidan olishingiz mumkin."
        )
    return {
        'state': state,
        'message': message,
        'starts_at': site.campaign_start,
        'ends_at': site.campaign_end,
    }


def start_spin(telegram_id: int, user_data: dict) -> tuple[WinningResult, bool]:
    """
    Sovg'ani serverda aniqlaydi va darhol PENDING yutuq sifatida saqlaydi.

    Spin shu yerda sarflanadi — foydalanuvchi natija yoqmasa ilovani yopib
    qayta aylantira olmaydi. Rasmiylashtirilmagan yutuq bo'lsa, yangisi
    aylantirilmaydi, o'sha qaytariladi.

    Returns (winning, created). Imkoniyat qolmagan bo'lsa NoSpinsLeft.
    """
    with transaction.atomic():
        lead, _ = StudentLead.objects.select_for_update().get_or_create(
            telegram_id=telegram_id,
            defaults={
                'first_name': user_data.get('first_name') or "Foydalanuvchi",
                'last_name': user_data.get('last_name') or '',
                'phone_number': "",
            },
        )

        if lead.is_banned:
            raise SpinBlocked(*spin_block_reason(lead))

        pending = get_pending_winning(lead)
        if pending:
            return pending, False

        blocked = spin_block_reason(lead)
        if blocked:
            raise SpinBlocked(*blocked)

        state = SiteSettings.load().campaign_state()
        if state != 'active':
            raise CampaignClosed(state)

        if 1 + lead.extra_spins - lead.winnings.count() <= 0:
            raise NoSpinsLeft()

        prize = _reserve_prize()
        winning = WinningResult.objects.create(
            lead=lead,
            prize=prize,
            promo_code=generate_unique_promo_code(),
            status=WinningResult.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=prize.valid_days),
        )

    return winning, True


def referrals_per_spin() -> int:
    """Necha tasdiqlangan do'st uchun +1 aylantirish beriladi (dashboard sozlamasi)."""
    return max(1, SiteSettings.load().referrals_per_spin)


def confirmed_referrals(lead: StudentLead):
    """Birinchi yutug'ini rasmiylashtirgan (haqiqiy) do'stlar."""
    return lead.referrals.filter(referral_confirmed_at__isnull=False)


def process_referral(
    referrer_tg_id: int,
    new_user_tg_id: int,
    new_user_first_name: str = '',
) -> tuple[bool, StudentLead | None]:
    """
    ref_123456789 havolasi orqali kirgan yangi foydalanuvchini taklif
    qiluvchiga bog'laydi. Bonus hali berilmaydi — do'st birinchi yutug'ini
    rasmiylashtirganda confirm_referral() hisoblaydi.

    Faqat botga birinchi marta kirayotgan foydalanuvchi hisoblanadi —
    aks holda bitta odam havolani qayta bosib cheksiz spin yig'ib olardi.

    Returns (success, referrer_lead).
    """
    if not referrer_tg_id or not new_user_tg_id or referrer_tg_id == new_user_tg_id:
        return False, None

    with transaction.atomic():
        if StudentLead.objects.filter(telegram_id=new_user_tg_id).exists():
            return False, None

        referrer_lead, _ = StudentLead.objects.select_for_update().get_or_create(
            telegram_id=referrer_tg_id,
            # Taklif qiluvchi hali forma to'ldirmagan bo'lsa — vaqtinchalik yozuv
            defaults={'first_name': "Foydalanuvchi", 'phone_number': ""},
        )

        StudentLead.objects.create(
            telegram_id=new_user_tg_id,
            first_name=new_user_first_name or "Foydalanuvchi",
            phone_number="",
            referrer=referrer_lead,
        )

    return True, referrer_lead


def confirm_referral(lead: StudentLead) -> tuple[StudentLead | None, bool]:
    """
    Taklif qilingan do'st birinchi yutug'ini rasmiylashtirdi — endi u
    taklif qiluvchining hisobiga qo'shiladi. Har referrals_per_spin() ta
    tasdiqlangan do'st uchun +1 spin. Tranzaksiya ichida chaqiriladi.

    Returns (referrer_lead, spin_awarded). Taklif bo'lmasa (None, False).
    """
    if not lead.referrer_id or lead.referral_confirmed_at:
        return None, False

    referrer = StudentLead.objects.select_for_update().get(pk=lead.referrer_id)
    lead.referral_confirmed_at = timezone.now()
    lead.save(update_fields=['referral_confirmed_at'])

    spin_awarded = confirmed_referrals(referrer).count() % referrals_per_spin() == 0
    if spin_awarded:
        grant_spins(
            referrer, 1, SpinGrant.Reason.REFERRAL,
            note=f"Do'st: {lead.first_name} (tg {lead.telegram_id})",
        )

    return referrer, spin_awarded


def daily_bonus_available(lead: StudentLead | None, site=None) -> bool:
    site = site or SiteSettings.load()
    if not site.daily_bonus_enabled or site.campaign_state() != 'active':
        return False
    return not lead or lead.last_daily_bonus != timezone.localdate()


def claim_daily_bonus(telegram_id: int, user_data: dict) -> bool:
    """
    Kunlik +1 aylantirish. Kuniga bir marta (Toshkent vaqti bo'yicha).
    Returns True — bonus berildi, False — bugun allaqachon olingan yoki o'chiq.
    """
    today = timezone.localdate()
    with transaction.atomic():
        lead, _ = StudentLead.objects.select_for_update().get_or_create(
            telegram_id=telegram_id,
            defaults={
                'first_name': user_data.get('first_name') or "Foydalanuvchi",
                'last_name': user_data.get('last_name') or '',
                'phone_number': "",
            },
        )
        if lead.is_banned or not daily_bonus_available(lead):
            return False
        lead.last_daily_bonus = today
        lead.save(update_fields=['last_daily_bonus'])
        grant_spins(lead, 1, SpinGrant.Reason.DAILY_BONUS, note=str(today))
    return True


def mask_name(first_name, last_name='') -> str:
    """Ochiq ro'yxatlar uchun: "Sevara Y." — familiya faqat bosh harf."""
    first = (first_name or '').strip()
    last = (last_name or '').strip()
    if last:
        return f"{first} {last[0].upper()}."
    return first or "Ishtirokchi"


def top_referrers(limit=10):
    """Eng ko'p (tasdiqlangan) do'st taklif qilganlar reytingi."""
    rows = (
        StudentLead.objects
        .annotate(invited=Count('referrals', filter=Q(referrals__referral_confirmed_at__isnull=False)))
        .filter(invited__gt=0)
        .order_by('-invited', 'created_at')[:limit]
    )
    return [
        {'rank': i, 'display_name': mask_name(lead.first_name, lead.last_name), 'invited': lead.invited}
        for i, lead in enumerate(rows, start=1)
    ]


# O'xshash belgilar (0/O, 1/I/L) chiqarib tashlangan — xodim kodni qo'lda
# kiritganda adashmasligi uchun
PROMO_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
PROMO_LENGTH = 6


def generate_unique_promo_code() -> str:
    """
    TX-XXXXXX ko'rinishidagi noyob promokod (masalan TX-7KQ4MZ).
    31^6 ≈ 887 mln variant — taxmin qilib topish amalda imkonsiz.
    """
    for _ in range(20):
        code = 'TX-' + ''.join(secrets.choice(PROMO_ALPHABET) for _ in range(PROMO_LENGTH))
        if not WinningResult.objects.filter(promo_code=code).exists():
            return code
    raise RuntimeError("Noyob promokod yaratib bo'lmadi")
