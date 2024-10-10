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

## Troubleshooting

## Errors caused by weasyprint

### MacOS

Error:
```
OSError: cannot load library 'pango-1.0-0': dlopen(pango-1.0-0, 0x0002): tried: 'pango-1.0-0' (no such file), '/System/Volumes/Preboot/Cryptexes/OSpango-1.0-0' (no such file), '/Users/yakser/.pyenv/versions/3.11.9/lib/pango-1.0-0' (no such file), '/System/Volumes/Preboot/Cryptexes/OS/Users/yakser/.pyenv/versions/3.11.9/lib/pango-1.0-0' (no such file), '/opt/homebrew/lib/pango-1.0-0' (no such file), '/System/Volumes/Preboot/Cryptexes/OS/opt/homebrew/lib/pango-1.0-0' (no such file), '/usr/lib/pango-1.0-0' (no such file, not in dyld cache), 'pango-1.0-0' (no such file), '/usr/local/lib/pango-1.0-0' (no such file), '/usr/lib/pango-1.0-0' (no such file, not in dyld cache).  Additionally, ctypes.util.find_library() did not manage to locate a library called 'pango-1.0-0'
```

Fix:

```shell
brew install weasyprint
```

### Windows

Error:
```
OSError: cannot load library 'gobject-2.0-0': error 0x7e.  Additionally, ctypes.util.find_library() did not manage to locate a library called 'gobject-2.0-0'
```

Fix:

Go to [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) step by step install dependencies. If the error persists, add the path to the windows environment variable: `C:\msys64\mingw64\bin`


## [Docs](/docs/readme.md)
