from django.db import migrations
import random

def generate_unique_slug(model_class, existing_slugs, length=7):
    while True:
        slug = ''.join([str(random.randint(0, 9)) for _ in range(length)])
        if slug not in existing_slugs:
            return slug

def populate_slugs(apps, schema_editor):
    Event = apps.get_model('callManager', 'Event')
    CallTime = apps.get_model('callManager', 'CallTime')
    LaborRequirement = apps.get_model('callManager', 'LaborRequirement')
    
    for model in [Event, CallTime, LaborRequirement]:
        existing_slugs = set(model.objects.exclude(slug__isnull=True).values_list('slug', flat=True))
        for obj in model.objects.filter(slug__isnull=True):
            obj.slug = generate_unique_slug(model, existing_slugs)
            existing_slugs.add(obj.slug)
            obj.save()

class Migration(migrations.Migration):
    dependencies = [('callManager', '0019_calltime_slug_event_slug_laborrequirement_slug')]
    operations = [
        migrations.RunPython(populate_slugs, reverse_code=migrations.RunPython.noop),
    ]
