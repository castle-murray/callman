# callManager/management/commands/generate_dummy_data.py
from django.core.management.base import BaseCommand
from django.db import transaction
from callManager.models import Company, LaborType, Worker
import random

class Command(BaseCommand):
    help = 'Generate 100 dummy workers with random labor types for an existing company'

    def add_arguments(self, parser):
        parser.add_argument(
            '--company_name',
            type=str,
            default='ABC Production Co.',  # Replace with your company name
            help='Name of the existing company to attach data to'
        )

    def handle(self, *args, **kwargs):
        company_name = kwargs['company_name']

        # Get the existing company
        try:
            company = Company.objects.get(name=company_name)
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Company "{company_name}" not found. Please provide a valid company name.'))
            return

        # Define labor types
        labor_type_names = [
            'Loader', 'Pusher', 'Audio', 'Carpenter', 
            'Electrician', 'Down Rigger', 'Up Rigger'
        ]
        labor_types = {}
        for name in labor_type_names:
            labor_type, _ = LaborType.objects.get_or_create(
                company=company,
                name=name
            )
            labor_types[name] = labor_type

        # Generate dummy names
        first_names = ['John', 'Jane', 'Mike', 'Sara', 'Tom', 'Emily', 'Chris', 'Alex', 'Kelly', 'Pat']
        last_names = ['Smith', 'Johnson', 'Brown', 'Davis', 'Wilson', 'Taylor', 'Clark', 'Lewis', 'Moore', 'Hall']

        # Generate 100 workers
        with transaction.atomic():
            for i in range(100):
                name = f"{random.choice(first_names)} {random.choice(last_names)}"
                phone = f"+1{random.randint(200, 999)}{random.randint(100, 999)}{random.randint(1000, 9999)}"
                
                # Ensure unique phone numbers
                while Worker.objects.filter(phone_number=phone).exists():
                    phone = f"+1{random.randint(200, 999)}{random.randint(100, 999)}{random.randint(1000, 9999)}"
                
                worker = Worker.objects.create(
                    name=name,
                    phone_number=phone
                )
                
                # Assign 1 to 3 random labor types
                num_labor_types = random.randint(1, 3)
                assigned_labor_types = random.sample(list(labor_types.values()), num_labor_types)
                worker.labor_types.set(assigned_labor_types)

        self.stdout.write(self.style.SUCCESS(f'Successfully generated 100 workers for {company.name}'))
