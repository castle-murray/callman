from django.urls import path
from callManager import views

urlpatterns = [
    path('confirm/<uuid:token>/', views.confirm_assignment, name='confirm_assignment'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'), 
    path('labor-type/create/', views.create_labor_type, name='create_labor_type'),
    path('event/create/', views.create_event, name='create_event'),
    path('event/<int:event_id>/add-call/', views.add_call_time, name='add_call_time'),
    path('call/<int:call_time_id>/add-labor/', views.add_labor_to_call, name='add_labor_to_call'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'),
    path('', views.manager_dashboard, name='manager_dashboard'),
    path('skills/', views.view_skills, name='view_skills'),
   # path('worker/add/', views.add_worker, name='add_worker'),
    path('workers/', views.view_workers, name='view_workers'),
    path('worker/edit/<int:worker_id>/', views.edit_worker, name='edit_worker'),
    path('labor/<int:labor_requirement_id>/fill/', views.fill_labor_call, name='fill_labor_call'),
    path('labor/<int:labor_requirement_id>/list/', views.fill_labor_call_list, name='fill_labor_call_list'),
    path('sms/reply/', views.sms_reply_webhook, name='sms_reply_webhook'),
    path('worker/import/', views.import_workers, name='import_workers'),
    path('event/<int:event_id>/confirm/<uuid:event_token>/', views.confirm_event_requests, name='confirm_event_requests'),
    path('worker/register/', views.worker_registration, name='worker_registration'),
    path('worker/register/success/', views.registration_success, name='registration_success'),
    path('labor/<int:labor_requirement_id>/requests/', views.labor_request_list, name='labor_request_list'),
    path('calltime/<int:call_time_id>/requests/', views.call_time_request_list, name='call_time_request_list'),
    path('labor/<int:labor_requirement_id>/fill-list/', views.fill_labor_request_list, name='fill_labor_request_list'),
    path('labor/requests/declined', views.declined_requests, name='declined_requests'),
]
