from projects.models import Project


def get_n_random_projects(num: int) -> list[Project]:
    tries = 3
    projects = set()

    while len(projects) < num and tries > 0:
        project = Project.objects.filter(draft=False).order_by("?").first()

        if project not in projects:
            projects.add(project)
        else:
            tries -= 1
    return list(projects)


def get_n_latest_created_projects(num: int) -> list[Project]:
    return list(Project.objects.filter(draft=False).order_by("-datetime_created")[:num])
