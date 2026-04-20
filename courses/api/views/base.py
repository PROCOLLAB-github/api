from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView


class AuthenticatedCourseAPIView(APIView):
    permission_classes = [IsAuthenticated]
