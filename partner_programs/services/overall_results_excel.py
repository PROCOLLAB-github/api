"""Простая XLSX-выгрузка того же общего рейтинга, который отдает API."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.workbook.properties import CalcProperties

from partner_programs.services.overall_results import STATUS_LABELS
from partner_programs.services.results_excel import text_cell


def export_overall_results(snapshot):
    workbook = Workbook()
    workbook.calculation = CalcProperties(fullCalcOnLoad=True)
    sheet = workbook.active
    sheet.title = "Общий рейтинг"
    sheet.append(
        [
            "Место",
            "Команда",
            "Кейс",
            "Кейс из 100",
            "Квиз из 100",
            "Итог из 200",
            "Статус",
        ]
    )
    for number, project in enumerate(snapshot["projects"], 2):
        sheet.cell(number, 1, project["place"])
        text_cell(sheet, number, 2, project["name"])
        text_cell(sheet, number, 3, project["case_name"] or "Без кейса")
        for column, key in ((4, "case_score"), (5, "quiz_score")):
            if project[key] is not None:
                sheet.cell(number, column, project[key])
        if project["ready"]:
            sheet.cell(number, 6, f"=ROUND(D{number}+E{number},2)")
        text_cell(sheet, number, 7, STATUS_LABELS[project["status"]])
    for row in sheet:
        for cell in row:
            cell.font = Font(name="Arial", size=10, bold=cell.row == 1)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.row > 1 and cell.column in (4, 5, 6):
                cell.number_format = "0.00"
    for column, width in (
        ("A", 10),
        ("B", 34),
        ("C", 26),
        ("D", 18),
        ("E", 18),
        ("F", 18),
        ("G", 36),
    ):
        sheet.column_dimensions[column].width = width
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
