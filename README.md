# Procollab backend service

## Документация

[Здесь](/docs/readme.md)

## Usage

### Clone project

📌 `git clone https://github.com/procollab-github/api.git`

### Create virtual environment

🔑 Copy `.env.example` to `.env` and change api settings

### Install dependencies

* 🐍 Install poetry with command `pip install poetry`
* 📎 Install dependencies with command `poetry install`

### Accept migrations

🎓 Run  `python manage.py migrate`

### Run project

🚀 Run project via `python manage.py runserver`
Run celery worker via `celery -A procollab worker -l INFO -P eventlet`
Run celery scheduler via `celery -A procollab beat`
## For developers

### Install pre-commit hooks

To install pre-commit simply run inside the shell:

```bash
pre-commit install
```

To run it on all of your files, do

```bash
pre-commit run --all-files
```
