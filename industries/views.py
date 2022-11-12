from rest_framework import generics, mixins

from core.permissions import IsStaffOrReadOnly
from industries.models import Industry
from industries.serializers import IndustrySerializer


class IndustryList(generics.ListCreateAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    permission_classes = [IsStaffOrReadOnly]


class IndustryDetail(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView,
):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    permission_classes = [IsStaffOrReadOnly]

    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)
