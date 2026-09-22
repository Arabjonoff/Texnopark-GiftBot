"""
Admin Dashboard view'lari.
Barcha sahifalar staff huquqiga ega foydalanuvchi uchun ochiq.
Biznes mantiq dashboard_services.py da, bu yerda faqat so'rov/javob.
"""
import csv
import json

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from app_main.dashboard_services import (
    get_daily_chart,
    get_dashboard_stats,
    get_prize_performance,
    get_probability_summary,
    get_rarity_breakdown,
    get_recent_winnings,
)
from app_main.forms import PrizeCategoryForm, PrizeForm
from app_main.models import Prize, PrizeCategory, StudentLead, WinningResult


def _is_staff(user):
    return user.is_authenticated and user.is_staff


# Barcha dashboard sahifalari uchun yagona himoya dekoratori
staff_required = user_passes_test(_is_staff, login_url='/dashboard/login/')


# ---------------------------------------------------------------- Auth

def dashboard_login(request):
    if _is_staff(request.user):
        return redirect('dashboard-index')

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)

        if user is None:
            messages.error(request, "Login yoki parol noto'g'ri.")
        elif not user.is_staff:
            messages.error(request, "Bu hisobda admin paneliga kirish huquqi yo'q.")
        else:
            login(request, user)
            next_url = request.GET.get('next') or '/dashboard/'
            # Ochiq redirect (open redirect) xavfini oldini olish
            if not next_url.startswith('/'):
                next_url = '/dashboard/'
            return redirect(next_url)

    return render(request, 'dashboard/login.html')


def dashboard_logout(request):
    logout(request)
    return redirect('dashboard-login')


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
    }
    return render(request, 'dashboard/index.html', context)


# ---------------------------------------------------------------- Sovg'alar

@staff_required
def prize_list(request):
    prizes = Prize.objects.select_related('category').annotate(
        win_count=Count('winnings'),
    ).order_by('-probability', 'title')

    context = {
        'active_page': 'prizes',
        'prizes': prizes,
        'prob': get_probability_summary(),
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

def _filter_leads(request, queryset):
    """Lead ro'yxati va CSV eksport uchun umumiy filtr."""
    query = (request.GET.get('q') or '').strip()

    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone_number__icontains=query)
            | Q(telegram_id__icontains=query)
        )
    return queryset, query


@staff_required
def lead_list(request):
    base = StudentLead.objects.annotate(
        win_count=Count('winnings', distinct=True),
        invited_count=Count('referrals', distinct=True),
    ).select_related('referrer')

    leads, query = _filter_leads(request, base)

    paginator = Paginator(leads.order_by('-created_at'), 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_page': 'leads',
        'page_obj': page,
        'total_found': paginator.count,
        'q': query,
    }
    return render(request, 'dashboard/leads.html', context)


@staff_required
def lead_export(request):
    """Filtrlangan o'quvchilar ro'yxatini CSV (Excel) faylga eksport qiladi."""
    base = StudentLead.objects.select_related('referrer').prefetch_related('winnings__prize')
    leads, _q = _filter_leads(request, base)

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

    for lead in leads.order_by('-created_at'):
        prizes = ', '.join(w.prize.title for w in lead.winnings.all())
        writer.writerow([
            lead.id,
            lead.telegram_id,
            lead.first_name,
            lead.last_name or '',
            lead.phone_number,
            lead.referrals.count(),
            lead.extra_spins,
            prizes,
            timezone.localtime(lead.created_at).strftime('%Y-%m-%d %H:%M'),
        ])

    return response


# ---------------------------------------------------------------- Yutuqlar

def _filter_winnings(request, queryset):
    query = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()

    if query:
        queryset = queryset.filter(
            Q(promo_code__icontains=query)
            | Q(lead__first_name__icontains=query)
            | Q(lead__last_name__icontains=query)
            | Q(lead__phone_number__icontains=query)
        )
    if status_filter in WinningResult.Status.values:
        queryset = queryset.filter(status=status_filter)

    return queryset, query, status_filter


@staff_required
def winning_list(request):
    base = WinningResult.objects.select_related('lead', 'prize')
    winnings, query, status_filter = _filter_winnings(request, base)

    paginator = Paginator(winnings.order_by('-created_at'), 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_page': 'winnings',
        'page_obj': page,
        'total_found': paginator.count,
        'q': query,
        'status': status_filter,
        'status_choices': WinningResult.Status.choices,
    }
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
    elif winning.is_expired():
        winning.status = WinningResult.Status.EXPIRED
        winning.save(update_fields=['status'])
        messages.error(request, winning.promo_code + " muddati o'tgan, aktivlashtirib bo'lmaydi.")
    else:
        winning.status = WinningResult.Status.USED
        winning.used_at = timezone.now()
        winning.save(update_fields=['status', 'used_at'])
        messages.success(
            request,
            "{0} — «{1}» {2}ga berildi.".format(
                winning.promo_code, winning.prize.title, winning.lead.first_name
            )
        )

    return redirect('dashboard-winnings')


@staff_required
def winning_export(request):
    base = WinningResult.objects.select_related('lead', 'prize')
    winnings, _q, _s = _filter_winnings(request, base)

    stamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d_%H-%M')
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename=yutuqlar_{0}.csv'.format(stamp)

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Promokod', "O'quvchi", 'Telefon',
        "Sovg'a", 'Rarity', 'Holati', 'Yaratilgan', 'Muddati', 'Ishlatilgan',
    ])

    for w in winnings.order_by('-created_at'):
        writer.writerow([
            w.promo_code,
            "{0} {1}".format(w.lead.first_name, w.lead.last_name or '').strip(),
            w.lead.phone_number,
            w.prize.title,
            w.prize.rarity,
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
