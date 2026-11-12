"""Конкурентные завершения попытки на настоящем PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from partner_programs.overall_models import ProgramQuizOutcome
from partner_programs.services.quiz_outcomes import (
    QuizOutcomeConflict,
    record_quiz_outcome,
)
from partner_programs.tests.test_overall_results import team, weighted_program


@skipUnlessDBFeature("has_select_for_update")
class QuizOutcomeRaceTests(TransactionTestCase):
    def race(self, calls):
        barrier = Barrier(2)

        def worker(args):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                try:
                    return ("ok", record_quiz_outcome(*args).pk)
                except QuizOutcomeConflict:
                    return ("conflict", None)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(worker, calls))

    def test_repeated_same_completion_has_one_record(self):
        program, _ = weighted_program()
        project, _ = team(program, submitted=False)
        event = (program.pk, project.pk, "same-finalized-attempt", "88.25")
        results = self.race([event, event])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")
        self.assertEqual(ProgramQuizOutcome.objects.count(), 1)

    def test_second_attempt_cannot_win_a_race_for_same_team(self):
        program, _ = weighted_program()
        project, _ = team(program, submitted=False)
        results = self.race(
            [
                (program.pk, project.pk, "first-attempt", 50),
                (program.pk, project.pk, "second-attempt", 100),
            ]
        )
        self.assertCountEqual([row[0] for row in results], ["ok", "conflict"])
        self.assertEqual(ProgramQuizOutcome.objects.count(), 1)

    def test_same_source_attempt_cannot_be_claimed_in_two_programs(self):
        first, _ = weighted_program()
        second, _ = weighted_program()
        first_team, _ = team(first, submitted=False)
        second_team, _ = team(second, submitted=False)
        results = self.race(
            [
                (first.pk, first_team.pk, "global-attempt", 75),
                (second.pk, second_team.pk, "global-attempt", 75),
            ]
        )
        self.assertCountEqual([row[0] for row in results], ["ok", "conflict"])
        self.assertEqual(ProgramQuizOutcome.objects.count(), 1)
