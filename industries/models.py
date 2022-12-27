from django.db import models


class Industry(models.Model):
    """
    Industry model

    Industry represents the scope of activity of the project.

     Attributes:
        name: A CharField name of Industry.
        datetime_created: A DateTimeField indicating date of creation.
    """

    name = models.CharField(max_length=256, null=False)
    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )

    def __str__(self):
        return f"Industry<{self.id}> - {self.name}"

    class Meta:
        verbose_name = "Индустрия"
        verbose_name_plural = "Индустрии"
        ordering = ["name"]
