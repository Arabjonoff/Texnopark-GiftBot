"""
Admin Dashboard uchun biznes mantiq va statistika hisob-kitoblari.
TZ 4-qoidasiga muvofiq views.py faqat so'rov/javob bilan ishlaydi.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from app_main.models import Prize, StudentLead, WinningResult


def _sync_expired_winnings():
    """
    Muddati o'tgan, lekin hali ACTIVE turgan yutuqlarni EXPIRED ga o'tkazadi.
    Statistika har doim haqiqiy holatni ko'rsatishi uchun kerak.
    """
    now = timezone.now()
    return WinningResult.objects.filter(
        status=WinningResult.Status.ACTIVE,
        expires_at__lt=now
    ).update(status=WinningResult.Status.EXPIRED)


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

    leads_qs = StudentLead.objects.all()
    winnings_qs = _claimed_winnings()

    status_counts = {
        row['status']: row['total']
        for row in winnings_qs.values('status').annotate(total=Count('id'))
    }

    total_winnings = winnings_qs.count()
    used_count = status_counts.get(WinningResult.Status.USED, 0)

    return {
        'total_leads': leads_qs.count(),
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
        'referral_count': leads_qs.filter(referrer__isnull=False).count(),
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

    color_map = {
        'COMMON': '#3b82f6',
        'RARE': '#8b5cf6',
        'EPIC': '#ec4899',
        'LEGENDARY': '#eab308',
    }
    label_map = dict(Prize.Rarity.choices)

    return [
        {
            'rarity': row['prize__rarity'],
            'label': label_map.get(row['prize__rarity'], row['prize__rarity']),
            'count': row['total'],
            'percent': round(row['total'] / total * 100, 1),
            'color': color_map.get(row['prize__rarity'], '#3b82f6'),
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

    total_weight = sum(p.probability for p in prizes if p.is_active) or 1
    total_wins = sum(p.win_count for p in prizes) or 1

    rows = []
    for prize in prizes:
        rows.append({
            'prize': prize,
            'expected_percent': round(prize.probability / total_weight * 100, 1) if prize.is_active else 0.0,
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
    Aktiv sovg'alarning og'irliklari yig'indisi va har birining real ulushi.
    Dashboardda "yig'indi 100% emas" ogohlantirishini ko'rsatish uchun.
    """
    active = Prize.objects.filter(is_active=True)
    total = sum(p.probability for p in active)
    return {'total_weight': total, 'active_count': active.count()}
