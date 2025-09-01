from rest_framework.permissions import BasePermission

from partner_programs.models import PartnerProgram


class IsProjectLeader(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.project.leader == request.user


class IsExpertOrManagerOfProgram(BasePermission):
    """
    Доступ разрешён только экспертам и менеджерам конкретной программы.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        program_id = view.kwargs.get("pk")
        if not program_id:
            return False

        try:
            program = PartnerProgram.objects.get(pk=program_id)
        except PartnerProgram.DoesNotExist:
            return False

        if program.is_manager(request.user):
            return True

        return program.experts.filter(user=request.user).exists()
