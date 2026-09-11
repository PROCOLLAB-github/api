from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase, override_settings

from partner_programs.admin import PartnerProgramAdmin
from partner_programs.models import PartnerProgram


NEXTGEN_PROGRAM_FIELDS = {
    "participation_format",
    "team_min_size",
    "team_max_size",
    "datetime_application_ends",
}


class PartnerProgramAdminSurfaceTests(SimpleTestCase):
    def setUp(self):
        self.model_admin = PartnerProgramAdmin(PartnerProgram, admin.AdminSite())
        self.request = RequestFactory().get("/admin/partner_programs/partnerprogram/")

    def get_runtime_configuration(self):
        list_display = tuple(self.model_admin.get_list_display(self.request))
        list_display_links = tuple(
            self.model_admin.get_list_display_links(self.request, list_display) or ()
        )
        list_filter = tuple(self.model_admin.get_list_filter(self.request))
        fieldsets = self.model_admin.get_fieldsets(self.request)
        fieldset_titles = {title for title, _options in fieldsets}
        fieldset_fields = set()
        for _title, options in fieldsets:
            for field in options["fields"]:
                if isinstance(field, (list, tuple)):
                    fieldset_fields.update(field)
                else:
                    fieldset_fields.add(field)
        return {
            "list_display": list_display,
            "list_display_links": list_display_links,
            "list_filter": list_filter,
            "fieldset_titles": fieldset_titles,
            "fieldset_fields": fieldset_fields,
        }

    @override_settings(NEXTGEN_SURFACE_ENABLED=False)
    def test_nextgen_program_fields_are_hidden_when_surface_is_disabled(self):
        configuration = self.get_runtime_configuration()

        self.assertNotIn("participation_format", configuration["list_display"])
        self.assertNotIn("participation_format", configuration["list_display_links"])
        self.assertNotIn("participation_format", configuration["list_filter"])
        self.assertNotIn("Участие и заявки", configuration["fieldset_titles"])
        self.assertTrue(
            NEXTGEN_PROGRAM_FIELDS.isdisjoint(configuration["fieldset_fields"])
        )

    @override_settings(NEXTGEN_SURFACE_ENABLED=True)
    def test_nextgen_program_fields_are_visible_when_surface_is_enabled(self):
        configuration = self.get_runtime_configuration()

        self.assertIn("participation_format", configuration["list_display"])
        self.assertIn("participation_format", configuration["list_display_links"])
        self.assertIn("participation_format", configuration["list_filter"])
        self.assertIn("Участие и заявки", configuration["fieldset_titles"])
        self.assertTrue(NEXTGEN_PROGRAM_FIELDS.issubset(configuration["fieldset_fields"]))
