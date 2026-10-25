"""Анонимное чтение allowlist опубликованных материалов решения."""

from django.http import Http404
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from partner_programs.services.solution_publication import (
    published_solutions,
    public_card,
    public_materials,
)
from partner_programs.solution_api import SolutionAPIView, StrictSerializer
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_team import program_for


class PublishedSolutionQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(allow_blank=True, max_length=200, default="")


class PublishedSolutionAPIView(SolutionAPIView):
    permission_classes = [AllowAny]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def program(self, pk):
        program = program_for(pk)
        if program.solution_storage_mode != "solution":
            raise Http404
        return program


class PublishedSolutionListView(PublishedSolutionAPIView):
    def get(self, request, pk):
        program = self.program(pk)
        query = PublishedSolutionQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        rows = published_solutions(program, data["search"])
        count, limit, offset = rows.count(), data["limit"], data["offset"]
        stop = offset + limit

        def page_url(position):
            params = request.query_params.copy()
            params["limit"], params["offset"] = str(limit), str(position)
            return request.build_absolute_uri(request.path + "?" + params.urlencode())

        return Response(
            dict(
                program_id=program.pk,
                count=count,
                next=page_url(stop) if stop < count else None,
                previous=page_url(max(0, offset - limit)) if offset else None,
                results=[public_card(row) for row in rows[offset:stop]],
            )
        )


class PublishedSolutionDetailView(PublishedSolutionAPIView):
    def get(self, request, pk, solution_id):
        program = self.program(pk)
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        if not 0 < solution_id <= MAX_ID:
            raise Http404
        solution = (
            published_solutions(program, with_answers=True).filter(pk=solution_id).first()
        )
        if solution is None:
            raise Http404
        solution.program = program
        return Response(public_materials(solution))
