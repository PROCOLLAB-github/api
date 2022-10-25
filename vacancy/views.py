from rest_framework import generics, permissions, mixins, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from vacancy.models import Vacancy, VacancyResponse
from vacancy.serializers import VacancySerializer, VacancyResponseSerializer


class VacancyList(generics.ListCreateAPIView):
    queryset = Vacancy.objects.all()
    serializer_class = VacancySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.all()
    serializer_class = VacancySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def put(self, request, *args, **kwargs):
        if not request.data.get("is_active"):
            vacancy = self.get_object()
            vacancy_requests = VacancyResponse.objects.filter(
                vacancy=vacancy, is_approve=None
            )
            for vacancy_request in vacancy_requests:
                vacancy_request.is_approve = False
                vacancy_request.save()
        return self.update(request, *args, **kwargs)


class VacancyResponseList(mixins.ListModelMixin, mixins.CreateModelMixin, GenericAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = VacancyResponseSerializer

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        return VacancyResponse.objects.filter(vacancy_id=self.kwargs["pk"])

    def post(self, request, *args, **kwargs):
        if request.data.get("is_approve"):
            return Response(status=status.HTTP_400_BAD_REQUEST)
        if self.request.user != request.data.get("user"):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            request.data["vacancy"] = str(self.kwargs["pk"])
        except AttributeError:
            pass
        return self.create(request, *args, **kwargs)


class VacancyResponseDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = VacancyResponse.objects.all()
    serializer_class = VacancyResponseSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def put(self, request, *args, **kwargs):
        if request.data.get("is_approve"):
            # Add user to project collaborators
            vacancy_request = self.get_object()
            vacancy = vacancy_request.vacancy
            if vacancy.project.leader == self.request.user:
                vacancy.project.collaborators.add(vacancy_request.user)
                vacancy.project.save()
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        return self.update(request, *args, **kwargs)
