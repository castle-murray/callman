from django.urls import path
from callManager import views

urlpatterns = [
    path('confirm/<uuid:token>/', views.confirm_assignment, name='confirm_assignment'),
    path('event/create/', views.create_event, name='create_event'),
    path('event/<slug:slug>/', views.event_detail, name='event_detail'),
    path('labor-type/create/', views.create_labor_type, name='create_labor_type'),
    path('event/<slug:slug>/add-call/', views.add_call_time, name='add_call_time'),
    path('call/<slug:slug>/add-labor/', views.add_labor_to_call, name='add_labor_to_call'),
    path('call/<slug:slug>/edit/', views.edit_call_time, name='edit_call_time'),
    path('call/<slug:slug>/delete/', views.delete_call_time, name='delete_call_time'),
    path('', views.manager_dashboard, name='manager_dashboard'),
    path('skills/', views.view_skills, name='view_skills'),
    path('workers/', views.view_workers, name='view_workers'),
    path('worker/edit/<int:worker_id>/', views.edit_worker, name='edit_worker'),
    path('labor/<slug:slug>/fill/', views.fill_labor_call, name='fill_labor_call'),
    path('labor/<slug:slug>/list/', views.fill_labor_call_list, name='fill_labor_call_list'),
    path('sms/reply/', views.sms_webhook, name='sms_webhook'),
    path('worker/import/', views.import_workers, name='import_workers'),
    path('event/<slug:slug>/confirm/<uuid:event_token>/', views.confirm_event_requests, name='confirm_event_requests'),
    path('worker/register/', views.worker_registration, name='worker_registration'),
    path('worker/register/success/', views.registration_success, name='registration_success'),
    path('labor/<slug:slug>/requests/', views.labor_request_list, name='labor_request_list'),
    path('calltime/<slug:slug>/requests/', views.call_time_request_list, name='call_time_request_list'),
    path('labor/<slug:slug>/fill-list/', views.fill_labor_request_list, name='fill_labor_request_list'),
    path('labor/requests/declined', views.declined_requests, name='declined_requests'),
    path('labor/<slug:slug>/edit/', views.edit_labor_requirement, name='edit_labor_requirement'),
    path('labor/<slug:slug>/delete/', views.delete_labor_requirement, name='delete_labor_requirement'),

]
