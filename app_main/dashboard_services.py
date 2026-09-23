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
    """Rasmiylashtirilgan yutuqlar — PENDING (forma yuborilmagan) spinlarsiz."""
    return WinningResult.objects.exclude(status=WinningResult.Status.PENDING)


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
