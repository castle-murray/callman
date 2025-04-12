from django.core.management.base import BaseCommand
from callManager.models import TimeEntry, Manager
from datetime import datetime
import pytz

class Command(BaseCommand):
    help = 'Convert UTC TimeEntry times to local naive times'

    def handle(self, *args, **kwargs):
        for time_entry in TimeEntry.objects.all():
            manager = time_entry.labor_request.manager
            if not manager:
                self.stdout.write(self.style.WARNING(f"No manager for TimeEntry {time_entry.id}, skipping"))
                continue
            manager_tz = pytz.timezone(manager.timezone)
            if time_entry.start_time:
                local_start = time_entry.start_time.astimezone(manager_tz)
                time_entry.start_time = local_start.replace(tzinfo=None)
            if time_entry.end_time:
                local_end = time_entry.end_time.astimezone(manager_tz)
                time_entry.end_time = local_end.replace(tzinfo=None)
            time_entry.save()
            self.stdout.write(self.style.SUCCESS(f"Converted TimeEntry {time_entry.id} for {time_entry.worker.name}"))
