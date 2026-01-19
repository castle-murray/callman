from django.urls import path
from .views import (
        login_view,
        logout,
        user_info,
        skills_list,
        location_profiles,
        )
from api.view_files import (
        event_views,
        request_views,
        sms_views,
        worker_views,
        call_times,
        owner_dashboard,
        )


urlpatterns = [
    path('login/', login_view),
    path('user/info/', user_info),
    path('logout/', logout),
    path('events/list', event_views.list_events),
    path('create-event/', event_views.create_event),
    path('skills/', skills_list),
    path('event/<slug:slug>', event_views.event_details),
    path('call-time/<slug:slug>/add-call-time/', call_times.add_call_time),
    path('upcoming-event-count/', event_views.upcoming_event_count),
    path('pending-count/', request_views.pending_count),
    path('declined-count/', request_views.declined_count),
    path('sms-count/', sms_views.sms_count),
    path('workers/', worker_views.list_workers),
    path('call-times/<slug:slug>/add-labor/', call_times.add_labor_to_call),
    path('call-times/<slug:slug>/requests/', request_views.call_time_list),
    path('labor/<slug:slug>/status/', call_times.labor_requirement_status),
    path('request/<token>/action/', request_views.request_action),
    path('request/<slug:slug>/fill-list/', request_views.fill_labor_request_list),
    path('request/<slug:slug>/worker/', request_views.request_worker),
    path('labor/<slug:slug>/edit/', call_times.edit_labor_requirement),
    path('labor/<slug:slug>/delete/', call_times.delete_labor_requirement),
    path('location-profiles/', location_profiles),
    path('company/settings/', owner_dashboard.owner_dashboard),
]
