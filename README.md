# Procollab backend service

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

## If have errors (Win)
```
OSError: cannot load library 'gobject-2.0-0': error 0x7e.  Additionally, ctypes.util.find_library() did not manage to locate a library called 'gobject-2.0-0'
```
Go to [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) step by step install dependencies. If the error persists, add the path to the windows environment variable: `C:\msys64\mingw64\bin`


## [Docs](/docs/readme.md)
