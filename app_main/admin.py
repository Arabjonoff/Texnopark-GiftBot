import csv
from django.contrib import admin
from django.http import HttpResponse
from app_main.models import (
    BotMessage, Broadcast, Prize, PrizeCategory, RequiredChannel, SiteSettings, SpinGrant, StudentLead,
    WinningResult,
)

def export_as_csv(modeladmin, request, queryset):
    """Generic CSV export admin action"""
    meta = modeladmin.model._meta
    field_names = [field.name for field in meta.fields]

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
    writer = csv.writer(response)

    writer.writerow(field_names)
    for obj in queryset:
        writer.writerow([getattr(obj, field) for field in field_names])

    return response

export_as_csv.short_description = "Tanlangan ma'lumotlarni CSV/Excel faylga yuklash"


@admin.register(PrizeCategory)
class PrizeCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'icon', 'sort_order', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('title', 'description')
    list_editable = ('sort_order', 'is_active')
    actions = [export_as_csv]


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'category', 'rarity', 'probability', 'valid_days', 'pickup_address', 'is_active')
    list_filter = ('rarity', 'is_active', 'category')
    search_fields = ('title', 'pickup_address')
    list_editable = ('probability', 'valid_days', 'is_active')
    actions = [export_as_csv]


@admin.register(StudentLead)
class StudentLeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'telegram_id', 'first_name', 'last_name', 'phone_number', 'extra_spins',
                    'is_banned', 'bot_blocked', 'created_at')
    list_filter = ('is_banned', 'bot_blocked', 'created_at')
    # Qo'shimcha spinlar faqat tizim orqali (tarixi bilan) o'zgaradi — qo'lda tahrirlanmaydi
    readonly_fields = ('extra_spins', 'referral_confirmed_at', 'last_daily_bonus')
    search_fields = ('first_name', 'last_name', 'phone_number', 'telegram_id')
    actions = [export_as_csv]


@admin.register(WinningResult)
class WinningResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'promo_code', 'get_lead_name', 'get_prize_title', 'status', 'expires_at', 'created_at', 'used_at')
    list_filter = ('status', 'created_at', 'prize__rarity')
    search_fields = ('promo_code', 'lead__first_name', 'lead__last_name', 'lead__phone_number', 'prize__title')
    actions = [export_as_csv]

    def get_lead_name(self, obj):
        return f"{obj.lead.first_name} {obj.lead.last_name or ''}".strip()
    get_lead_name.short_description = "O'quvchi"

    def get_prize_title(self, obj):
        return f"{obj.prize.title} [{obj.prize.rarity}]"
    get_prize_title.short_description = "Sovg'a"


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ('id', 'audience', 'status', 'total', 'sent_count', 'failed_count', 'created_by', 'created_at')
    list_filter = ('status', 'audience')
    search_fields = ('text',)
    readonly_fields = ('total', 'sent_count', 'failed_count', 'created_by', 'created_at', 'finished_at')


@admin.register(BotMessage)
class BotMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'kind', 'chat_id', 'status', 'attempts', 'error', 'created_at', 'sent_at')
    list_filter = ('kind', 'status')
    search_fields = ('chat_id', 'text')


@admin.register(RequiredChannel)
class RequiredChannelAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'chat_id', 'invite_link', 'sort_order', 'is_active')
    list_editable = ('sort_order', 'is_active')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'subscription_required', 'campaign_start', 'campaign_end',
                    'daily_bonus_enabled', 'referrals_per_spin', 'updated_at')

    def has_add_permission(self, request):
        # Yagona qator — SiteSettings.load() yaratadi
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SpinGrant)
class SpinGrantAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'amount', 'reason', 'note', 'created_by', 'created_at')
    list_filter = ('reason',)
    search_fields = ('lead__telegram_id', 'lead__first_name', 'note')

    # Tarix — faqat o'qish uchun
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
