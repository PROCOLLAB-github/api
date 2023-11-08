from django.contrib.auth import get_user_model

from news.models import News
from partner_programs.models import PartnerProgram
from projects.models import Project

User = get_user_model()


class NewsQuerysetMixin:
    """
    Mixin for getting queryset for news
    """

    def get_queryset_for_project(self):
        project_id = self.kwargs.get("project_pk")
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            # TODO: raise http 404 here
            return News.objects.none()
        return News.objects.get_news(obj=project)

    def get_queryset_for_program(self):
        partner_program_id = self.kwargs.get("partnerprogram_pk")
        try:
            program = PartnerProgram.objects.get(pk=partner_program_id)
        except PartnerProgram.DoesNotExist:
            # TODO: raise http 404 here
            return News.objects.none()
        return News.objects.get_news(obj=program)

    def get_queryset_for_user(self):
        user_id = self.kwargs.get("user_pk")
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            # TODO: raise http 404 here
            return News.objects.none()
        return News.objects.get_news(obj=user)

    def get_queryset(self):
        if self.kwargs.get("project_pk") is not None:
            # it's a project
            return self.get_queryset_for_project()
        elif self.kwargs.get("partnerprogram_pk") is not None:
            # it's a partner program
            return self.get_queryset_for_program()
        elif self.kwargs.get("user_pk") is not None:
            # it's a user news
            return self.get_queryset_for_user()
        else:
            return News.objects.none()
