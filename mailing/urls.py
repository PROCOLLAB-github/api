from django.urls import path

from mailing.views import TemplateFieldsView, MailingSchemaView, SendMailView

app_name = "mailing"

urlpatterns = [
    path("mail", MailingSchemaView.as_view()),
    path(
        "template_fileds/<int:schema_id>/",
        TemplateFieldsView.as_view(),
        name="template_fields",
    ),
    path("send_email", SendMailView.as_view(), name="send_mail"),
]
