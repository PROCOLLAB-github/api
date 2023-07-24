from news.models import News
from partner_programs.models import PartnerProgram
from projects.models import Project


class NewsQuerysetMixin:
    """
    Mixin for getting queryset for news
    """

    def get_queryset_for_project(self):
        try:
            project = Project.objects.get(pk=self.kwargs.get("project_pk"))
        except Project.DoesNotExist:
            return News.objects.none()
        return News.objects.get_news(obj=project)

    def get_queryset_for_program(self):
        try:
            program = PartnerProgram.objects.get(pk=self.kwargs.get("partnerprogram_pk"))
        except PartnerProgram.DoesNotExist:
            return News.objects.none()
        return News.objects.get_news(obj=program)

    def get_queryset(self):
        if self.kwargs.get("project_pk") is not None:
            # it's a project
            return self.get_queryset_for_project()
        elif self.kwargs.get("partnerprogram_pk") is not None:
            # it's a partner program
            return self.get_queryset_for_program()
        else:
            return News.objects.none()
