from django.core.management.base import BaseCommand
from callManager.models import Worker

class Command(BaseCommand): 
    help = 'Format phone numbers for workers'

    def handle(self, *args, **kwargs):
        for worker in Worker.objects.all():
            worker.save()
