from django.db import models


class Industry(models.Model):
    """
    Industry model

     Attributes:
        name: A CharField name of Industry.
        datetime_created: A DateTimeField indicating date of creation.
    """

    name = models.CharField(max_length=256,
                            null=False)
    datetime_created = models.DateTimeField(verbose_name='Дата создания',
                                            null=False,
                                            auto_now_add=True)

    def __str__(self):
        return f"Industry<{self.id}>"

    class Meta:
        verbose_name = 'Industry'
        verbose_name_plural = 'Industries'
