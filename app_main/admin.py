import csv
from django.contrib import admin
from django.http import HttpResponse
from app_main.models import Prize, PrizeCategory, StudentLead, WinningResult

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
    list_display = ('id', 'telegram_id', 'first_name', 'last_name', 'phone_number', 'created_at')
    list_filter = ('created_at',)
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
