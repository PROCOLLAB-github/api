from django.contrib.auth import get_user_model

from rest_framework import generics, status
from rest_framework.response import Response


from rate_projects.serializers import ProjectScoreCreateSerializer
from users.permissions import IsExpert

User = get_user_model()


class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpert]

    def create(self, request, *args, **kwargs):
        try:
            data = self.request.data
            data["user"] = self.request.user.id

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                serializer.save()
                self.perform_create(serializer)
                return Response({"success": True}, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
