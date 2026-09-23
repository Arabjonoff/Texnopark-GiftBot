"""
Admin Dashboard uchun biznes mantiq va statistika hisob-kitoblari.
TZ 4-qoidasiga muvofiq views.py faqat so'rov/javob bilan ishlaydi.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from app_main.models import RARITY_COLORS, Prize, StudentLead, WinningResult
from app_main.messaging import expire_winnings
from app_main.services import get_spinnable_prizes


def _sync_expired_winnings():
    """
    Statistika har doim haqiqiy holatni ko'rsatishi uchun. Asosan bot
    jarayonidagi fon sikli yangilab turadi, bu — zaxira.
    """
    return expire_winnings()


def _claimed_winnings():
    """Rasmiylashtirilgan yutuqlar — PENDING (forma yuborilmagan) va bekor qilinganlarsiz."""
    return WinningResult.objects.exclude(
        status__in=[WinningResult.Status.PENDING, WinningResult.Status.CANCELLED]
    )


def get_dashboard_stats():
    """
    Asosiy sahifadagi ko'rsatkichlar to'plamini qaytaradi.
    """
    _sync_expired_winnings()

    now = timezone.now()
    today = timezone.localtime(now).date()
    week_ago = now - timedelta(days=7)

    # Forma to'ldirgan (telefon qoldirgan) o'quvchilar. Botga kirib, hali
    # yutuq rasmiylashtirmaganlar alohida hisoblanadi.
    all_users_qs = StudentLead.objects.all()
    leads_qs = all_users_qs.exclude(phone_number='')
    winnings_qs = _claimed_winnings()

    status_counts = {
        row['status']: row['total']
        for row in winnings_qs.values('status').annotate(total=Count('id'))
    }

    total_winnings = winnings_qs.count()
    used_count = status_counts.get(WinningResult.Status.USED, 0)

    return {
        'total_leads': leads_qs.count(),
        'total_users': all_users_qs.count(),
        'leads_today': leads_qs.filter(created_at__date=today).count(),
        'leads_week': leads_qs.filter(created_at__gte=week_ago).count(),

        'total_winnings': total_winnings,
        'winnings_today': winnings_qs.filter(created_at__date=today).count(),

        'active_count': status_counts.get(WinningResult.Status.ACTIVE, 0),
        'used_count': used_count,
        'expired_count': status_counts.get(WinningResult.Status.EXPIRED, 0),

        # Sovg'alarning necha foizi haqiqatda qo'lga tegdi
        'redemption_rate': round(used_count / total_winnings * 100, 1) if total_winnings else 0.0,

        'total_prizes': Prize.objects.count(),
        'active_prizes': Prize.objects.filter(is_active=True).count(),
        'referral_count': leads_qs.filter(referral_confirmed_at__isnull=False).count(),
        'out_of_stock': Prize.objects.filter(is_active=True, stock=0).count(),
    }


def get_daily_chart(days=14):
    """
    Oxirgi `days` kun uchun kunlik lead va spin sonini qaytaradi.
    Ma'lumot yo'q kunlar ham 0 qiymat bilan to'ldiriladi.
    """
    start = timezone.now() - timedelta(days=days - 1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    def _bucket(queryset):
        rows = (
            queryset.filter(created_at__gte=start)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(total=Count('id'))
        )
        return {row['day']: row['total'] for row in rows}

    leads_map = _bucket(StudentLead.objects.all())
    wins_map = _bucket(_claimed_winnings())

    labels, leads_data, wins_data = [], [], []
    first_day = timezone.localtime(start).date()

    for offset in range(days):
        day = first_day + timedelta(days=offset)
        labels.append(day.strftime('%d.%m'))
        leads_data.append(leads_map.get(day, 0))
        wins_data.append(wins_map.get(day, 0))

    return {'labels': labels, 'leads': leads_data, 'winnings': wins_data}


def get_rarity_breakdown():
    """
    Har bir rarity bo'yicha nechta yutuq chiqqanini va ulushini qaytaradi.
    """
    rows = (
        _claimed_winnings().values('prize__rarity')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    total = sum(row['total'] for row in rows) or 1

    label_map = dict(Prize.Rarity.choices)

    return [
        {
            'rarity': row['prize__rarity'],
            'label': label_map.get(row['prize__rarity'], row['prize__rarity']),
            'count': row['total'],
            'percent': round(row['total'] / total * 100, 1),
            'color': RARITY_COLORS.get(row['prize__rarity'], RARITY_COLORS['COMMON']),
        }
        for row in rows
    ]


def get_prize_performance():
    """
    Har bir sovg'a bo'yicha: sozlangan ehtimollik, real chiqish ulushi va
    nechtasi qo'lga tegkani. Ehtimollik to'g'ri sozlanganini tekshirish uchun.
    """
    prizes = Prize.objects.annotate(
        win_count=Count('winnings'),
        used_count=Count('winnings', filter=Q(winnings__status=WinningResult.Status.USED)),
    ).order_by('-probability', 'title')

    spinnable_ids = set(get_spinnable_prizes().values_list('pk', flat=True))
    total_weight = sum(p.probability for p in prizes if p.pk in spinnable_ids) or 1
    total_wins = sum(p.win_count for p in prizes) or 1

    rows = []
    for prize in prizes:
        rows.append({
            'prize': prize,
            'expected_percent': (
                round(prize.probability / total_weight * 100, 1) if prize.pk in spinnable_ids else 0.0
            ),
            'actual_percent': round(prize.win_count / total_wins * 100, 1),
            'win_count': prize.win_count,
            'used_count': prize.used_count,
        })
    return rows


def get_recent_winnings(limit=10):
    return list(
        _claimed_winnings().select_related('lead', 'prize').order_by('-created_at')[:limit]
    )


def get_probability_summary():
    """
    Barabanda qatnashayotgan sovg'alarning og'irliklari yig'indisi.
    Dashboardda "yig'indi 100% emas" ogohlantirishini ko'rsatish uchun.
    Noaktiv kategoriyadagi va qoldig'i tugagan sovg'alar hisobga olinmaydi.
    """
    weights = list(get_spinnable_prizes().values_list('probability', flat=True))
    return {'total_weight': sum(weights), 'active_count': len(weights)}


def get_funnel():
    """
    Konversiya voronkasi: botga kirdi → aylantirdi → rasmiylashtirdi → sovg'ani oldi.
    Har bosqich — o'sha bosqichga yetgan noyob foydalanuvchilar soni.
    """
    started = StudentLead.objects.count()
    spun = StudentLead.objects.filter(winnings__isnull=False).distinct().count()
    claimed = (
        StudentLead.objects
        .filter(winnings__status__in=[
            WinningResult.Status.ACTIVE, WinningResult.Status.USED, WinningResult.Status.EXPIRED,
        ])
        .distinct().count()
    )
    redeemed = StudentLead.objects.filter(winnings__status=WinningResult.Status.USED).distinct().count()

    steps = [
        ('Botga kirdi', started),
        ('Barabanni aylantirdi', spun),
        ('Yutuqni rasmiylashtirdi', claimed),
        ("Sovg'ani qo'lga oldi", redeemed),
    ]
    base = started or 1
    rows = []
    prev = None
    for label, count in steps:
        rows.append({
            'label': label,
            'count': count,
            'percent': round(count / base * 100, 1),
            # Oldingi bosqichdan necha foizi o'tgan
            'step_percent': round(count / prev * 100, 1) if prev else None,
        })
        prev = count or None
    return rows


def get_staff_activity(limit=10):
    """Qaysi xodim nechta sovg'a bergani — bugun va jami."""
    from django.contrib.auth import get_user_model
    from django.db.models import Max

    today = timezone.localdate()
    return list(
        get_user_model().objects
        .annotate(
            issued_total=Count('issued_winnings'),
            issued_today=Count('issued_winnings', filter=Q(issued_winnings__used_at__date=today)),
            last_issued=Max('issued_winnings__used_at'),
        )
        .filter(issued_total__gt=0)
        .order_by('-issued_total')[:limit]
    )


# ---------------------------------------------------------------- Shubhali foydalanuvchilar

def _shared_phone_groups():
    """Oxirgi 9 raqami bir xil bo'lgan telefonlar: {raqam: [lead_id, ...]} (2+ akkaunt)."""
    from app_main.services import phone_digits

    groups = {}
    for lead_id, phone in StudentLead.objects.exclude(phone_number='').values_list('id', 'phone_number'):
        digits = phone_digits(phone)
        if len(digits) == 9:
            groups.setdefault(digits, []).append(lead_id)
    return {digits: ids for digits, ids in groups.items() if len(ids) > 1}


def get_suspicious_leads():
    """
    Ko'p yutuq olgan, bir telefonni boshqalar bilan bo'lishgan yoki
    bloklangan foydalanuvchilar — firibgarlikni tekshirish uchun.
    """
    from app_main.models import SiteSettings, SpinGrant
    from app_main.services import phone_digits

    site = SiteSettings.load()
    threshold = site.max_wins_total or 3
    shared = _shared_phone_groups()
    shared_ids = {lead_id for ids in shared.values() for lead_id in ids}

    not_cancelled = ~Q(winnings__status=WinningResult.Status.CANCELLED)
    leads = (
        StudentLead.objects
        .annotate(
            win_count=Count('winnings', filter=not_cancelled, distinct=True),
            active_count=Count(
                'winnings',
                filter=Q(winnings__status__in=[WinningResult.Status.ACTIVE, WinningResult.Status.PENDING]),
                distinct=True,
            ),
            confirmed_refs=Count(
                'referrals', filter=Q(referrals__referral_confirmed_at__isnull=False), distinct=True
            ),
        )
        .filter(Q(win_count__gte=threshold) | Q(pk__in=shared_ids) | Q(is_banned=True))
        .order_by('-win_count', '-extra_spins')
    )

    reason_labels = dict(SpinGrant.Reason.choices)
    rows = []
    for lead in leads:
        grants = {}
        for reason, amount in lead.spin_grants.values_list('reason', 'amount'):
            grants[reason] = grants.get(reason, 0) + amount
        # Qonuniy manbadan kelmagan spinlar — referal va kunlik bonusdan tashqari
        unexplained = lead.extra_spins - grants.get('REFERRAL', 0) - grants.get('DAILY_BONUS', 0)

        flags = []
        if lead.win_count >= threshold:
            flags.append("{0} ta yutuq".format(lead.win_count))
        digits = phone_digits(lead.phone_number)
        twins = [i for i in shared.get(digits, []) if i != lead.pk]
        if twins:
            flags.append("telefon {0} ta akkauntda".format(len(twins) + 1))
        if unexplained > 0:
            flags.append("{0} ta manbasiz spin".format(unexplained))

        rows.append({
            'lead': lead,
            'flags': flags,
            'grants': [(reason_labels.get(r, r), a) for r, a in grants.items() if a],
            'twin_ids': twins,
        })
    return rows, threshold


def reset_unused_spins(lead, staff_user):
    """Ishlatilmagan qo'shimcha spinlarni olib tashlaydi (tarixga yoziladi)."""
    from django.db import transaction
    from app_main.models import SpinGrant
    from app_main.services import grant_spins

    with transaction.atomic():
        lead = StudentLead.objects.select_for_update().get(pk=lead.pk)
        # Hozirgacha aylantirilganlarga yetadigan darajada qoldiramiz — ortig'i olinadi
        target = max(0, lead.winnings.count() - 1)
        return -grant_spins(
            lead, target - lead.extra_spins, SpinGrant.Reason.STAFF,
            note="Ishlatilmagan spinlar olib tashlandi (shubhali faollik)", created_by=staff_user,
        )


def cancel_open_winnings(lead):
    """
    Olib ketilmagan (ACTIVE/PENDING) yutuqlarni bekor qiladi. Qoldiq kuzatiladigan
    sovg'alar omborga qaytariladi — ular hech kimga berilmagan.
    """
    from django.db import transaction
    from django.db.models import F

    with transaction.atomic():
        open_qs = lead.winnings.select_for_update().filter(
            status__in=[WinningResult.Status.ACTIVE, WinningResult.Status.PENDING]
        )
        winnings = list(open_qs)
        for w in winnings:
            Prize.objects.filter(pk=w.prize_id, stock__isnull=False).update(stock=F('stock') + 1)
        WinningResult.objects.filter(pk__in=[w.pk for w in winnings]).update(
            status=WinningResult.Status.CANCELLED
        )
    return len(winnings)
