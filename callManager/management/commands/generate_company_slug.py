from django.core.management.base import BaseCommand
from callManager.models import Company

class Command(BaseCommand):
    help = 'Generate a slug for each company'

    def handle(self, *args, **options):
        for company in Company.objects.all():
            company.save()  
