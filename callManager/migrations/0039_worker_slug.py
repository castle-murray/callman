from django.db import migrations, models
import string
import random
def generate_unique_slugs(apps, schema_editor):
    Worker = apps.get_model('callManager', 'Worker')
    for worker in Worker.objects.all():
        while True:
            slug = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            if not Worker.objects.filter(slug=slug).exists():
                worker.slug = slug
                worker.save()
                break
class Migration(migrations.Migration):
    dependencies = [
        ('callManager', '0038_clockintoken_qr_sent'),
    ]
    operations = [
        migrations.AddField(
            model_name='Worker',
            name='slug',
            field=models.CharField(max_length=10, unique=True, editable=False, null=True),
        ),
        migrations.RunPython(generate_unique_slugs, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='Worker',
            name='slug',
            field=models.CharField(max_length=10, unique=True, editable=False),
        ),
    ]
