from django.core.management.base import BaseCommand
from django.utils import timezone
from callManager.models import TemporaryScanner

class Command(BaseCommand):
    help = 'Deletes expired TemporaryScanner instances and their associated users'

    def handle(self, *args, **kwargs):
        expired_scanners = TemporaryScanner.objects.filter(expires_at__lte=timezone.now())
        count = expired_scanners.count()
        for scanner in expired_scanners:
            user = scanner.user
            scanner.delete()
            user.delete()
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} expired scanners and users.'))
