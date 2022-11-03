from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsVacancyResponseOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or obj.user == request.user:
            return True
        return False
