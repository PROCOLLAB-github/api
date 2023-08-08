from rest_framework.permissions import BasePermission


class IsProjectChatMember(BasePermission):
    def has_object_permission(self, request, view, obj):
        collaborators = [
            collaborator.user for collaborator in obj.project.collaborator_set.all()
        ]
        if request.user in collaborators:
            return True
        return False
