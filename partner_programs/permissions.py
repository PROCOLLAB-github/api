from rest_framework.permissions import BasePermission


class IsProjectLeader(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.project.leader == request.user
