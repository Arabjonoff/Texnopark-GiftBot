from django.shortcuts import redirect, render


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
