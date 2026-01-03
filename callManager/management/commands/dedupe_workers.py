from django.core.management.base import BaseCommand
from callManager.models import Worker, Company

class Command(BaseCommand):
    help = 'Deduplicate workers by phone number,name and company'
    
    def handle(self, *args, **kwargs):
        for company in Company.objects.all():
            # Get all workers for this company, ordered by ID to keep the oldest
            workers = Worker.objects.filter(company=company).order_by('id')
            processed_combinations = set()
            
            for worker in workers:
                # Skip workers with missing critical data
                if not worker.phone_number or not worker.name:
                    self.stdout.write(f"Skipping worker {worker.id} - missing name or phone")
                    continue
                
                # Create a unique key for this combination
                combo_key = (worker.phone_number, worker.name, company.id)
                
                # Skip if we've already processed this combination
                if combo_key in processed_combinations:
                    continue
                    
                processed_combinations.add(combo_key)
                
                self.stdout.write(f"Checking {worker.name} - {worker.phone_number}")
                
                # Find all duplicates (including the current worker)
                all_duplicates = Worker.objects.filter(
                    phone_number=worker.phone_number, 
                    name=worker.name, 
                    company=company
                ).order_by('id')
                
                if all_duplicates.count() > 1:
                    # Keep the first (oldest) worker
                    keeper = all_duplicates.first()
                    duplicates_to_remove = all_duplicates.exclude(pk=keeper.pk)
                    
                    for duplicate in duplicates_to_remove:
                        # Move all labor requests to the keeper
                        duplicate.labor_requests.update(worker=keeper)
                        self.stdout.write(f"  Merged {duplicate.name} (ID: {duplicate.id}) into {keeper.name} (ID: {keeper.id})")
                        duplicate.delete()
