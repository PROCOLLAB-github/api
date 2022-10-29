from django_filters import rest_framework as filters
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsProjectLeaderOrReadOnly, IsStaffOrReadOnly
from projects.filters import ProjectFilter
from projects.helpers import VERBOSE_STEPS
from projects.models import Project, Achievement
from projects.serializers import (
    ProjectDetailSerializer,
    AchievementSerializer,
    ProjectCollaboratorsSerializer,
    ProjectListSerializer,
)


class ProjectList(generics.ListCreateAPIView):
    queryset = Project.objects.get_projects_for_list_view()
    serializer_class = ProjectListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = ProjectFilter


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class ProjectCollaborators(generics.GenericAPIView):
    """
    Project collaborator delete view
    """

    # maybe should get/add collaborators here also? (e.g. retrieve/create, get/post methods)

    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    queryset = Project.objects.all()
    serializer_class = ProjectCollaboratorsSerializer

    def delete(self, request, pk: int):
        m2m_manager = self.get_object().collaborators
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaborators = serializer.validated_data["collaborators"]
        for user in collaborators:
            # note: doesn't raise an error when we try to delete someone who isn't a collaborator
            m2m_manager.remove(user)
        return Response(status=200)


class ProjectSteps(APIView):
    permission_classes = [IsStaffOrReadOnly]

    def get(self, request, format=None):
        """
        Return a tuple of project steps.
        """
        return Response(VERBOSE_STEPS)


class AchievementList(generics.ListCreateAPIView):
    queryset = Achievement.objects.all()
    serializer_class = AchievementSerializer
    permission_classes = [IsProjectLeaderOrReadOnly]


class AchievementDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Achievement.objects.all()
    serializer_class = AchievementSerializer
    permission_classes = [IsProjectLeaderOrReadOnly]
