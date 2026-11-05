from django.apps import AppConfig
from django.db.models.signals import pre_save


def refuse_a_slug_that_holds_a_signing_key(sender, instance, update_fields=None, **kwargs):
    """A package is signed with a key derived from the workspace slug, so a slug that another workspace has signed with
    cannot be given to this one: it would inherit that identity. The backstop for every save (the API answers it with a
    400); the admin form shows the same refusal as a field error through Workspace.clean."""
    if update_fields is not None and "slug" not in update_fields:
        return
    if not instance._state.adding:
        was = sender.objects.filter(pk=instance.pk).values_list("slug", flat=True).first()
        if was == instance.slug:
            return
    from rest_framework.exceptions import ValidationError

    from . import signing

    if signing.slug_reuses_a_registered_key(instance.slug, instance.pk):
        raise ValidationError({"slug": (
            "Another workspace has signed packages under this slug, and its signing key would carry over. "
            "Choose a slug no workspace has used.")})


class AttestationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attestations"
    verbose_name = "Evidence packages"

    def ready(self):
        pre_save.connect(refuse_a_slug_that_holds_a_signing_key, sender="accounts.Workspace",
                         dispatch_uid="attestations.workspace_slug_signing_key")
