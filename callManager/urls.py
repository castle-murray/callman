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
    path('labor-type/list/', views.labor_type_list, name='labor_type_list'),
    path('worker/add/', views.add_worker, name='add_worker'),
    path('worker/list/', views.worker_list, name='worker_list'),
    path('worker/edit/<int:worker_id>/', views.edit_worker, name='edit_worker'),
    path('labor/<int:labor_requirement_id>/fill/', views.fill_labor_call, name='fill_labor_call'),
    path('labor/<int:labor_requirement_id>/list/', views.fill_labor_call_list, name='fill_labor_call_list'),
    path('sms/reply/', views.sms_reply_webhook, name='sms_reply_webhook'),
    path('worker/import/', views.import_workers, name='import_workers'),
]
