"""Private certificate assets, immutable issuance snapshots and delivery journal."""

import uuid

from django.conf import settings
from django.db import models


class ProgramCertificateAsset(models.Model):
    program = models.ForeignKey("PartnerProgram", on_delete=models.CASCADE)
    kind = models.CharField(max_length=12)
    name = models.CharField(max_length=255)
    content = models.BinaryField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class ProgramCertificateConfig(models.Model):
    program = models.OneToOneField(
        "PartnerProgram", on_delete=models.CASCADE, related_name="certificate_config"
    )
    revision = models.PositiveIntegerField(default=1)
    draft = models.JSONField(default=dict)
    last_test_at = models.DateTimeField(null=True)


class ProgramCertificateBatch(models.Model):
    program = models.ForeignKey("PartnerProgram", on_delete=models.CASCADE)
    snapshot = models.JSONField()
    background = models.ForeignKey(
        ProgramCertificateAsset,
        null=True,
        on_delete=models.RESTRICT,
        related_name="background_batches",
    )
    signature = models.ForeignKey(
        ProgramCertificateAsset,
        null=True,
        on_delete=models.RESTRICT,
        related_name="signature_batches",
    )
    active = models.BooleanField(default=True)
    issue_at = models.DateTimeField(db_index=True)
    initialized_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    public_base_url = models.URLField()


class ProgramCertificate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    download_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    program = models.ForeignKey("PartnerProgram", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    batch = models.ForeignKey(ProgramCertificateBatch, on_delete=models.RESTRICT)
    rendered_batch = models.ForeignKey(
        ProgramCertificateBatch,
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="rendered_certificates",
    )
    name = models.CharField(max_length=500)
    email = models.EmailField()
    pdf = models.BinaryField(null=True)
    status = models.CharField(max_length=16, default="pending", db_index=True)
    error = models.CharField(max_length=300, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    queued_at = models.DateTimeField(null=True)
    claimed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["program", "user"], name="unique_program_certificate"
            )
        ]
