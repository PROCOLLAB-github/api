import django.db.models
from django.http import JsonResponse
from django.shortcuts import render
from rest_framework.views import APIView

from users.models import CustomUser
from .utils import MailSender
from .models import MailingSchema


class SendMailView(APIView):
    def post(self, request):
        users = request.POST["users[]"]
        schema_id = request.POST["schemas"]
        subject = request.POST["subject"]
        mail_schema = MailingSchema.objects.get(pk=schema_id)
        context = {}
        for key in mail_schema.schema:
            key_in_post = "field-" + key
            if key_in_post in request.POST:
                context[key] = request.POST[key_in_post]
        users_to_send = CustomUser.objects.filter(pk__in=users)
        MailSender.send(users_to_send, subject, mail_schema.template.path)
        return JsonResponse({"detail": "ok"})


class MailingSchemaView(APIView):
    def get(self, request):
        return MailingTemplateRender().render_template(request)


def template_fields(request, schema_id):
    return JsonResponse(
        dict(MailingTemplateRender().get_template_fields_context(schema_id))
    )


class MailingTemplateRender:
    template_name = "templates/mailing/mail_schema.html"

    def render_template(
        self,
        request,
        schema_id: int | None = None,
        picked_users: list[CustomUser] | django.db.models.QuerySet = None,
        unpicked_users: list[CustomUser] | django.db.models.QuerySet = None,
    ):
        return render(
            request,
            self.template_name,
            self._get_context(
                schema_id,
                picked_users,
                unpicked_users,
            ),
        )

    def _get_context(
        self,
        schema_id: int | None = None,
        picked_users: list[CustomUser] | django.db.models.QuerySet = None,
        unpicked_users: list[CustomUser] | django.db.models.QuerySet = None,
    ):
        context = self._get_schema_context(schema_id)
        context += self._get_users_context(picked_users, unpicked_users)
        context += self.get_template_fields_context(schema_id)
        return dict(context)

    def _get_schema_context(self, schema_id: int | None = None):
        all_schemas = MailingSchema.objects.all()
        context = {"schemas": []}

        for schema in all_schemas:
            selected = schema.id == schema_id
            context["schemas"].append(
                {"id": schema.id, "title": str(schema), "selected": selected}
            )
        return list(context.items())

    def _get_users_context(
        self,
        picked_users: list[CustomUser] | django.db.models.QuerySet = None,
        unpicked_users: list[CustomUser] | django.db.models.QuerySet = None,
    ):
        if picked_users is None:
            picked_users = []
        if unpicked_users is None:
            unpicked_users = []
        context = {"picked_users": [], "unpicked_users": []}
        for user in picked_users:
            context["picked_users"].append(self._user_to_dict_for_template(user, True))
        for user in unpicked_users:
            context["unpicked_users"].append(self._user_to_dict_for_template(user, False))
        return list(context.items())

    def _user_to_dict_for_template(self, user, picked):
        return {
            "id": user.id,
            "picked": picked,
            "title": str(user),
        }

    def get_template_fields_context(self, schema_id):
        context = {"template_fields": []}
        if schema_id is None:
            return list(context.items())
        schema = MailingSchema.objects.get(pk=schema_id).schema

        for key in schema:
            context["template_fields"].append(
                {
                    "key": key,
                    "title": schema[key]["title"],
                    "default": schema[key].get("default", ""),
                }
            )
        return list(context.items())
