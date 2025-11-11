from django.urls import path
from callManager import views
from callManager.view_files.dashboards import admin_dashboard, manager_dashboard, steward_dashboard, owner_dashboard
from callManager.view_files import (
        invites,
        reports,
        event_views,
        registrations,
        locations,
        loginviews,
        time_tracking,
        labor_requests,
        call_times,
        workers,
        )

urlpatterns = [
    path('', views.index, name='index'),
    path('confirm/<uuid:token>', views.confirm_assignment, name='confirm_assignment'),

    #event views
    path('events/<slug:slug>', event_views.event_detail, name='event_detail'),
    path('events/<slug:slug>/edit', event_views.edit_event, name='edit_event'),
    path('events/create', event_views.create_event, name='create_event'),
    path('events/<slug:slug>/delete', event_views.delete_event, name='delete_event'),
    path('events/<slug:slug>/cancel', event_views.cancel_event, name='cancel_event'),
    path('events/<slug:slug>/add-call', event_views.add_call_time, name='add_call_time'),
    path('events/<slug:slug>/assign-steward', event_views.assign_steward, name='assign_steward'),
    path('events/<slug:slug>/generate-signin-qr', event_views.generate_signin_qr, name='generate_signin_qr'),
    path('events/search', event_views.search_events, name='search_events'),
    path('callman-admin/search-events', event_views.admin_search_events, name='admin_search_events'),

    #workers and skills
    path('labor-type/create', workers.create_labor_type, name='create_labor_type'),
    path('skills', workers.view_skills, name='view_skills'),
    path('workers', workers.view_workers, name='view_workers'),
    path('<int:worker_id>/increment-nocallnoshow', workers.increment_nocallnoshow, name='increment_nocallnoshow'),
    path('<int:worker_id>/decrement-nocallnoshow', workers.decrement_nocallnoshow, name='decrement_nocallnoshow'),
    path('worker/edit/<int:worker_id>', workers.edit_worker, name='edit_worker'),
    path('contacts/import', workers.import_workers, name='import_workers'),
    path('htmx-add-worker/<slug:labor_requirement_slug>', workers.htmx_add_worker, name='htmx_add_worker'),
    path('workers/search', workers.search_workers, name='search_workers'),
    path('worker/delete/<slug:slug>', workers.delete_worker, name='delete_worker'),
    path('info/add/<slug:slug>', workers.worker_self_add, name='worker_self_add'),
    path('info/add/qr/<slug:slug>', workers.worker_self_add_qr, name='worker_self_add_qr'),
    path('worker/history/<slug:slug>', workers.worker_history, name='worker_history'),

    #call_times
    path('call/<slug:slug>/add-labor', call_times.add_labor_to_call, name='add_labor_to_call'),
    path('call/<slug:slug>/edit', call_times.edit_call_time, name='edit_call_time'),
    path('call/<slug:slug>/delete', call_times.delete_call_time, name='delete_call_time'),
    path('call/<slug:slug>/copy', call_times.copy_call_time, name='copy_call_time'),
    path('call/<slug:slug>/requests', call_times.call_time_request_list, name='call_time_request_list'),
    path('call/<slug:slug>/track', call_times.call_time_tracking, name='call_time_tracking'),
    path('call/<slug:slug>/track/edit', call_times.call_time_tracking_edit, name='call_time_tracking_edit'),
    path('call/time-sheet-row/<int:id>', call_times.htmx_time_sheet_row, name='htmx_time_sheet_row'),
    path('call/confirm-time-change/<uuid:token>', call_times.confirm_time_change, name='confirm_time_change'),
    path('call/confirmations/<slug:slug>', call_times.call_time_confirmations, name='call_time_confirmations'),

    #labor requests
    path('labor/<slug:slug>/requests', labor_requests.labor_request_list, name='labor_request_list'),
    path('labor/<slug:slug>/fill-list', labor_requests.fill_labor_request_list, name='fill_labor_request_list'),
    path('labor/<slug:slug>/worker/<int:worker_id>', labor_requests.worker_fill_partial, name='worker_fill_partial'),
    path('labor/requests/declined', labor_requests.declined_requests, name='declined_requests'),
    path('labor/requests/pending', labor_requests.pending_requests, name='pending_requests'),
    path('labor/<slug:slug>/edit', labor_requests.edit_labor_requirement, name='edit_labor_requirement'),
    path('labor/<slug:slug>/delete', labor_requests.delete_labor_requirement, name='delete_labor_requirement'),
    path('labor-request/<int:request_id>/<str:action>', labor_requests.labor_request_action, name='labor_request_action'),

    #time tracking
    path('call/<slug:slug>/track/meal_edit', time_tracking.call_time_tracking_meal_edit, name='call_time_tracking_meal_edit'),
    path('call/<slug:slug>/track/meal_display', time_tracking.call_time_tracking_meal_display, name='call_time_tracking_meal_display'),
    path('call/<slug:slug>/track/display', time_tracking.call_time_tracking_display, name='call_time_tracking_display'),
    path('event/<slug:slug>/qr-code/<slug:worker_slug>', time_tracking.display_qr_code, name='display_qr_code'),
    path('event/<slug:slug>/manager-qr-code/<slug:worker_slug>', time_tracking.manager_display_qr_code, name='manager_display_qr_code'),
    path('event/<slug:slug>/scan-qr', time_tracking.scan_qr_code, name='scan_qr_code'),
    path('clock-in/<uuid:token>', time_tracking.worker_clock_in_out, name='worker_clock_in_out'),
    path('signin-station/<uuid:token>', time_tracking.signin_station, name='signin_station'),
    path('call/delete_meal_break/<int:meal_break_id>', time_tracking.delete_meal_break, name='delete_meal_break'),

    #dashboards
    path('dashboard', manager_dashboard.manager_dashboard, name='manager_dashboard'),
    path('callman-admin', admin_dashboard.admin_dashboard, name='admin_dashboard'),
    path('steward', steward_dashboard.steward_dashboard, name='steward_dashboard'),
    path('owner', owner_dashboard.owner_dashboard, name='owner_dashboard'),

    #SMS
    path('sms/reply', views.sms_webhook, name='sms_webhook'),
    path('event/<slug:slug>/send-clock-in', views.send_clock_in_link, name='send_clock_in_link'),

    #confirmations
    path('event/<slug:slug>/confirm/<event_token>', views.confirm_event_requests, name='confirm_event_requests'),

    #registrations
    path('user/register/success', registrations.registration_success, name='registration_success'),
    path('manager/register/<uuid:token>', registrations.register_manager, name='register_manager'),
    path('owner/register/<uuid:token>', registrations.register_owner, name='register_owner'),
    path('steward/register/<uuid:token>', registrations.register_steward, name='register_steward'),
    path('user/register', registrations.user_registration, name='user_registration'),

    #reports
    path('call/<slug:slug>/report', reports.call_time_report, name='call_time_report'),
    path('sms-usage', reports.sms_usage_report, name='sms_usage_report'),
    path('callman-admin/sms-usage', reports.admin_sms_usage_report, name='admin_sms_usage_report'),
    path('event-workers-report', reports.event_workers_report, name='event_workers_report'),
    
    #invites
    path('steward/invite', invites.steward_invite, name='steward_invite'),
    path('steward/invite/search', invites.steward_invite_search, name='steward_invite_search'),

    #notifications
    path('get-messages', views.get_messages, name='get_messages'),

    #location profiles
    path('location-profiles', locations.location_profiles, name='location_profiles'),
    path('location-profiles/create', locations.create_location_profile, name='create_location_profile'),
    path('location-profiles/edit/<int:pk>', locations.edit_location_profile, name='edit_location_profile'),
    path('location-profiles/delete/<int:pk>', locations.delete_location_profile, name='delete_location_profile'),
    
    #login/profile
    path('login', loginviews.CustomLoginView.as_view(), name='login'),
    path('user-profile', loginviews.user_profile, name='user_profile'),
    path('auto-login/<uuid:token>', loginviews.auto_login, name='auto_login'),
    path('reset-password/<uuid:token>', loginviews.reset_password, name='reset_password'),
    path('forgot-password', loginviews.forgot_password, name='forgot_password'),

]
