from django.contrib.auth import get_user_model

from rest_framework import generics, status
from rest_framework.response import Response

from projects.models import Project
from rate_projects.models import Criteria, ProjectScore
from rate_projects.serializers import ProjectScoreCreateSerializer, CriteriaSerializer, ProjectScoreSerializer, \
    ProjectSerializer
from users.permissions import IsExpert

User = get_user_model()

class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpert]

    def create(self, request, *args, **kwargs):
        try:
            data = self.request.data
            data['user'] = self.request.user.id

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                serializer.save()
                self.perform_create(serializer)
                return Response({'success': True}, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class RateProjects(generics.ListAPIView):
    permission_classes = [IsExpert]

    def get(self, request, *args, **kwargs):
        user = self.request.user
        program_id = self.kwargs.get('program_id')


        criterias = Criteria.objects.prefetch_related('partner_program').filter(partner_program_id=program_id)
        scores = (
            ProjectScore.objects
            .prefetch_related('criteria')
            .filter(criteria__in=
                criterias.values_list('id', flat=True),
                user=user
            )
        )
        projects = (
            Project.objects
            .filter(partner_program_profiles__partner_program_id=program_id)
            .distinct()
        )
        criteria_serializer = CriteriaSerializer(data=criterias, many=True)
        scores_serializer = ProjectScoreSerializer(data=[scores], many=True)# idk why it needs [], but don't fix what ain't broken

        criteria_serializer.is_valid()
        scores_serializer.is_valid()

        projects_serializer = ProjectSerializer(
            data=projects,
            context={'data_criterias': criteria_serializer.data, 'data_scores': scores_serializer.data},
            many=True
        )

        projects_serializer.is_valid()

        return Response(projects_serializer.data, status=200)