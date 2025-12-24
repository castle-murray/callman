# callManager/management/commands/merge_data_with_slugs.py

import os
from django.core.management.base import BaseCommand
from django.core import serializers
from django.db import transaction
from django.apps import apps
from django.contrib.auth.models import User

SLUG_MODELS = [
    'callManager.Company',
    'callManager.Event',
    'callManager.CallTime',
    'callManager.LaborRequirement',
    'callManager.Worker',
]

class Command(BaseCommand):
    help = "Safe merge: deduplicate User (username) and slug models, robust printing"

    def add_arguments(self, parser):
        parser.add_argument('fixture_file', type=str)

    @transaction.atomic
    def handle(self, *args, **options):
        fixture_file = options['fixture_file']
        verbosity = options['verbosity']

        if not os.path.exists(fixture_file):
            self.stderr.write(self.style.ERROR(f"File {fixture_file} not found"))
            return

        self.stdout.write("Starting final safe merge...")

        with open(fixture_file, 'r') as f:
            deserialized_objects = list(serializers.deserialize('json', f))

        skipped = 0
        inserted = 0

        slug_model_classes = {apps.get_model(label) for label in SLUG_MODELS}

        # First pass: replace duplicates
        for obj in deserialized_objects:
            instance = obj.object
            model_label = f"{instance._meta.app_label}.{instance._meta.model_name}"

            if model_label == 'auth.user' and getattr(instance, 'username', None):
                try:
                    existing = User.objects.get(username=instance.username)
                    obj.object = existing
                    skipped += 1
                    if verbosity >= 2:
                        self.stdout.write(self.style.WARNING(f"Replaced duplicate User: {instance.username}"))
                except User.DoesNotExist:
                    pass

            elif instance.__class__ in slug_model_classes and getattr(instance, 'slug', None):
                try:
                    existing = instance.__class__.objects.get(slug=instance.slug)
                    obj.object = existing
                    skipped += 1
                    if verbosity >= 2:
                        self.stdout.write(self.style.WARNING(f"Replaced existing {instance._meta.verbose_name} (slug={instance.slug})"))
                except instance.__class__.DoesNotExist:
                    pass

        # Second pass: save everything
        for obj in deserialized_objects:
            try:
                obj.save()
                inserted += 1
                if verbosity >= 2:
                    # Safe printing: avoid triggering __str__ that accesses related objects
                    model_name = obj.object._meta.verbose_name
                    pk = obj.object.pk or "(new)"
                    safe_repr = f"{model_name} [pk={pk}]"
                    self.stdout.write(self.style.SUCCESS(f"Saved: {safe_repr}"))
            except Exception as e:
                # This should be extremely rare now
                model_name = obj.object._meta.verbose_name
                self.stderr.write(self.style.ERROR(f"Failed to save {model_name} [pk={obj.object.pk}]: {e}"))
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"MERGE SUCCESSFUL! {inserted} objects inserted, {skipped} duplicates skipped/replaced."
            )
        )
