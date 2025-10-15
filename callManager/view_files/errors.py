
from django.shortcuts import render

def custom_404(request, exception):
    return render(request, 'callManager/404.html', status=404)

def custom_500(request):
    return render(request, 'callManager/500.html', status=500)

def custom_403(request, exception):
    return render(request, 'callManager/403.html', status=403)

def custom_400(request, exception):
    return render(request, 'callManager/400.html', status=400)

def index(request):
    return render(request, 'callManager/index.html')

