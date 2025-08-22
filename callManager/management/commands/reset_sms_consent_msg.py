from django.core.management.base import BaseCommand
from callManager.models import Worker

class Command(BaseCommand):
    help = 'Sets sent_consent_msg to False for workers with sms_consent=False and stop_sms=False'

    def handle(self, *args, **kwargs):
        updated = Worker.objects.filter(sms_consent=False, stop_sms=False, sent_consent_msg=True).update(sent_consent_msg=False)
        self.stdout.write(self.style.SUCCESS(f'Updated {updated} workers with sent_consent_msg=False'))
