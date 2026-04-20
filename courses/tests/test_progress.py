from django.test import TestCase

from courses.services.progress import (
    build_progress_snapshot_from_percent,
    percent_from_total_percent,
)


class ProgressServiceTests(TestCase):
    def test_percent_from_total_percent_uses_average_and_truncates(self):
        percent = percent_from_total_percent(200, 9)

        self.assertEqual(percent, 22)

    def test_build_progress_snapshot_from_percent_marks_in_progress(self):
        snapshot = build_progress_snapshot_from_percent(25)

        self.assertEqual(snapshot.percent, 25)
        self.assertEqual(snapshot.status, "in_progress")
