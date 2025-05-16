from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

class NonWhitespaceCharacterValidator:
    def validate(self, password, user=None):
        if not any(char.strip() for char in password):
            raise ValidationError(
                _("Your password must contain at least one letter, number, or special character."),
                code='password_no_valid_characters',
            )

    def get_help_text(self):
        return _("Your password must contain at least one letter, number, or special character.")
