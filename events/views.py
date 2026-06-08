from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsStaffOrReadOnly
from events.constants import VERBOSE_EVENT_TYPE
from events.filters import EventFilter
from events.models import Event
from events.serializers import (
    EventsListSerializer,
    EventDetailSerializer,
    RegisteredUserListSerializer,
)


class EventsList(generics.ListCreateAPIView):
    queryset = Event.objects.all()
    serializer_class = EventsListSerializer
    permission_classes = [IsStaffOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = EventFilter


class EventDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Event.objects.all()
    serializer_class = EventDetailSerializer
    permission_classes = [IsStaffOrReadOnly]


class EventRegisteredUsersList(generics.ListAPIView):
    serializer_class = RegisteredUserListSerializer
    permission_classes = [IsStaffOrReadOnly]

    def get_queryset(self):
        event = get_object_or_404(Event, pk=self.kwargs["id"])
        return event.registered_users.all()


class EventTypes(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Return a list of tuples [(id, type), ..] of event types.
        """
        return Response(VERBOSE_EVENT_TYPE)
