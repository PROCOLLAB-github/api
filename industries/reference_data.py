from dataclasses import dataclass

from django.db import transaction

from industries.models import Industry


# Список повторяет действующий справочник legacy-контура; идентификаторы намеренно
# не фиксируются, потому что Project хранит локальный FK конкретной базы данных.
REACT_DEV_INDUSTRY_NAMES = (
    "AR/VR",
    "AgTech",
    "CV/ML",
    "Customer Services",
    "Cybersecurity",
    "Devices",
    "E-auto & Taxi Services",
    "E-commerce",
    "EdTech",
    "Entertainment Tech",
    "FinTech",
    "FoodTech",
    "Games",
    "GovTech",
    "HRTech",
    "InsurTech",
    "InvestTech",
    "LegalTech",
    "Logistics",
    "Mapping & Geolocation",
    "MedTech",
    "PropTech",
    "RegTech",
    "Smart Home Solutions",
    "SportTech",
    "Другое",
    "Социальные проекты",
)


@dataclass(frozen=True)
class IndustryReferenceDataSummary:
    created: int
    existing: int


@transaction.atomic
def ensure_react_dev_industries() -> IndustryReferenceDataSummary:
    """Создаёт отсутствующие отрасли React-dev, не изменяя существующие записи."""
    existing_names = set(
        Industry.objects.filter(name__in=REACT_DEV_INDUSTRY_NAMES).values_list(
            "name",
            flat=True,
        )
    )
    missing_names = [
        name for name in REACT_DEV_INDUSTRY_NAMES if name not in existing_names
    ]
    Industry.objects.bulk_create([Industry(name=name) for name in missing_names])
    return IndustryReferenceDataSummary(
        created=len(missing_names),
        existing=len(existing_names),
    )
