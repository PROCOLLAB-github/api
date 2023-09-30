from django.urls import path

from mailing.views import some_task, MailingSchemaView, template_fields, SendMailView

app_name = "mailing"

urlpatterns = [
    path("", some_task),
    path("mail", MailingSchemaView.as_view()),
    path("template_fileds/<int:schema_id>/", template_fields, name="template_fields"),
    path("send_email", SendMailView.as_view(), name="send_mail"),
]
