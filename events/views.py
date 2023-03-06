from django_filters import rest_framework as filters
from rest_framework import generics

from core.permissions import IsStaffOrReadOnly
from events.filters import EventFilter
from events.models import Event
from events.serializers import EventsListSerializer, EventDetailSerializer


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
