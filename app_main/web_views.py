from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_exempt


# Telegram Web (web.telegram.org) MiniApp'ni iframe ichida ochadi —
# standart SAMEORIGIN sarlavhasi uni bloklab qo'yadi.
@xframe_options_exempt
def index_view(request):
    """
    Telegram MiniApp.
    """
    return render(request, 'miniapp/index.html')


def admin_scan_redirect(request):
    """
    Eski /admin-scan/ manzili himoyalanmagan edi.
    Endi u dashboarddagi himoyalangan skanerga yo'naltiradi.
    """
    return redirect('dashboard-scan')
