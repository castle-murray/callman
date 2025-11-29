from callManager.models import LaborRequest, Notifications
from django.shortcuts import get_object_or_404
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def notify(labor_request_id, response, message):

    labor_request = get_object_or_404(LaborRequest, id=labor_request_id)
    labor_requirement = labor_request.labor_requirement
    call_time = labor_requirement.call_time
    event = call_time.event
    company = event.company

    notification = Notifications.objects.create(
        company=company,
        event=event,
        call_time=call_time,
        labor_requirement=labor_requirement,
        labor_request=labor_request,
        message=message,
        response=response,
        read=False,
    )
    notification.save()
    push_notification(company)
    return

def push_notification(company):
    # Send via WebSocket to all users in the company
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"company_{company.id}_notifications",
        {
            "type": "send.notification",
            "notification": {
                "type": "send_notification",  # maps to send_notification() in consumer
            }
        }
    )
    return
