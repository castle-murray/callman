# callManager/management/commands/merge_data_with_slugs.py

import os
from django.core.management.base import BaseCommand
from django.core import serializers
from django.db import transaction
from django.apps import apps
from django.contrib.auth.models import User

# Models we deduplicate
DEDUPLICATED_MODELS = {
    'auth.user': ('username', User),
    'callManager.Company': ('slug', 'callManager.Company'),
    'callManager.Event': ('slug', 'callManager.Event'),
    'callManager.CallTime': ('slug', 'callManager.CallTime'),
    'callManager.LaborRequirement': ('slug', 'callManager.LaborRequirement'),
    'callManager.Worker': ('slug', 'callManager.Worker'),
}

class Command(BaseCommand):
    help = "Final merge: deduplicates and remaps FKs to existing objects"

    def add_arguments(self, parser):
        parser.add_argument('fixture_file', type=str)

    def handle(self, *args, **options):
        fixture_file = options['fixture_file']
        verbosity = options['verbosity']

        if not os.path.exists(fixture_file):
            self.stderr.write(self.style.ERROR(f"File {fixture_file} not found"))
            return

        self.stdout.write("Starting FINAL merge with FK remapping...")

        with open(fixture_file, 'r') as f:
            deserialized_objects = list(serializers.deserialize('json', f))

        skipped = 0
        inserted = 0
        mapping = {}  # (model_label, old_pk) -> new_instance

        # First pass: deduplicate and build mapping
        for obj in deserialized_objects:
            instance = obj.object
            model_label = f"{instance._meta.app_label}.{instance._meta.model_name}"

            if model_label in DEDUPLICATED_MODELS:
                unique_field, _ = DEDUPLICATED_MODELS[model_label]
                unique_value = getattr(instance, unique_field)

                if unique_value:
                    try:
                        ModelClass = apps.get_model(model_label)
                        existing = ModelClass.objects.get(**{unique_field: unique_value})
                        old_pk = instance.pk
                        obj.object = existing  # replace
                        mapping[(model_label, old_pk)] = existing
                        skipped += 1
                        if verbosity >= 2:
                            self.stdout.write(self.style.WARNING(f"Replaced {model_label} {unique_value} (old pk {old_pk} → {existing.pk})"))
                    except ModelClass.DoesNotExist:
                        pass  # new, keep original

        # Second pass: remap FKs in all objects using the mapping
        for obj in deserialized_objects:
            instance = obj.object
            for field in instance._meta.get_fields():
                if field.is_relation and field.related_model:
                    related_model_label = f"{field.related_model._meta.app_label}.{field.related_model._meta.model_name}"
                    if related_model_label in DEDUPLICATED_MODELS:
                        old_fk_value = getattr(instance, field.name + '_id', None)
                        if old_fk_value is not None:
                            key = (related_model_label, old_fk_value)
                            if key in mapping:
                                new_instance = mapping[key]
                                setattr(instance, field.name, new_instance)
                                if verbosity >= 2:
                                    self.stdout.write(f"Remapped {field.name} {old_fk_value} → {new_instance.pk}")

        # Third pass: save everything with individual protection
        for obj in deserialized_objects:
            try:
                with transaction.atomic():
                    obj.save()
                inserted += 1
                if verbosity >= 1:
                    self.stdout.write(self.style.SUCCESS(f"Saved: {obj.object._meta.verbose_name} [pk={obj.object.pk or 'new'}]"))
            except Exception as e:
                safe_name = obj.object._meta.verbose_name
                self.stderr.write(self.style.ERROR(f"Failed to save {safe_name}: {e}"))
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"FINAL MERGE COMPLETE! {inserted} objects saved, {skipped} skipped/failed."
            )
        )
