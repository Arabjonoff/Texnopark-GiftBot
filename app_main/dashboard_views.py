"""
Admin Dashboard view'lari.
Barcha sahifalar staff huquqiga ega foydalanuvchi uchun ochiq.
Biznes mantiq dashboard_services.py da, bu yerda faqat so'rov/javob.
"""
import csv
import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import user_passes_test
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from app_main.dashboard_services import (
    cancel_open_winnings,
    get_suspicious_leads,
    reset_unused_spins,
    get_daily_chart,
    get_dashboard_stats,
    get_funnel,
    get_staff_activity,
    get_prize_performance,
    get_probability_summary,
    get_rarity_breakdown,
    get_recent_winnings,
)
from app_main.forms import (
    BroadcastForm,
    PrizeCategoryForm,
    PrizeForm,
    RequiredChannelForm,
    SiteSettingsForm,
)
from app_main.messaging import audience_counts, cancel_broadcast, create_broadcast, pending_counts_by_kind
from app_main.models import (
    Broadcast,
    BotMessage,
    Prize,
    PrizeCategory,
    RequiredChannel,
    SiteSettings,
    StudentLead,
    WinningResult,
)
from app_main.subscription import diagnose_channel


def _is_staff(user):
    return user.is_authenticated and user.is_staff


# Barcha dashboard sahifalari uchun yagona himoya dekoratori
staff_required = user_passes_test(_is_staff, login_url='/dashboard/login/')


# ---------------------------------------------------------------- Auth

def _safe_next(request, param='next', fallback='/dashboard/'):
    """
    Foydalanuvchi bergan manzilga faqat u shu saytga tegishli bo'lsagina
    yo'naltiramiz. "//boshqa-sayt.uz" ham "/" bilan boshlanadi, shuning
    uchun oddiy startswith('/') tekshiruvi yetarli emas.
    """
    url = request.GET.get(param) or request.POST.get(param) or ''
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return fallback


# Parolni brute-force qilishga qarshi: bir IP dan 15 daqiqada 10 urinish
LOGIN_MAX_ATTEMPTS = 10
LOGIN_BLOCK_SECONDS = 15 * 60


def _login_throttle_key(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    return 'dashboard-login-attempts:{0}'.format(ip or 'unknown')


def dashboard_login(request):
    if _is_staff(request.user):
        return redirect('dashboard-index')

    throttle_key = _login_throttle_key(request)
    attempts = cache.get(throttle_key, 0)

    if request.method == 'POST':
        if attempts >= LOGIN_MAX_ATTEMPTS:
            messages.error(
                request,
                "Juda ko'p urinish bo'ldi. 15 daqiqadan keyin qayta urinib ko'ring."
            )
            return render(request, 'dashboard/login.html', status=429)

        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)

        if user is None or not user.is_staff:
            # Urinishlar sonini faqat muvaffaqiyatsiz holatda oshiramiz
            cache.set(throttle_key, attempts + 1, LOGIN_BLOCK_SECONDS)
            if user is not None and not user.is_staff:
                messages.error(request, "Bu hisobda admin paneliga kirish huquqi yo'q.")
            else:
                messages.error(request, "Login yoki parol noto'g'ri.")
        else:
            login(request, user)
            cache.delete(throttle_key)
            return redirect(_safe_next(request))

    return render(request, 'dashboard/login.html')


@require_POST
def dashboard_logout(request):
    """
    Chiqish faqat POST orqali — GET havola bo'lsa, boshqa saytdagi rasm
    yoki havola foydalanuvchini bildirmasdan tizimdan chiqarib yuborishi mumkin.
    """
    logout(request)
    return redirect('dashboard-login')



# ---------------------------------------------------------------- Filtrlar

# Tezkor davr tugmalari: ?period=today|week|month
PERIOD_PRESETS = {
    'today': ("Bugun", 0),
    'week': ("7 kun", 6),
    'month': ("30 kun", 29),
}


def _date_range(request):
    """
    Sana oralig'ini o'qiydi: ?from=YYYY-MM-DD&to=YYYY-MM-DD yoki ?period=week.
    Noto'g'ri sana yozilsa e'tiborsiz qoldiriladi (xato bermaydi).
    """
    period = (request.GET.get('period') or '').strip()
    date_from = parse_date((request.GET.get('from') or '').strip())
    date_to = parse_date((request.GET.get('to') or '').strip())

    if period in PERIOD_PRESETS:
        today = timezone.localdate()
        date_from = today - timedelta(days=PERIOD_PRESETS[period][1])
        date_to = today

    # Foydalanuvchi oralig'ni teskari yozsa, o'rnini almashtiramiz
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    return date_from, date_to, period


def _apply_date_range(queryset, field, date_from, date_to):
    if date_from:
        queryset = queryset.filter(**{field + '__date__gte': date_from})
    if date_to:
        queryset = queryset.filter(**{field + '__date__lte': date_to})
    return queryset


def _date_filter_context(date_from, date_to, period):
    return {
        'date_from': date_from.isoformat() if date_from else '',
        'date_to': date_to.isoformat() if date_to else '',
        'period': period,
        'period_presets': [(key, label) for key, (label, _days) in PERIOD_PRESETS.items()],
    }


def _sort_choice(request, allowed, default):
    value = (request.GET.get('sort') or '').strip()
    return value if value in allowed else default


# ---------------------------------------------------------------- Statistika

@staff_required
def dashboard_index(request):
    context = {
        'active_page': 'index',
        'stats': get_dashboard_stats(),
        'chart': json.dumps(get_daily_chart(14)),
        'rarity_rows': get_rarity_breakdown(),
        'performance': get_prize_performance(),
        'recent': get_recent_winnings(10),
        'prob': get_probability_summary(),
        'funnel': get_funnel(),
        'staff_activity': get_staff_activity(),
        'site': SiteSettings.load(),
    }
    return render(request, 'dashboard/index.html', context)


# ---------------------------------------------------------------- Sovg'alar

PRIZE_SORTS = {
    'prob': ('-probability', 'title'),
    'prob_asc': ('probability', 'title'),
    'wins': ('-win_count', 'title'),
    'new': ('-id',),
    'title': ('title',),
}

PRIZE_SORT_LABELS = [
    ('prob', "Ehtimollik (katta → kichik)"),
    ('prob_asc', "Ehtimollik (kichik → katta)"),
    ('wins', "Ko'p chiqqani"),
    ('new', "Yangi qo'shilgani"),
    ('title', "Nomi bo'yicha"),
]


@staff_required
def prize_list(request):
    query = (request.GET.get('q') or '').strip()
    rarity = (request.GET.get('rarity') or '').strip()
    category = (request.GET.get('category') or '').strip()
    state = (request.GET.get('state') or '').strip()
    sort = _sort_choice(request, PRIZE_SORTS, 'prob')

    prizes = Prize.objects.select_related('category').annotate(win_count=Count('winnings'))

    if query:
        prizes = prizes.filter(
            Q(title__icontains=query) | Q(pickup_address__icontains=query)
        )
    if rarity in Prize.Rarity.values:
        prizes = prizes.filter(rarity=rarity)
    if category == 'none':
        prizes = prizes.filter(category__isnull=True)
    elif category.isdigit():
        prizes = prizes.filter(category_id=int(category))
    if state == 'active':
        prizes = prizes.filter(is_active=True)
    elif state == 'off':
        prizes = prizes.filter(is_active=False)

    prizes = prizes.order_by(*PRIZE_SORTS[sort])

    context = {
        'active_page': 'prizes',
        'prizes': prizes,
        'total_found': prizes.count(),
        'prob': get_probability_summary(),
        'q': query,
        'rarity': rarity,
        'category': category,
        'state': state,
        'sort': sort,
        'sort_labels': PRIZE_SORT_LABELS,
        'rarity_choices': Prize.Rarity.choices,
        'categories': PrizeCategory.objects.order_by('sort_order', 'title'),
        'has_filters': bool(query or rarity or category or state),
    }
    return render(request, 'dashboard/prizes.html', context)


@staff_required
def prize_create(request):
    if request.method == 'POST':
        form = PrizeForm(request.POST, request.FILES)
        if form.is_valid():
            prize = form.save()
            messages.success(request, "Sovg'a qo'shildi: " + prize.title)
            return redirect('dashboard-prizes')
        messages.error(request, "Formada xatolik bor, maydonlarni tekshiring.")
    else:
        form = PrizeForm()

    return render(request, 'dashboard/prize_form.html', {
        'active_page': 'prizes',
        'form': form,
        'is_edit': False,
    })


@staff_required
def prize_edit(request, pk):
    prize = get_object_or_404(Prize, pk=pk)

    if request.method == 'POST':
        form = PrizeForm(request.POST, request.FILES, instance=prize)
        if form.is_valid():
            form.save()
            messages.success(request, "Yangilandi: " + prize.title)
            return redirect('dashboard-prizes')
        messages.error(request, "Formada xatolik bor, maydonlarni tekshiring.")
    else:
        form = PrizeForm(instance=prize)

    return render(request, 'dashboard/prize_form.html', {
        'active_page': 'prizes',
        'form': form,
        'prize': prize,
        'is_edit': True,
    })


@staff_required
@require_POST
def prize_delete(request, pk):
    prize = get_object_or_404(Prize, pk=pk)

    # PROTECT tufayli yutuqqa bog'langan sovg'ani o'chirib bo'lmaydi
    win_count = prize.winnings.count()
    if win_count:
        messages.error(
            request,
            "O'chirilmadi: bu sovg'aga bog'langan {0} ta yutuq bor. "
            "O'chirish o'rniga uni «Aktiv emas» holatiga o'tkazing.".format(win_count)
        )
        return redirect('dashboard-prizes')

    title = prize.title
    prize.delete()
    messages.success(request, "O'chirildi: " + title)
    return redirect('dashboard-prizes')


@staff_required
@require_POST
def prize_toggle(request, pk):
    """Ro'yxat sahifasidan bir bosishda aktiv/noaktiv qilish."""
    prize = get_object_or_404(Prize, pk=pk)
    prize.is_active = not prize.is_active
    prize.save(update_fields=['is_active'])
    state = "aktiv" if prize.is_active else "noaktiv"
    messages.success(request, prize.title + " — " + state + " holatiga o'tkazildi.")
    return redirect('dashboard-prizes')


# ---------------------------------------------------------------- O'quvchilar

LEAD_SORTS = {
    'new': ('-created_at',),
    'old': ('created_at',),
    'wins': ('-win_count', '-created_at'),
    'invites': ('-invited_count', '-created_at'),
}

LEAD_SORT_LABELS = [
    ('new', "Avval yangilari"),
    ('old', "Avval eskilari"),
    ('wins', "Ko'p yutuq olganlar"),
    ('invites', "Ko'p do'st taklif qilganlar"),
]


def _filter_leads(request, queryset):
    """
    Lead ro'yxati va CSV eksport uchun umumiy filtr.
    Returns (queryset, filters_context).
    """
    query = (request.GET.get('q') or '').strip()
    wins = (request.GET.get('wins') or '').strip()        # yes | no
    source = (request.GET.get('source') or '').strip()    # referral | direct
    inviter = (request.GET.get('inviter') or '').strip()  # yes
    date_from, date_to, period = _date_range(request)
    sort = _sort_choice(request, LEAD_SORTS, 'new')

    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone_number__icontains=query)
            | Q(telegram_id__icontains=query)
        )

    if wins == 'yes':
        queryset = queryset.filter(win_count__gt=0)
    elif wins == 'no':
        queryset = queryset.filter(win_count=0)

    if source == 'referral':
        queryset = queryset.filter(referrer__isnull=False)
    elif source == 'direct':
        queryset = queryset.filter(referrer__isnull=True)

    if inviter == 'yes':
        queryset = queryset.filter(invited_count__gt=0)

    queryset = _apply_date_range(queryset, 'created_at', date_from, date_to)
    queryset = queryset.order_by(*LEAD_SORTS[sort])

    filters = {
        'q': query,
        'wins': wins,
        'source': source,
        'inviter': inviter,
        'sort': sort,
        'sort_labels': LEAD_SORT_LABELS,
        'has_filters': bool(query or wins or source or inviter or date_from or date_to),
    }
    filters.update(_date_filter_context(date_from, date_to, period))
    return queryset, filters


def _lead_base_queryset():
    return StudentLead.objects.select_related('referrer').annotate(
        win_count=Count('winnings', distinct=True),
        invited_count=Count('referrals', distinct=True),
    )


@staff_required
def lead_list(request):
    leads, filters = _filter_leads(request, _lead_base_queryset())

    paginator = Paginator(leads, 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_page': 'leads',
        'page_obj': page,
        'total_found': paginator.count,
    }
    context.update(filters)
    return render(request, 'dashboard/leads.html', context)


@staff_required
def lead_export(request):
    """Filtrlangan o'quvchilar ro'yxatini CSV (Excel) faylga eksport qiladi."""
    # Har bir qator uchun alohida COUNT so'rovi ketmasligi uchun annotate
    base = _lead_base_queryset().prefetch_related('winnings__prize')
    leads, _filters = _filter_leads(request, base)

    stamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d_%H-%M')
    # utf-8-sig — Excel o'zbek harflarini to'g'ri ochishi uchun
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename=oquvchilar_{0}.csv'.format(stamp)

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'ID', 'Telegram ID', 'Ism', 'Familiya', 'Telefon',
        'Taklif qilganlar', "Qo'shimcha spin",
        'Yutuqlari', "Ro'yxatdan o'tgan",
    ])

    for lead in leads:
        prizes = ', '.join(w.prize.title for w in lead.winnings.all())
        writer.writerow([
            lead.id,
            lead.telegram_id,
            lead.first_name,
            lead.last_name or '',
            lead.phone_number,
            lead.invited_count,
            lead.extra_spins,
            prizes,
            timezone.localtime(lead.created_at).strftime('%Y-%m-%d %H:%M'),
        ])

    return response


# ---------------------------------------------------------------- Yutuqlar

WINNING_SORTS = {
    'new': ('-created_at',),
    'old': ('created_at',),
    'expiring': ('expires_at',),
    'given': ('-used_at',),
}

WINNING_SORT_LABELS = [
    ('new', "Avval yangilari"),
    ('old', "Avval eskilari"),
    ('expiring', "Muddati yaqinlari"),
    ('given', "Berilgan vaqti bo'yicha"),
]

# «Muddati tugayapti» filtri necha kunlik oraliqni tekshiradi
EXPIRING_SOON_DAYS = 3


def _filter_winnings(request, queryset):
    """
    Yutuqlar jurnali va CSV eksport uchun umumiy filtr.
    Returns (queryset, filters_context).
    """
    query = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()
    prize_id = (request.GET.get('prize') or '').strip()
    rarity = (request.GET.get('rarity') or '').strip()
    expiring = (request.GET.get('expiring') or '').strip()
    date_from, date_to, period = _date_range(request)
    sort = _sort_choice(request, WINNING_SORTS, 'new')

    if query:
        queryset = queryset.filter(
            Q(promo_code__icontains=query)
            | Q(lead__first_name__icontains=query)
            | Q(lead__last_name__icontains=query)
            | Q(lead__phone_number__icontains=query)
            | Q(lead__telegram_id__icontains=query)
        )
    if status_filter in WinningResult.Status.values:
        queryset = queryset.filter(status=status_filter)
    if prize_id.isdigit():
        queryset = queryset.filter(prize_id=int(prize_id))
    if rarity in Prize.Rarity.values:
        queryset = queryset.filter(prize__rarity=rarity)

    # Yaqin kunlarda muddati tugaydigan, hali olinmagan sovg'alar
    if expiring == 'yes':
        now = timezone.now()
        queryset = queryset.filter(
            status=WinningResult.Status.ACTIVE,
            expires_at__gte=now,
            expires_at__lte=now + timedelta(days=EXPIRING_SOON_DAYS),
        )

    queryset = _apply_date_range(queryset, 'created_at', date_from, date_to)
    queryset = queryset.order_by(*WINNING_SORTS[sort])

    filters = {
        'q': query,
        'status': status_filter,
        'prize': prize_id,
        'rarity': rarity,
        'expiring': expiring,
        'sort': sort,
        'sort_labels': WINNING_SORT_LABELS,
        'expiring_days': EXPIRING_SOON_DAYS,
        'status_choices': WinningResult.Status.choices,
        'rarity_choices': Prize.Rarity.choices,
        'prizes': Prize.objects.order_by('title').values('id', 'title'),
        'has_filters': bool(
            query or status_filter or prize_id or rarity or expiring or date_from or date_to
        ),
    }
    filters.update(_date_filter_context(date_from, date_to, period))
    return queryset, filters


@staff_required
def winning_list(request):
    base = WinningResult.objects.select_related('lead', 'prize', 'used_by')
    winnings, filters = _filter_winnings(request, base)

    paginator = Paginator(winnings, 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_page': 'winnings',
        'page_obj': page,
        'total_found': paginator.count,
    }
    context.update(filters)
    return render(request, 'dashboard/winnings.html', context)


@staff_required
@require_POST
def winning_activate(request, pk):
    """Yutuqni qo'lda USED holatiga o'tkazish (QR ishlamay qolgan holat uchun)."""
    winning = get_object_or_404(
        WinningResult.objects.select_related('lead', 'prize'), pk=pk
    )

    if winning.status == WinningResult.Status.USED:
        messages.error(request, winning.promo_code + " allaqachon ishlatilgan.")
    elif winning.status == WinningResult.Status.CANCELLED:
        messages.error(request, winning.promo_code + " bekor qilingan — sovg'a berilmaydi.")
    elif winning.lead.is_banned:
        messages.error(request, winning.promo_code + " egasi bloklangan — sovg'a berilmaydi.")
    elif winning.status == WinningResult.Status.PENDING:
        messages.error(request, winning.promo_code + " hali rasmiylashtirilmagan (o'quvchi formani yubormagan).")
    elif winning.is_expired():
        winning.status = WinningResult.Status.EXPIRED
        winning.save(update_fields=['status'])
        messages.error(request, winning.promo_code + " muddati o'tgan, aktivlashtirib bo'lmaydi.")
    else:
        winning.mark_used(request.user)
        messages.success(
            request,
            "{0} — «{1}» {2}ga berildi.".format(
                winning.promo_code, winning.prize.title, winning.lead.first_name
            )
        )

    # Xodim qaysi filtr va sahifada turgan bo'lsa, o'sha yerga qaytadi
    return redirect(_safe_next(request, fallback='/dashboard/winnings/'))


@staff_required
def winning_export(request):
    base = WinningResult.objects.select_related('lead', 'prize')
    winnings, _filters = _filter_winnings(request, base)

    stamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d_%H-%M')
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename=yutuqlar_{0}.csv'.format(stamp)

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Promokod', "O'quvchi", 'Telefon',
        "Sovg'a", 'Daraja', 'Holati', 'Yaratilgan', 'Muddati', 'Ishlatilgan',
    ])

    for w in winnings:
        writer.writerow([
            w.promo_code,
            "{0} {1}".format(w.lead.first_name, w.lead.last_name or '').strip(),
            w.lead.phone_number,
            w.prize.title,
            w.prize.get_rarity_display(),
            w.get_status_display(),
            timezone.localtime(w.created_at).strftime('%Y-%m-%d %H:%M'),
            timezone.localtime(w.expires_at).strftime('%Y-%m-%d %H:%M'),
            timezone.localtime(w.used_at).strftime('%Y-%m-%d %H:%M') if w.used_at else '',
        ])

    return response


# ---------------------------------------------------------------- QR Skaner

@staff_required
def dashboard_scan(request):
    return render(request, 'dashboard/scan.html', {'active_page': 'scan'})


# ---------------------------------------------------------------- Kategoriyalar

@staff_required
def category_list(request):
    categories = PrizeCategory.objects.annotate(
        prize_count=Count('prizes', distinct=True),
        active_prize_count=Count('prizes', filter=Q(prizes__is_active=True), distinct=True),
    ).order_by('sort_order', 'title')

    return render(request, 'dashboard/categories.html', {
        'active_page': 'categories',
        'categories': categories,
        'uncategorized_count': Prize.objects.filter(category__isnull=True).count(),
    })


@staff_required
def category_create(request):
    if request.method == 'POST':
        form = PrizeCategoryForm(request.POST, request.FILES)
        if form.is_valid():
            category = form.save()
            messages.success(request, "Kategoriya qo'shildi: " + category.title)
            return redirect('dashboard-categories')
        messages.error(request, "Formada xatolik bor, maydonlarni tekshiring.")
    else:
        # Yangi kategoriya ro'yxat oxiriga tushsin
        last = PrizeCategory.objects.order_by('-sort_order').first()
        form = PrizeCategoryForm(initial={'sort_order': (last.sort_order + 10) if last else 0})

    return render(request, 'dashboard/category_form.html', {
        'active_page': 'categories',
        'form': form,
        'is_edit': False,
    })


@staff_required
def category_edit(request, pk):
    category = get_object_or_404(PrizeCategory, pk=pk)

    if request.method == 'POST':
        form = PrizeCategoryForm(request.POST, request.FILES, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, "Yangilandi: " + category.title)
            return redirect('dashboard-categories')
        messages.error(request, "Formada xatolik bor, maydonlarni tekshiring.")
    else:
        form = PrizeCategoryForm(instance=category)

    return render(request, 'dashboard/category_form.html', {
        'active_page': 'categories',
        'form': form,
        'category': category,
        'is_edit': True,
        'prize_count': category.prizes.count(),
    })


@staff_required
@require_POST
def category_delete(request, pk):
    """
    Kategoriyani o'chirish. Sovg'alar o'chmaydi — ular SET_NULL tufayli
    "kategoriyasiz" holatga o'tadi, shuning uchun ma'lumot yo'qolmaydi.
    """
    category = get_object_or_404(PrizeCategory, pk=pk)
    title = category.title
    freed = category.prizes.count()
    category.delete()

    if freed:
        messages.success(
            request,
            "O'chirildi: {0}. {1} ta sovg'a «kategoriyasiz» holatiga o'tdi.".format(title, freed)
        )
    else:
        messages.success(request, "O'chirildi: " + title)
    return redirect('dashboard-categories')


@staff_required
@require_POST
def category_toggle(request, pk):
    category = get_object_or_404(PrizeCategory, pk=pk)
    category.is_active = not category.is_active
    category.save(update_fields=['is_active'])

    if category.is_active:
        messages.success(request, category.title + " aktiv holatiga o'tkazildi.")
    else:
        count = category.prizes.filter(is_active=True).count()
        messages.success(
            request,
            "{0} o'chirildi — {1} ta sovg'a barabandan olib tashlandi.".format(category.title, count)
        )
    return redirect('dashboard-categories')


# ---------------------------------------------------------------- Ommaviy xabarlar

@staff_required
def broadcast_list(request):
    broadcasts = Broadcast.objects.select_related('created_by')
    paginator = Paginator(broadcasts, 20)
    page = paginator.get_page(request.GET.get('page'))
    pending = pending_counts_by_kind()

    return render(request, 'dashboard/broadcasts.html', {
        'active_page': 'broadcasts',
        'page_obj': page,
        'is_sending': Broadcast.objects.filter(status=Broadcast.Status.SENDING).exists(),
        'pending_total': sum(pending.values()),
        'pending_reminders': pending.get(BotMessage.Kind.REMINDER, 0),
        'blocked_count': StudentLead.objects.filter(bot_blocked=True).count(),
    })


@staff_required
def broadcast_create(request):
    if request.method == 'POST':
        form = BroadcastForm(request.POST)
        if form.is_valid():
            broadcast = create_broadcast(
                form.cleaned_data['text'],
                form.cleaned_data['audience'],
                form.cleaned_data['with_button'],
                created_by=request.user,
            )
            if broadcast.total:
                messages.success(
                    request,
                    "Xabar {0} ta foydalanuvchiga navbatga qo'yildi. Bot uni bosqichma-bosqich "
                    "yuboradi.".format(broadcast.total)
                )
            else:
                messages.error(request, "Tanlangan guruhda birorta ham foydalanuvchi yo'q.")
            return redirect('dashboard-broadcasts')
        messages.error(request, "Formada xatolik bor, maydonlarni tekshiring.")
    else:
        form = BroadcastForm(initial={'audience': Broadcast.Audience.ALL, 'with_button': True})

    counts = audience_counts()
    audience_options = [
        {'value': value, 'label': label, 'count': counts.get(value, 0)}
        for value, label in Broadcast.Audience.choices
    ]
    return render(request, 'dashboard/broadcast_form.html', {
        'active_page': 'broadcasts',
        'form': form,
        'audience_options': audience_options,
        'selected_audience': form['audience'].value() or Broadcast.Audience.ALL,
    })


@staff_required
@require_POST
def broadcast_cancel(request, pk):
    broadcast = get_object_or_404(Broadcast, pk=pk)
    if broadcast.status != Broadcast.Status.SENDING:
        messages.error(request, "Bu xabar allaqachon yakunlangan.")
    else:
        removed = cancel_broadcast(broadcast)
        messages.success(request, "To'xtatildi. {0} ta xabar yuborilmay qoldi.".format(removed))
    return redirect('dashboard-broadcasts')


# ---------------------------------------------------------------- Shubhali foydalanuvchilar

@staff_required
def suspicious_list(request):
    rows, threshold = get_suspicious_leads()
    return render(request, 'dashboard/suspicious.html', {
        'active_page': 'suspicious',
        'rows': rows,
        'threshold': threshold,
        'site': SiteSettings.load(),
    })


@staff_required
@require_POST
def lead_reset_spins(request, pk):
    lead = get_object_or_404(StudentLead, pk=pk)
    removed = reset_unused_spins(lead, request.user)
    if removed:
        messages.success(request, "{0}: {1} ta ishlatilmagan spin olib tashlandi.".format(lead.first_name, removed))
    else:
        messages.success(request, "{0}: ishlatilmagan spin yo'q.".format(lead.first_name))
    return redirect(_safe_next(request, fallback='/dashboard/suspicious/'))


@staff_required
@require_POST
def lead_cancel_winnings(request, pk):
    lead = get_object_or_404(StudentLead, pk=pk)
    count = cancel_open_winnings(lead)
    messages.success(
        request,
        "{0}: {1} ta olib ketilmagan yutuq bekor qilindi.".format(lead.first_name, count)
    )
    return redirect(_safe_next(request, fallback='/dashboard/suspicious/'))


@staff_required
@require_POST
def lead_ban_toggle(request, pk):
    lead = get_object_or_404(StudentLead, pk=pk)
    lead.is_banned = not lead.is_banned
    lead.save(update_fields=['is_banned'])
    if lead.is_banned:
        messages.success(request, "{0} bloklandi — endi aylantira olmaydi va sovg'a ololmaydi.".format(lead.first_name))
    else:
        messages.success(request, "{0} blokdan chiqarildi.".format(lead.first_name))
    return redirect(_safe_next(request, fallback='/dashboard/suspicious/'))


# ---------------------------------------------------------------- Sozlamalar

def _settings_context(request, settings_form, channel_form):
    channels = list(RequiredChannel.objects.all())
    # Bot kanalda admin ekanini tekshirish — Telegram'ga so'rov ketadi,
    # shuning uchun faqat tugma bosilganda (?check=1)
    if request.GET.get('check') == '1':
        for channel in channels:
            channel.check_ok, channel.check_note = diagnose_channel(channel)
    return {
        'active_page': 'settings',
        'form': settings_form,
        'channel_form': channel_form,
        'channels': channels,
        'checked': request.GET.get('check') == '1',
        'site': SiteSettings.load(),
    }


@staff_required
def settings_view(request):
    site, _ = SiteSettings.objects.get_or_create(pk=1)

    if request.method == 'POST':
        form = SiteSettingsForm(request.POST, instance=site)
        if form.is_valid():
            form.save()
            messages.success(request, "Sozlamalar saqlandi.")
            return redirect('dashboard-settings')
        messages.error(request, "Formada xatolik bor, maydonlarni tekshiring.")
    else:
        form = SiteSettingsForm(instance=site)

    return render(request, 'dashboard/settings.html', _settings_context(request, form, RequiredChannelForm()))


@staff_required
@require_POST
def channel_create(request):
    channel_form = RequiredChannelForm(request.POST)
    if channel_form.is_valid():
        last = RequiredChannel.objects.order_by('-sort_order').first()
        channel = channel_form.save(commit=False)
        channel.sort_order = (last.sort_order + 10) if last else 0
        channel.save()
        messages.success(
            request,
            "Kanal qo'shildi: {0}. Botni shu kanalga ADMIN qilib qo'shishni unutmang.".format(channel.title)
        )
        return redirect('dashboard-settings')

    messages.error(request, "Kanal qo'shilmadi — maydonlarni tekshiring.")
    form = SiteSettingsForm(instance=SiteSettings.objects.get_or_create(pk=1)[0])
    return render(request, 'dashboard/settings.html', _settings_context(request, form, channel_form))


@staff_required
@require_POST
def channel_toggle(request, pk):
    channel = get_object_or_404(RequiredChannel, pk=pk)
    channel.is_active = not channel.is_active
    channel.save(update_fields=['is_active'])
    state = "yoqildi" if channel.is_active else "o'chirildi"
    messages.success(request, "{0} — obuna talabi {1}.".format(channel.title, state))
    return redirect('dashboard-settings')


@staff_required
@require_POST
def channel_delete(request, pk):
    channel = get_object_or_404(RequiredChannel, pk=pk)
    title = channel.title
    channel.delete()
    messages.success(request, "O'chirildi: " + title)
    return redirect('dashboard-settings')


# ---------------------------------------------------------------- Hisob

@staff_required
def account_password(request):
    """
    Dashboard ichida parolni o'zgartirish.

    Django'ning PasswordChangeForm'idan foydalanamiz — u eski parolni so'raydi
    va yangi parolni settings.AUTH_PASSWORD_VALIDATORS bo'yicha tekshiradi
    (uzunligi, keng tarqalganligi, faqat raqamdan iboratligi).
    """
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            # Parol o'zgargach sessiya bekor bo'lmasligi uchun
            update_session_auth_hash(request, user)
            messages.success(request, "Parol muvaffaqiyatli o'zgartirildi.")
            return redirect('dashboard-index')
        messages.error(request, "Parolni o'zgartirib bo'lmadi — quyidagi xatoliklarni tuzating.")
    else:
        form = PasswordChangeForm(user=request.user)

    # Django widgetlariga dashboard uslubini beramiz
    for field in form.fields.values():
        field.widget.attrs['class'] = 'form-input'
        field.widget.attrs['autocomplete'] = 'off'

    # Django'ning standart inglizcha maslahatini o'zbekchaga almashtiramiz
    form.fields['new_password1'].help_text = (
        "Kamida 8 ta belgi. Faqat raqamdan iborat bo'lmasin, "
        "keng tarqalgan parollar va login bilan o'xshash bo'lmasin."
    )

    return render(request, 'dashboard/account_password.html', {
        'active_page': 'account',
        'form': form,
    })
