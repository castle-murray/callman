from django.contrib import admin
from django.urls import path
from django.urls.conf import include
from django.contrib.auth import views as auth_views
from callManager import views

handler404 = 'callManager.views.custom_404'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='callManager/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('admin/', admin.site.urls),
    path("__reload__/", include("django_browser_reload.urls")),
    path("", include("callManager.urls")),
]
