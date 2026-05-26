import os
import random
from decimal import Decimal
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone

from certificates.models import (
    CertificateGenerationRun,
    IssuedCertificate,
    ProgramCertificateTemplate,
)
from core.models import Like, Skill, SkillCategory, SkillToObject, View
from core.models import Specialization, SpecializationCategory
from files.models import UserFile
from industries.models import Industry
from moderation.models import ModerationLog
from news.models import News
from notifications.models import Notification, NotificationDelivery
from partner_programs.models import (
    LegalDocument,
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramInvite,
    PartnerProgramLegalSettings,
    PartnerProgramParticipantConsent,
    PartnerProgramMaterial,
    PartnerProgramProject,
    PartnerProgramUserProfile,
    PartnerProgramVerificationRequest,
)
from project_rates.models import (
    Criteria,
    ProjectEvaluation,
    ProjectEvaluationScore,
    ProjectExpertAssignment,
    ProjectScore,
)
from projects.models import (
    Achievement,
    Collaborator,
    Company,
    Project,
    ProjectCompany,
    ProjectGoal,
    ProjectLink,
    ProjectNews,
    Resource,
)
from users import constants as user_constants
from users.models import (
    Expert,
    Investor,
    Member,
    Mentor,
    UserAchievement,
    UserEducation,
    UserLanguages,
    UserLink,
    UserNotificationPreferences,
    UserWorkExperience,
)

User = get_user_model()


DEFAULT_PASSWORD = "DemoPassword123"
EMAIL_DOMAIN = "demo.procollab.local"

DEMO_ACCOUNT_SPECS = [
    {
        "key": "admin",
        "email": f"demo.admin@{EMAIL_DOMAIN}",
        "first_name": "Demo",
        "last_name": "Admin",
        "user_type": User.MEMBER,
        "is_staff": True,
        "is_superuser": True,
    },
    {
        "key": "organizer_verified",
        "email": f"demo.organizer.verified@{EMAIL_DOMAIN}",
        "first_name": "Verified",
        "last_name": "Organizer",
        "user_type": User.MEMBER,
    },
    {
        "key": "organizer_pending",
        "email": f"demo.organizer.pending@{EMAIL_DOMAIN}",
        "first_name": "Pending",
        "last_name": "Organizer",
        "user_type": User.MEMBER,
    },
    {
        "key": "expert",
        "email": f"demo.expert@{EMAIL_DOMAIN}",
        "first_name": "Demo",
        "last_name": "Expert",
        "user_type": User.EXPERT,
    },
    {
        "key": "participant",
        "email": f"demo.participant@{EMAIL_DOMAIN}",
        "first_name": "Demo",
        "last_name": "Participant",
        "user_type": User.MEMBER,
    },
]

FIRST_NAMES = [
    "Алексей",
    "Анна",
    "Иван",
    "Мария",
    "Дмитрий",
    "Екатерина",
    "Никита",
    "Софья",
    "Михаил",
    "Виктория",
    "Артем",
    "Полина",
    "Кирилл",
    "Дарья",
    "Глеб",
    "Алина",
    "Роман",
    "Елена",
    "Максим",
    "Юлия",
]

LAST_NAMES = [
    "Иванов",
    "Смирнова",
    "Петров",
    "Кузнецова",
    "Соколов",
    "Попова",
    "Лебедев",
    "Новикова",
    "Козлов",
    "Морозова",
    "Волков",
    "Соловьева",
    "Васильев",
    "Зайцева",
    "Павлов",
    "Семенова",
    "Голубев",
    "Виноградова",
    "Федоров",
    "Орлова",
]

PATRONYMICS = [
    "Андреевич",
    "Александровна",
    "Сергеевич",
    "Дмитриевна",
    "Ильич",
    "Викторовна",
    "Павлович",
    "Романовна",
    "Максимович",
    "Игоревна",
]

REGIONS = [
    ("Москва", "Москва"),
    ("Московская область", "Долгопрудный"),
    ("Санкт-Петербург", "Санкт-Петербург"),
    ("Татарстан", "Казань"),
    ("Новосибирская область", "Новосибирск"),
    ("Свердловская область", "Екатеринбург"),
    ("Краснодарский край", "Краснодар"),
    ("Нижегородская область", "Нижний Новгород"),
]

INDUSTRIES = [
    "Образовательные технологии",
    "Цифровое здравоохранение",
    "Умный город",
    "Финансовые технологии",
    "Экология и устойчивое развитие",
    "Промышленная автоматизация",
    "Креативные индустрии",
    "Логистика и транспорт",
]

SPECIALIZATION_CATEGORIES = {
    "Разработка": [
        "Backend-разработчик",
        "Frontend-разработчик",
        "Data Scientist",
        "Mobile-разработчик",
    ],
    "Продукт": [
        "Product manager",
        "UX/UI дизайнер",
        "Маркетолог",
        "Бизнес-аналитик",
    ],
    "Исследования": [
        "Инженер-исследователь",
        "Методолог",
        "Аналитик данных",
    ],
}

SKILLS_BY_CATEGORY = {
    "Разработка": [
        "Python",
        "Django",
        "REST API",
        "PostgreSQL",
        "React",
        "TypeScript",
        "Docker",
    ],
    "Продукт": [
        "Customer Development",
        "Roadmap",
        "Figma",
        "Product Analytics",
        "Unit Economics",
    ],
    "Коммуникации": [
        "Публичные выступления",
        "Переговоры",
        "Менторство",
        "Копирайтинг",
    ],
    "Исследования": [
        "ML",
        "Computer Vision",
        "Data Analysis",
        "GIS",
        "IoT",
    ],
}

PROJECT_TOPICS = [
    (
        "Campus Navigator",
        "сервис навигации по кампусу с расписанием, событиями и подсказками",
    ),
    (
        "EcoTrack",
        "платформа мониторинга экологических инициатив и волонтерских активностей",
    ),
    (
        "MedAssist",
        "цифровой помощник для записи, напоминаний и анализа обращений пациентов",
    ),
    (
        "SkillBridge",
        "маркетплейс проектных задач для студентов, наставников и компаний",
    ),
    (
        "SmartLab",
        "система бронирования лабораторий и учета оборудования",
    ),
    (
        "AgroVision",
        "аналитика состояния посевов по снимкам и датчикам",
    ),
    (
        "TutorFlow",
        "инструмент для адаптивных образовательных траекторий",
    ),
    (
        "CityPulse",
        "дашборд городских данных для поиска проблемных зон и гипотез",
    ),
    (
        "FinCoach",
        "приложение для персонального финансового планирования",
    ),
    (
        "EventHub",
        "единая витрина мероприятий с рекомендациями для команд",
    ),
    (
        "SupplyMind",
        "прогнозирование задержек в поставках и подбор альтернатив",
    ),
    (
        "CultureMap",
        "карта локальных культурных пространств и творческих команд",
    ),
]

USER_NEWS = [
    "Опубликовал обновленное портфолио и открыт к участию в новых проектных командах.",
    "Завершил интенсив по продуктовой аналитике и добавил новые навыки в профиль.",
    "Провел консультацию для студенческой команды и собрал список следующих гипотез.",
    "Подготовил подборку полезных материалов для участников проектного трека.",
    "Получил новый опыт на хакатоне и ищет команду для развития прототипа.",
]

PROJECT_NEWS = [
    "Команда завершила первый пользовательский сценарий и начала тестирование прототипа.",
    "Добавлены новые задачи в дорожную карту и распределены зоны ответственности.",
    "Проект прошел экспертную сессию, команда обновила приоритеты на ближайший спринт.",
    "Подготовлена демонстрационная версия для сбора обратной связи от первых пользователей.",
    "Команда договорилась о пилотном запуске и собирает метрики для оценки результата.",
]

PROGRAM_TOPICS = [
    (
        "Акселератор технологических команд",
        "ACCEL-TECH",
        "Интенсив для команд, которые хотят проверить продуктовую гипотезу, собрать MVP и подготовиться к пилотному запуску.",
    ),
    (
        "Городские цифровые сервисы",
        "CITY-DIGITAL",
        "Программа для проектов в сфере городских данных, навигации, транспорта и комфортной городской среды.",
    ),
    (
        "Индустриальный трек партнеров",
        "INDUSTRY-LAB",
        "Совместная программа с компаниями для поиска решений под реальные производственные и операционные задачи.",
    ),
    (
        "EdTech и новые образовательные практики",
        "EDTECH-PRACTICE",
        "Трек для команд, создающих инструменты обучения, наставничества и оценки образовательных результатов.",
    ),
    (
        "Социальные и экологические инициативы",
        "IMPACT-START",
        "Программа поддержки проектов с измеримым социальным, экологическим или общественным эффектом.",
    ),
]

PROGRAM_STATUS_CYCLE = [
    "draft",
    "pending_moderation",
    "published",
    "rejected",
    "completed",
    "frozen",
    "archived",
    "published",
    "pending_moderation",
]

PROGRAM_FILL_LEVEL_CYCLE = [
    "minimal",
    "full",
    "full",
    "partial",
    "full",
    "partial",
    "minimal",
    "partial",
    "full",
]

PROGRAM_FIELDS = [
    {
        "name": "track",
        "label": "Тематический трек",
        "field_type": "select",
        "is_required": True,
        "show_filter": True,
        "help_text": "Выберите направление, к которому ближе проект.",
        "options": "EdTech|HealthTech|UrbanTech|GreenTech|IndustrialTech",
    },
    {
        "name": "stage",
        "label": "Стадия проекта",
        "field_type": "select",
        "is_required": True,
        "show_filter": True,
        "help_text": "Текущая стадия готовности решения.",
        "options": "Идея|Прототип|MVP|Пилот|Первые продажи",
    },
    {
        "name": "support_request",
        "label": "Какая поддержка нужна",
        "field_type": "textarea",
        "is_required": False,
        "show_filter": False,
        "help_text": "Кратко опишите запрос к экспертам и партнерам.",
        "options": "",
    },
]

PROGRAM_CRITERIA = [
    ("Проблема", "Насколько ясно описана проблема и целевая аудитория."),
    ("Решение", "Насколько убедительно решение закрывает выбранную проблему."),
    ("Команда", "Компетенции команды и способность довести проект до результата."),
    ("Потенциал", "Возможность масштабирования и ценность для партнеров."),
    ("Комментарий", "Доп. поле для впечатлений о проекте"),
]

PROGRAM_NEWS = [
    "Открыта регистрация участников, команды могут подать заявку и добавить проект.",
    "Опубликованы материалы установочной встречи и шаблон для описания проекта.",
    "Сформирован пул экспертов, скоро начнутся консультации и промежуточные ревью.",
    "Добавлены критерии оценки и чек-лист подготовки к финальной защите.",
]

ACHIEVEMENTS = [
    ("Финалист акселератора", "топ-10 команд"),
    ("Победитель хакатона", "1 место"),
    ("Пилот с индустриальным партнером", "подтвержден"),
    ("Грантовая поддержка", "заявка одобрена"),
]

PROJECT_ROLES = [
    "Backend",
    "Frontend",
    "Product",
    "UX/UI",
    "Data",
    "Marketing",
    "Research",
]


class Command(BaseCommand):
    help = (
        "Create idempotent demo data for the Selectel pre-prod stand. "
        "Usage: DEMO_PASSWORD=... python manage.py seed_demo_data"
    )

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=30)
        parser.add_argument("--projects", type=int, default=12)
        parser.add_argument("--programs", type=int, default=4)
        parser.add_argument("--news-per-user", type=int, default=2)
        parser.add_argument("--news-per-project", type=int, default=3)
        parser.add_argument("--seed", type=int, default=20260501)
        parser.add_argument(
            "--password",
            default=os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        users_count = options["users"]
        projects_count = options["projects"]
        programs_count = options["programs"]
        news_per_user = options["news_per_user"]
        news_per_project = options["news_per_project"]

        if (
            min(
                users_count,
                projects_count,
                programs_count,
                news_per_user,
                news_per_project,
            )
            < 0
        ):
            raise CommandError("Counts must be greater than or equal to zero.")
        if projects_count and users_count == 0:
            raise CommandError("At least one user is required to create projects.")

        rnd = random.Random(options["seed"])
        self._programs_count = programs_count

        industries = self._ensure_industries()
        specializations = self._ensure_specializations()
        skills = self._ensure_skills()
        demo_accounts = self._ensure_demo_accounts(
            password=options["password"],
            skills=skills,
            rnd=rnd,
        )

        generated_users = [
            self._create_user(index, rnd, specializations, skills, options["password"])
            for index in range(1, users_count + 1)
        ]
        users = self._merge_unique_users(demo_accounts.values(), generated_users)
        projects = [
            self._create_project(index, rnd, users, industries, skills)
            for index in range(1, projects_count + 1)
        ]
        available_users = users or list(
            User.objects.filter(email__endswith=f"@{EMAIL_DOMAIN}").order_by("id")
        )
        available_projects = projects or list(
            Project.objects.filter(name__contains="#").order_by("id")
        )
        if programs_count and (not available_users or not available_projects):
            raise CommandError(
                "Programs require existing demo users and projects. "
                "Run without --users 0/--projects 0 first."
            )
        programs = [
            self._create_program(index, rnd, available_users, available_projects)
            for index in range(1, programs_count + 1)
        ]

        user_news_created = self._create_user_news(users, news_per_user, rnd)
        project_news_created = self._create_project_news(projects, news_per_project, rnd)
        program_news_created = self._create_program_news(programs, rnd)
        domain_records = self._ensure_demo_domain_records(
            programs=programs,
            users=users,
            projects=projects,
            demo_accounts=demo_accounts,
            rnd=rnd,
        )
        demo_record_count = self._demo_record_count()

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data is ready: "
                f"users={len(users)}, projects={len(projects)}, "
                f"programs={len(programs)}, "
                f"user_news={user_news_created}, "
                f"project_news={project_news_created}, "
                f"program_news={program_news_created}, "
                f"domain_records={domain_records}, "
                f"non_cross_table_records={demo_record_count}."
            )
        )
        self.stdout.write(
            f"Demo users use emails demo.user.001@{EMAIL_DOMAIN} ... "
            f"and password: {options['password']}"
        )
        self.stdout.write(
            "Named demo accounts: "
            + ", ".join(spec["email"] for spec in DEMO_ACCOUNT_SPECS)
        )

    def _ensure_industries(self):
        return [self._get_or_create(Industry, name=name) for name in INDUSTRIES]

    def _ensure_specializations(self):
        specializations = []
        for category_name, names in SPECIALIZATION_CATEGORIES.items():
            category = self._get_or_create(SpecializationCategory, name=category_name)
            for name in names:
                specializations.append(
                    self._get_or_create(
                        Specialization,
                        category=category,
                        name=name,
                    )
                )
        return specializations

    def _ensure_skills(self):
        skills = []
        for category_name, names in SKILLS_BY_CATEGORY.items():
            category = self._get_or_create(SkillCategory, name=category_name)
            for name in names:
                skills.append(self._get_or_create(Skill, category=category, name=name))
        return skills

    def _ensure_demo_accounts(self, password, skills, rnd):
        accounts = {}
        for index, spec in enumerate(DEMO_ACCOUNT_SPECS, start=1):
            user = self._ensure_named_user(
                email=spec["email"],
                password=password,
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                user_type=spec["user_type"],
                is_staff=spec.get("is_staff", False),
                is_superuser=spec.get("is_superuser", False),
            )
            self._ensure_role_profile(user, rnd)
            self._ensure_user_details(user, 900 + index, rnd, skills)
            accounts[spec["key"]] = user
        return accounts

    def _ensure_named_user(
        self,
        *,
        email,
        password,
        first_name,
        last_name,
        user_type,
        is_staff=False,
        is_superuser=False,
    ):
        defaults = {
            "first_name": first_name,
            "last_name": last_name,
            "patronymic": "",
            "user_type": user_type,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
            "is_active": True,
            "birthday": date(1995, 1, 1),
            "about_me": "Demo account for the Selectel pre-prod stand.",
            "status": "Demo",
            "region": "Moscow",
            "city": "Moscow",
            "phone_number": "+79990000000",
            "onboarding_stage": user_constants.OnboardingStage.completed.value,
            "verification_date": timezone.localdate(),
            "last_activity": timezone.now(),
            "is_mospolytech_student": False,
        }
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email=email, password=password, **defaults)
        else:
            for field, value in defaults.items():
                setattr(user, field, value)
            user.set_password(password)
            user.save()
        return user

    def _merge_unique_users(self, primary_users, secondary_users):
        users = []
        seen_ids = set()
        for user in [*primary_users, *secondary_users]:
            if user.id in seen_ids:
                continue
            users.append(user)
            seen_ids.add(user.id)
        return users

    def _create_user(self, index, rnd, specializations, skills, password):
        first_name = FIRST_NAMES[(index - 1) % len(FIRST_NAMES)]
        last_name = LAST_NAMES[(index - 1) % len(LAST_NAMES)]
        patronymic = PATRONYMICS[(index - 1) % len(PATRONYMICS)]
        region, city = REGIONS[(index - 1) % len(REGIONS)]
        user_type = self._get_user_type(index)
        email = f"demo.user.{index:03d}@{EMAIL_DOMAIN}"
        speciality = rnd.choice(specializations)

        defaults = {
            "first_name": first_name,
            "last_name": last_name,
            "patronymic": patronymic,
            "user_type": user_type,
            "is_active": True,
            "birthday": self._birthday_for(index),
            "about_me": self._user_about(first_name, speciality.name),
            "status": rnd.choice(
                [
                    "Ищу проектную команду",
                    "Готов к менторству",
                    "Открыт к пилотам",
                    "Помогаю с продуктовой упаковкой",
                ]
            ),
            "region": region,
            "city": city,
            "phone_number": f"+7916{1000000 + index:07d}",
            "v2_speciality": speciality,
            "speciality": speciality.name,
            "avatar": f"https://i.pravatar.cc/300?u=procollab-demo-{index:03d}",
            "onboarding_stage": user_constants.OnboardingStage.completed.value,
            "verification_date": timezone.localdate() - timedelta(days=index % 30),
            "last_activity": timezone.now() - timedelta(hours=index * 3),
            "is_mospolytech_student": index % 3 != 0,
            "study_group": f"22{index % 9 + 1}-0{index % 4 + 1}",
        }

        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email=email, password=password, **defaults)
        else:
            for field, value in defaults.items():
                setattr(user, field, value)
            user.set_password(password)
            user.save()

        self._ensure_role_profile(user, rnd)
        self._ensure_user_details(user, index, rnd, skills)
        return user

    def _get_user_type(self, index):
        cycle = [
            User.MEMBER,
            User.MEMBER,
            User.MENTOR,
            User.EXPERT,
            User.INVESTOR,
        ]
        return cycle[(index - 1) % len(cycle)]

    def _birthday_for(self, index):
        year = 1985 + (index % 18)
        month = index % 12 + 1
        day = min(index % 27 + 1, 28)
        return date(year, month, day)

    def _user_about(self, first_name, speciality):
        return (
            f"{first_name} развивает проекты на стыке технологий и реальных "
            f"пользовательских задач. Основная специализация: {speciality}."
        )

    def _ensure_role_profile(self, user, rnd):
        role_defaults = {
            "useful_to_project": rnd.choice(
                [
                    "Поможет проверить гипотезы, собрать обратную связь и оформить MVP.",
                    "Готов подключиться к разработке, аналитике и упаковке продукта.",
                    "Может провести экспертную сессию и помочь с дорожной картой.",
                ]
            )
        }

        if user.user_type == User.MEMBER:
            profile = self._get_or_create(Member, user=user)
            profile.useful_to_project = role_defaults["useful_to_project"]
        elif user.user_type == User.MENTOR:
            profile = self._get_or_create(Mentor, user=user)
            profile.preferred_industries = ", ".join(rnd.sample(INDUSTRIES, 3))
            profile.useful_to_project = role_defaults["useful_to_project"]
            profile.first_additional_role = User.EXPERT
            profile.second_additional_role = User.INVESTOR
        elif user.user_type == User.EXPERT:
            profile = self._get_or_create(Expert, user=user)
            profile.preferred_industries = ", ".join(rnd.sample(INDUSTRIES, 3))
            profile.useful_to_project = role_defaults["useful_to_project"]
            profile.first_additional_role = User.MENTOR
            profile.second_additional_role = User.INVESTOR
        else:
            profile = self._get_or_create(Investor, user=user)
            profile.preferred_industries = ", ".join(rnd.sample(INDUSTRIES, 3))
            profile.interaction_process_description = (
                "Смотрит на команды с понятной проблемой, первыми метриками "
                "и готовностью быстро проверять партнерские гипотезы."
            )
            profile.first_additional_role = User.MENTOR
            profile.second_additional_role = User.EXPERT
        profile.save()
        UserNotificationPreferences.objects.get_or_create(user=user)

    def _ensure_user_details(self, user, index, rnd, skills):
        user_content_type = ContentType.objects.get_for_model(User)
        for skill in rnd.sample(skills, k=min(5, len(skills))):
            SkillToObject.objects.get_or_create(
                skill=skill,
                content_type=user_content_type,
                object_id=user.pk,
            )

        self._upsert_user_education(user, index)
        self._upsert_user_work(user, index)
        self._upsert_user_languages(user, rnd)
        self._upsert_user_achievements(user, index, rnd)

        UserLink.objects.get_or_create(
            user=user,
            link=f"https://portfolio.example.com/procollab/demo-user-{index:03d}",
        )
        UserLink.objects.get_or_create(
            user=user,
            link=f"https://github.com/procollab-demo-user-{index:03d}",
        )

        score = user.calculate_ordering_score()
        User.objects.filter(pk=user.pk).update(
            ordering_score=score,
            dataset_migration_applied=True,
        )

    def _upsert_user_education(self, user, index):
        obj = UserEducation.objects.filter(
            user=user,
            organization_name="Московский Политех",
        ).first()
        defaults = {
            "education_level": user_constants.UserEducationLevels.HIGHER_BACALAVR.value,
            "education_status": user_constants.UserEducationStatuses.STUDENT.value,
            "description": "Проектная деятельность и цифровые продукты",
            "entry_year": 2020 + index % 4,
            "completion_year": 2024 + index % 4,
        }
        if obj is None:
            UserEducation.objects.create(
                user=user,
                organization_name="Московский Политех",
                **defaults,
            )
            return
        for field, value in defaults.items():
            setattr(obj, field, value)
        obj.save()

    def _upsert_user_work(self, user, index):
        obj = UserWorkExperience.objects.filter(
            user=user,
            organization_name="Проектная лаборатория PROCOLLAB",
        ).first()
        defaults = {
            "job_position": PROJECT_ROLES[index % len(PROJECT_ROLES)],
            "description": "Работа с прототипами, исследованиями и презентациями.",
            "entry_year": 2022,
            "completion_year": timezone.localdate().year,
        }
        if obj is None:
            UserWorkExperience.objects.create(
                user=user,
                organization_name="Проектная лаборатория PROCOLLAB",
                **defaults,
            )
            return
        for field, value in defaults.items():
            setattr(obj, field, value)
        obj.save()

    def _upsert_user_languages(self, user, rnd):
        base_languages = [
            user_constants.UserLanguagesEnum.RUSSIAN.value,
            user_constants.UserLanguagesEnum.ENGLISH.value,
        ]
        extra_languages = [
            user_constants.UserLanguagesEnum.GERMAN.value,
            user_constants.UserLanguagesEnum.FRENCH.value,
            user_constants.UserLanguagesEnum.CHINESE.value,
        ]
        levels = [level.value for level in user_constants.UserLanguagesLevels]

        for language in base_languages + rnd.sample(extra_languages, 1):
            UserLanguages.objects.get_or_create(
                user=user,
                language=language,
                defaults={"language_level": rnd.choice(levels)},
            )

    def _upsert_user_achievements(self, user, index, rnd):
        title, status = rnd.choice(ACHIEVEMENTS)
        UserAchievement.objects.get_or_create(
            user=user,
            title=f"{title} #{index:03d}",
            year=2022 + index % 4,
            defaults={"status": status},
        )

    def _create_project(self, index, rnd, users, industries, skills):
        topic_name, topic_description = PROJECT_TOPICS[(index - 1) % len(PROJECT_TOPICS)]
        leader = users[(index - 1) % len(users)]
        industry = industries[(index - 1) % len(industries)]
        name = f"{topic_name} #{index:02d}"

        defaults = {
            "description": (
                f"{topic_name} — {topic_description}. Команда проверяет спрос, "
                "готовит пилот и собирает обратную связь от первых пользователей."
            ),
            "region": REGIONS[index % len(REGIONS)][0],
            "hidden_score": rnd.randint(60, 100),
            "actuality": (
                "Проект помогает быстрее находить работающие решения и снижает "
                "стоимость проверки гипотез для команды и партнеров."
            ),
            "target_audience": rnd.choice(
                [
                    "студенты, проектные команды и наставники",
                    "университетские лаборатории и индустриальные партнеры",
                    "городские сервисы, НКО и локальные сообщества",
                    "малые команды, которым нужен быстрый запуск пилота",
                ]
            ),
            "implementation_deadline": timezone.localdate()
            + timedelta(days=60 + index * 7),
            "problem": (
                "Пользователям сложно быстро собрать данные, проверить гипотезу "
                "и увидеть понятный результат без лишней ручной работы."
            ),
            "trl": rnd.randint(3, 8),
            "industry": industry,
            "presentation_address": (
                f"https://docs.example.com/procollab/projects/{index:03d}/presentation"
            ),
            "image_address": (
                f"https://picsum.photos/seed/procollab-project-{index:03d}/480/480"
            ),
            "cover_image_address": (
                f"https://picsum.photos/seed/procollab-cover-{index:03d}/1200/420"
            ),
            "leader": leader,
            "draft": False,
            "is_company": index % 5 == 0,
            "is_public": True,
        }

        project = Project.objects.filter(name=name).first()
        if project is None:
            project = Project.objects.create(name=name, **defaults)
        else:
            for field, value in defaults.items():
                setattr(project, field, value)
            project.save()

        self._ensure_project_details(project, index, rnd, users, skills)
        return project

    def _ensure_project_details(self, project, index, rnd, users, skills):
        project_content_type = ContentType.objects.get_for_model(Project)
        for skill in rnd.sample(skills, k=min(5, len(skills))):
            SkillToObject.objects.get_or_create(
                skill=skill,
                content_type=project_content_type,
                object_id=project.pk,
            )

        ProjectLink.objects.get_or_create(
            project=project,
            link=f"https://demo.example.com/projects/{project.pk}",
        )
        ProjectLink.objects.get_or_create(
            project=project,
            link=f"https://github.com/procollab-demo/project-{index:03d}",
        )

        for title, status in rnd.sample(ACHIEVEMENTS, k=2):
            Achievement.objects.get_or_create(
                project=project,
                title=f"{title} проекта {index:02d}",
                defaults={"status": status},
            )

        collaborators = rnd.sample(users, k=min(len(users), rnd.randint(3, 6)))
        if project.leader not in collaborators:
            collaborators[0] = project.leader
        program_link = project.program_links.select_related("partner_program").first()
        for user in collaborators:
            if program_link:
                self._upsert_program_profile(
                    program=program_link.partner_program,
                    user=user,
                    project=project if user == project.leader else None,
                )
            Collaborator.objects.get_or_create(
                project=project,
                user=user,
                defaults={
                    "role": rnd.choice(PROJECT_ROLES),
                    "specialization": user.speciality,
                },
            )

        project.subscribers.set(rnd.sample(users, k=min(len(users), rnd.randint(4, 10))))

        for goal_index in range(1, 4):
            title = self._project_goal_title(goal_index)
            goal = ProjectGoal.objects.filter(project=project, title=title).first()
            defaults = {
                "completion_date": timezone.localdate()
                + timedelta(days=goal_index * 21 + index),
                "responsible": rnd.choice(collaborators),
                "is_done": goal_index == 1 and index % 2 == 0,
            }
            if goal is None:
                ProjectGoal.objects.create(project=project, title=title, **defaults)
            else:
                for field, value in defaults.items():
                    setattr(goal, field, value)
                goal.save()

        company = self._ensure_company(index)
        ProjectCompany.objects.get_or_create(
            project=project,
            company=company,
            defaults={
                "contribution": "Экспертиза, пилотная площадка и обратная связь.",
                "decision_maker": project.leader,
            },
        )
        for resource_type in [
            Resource.ResourceType.STAFF,
            Resource.ResourceType.INFORMATION,
        ]:
            Resource.objects.get_or_create(
                project=project,
                type=resource_type,
                defaults={
                    "description": self._resource_description(resource_type),
                    "partner_company": company,
                },
            )

        self._add_reactions(project, users, rnd)

    def _project_goal_title(self, index):
        return {
            1: "Собрать обратную связь по прототипу",
            2: "Подготовить демонстрацию для партнеров",
            3: "Запустить пилот и зафиксировать метрики",
        }[index]

    def _ensure_company(self, index):
        inn = f"7701{index:06d}"
        company = Company.objects.filter(inn=inn).first()
        if company is None:
            return Company.objects.create(
                inn=inn,
                name=f"Демо-партнер {index:02d}",
            )
        company.name = f"Демо-партнер {index:02d}"
        company.save()
        return company

    def _resource_description(self, resource_type):
        descriptions = {
            Resource.ResourceType.STAFF: "Нужны участники для разработки и аналитики.",
            Resource.ResourceType.INFORMATION: "Нужны данные, интервью и экспертные материалы.",
        }
        return descriptions[resource_type]

    def _create_program(self, index, rnd, users, projects):
        name, tag, description = self._program_seed_data(index)
        status = self._program_status(index)
        fill_level = self._program_fill_level(index)
        dates = self._program_dates(index, status)
        now = timezone.now()
        company = self._ensure_company(index + 100)
        defaults = {
            "tag": tag,
            "description": description if fill_level != "minimal" else "",
            "is_competitive": index % 2 == 1,
            "city": REGIONS[index % len(REGIONS)][1],
            "image_address": self._program_image(index, fill_level, "program"),
            "cover_image_address": self._program_image(index, fill_level, "cover"),
            "advertisement_image_address": self._program_image(index, fill_level, "ad"),
            "mobile_cover_image_address": self._program_image(
                index,
                fill_level,
                "mobile",
            ),
            "presentation_address": (
                f"https://docs.example.com/procollab/programs/{index:03d}/presentation"
                if fill_level in {"partial", "full"}
                else None
            ),
            "registration_link": (
                f"https://demo.example.com/programs/{tag.lower()}/registration"
                if fill_level == "full"
                else None
            ),
            "is_private": index % 4 == 0,
            "max_project_rates": 2,
            "is_distributed_evaluation": index % 2 == 1,
            "draft": status == "draft",
            "status": status,
            "frozen_at": now - timedelta(days=index) if status == "frozen" else None,
            "verification_status": self._program_verification_status(status),
            "company": company if fill_level != "minimal" else None,
            "projects_availability": "all_users",
            "publish_projects_after_finish": index % 2 == 0,
            **dates,
            "readiness": {},
            "sent_reminders": [],
        }
        self._validate_model_fields(PartnerProgram, defaults.keys())

        program = PartnerProgram.objects.filter(tag=tag).first()
        if program is None:
            program = PartnerProgram.objects.create(name=name, **defaults)
        else:
            program.name = name
            for field, value in defaults.items():
                setattr(program, field, value)
            self._save_program_without_completion_tasks(program)

        self._ensure_program_details(
            program,
            index,
            rnd,
            users,
            projects,
            fill_level,
        )
        return program

    def _program_seed_data(self, index):
        base_name, base_tag, base_description = PROGRAM_TOPICS[
            (index - 1) % len(PROGRAM_TOPICS)
        ]
        cycle_number = (index - 1) // len(PROGRAM_TOPICS)
        if cycle_number == 0:
            return base_name, base_tag, base_description

        suffix = cycle_number + 1
        return (
            f"{base_name} #{suffix:02d}",
            f"{base_tag}-{suffix:02d}",
            (
                f"{base_description} Дополнительный набор #{suffix:02d} "
                "с отдельными участниками, проектами и этапами отбора."
            ),
        )

    def _program_status(self, index):
        return PROGRAM_STATUS_CYCLE[(index - 1) % len(PROGRAM_STATUS_CYCLE)]

    def _program_fill_level(self, index):
        return PROGRAM_FILL_LEVEL_CYCLE[(index - 1) % len(PROGRAM_FILL_LEVEL_CYCLE)]

    def _program_verification_status(self, status):
        return {
            "draft": "not_requested",
            "pending_moderation": "pending",
            "published": "verified",
            "rejected": "rejected",
            "completed": "verified",
            "frozen": "verified",
            "archived": "revoked",
        }[status]

    def _program_dates(self, index, status):
        now = timezone.now()
        if status in {"completed", "archived"}:
            return {
                "datetime_started": now - timedelta(days=120 + index),
                "datetime_registration_ends": now - timedelta(days=90 + index),
                "datetime_project_submission_ends": now - timedelta(days=75 + index),
                "datetime_evaluation_ends": now - timedelta(days=50 + index),
                "datetime_finished": now - timedelta(days=20 + index),
            }

        return {
            "datetime_started": now - timedelta(days=7 + index),
            "datetime_registration_ends": now + timedelta(days=20 + index * 2),
            "datetime_project_submission_ends": now + timedelta(days=30 + index * 2),
            "datetime_evaluation_ends": now + timedelta(days=45 + index * 2),
            "datetime_finished": now + timedelta(days=60 + index * 2),
        }

    def _program_image(self, index, fill_level, image_type):
        if fill_level == "minimal":
            return None
        if fill_level == "partial" and image_type in {"ad", "mobile"}:
            return None

        sizes = {
            "program": "480/480",
            "cover": "1200/420",
            "ad": "1080/540",
            "mobile": "640/900",
        }
        return (
            f"https://picsum.photos/seed/procollab-program-{image_type}-"
            f"{index:03d}/{sizes[image_type]}"
        )

    def _validate_model_fields(self, model, field_names):
        valid_fields = {field.name for field in model._meta.get_fields()}
        unknown_fields = sorted(set(field_names) - valid_fields)
        if unknown_fields:
            raise CommandError(
                f"{model.__name__} seed contains unknown fields: "
                + ", ".join(unknown_fields)
            )

    def _ensure_program_details(self, program, index, rnd, users, projects, fill_level):
        managers = [users[(index - 1) % len(users)]]
        managers.extend(users[index : index + 2])
        program.managers.set(managers[: 1 if fill_level == "minimal" else 3])

        fields = self._ensure_program_fields(program, fill_level)
        self._ensure_program_materials(program, index, fill_level)
        self._ensure_program_criteria(program, fill_level)

        expert_profiles = list(
            Expert.objects.filter(user__in=users).select_related("user").order_by("id")
        )
        selected_experts = []
        if expert_profiles and fill_level != "minimal":
            experts_count = 1 if fill_level == "partial" else 3
            selected_experts = expert_profiles[: min(experts_count, len(expert_profiles))]
            program.experts.set(selected_experts)
        else:
            program.experts.clear()
            ProjectExpertAssignment.objects.filter(partner_program=program).delete()
            ProjectScore.objects.filter(criteria__partner_program=program).delete()
            ProjectEvaluation.objects.filter(
                program_project__partner_program=program,
            ).delete()

        if not program.is_competitive:
            ProjectExpertAssignment.objects.filter(partner_program=program).delete()
            ProjectScore.objects.filter(criteria__partner_program=program).delete()
            ProjectEvaluation.objects.filter(
                program_project__partner_program=program,
            ).delete()

        participant_count = {
            "minimal": 2,
            "partial": 6 + index % 4,
            "full": 10 + index,
        }[fill_level]
        participant_count = min(len(users), participant_count)
        participants = rnd.sample(users, k=participant_count)
        program_projects = (
            self._select_program_projects(index, projects)
            if fill_level != "minimal"
            else []
        )
        program_project_ids = {project.id for project in program_projects}
        stale_project_ids = list(
            program.program_projects.exclude(
                project_id__in=program_project_ids
            ).values_list("project_id", flat=True)
        )
        if stale_project_ids:
            ProjectScore.objects.filter(
                criteria__partner_program=program,
                project_id__in=stale_project_ids,
            ).delete()
            ProjectEvaluation.objects.filter(
                program_project__partner_program=program,
                program_project__project_id__in=stale_project_ids,
            ).delete()
            ProjectExpertAssignment.objects.filter(
                partner_program=program,
                project_id__in=stale_project_ids,
            ).delete()
            program.program_projects.exclude(project_id__in=program_project_ids).delete()

        for user in participants:
            self._upsert_program_profile(program, user)

        for project in program_projects:
            self._upsert_program_profile(program, project.leader, project)
            should_submit = program.is_competitive and project.id % 2 == 0
            link, _ = PartnerProgramProject.objects.get_or_create(
                partner_program=program,
                project=project,
                defaults={"submitted": False, "datetime_submitted": None},
            )
            if link.submitted:
                link.submitted = False
                link.datetime_submitted = None
                link.save(update_fields=["submitted", "datetime_submitted"])
            self._ensure_program_field_values(link, fields, rnd)
            link.submitted = should_submit
            link.datetime_submitted = (
                timezone.now() - timedelta(days=project.id % 7) if should_submit else None
            )
            link.save(update_fields=["submitted", "datetime_submitted"])
            self._ensure_program_project_scores(
                program,
                link,
                selected_experts[:2],
                rnd,
            )

        if fill_level != "minimal":
            self._add_reactions(program, users, rnd)
        program.readiness = program.calculate_readiness()
        self._save_program_without_completion_tasks(program, update_fields=["readiness"])

    def _save_program_without_completion_tasks(self, program, **kwargs):
        from certificates.signals import generate_certificates_after_program_completion

        disconnected = post_save.disconnect(
            receiver=generate_certificates_after_program_completion,
            sender=PartnerProgram,
        )
        try:
            program.save(**kwargs)
        finally:
            if disconnected:
                post_save.connect(
                    receiver=generate_certificates_after_program_completion,
                    sender=PartnerProgram,
                )

    def _select_program_projects(self, index, projects):
        total_programs = max(getattr(self, "_programs_count", len(PROGRAM_TOPICS)), 1)
        start = (index - 1) * len(projects) // total_programs
        end = index * len(projects) // total_programs
        return projects[start:end]

    def _ensure_program_fields(self, program, fill_level):
        field_names = {
            "minimal": set(),
            "partial": {"track", "stage"},
            "full": {field["name"] for field in PROGRAM_FIELDS},
        }[fill_level]
        if not field_names:
            program.fields.all().delete()
            return []

        program.fields.exclude(name__in=field_names).delete()
        fields = []
        for field_data in PROGRAM_FIELDS:
            if field_data["name"] not in field_names:
                continue
            field = PartnerProgramField.objects.filter(
                partner_program=program,
                name=field_data["name"],
            ).first()
            if field is None:
                field = PartnerProgramField.objects.create(
                    partner_program=program,
                    **field_data,
                )
            else:
                for key, value in field_data.items():
                    setattr(field, key, value)
                field.save()
            fields.append(field)
        return fields

    def _ensure_program_materials(self, program, index, fill_level):
        materials = [
            (
                "Регламент программы",
                f"https://docs.example.com/procollab/programs/{index:03d}/rules",
            ),
            (
                "Шаблон презентации проекта",
                f"https://docs.example.com/procollab/programs/{index:03d}/pitch-template",
            ),
        ]
        if fill_level == "minimal":
            program.materials.all().delete()
            return
        if fill_level == "partial":
            materials = materials[:1]
            program.materials.exclude(title=materials[0][0]).delete()

        for title, url in materials:
            material = PartnerProgramMaterial.objects.filter(
                program=program,
                title=title,
            ).first()
            if material is None:
                PartnerProgramMaterial.objects.create(
                    program=program,
                    title=title,
                    url=url,
                )
            else:
                material.url = url
                material.save()

    def _ensure_program_criteria(self, program, fill_level):
        if fill_level == "minimal":
            Criteria.objects.filter(partner_program=program).exclude(
                name="Комментарий"
            ).delete()
            self._delete_duplicate_program_criteria(program, {"Комментарий"})
            return

        criteria_seed = PROGRAM_CRITERIA if fill_level == "full" else PROGRAM_CRITERIA[:3]
        expected_names = {name for name, _ in criteria_seed} | {"Комментарий"}
        Criteria.objects.filter(partner_program=program).exclude(
            name__in=expected_names
        ).delete()

        for name, description in criteria_seed:
            criteria_type = "str" if name == "Комментарий" else "int"
            defaults = {
                "description": description,
                "type": criteria_type,
                "min_value": None if criteria_type == "str" else 1,
                "max_value": None if criteria_type == "str" else 10,
            }
            criteria = Criteria.objects.filter(
                partner_program=program,
                name=name,
            ).first()
            if criteria is None:
                Criteria.objects.create(partner_program=program, name=name, **defaults)
            else:
                for field, value in defaults.items():
                    setattr(criteria, field, value)
                criteria.save()

        self._delete_duplicate_program_criteria(program, expected_names)

    def _delete_duplicate_program_criteria(self, program, criteria_names):
        for name in criteria_names:
            criteria_for_name = Criteria.objects.filter(
                partner_program=program,
                name=name,
            ).order_by("id")
            keeper = criteria_for_name.first()
            if keeper is None:
                continue
            duplicate_ids = list(
                criteria_for_name.exclude(pk=keeper.pk).values_list("id", flat=True)
            )
            if duplicate_ids:
                ProjectScore.objects.filter(criteria_id__in=duplicate_ids).delete()
                Criteria.objects.filter(id__in=duplicate_ids).delete()

    def _upsert_program_profile(self, program, user, project=None):
        data = {
            "email": user.email,
            "region": user.region or "",
            "city": user.city or "",
            "education_type": "Университет",
            "institution_name": "Московский Политех",
            "class_course": user.study_group or "",
            "motivation": "Хочу проверить проектную гипотезу и получить обратную связь.",
        }
        profile = PartnerProgramUserProfile.objects.filter(
            partner_program=program,
            user=user,
        ).first()
        if profile is None:
            PartnerProgramUserProfile.objects.create(
                partner_program=program,
                user=user,
                project=project,
                partner_program_data=data,
            )
            return

        profile.partner_program_data = data
        if project is not None:
            profile.project = project
        profile.save()

    def _ensure_program_field_values(self, program_project, fields, rnd):
        option_values = {
            "track": ["EdTech", "HealthTech", "UrbanTech", "GreenTech", "IndustrialTech"],
            "stage": ["Идея", "Прототип", "MVP", "Пилот", "Первые продажи"],
            "support_request": [
                "Нужны консультации по рынку и первые контакты с партнерами.",
                "Нужна помощь с метриками пилота и упаковкой презентации.",
                "Нужна экспертная оценка архитектуры и пользовательского сценария.",
            ],
        }
        for field in fields:
            value = rnd.choice(option_values[field.name])
            field_value = PartnerProgramFieldValue.objects.filter(
                program_project=program_project,
                field=field,
            ).first()
            if field_value is None:
                PartnerProgramFieldValue.objects.create(
                    program_project=program_project,
                    field=field,
                    value_text=value,
                )
            else:
                field_value.value_text = value
                field_value.save()

    def _ensure_program_project_scores(self, program, program_project, experts, rnd):
        if not program.is_competitive or not experts:
            return

        project = program_project.project
        criteria = list(Criteria.objects.filter(partner_program=program).order_by("id"))
        for expert in experts:
            if (
                ProjectExpertAssignment.objects.filter(
                    partner_program=program,
                    project=project,
                ).count()
                < program.max_project_rates
            ):
                ProjectExpertAssignment.objects.get_or_create(
                    partner_program=program,
                    project=project,
                    expert=expert,
                )

            evaluation, _ = ProjectEvaluation.objects.get_or_create(
                program_project=program_project,
                user=expert.user,
                defaults={
                    "status": (
                        ProjectEvaluation.STATUS_SUBMITTED
                        if program_project.submitted
                        else ProjectEvaluation.STATUS_DRAFT
                    ),
                    "submitted_at": (
                        timezone.now() if program_project.submitted else None
                    ),
                },
            )
            for criterion in criteria:
                if criterion.type == "str":
                    value = rnd.choice(
                        [
                            "Хорошая база, стоит точнее описать метрики пилота.",
                            "Команда выглядит сильной, нужен фокус на одном сценарии.",
                            "Рекомендуется усилить описание целевой аудитории.",
                        ]
                    )
                else:
                    value = str(rnd.randint(6, 10))
                value = value[:50]
                ProjectScore.objects.update_or_create(
                    criteria=criterion,
                    user=expert.user,
                    project=project,
                    defaults={"value": value},
                )
                ProjectEvaluationScore.objects.update_or_create(
                    evaluation=evaluation,
                    criterion=criterion,
                    defaults={"value": value},
                )

            evaluation.total_score = evaluation.calculate_total_score()
            evaluation.comment = "Demo expert evaluation."
            if program_project.submitted:
                evaluation.status = ProjectEvaluation.STATUS_SUBMITTED
                evaluation.submitted_at = evaluation.submitted_at or timezone.now()
            else:
                evaluation.status = ProjectEvaluation.STATUS_DRAFT
                evaluation.submitted_at = None
            evaluation.save()

    def _ensure_demo_domain_records(self, *, programs, users, projects, demo_accounts, rnd):
        if not programs:
            return 0

        created_or_updated = 0
        self._ensure_legal_documents()

        admin = demo_accounts["admin"]
        organizer_verified = demo_accounts["organizer_verified"]
        organizer_pending = demo_accounts["organizer_pending"]
        expert_user = demo_accounts["expert"]
        participant = demo_accounts["participant"]

        primary_program = programs[0]
        primary_program.managers.add(organizer_verified)
        if hasattr(expert_user, "expert"):
            primary_program.experts.add(expert_user.expert)
        if primary_program.company_id is None:
            primary_program.company = self._ensure_company(300)
            primary_program.save(update_fields=["company"])

        if len(programs) > 1:
            programs[1].managers.add(organizer_pending)
        private_program = next((program for program in programs if program.is_private), None)
        if private_program is None:
            private_program = primary_program
            private_program.is_private = True
            private_program.save(update_fields=["is_private"])

        created_or_updated += self._ensure_program_file_material(
            primary_program,
            organizer_verified,
        )
        created_or_updated += self._ensure_verification_records(
            programs,
            admin,
            organizer_verified,
            organizer_pending,
        )
        created_or_updated += self._ensure_invite_records(private_program, organizer_verified)
        created_or_updated += self._ensure_moderation_logs(programs, admin, organizer_verified)
        created_or_updated += self._ensure_notifications(
            programs,
            organizer_verified,
            expert_user,
            participant,
        )
        created_or_updated += self._ensure_participant_consent(primary_program, participant)
        created_or_updated += self._ensure_certificate_records(primary_program)
        return created_or_updated

    def _ensure_legal_documents(self):
        for doc_type, title in (
            (LegalDocument.TYPE_PRIVACY_POLICY, "Demo privacy policy"),
            (LegalDocument.TYPE_PARTICIPANT_CONSENT, "Demo participant consent"),
            (LegalDocument.TYPE_PARTICIPATION_TERMS, "Demo participation terms"),
            (LegalDocument.TYPE_ORGANIZER_TERMS, "Demo organizer terms"),
        ):
            LegalDocument.objects.update_or_create(
                type=doc_type,
                version="demo-2026",
                defaults={
                    "title": title,
                    "content_html": f"<p>{title}</p>",
                    "is_active": True,
                },
            )

    def _ensure_program_file_material(self, program, owner):
        user_file = self._ensure_demo_file(
            owner,
            f"program-{program.id}-brief.pdf",
            b"PROCOLLAB demo championship material\n",
            "application/pdf",
        )
        material = PartnerProgramMaterial.objects.filter(
            program=program,
            title="Demo brief PDF",
        ).first()
        if material is None:
            PartnerProgramMaterial.objects.create(
                program=program,
                title="Demo brief PDF",
                file=user_file,
            )
            return 1

        material.file = user_file
        material.url = None
        material.save()
        return 1

    def _ensure_demo_file(self, user, filename, content, mime_type):
        relative_path = Path("uploads") / "demo" / filename
        file_path = Path(settings.MEDIA_ROOT) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        base_url = getattr(settings, "LOCAL_MEDIA_BASE_URL", "http://localhost:8000")
        link = urljoin(
            base_url.rstrip("/") + "/",
            f"{settings.MEDIA_URL.lstrip('/')}{relative_path.as_posix()}",
        )
        user_file, _ = UserFile.objects.update_or_create(
            link=link,
            defaults={
                "user": user,
                "name": Path(filename).stem,
                "extension": Path(filename).suffix.lstrip("."),
                "mime_type": mime_type,
                "size": len(content),
            },
        )
        return user_file

    def _ensure_verification_records(
        self,
        programs,
        admin,
        organizer_verified,
        organizer_pending,
    ):
        count = 0
        for index, program in enumerate(programs[:3], start=1):
            company = program.company or self._ensure_company(400 + index)
            status = (
                PartnerProgramVerificationRequest.STATUS_APPROVED
                if index == 1
                else PartnerProgramVerificationRequest.STATUS_PENDING
                if index == 2
                else PartnerProgramVerificationRequest.STATUS_REJECTED
            )
            request = PartnerProgramVerificationRequest.objects.filter(
                program=program,
            ).first()
            defaults = {
                "company": company,
                "company_name": company.name,
                "inn": company.inn,
                "legal_name": f"{company.name} LLC",
                "ogrn": f"1027700000{index:03d}",
                "website": "https://demo.procollab.local",
                "region": "Moscow",
                "initiator": organizer_verified if index != 2 else organizer_pending,
                "contact_full_name": "Demo Organizer",
                "contact_position": "Program manager",
                "contact_email": f"organizer.{index}@{EMAIL_DOMAIN}",
                "contact_phone": "+79990000000",
                "company_role_description": "Demo organizer verification request.",
                "status": status,
                "decided_by": admin if status != "pending" else None,
                "decided_at": timezone.now() if status != "pending" else None,
                "admin_comment": "Demo verification record.",
                "rejection_reason": (
                    PartnerProgramVerificationRequest.REJECTION_OTHER
                    if status == PartnerProgramVerificationRequest.STATUS_REJECTED
                    else ""
                ),
            }
            if request is None:
                PartnerProgramVerificationRequest.objects.create(
                    program=program,
                    **defaults,
                )
            else:
                for field, value in defaults.items():
                    setattr(request, field, value)
                request.save()
            program.company = company
            program.verification_status = (
                PartnerProgram.VERIFICATION_STATUS_VERIFIED
                if status == PartnerProgramVerificationRequest.STATUS_APPROVED
                else PartnerProgram.VERIFICATION_STATUS_PENDING
                if status == PartnerProgramVerificationRequest.STATUS_PENDING
                else PartnerProgram.VERIFICATION_STATUS_REJECTED
            )
            program.save(update_fields=["company", "verification_status"])
            count += 1
        return count

    def _ensure_invite_records(self, program, created_by):
        count = 0
        program.is_private = True
        program.save(update_fields=["is_private"])
        for index in range(1, 4):
            invite, _ = PartnerProgramInvite.objects.update_or_create(
                program=program,
                email=f"invited.{index}@{EMAIL_DOMAIN}",
                defaults={
                    "created_by": created_by,
                    "status": PartnerProgramInvite.STATUS_PENDING,
                    "expires_at": timezone.now() + timedelta(days=30 + index),
                },
            )
            count += int(invite is not None)
        return count

    def _ensure_moderation_logs(self, programs, admin, organizer):
        count = 0
        for program in programs[:4]:
            for action, author in (
                (ModerationLog.ACTION_SUBMITTED, organizer),
                (ModerationLog.ACTION_APPROVED, admin),
            ):
                log = ModerationLog.objects.filter(
                    program=program,
                    action=action,
                ).first()
                defaults = {
                    "author": author,
                    "status_before": PartnerProgram.STATUS_DRAFT,
                    "status_after": program.status,
                    "comment": "Demo moderation history.",
                }
                if log is None:
                    ModerationLog.objects.create(
                        program=program,
                        action=action,
                        **defaults,
                    )
                else:
                    for field, value in defaults.items():
                        setattr(log, field, value)
                    log.save()
                count += 1
        return count

    def _ensure_notifications(self, programs, organizer, expert, participant):
        count = 0
        notification_specs = [
            (
                organizer,
                Notification.Type.PROGRAM_MODERATION_APPROVED,
                "Program approved",
                programs[0],
            ),
            (
                expert,
                Notification.Type.EXPERT_PROJECTS_ASSIGNED,
                "Expert projects assigned",
                programs[0],
            ),
            (
                participant,
                Notification.Type.PROGRAM_SUBMITTED_TO_MODERATION,
                "Project submitted",
                programs[0],
            ),
        ]
        for recipient, notification_type, title, program in notification_specs:
            notification, _ = Notification.objects.update_or_create(
                recipient=recipient,
                type=notification_type,
                dedupe_key=f"demo:{notification_type}:{program.id}",
                defaults={
                    "title": title,
                    "message": "Demo notification for championship workflow.",
                    "object_type": "partner_program",
                    "object_id": program.id,
                    "url": f"/office/program/{program.id}",
                    "is_read": False,
                },
            )
            NotificationDelivery.objects.update_or_create(
                notification=notification,
                channel=NotificationDelivery.Channel.IN_APP,
                defaults={
                    "status": NotificationDelivery.Status.SENT,
                    "sent_at": timezone.now(),
                },
            )
            count += 2
        return count

    def _ensure_participant_consent(self, program, participant):
        profile = PartnerProgramUserProfile.objects.filter(
            partner_program=program,
            user=participant,
        ).first()
        if profile is None:
            PartnerProgramUserProfile.objects.create(
                partner_program=program,
                user=participant,
                partner_program_data={"demo": True},
            )
        consent = PartnerProgramParticipantConsent.objects.filter(
            program=program,
            user=participant,
        ).first()
        defaults = {
            "consent_document_version": "demo-2026",
            "privacy_policy_version": "demo-2026",
            "participation_terms_version": "demo-2026",
            "consent_text_snapshot": "Demo participant consent.",
            "ip_address": "127.0.0.1",
            "user_agent": "seed_demo_data",
        }
        if consent is None:
            PartnerProgramParticipantConsent.objects.create(
                program=program,
                user=participant,
                **defaults,
            )
        else:
            for field, value in defaults.items():
                setattr(consent, field, value)
            consent.save()
        return 1

    def _ensure_certificate_records(self, program):
        template, _ = ProgramCertificateTemplate.objects.update_or_create(
            program=program,
            defaults={
                "is_enabled": True,
                "template_name": "Demo certificate template",
                "signer_name": "Demo Platform Admin",
                "show_project_title": True,
                "show_team_members": True,
                "show_rank": True,
            },
        )

        submitted_links = list(
            program.program_projects.filter(submitted=True).select_related(
                "project",
                "project__leader",
            )[:3]
        )
        run = CertificateGenerationRun.objects.filter(
            program=program,
            status=CertificateGenerationRun.STATUS_COMPLETED,
        ).first()
        defaults = {
            "total_expected": len(submitted_links),
            "enqueued_count": len(submitted_links),
            "issued_count": len(submitted_links),
            "error_count": 0,
            "error_message": "",
            "completed_at": timezone.now(),
        }
        if run is None:
            CertificateGenerationRun.objects.create(
                program=program,
                status=CertificateGenerationRun.STATUS_COMPLETED,
                **defaults,
            )
        else:
            for field, value in defaults.items():
                setattr(run, field, value)
            run.save()

        count = 2
        for position, program_project in enumerate(submitted_links, start=1):
            IssuedCertificate.objects.update_or_create(
                program=program,
                user=program_project.project.leader,
                program_project=program_project,
                defaults={
                    "certificate_id": (
                        f"DEMO-{program.id}-{program_project.project.leader_id}"
                    ),
                    "team_name": program_project.project.name,
                    "final_score": Decimal("8.50"),
                    "rating_position": position,
                    "status": IssuedCertificate.STATUS_GENERATED,
                    "generated_at": timezone.now(),
                },
            )
            count += 1
        return count

    def _demo_record_count(self):
        demo_models = (
            User,
            Industry,
            SkillCategory,
            Skill,
            SpecializationCategory,
            Specialization,
            Project,
            ProjectGoal,
            ProjectLink,
            Resource,
            Achievement,
            ProjectNews,
            News,
            PartnerProgram,
            PartnerProgramField,
            PartnerProgramFieldValue,
            PartnerProgramMaterial,
            PartnerProgramProject,
            PartnerProgramUserProfile,
            Criteria,
            ProjectScore,
            ProjectEvaluation,
            ProjectEvaluationScore,
            ProjectExpertAssignment,
            PartnerProgramVerificationRequest,
            PartnerProgramInvite,
            ModerationLog,
            Notification,
            NotificationDelivery,
            ProgramCertificateTemplate,
            CertificateGenerationRun,
            IssuedCertificate,
            LegalDocument,
            PartnerProgramLegalSettings,
            PartnerProgramParticipantConsent,
            UserFile,
            UserEducation,
            UserWorkExperience,
            UserLanguages,
            UserAchievement,
            UserLink,
            UserNotificationPreferences,
        )
        return sum(model.objects.count() for model in demo_models)

    def _create_user_news(self, users, news_per_user, rnd):
        created_count = 0
        for user_index, user in enumerate(users, start=1):
            for news_index in range(news_per_user):
                text = USER_NEWS[(user_index + news_index) % len(USER_NEWS)]
                news, created = News.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(User),
                    object_id=user.pk,
                    text=text,
                    defaults={
                        "datetime_created": timezone.now()
                        - timedelta(days=user_index + news_index)
                    },
                )
                created_count += int(created)
                self._add_reactions(news, users, rnd)
        return created_count

    def _create_project_news(self, projects, news_per_project, rnd):
        created_count = 0
        for project_index, project in enumerate(projects, start=1):
            for news_index in range(news_per_project):
                text = PROJECT_NEWS[(project_index + news_index) % len(PROJECT_NEWS)]
                news, created = News.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(Project),
                    object_id=project.pk,
                    text=text,
                    defaults={
                        "datetime_created": timezone.now()
                        - timedelta(hours=project_index * 4 + news_index)
                    },
                )
                ProjectNews.objects.get_or_create(project=project, text=text)
                created_count += int(created)
                self._add_reactions(news, [project.leader], rnd)
        return created_count

    def _create_program_news(self, programs, rnd):
        created_count = 0
        for program_index, program in enumerate(programs, start=1):
            users = list(program.users.all())
            for news_index, text in enumerate(PROGRAM_NEWS):
                news, created = News.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(PartnerProgram),
                    object_id=program.pk,
                    text=text,
                    defaults={
                        "pin": news_index == 0,
                        "datetime_created": timezone.now()
                        - timedelta(hours=program_index * 3 + news_index),
                    },
                )
                created_count += int(created)
                self._add_reactions(news, users, rnd)
        return created_count

    def _add_reactions(self, obj, users, rnd):
        if not users:
            return
        content_type = ContentType.objects.get_for_model(obj)
        viewers = rnd.sample(users, k=min(len(users), rnd.randint(1, 8)))
        fans = rnd.sample(viewers, k=min(len(viewers), rnd.randint(1, 4)))
        for user in viewers:
            View.objects.get_or_create(
                user=user,
                content_type=content_type,
                object_id=obj.pk,
            )
        for user in fans:
            Like.objects.get_or_create(
                user=user,
                content_type=content_type,
                object_id=obj.pk,
            )

    def _get_or_create(self, model, **lookup):
        obj = model.objects.filter(**lookup).first()
        if obj is not None:
            return obj
        return model.objects.create(**lookup)
