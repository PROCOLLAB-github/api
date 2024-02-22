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
        """Returns queryset of news for project"""
        project_pk = self.kwargs.get("project_pk")
        try:
            project = Project.objects.get(pk=project_pk)
        except Project.DoesNotExist:
            # TODO: raise http 404 here
            return News.objects.none()
        return News.objects.get_news(obj=project).exclude(
            content_type__model="project", text__is=None
        )

    def get_queryset_for_program(self):
        """Returns queryset of news for partner program"""
        partnerprogram_pk = self.kwargs.get("partnerprogram_pk")
        try:
            program = PartnerProgram.objects.get(pk=partnerprogram_pk)
        except PartnerProgram.DoesNotExist:
            # TODO: raise http 404 here
            return News.objects.none()
        return News.objects.get_news(obj=program)

    def get_queryset_for_user(self):
        """Returns queryset of news for user"""
        user_pk = self.kwargs.get("user_pk")
        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            # TODO: raise http 404 here
            return News.objects.none()
        return News.objects.get_news(obj=user)

    def get_queryset(self):
        """Chooses what queryset to return - for project, program or user"""
        if self.kwargs.get("project_pk") is not None:
            return self.get_queryset_for_project()
        elif self.kwargs.get("partnerprogram_pk") is not None:
            return self.get_queryset_for_program()
        elif self.kwargs.get("user_pk") is not None:
            return self.get_queryset_for_user()
        else:
            return News.objects.none()
