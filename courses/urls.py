from django.urls import path

from .views import (
    CourseDetailAPIView,
    CourseListAPIView,
    CourseStructureAPIView,
    CourseTaskAnswerSubmitAPIView,
    CourseVisitAPIView,
    LessonDetailAPIView,
)

app_name = "courses"

urlpatterns = [
    path("", CourseListAPIView.as_view(), name="course-list"),
    path("<int:pk>/", CourseDetailAPIView.as_view(), name="course-detail"),
    path(
        "<int:pk>/structure/",
        CourseStructureAPIView.as_view(),
        name="course-structure",
    ),
    path(
        "<int:pk>/visit/",
        CourseVisitAPIView.as_view(),
        name="course-visit",
    ),
    path("lessons/<int:pk>/", LessonDetailAPIView.as_view(), name="lesson-detail"),
    path(
        "tasks/<int:pk>/answer/",
        CourseTaskAnswerSubmitAPIView.as_view(),
        name="task-answer-submit",
    ),
]
