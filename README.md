# Procollab backend service

## Usage

### Clone project

📌 `git clone https://github.com/procollab-github/api.git`

### Create virtual environment

🔑 Copy `.env.example` to `.env` and change api settings

### Install dependencies
Before installing dependencies, make sure that you have python 3.11 (see the recommendations section below)  
  
* 🐍 Install poetry with command `pip install poetry==1.2.2`
* 📎 Install dependencies with command `poetry install`
* 🐚 Активируйте виртуальное окружение: `poetry shell`

### Accept migrations

🎓 Run  `python manage.py migrate`

### Run project

🚀 Run project via `python manage.py runserver`

### Run project in docker 

You can run project in docker with commands from Makefile (e.g. `make up`)

## Recommendations  
  
### 1.Installing Pyenv  
  
Clone Pyenv from the official GitHub repository:  
  
```zsh  
curl https://pyenv.run | bash  
```  
  
Add Pyenv to your shell profile (e.g., .bashrc, .bash_profile, or .zshrc):  
  
```zsh  
export PATH="$HOME/.pyenv/bin:$PATH"eval "$(pyenv init --path)"  
eval "$(pyenv init -)"  
eval "$(pyenv virtualenv-init -)"  
```  
  
Apply changes to your shell environment:  
  
```zsh  
source ~/.bashrc # or equivalent profile, e.g., for Zsh use .zshrc
```  
  
Verify Pyenv is installed correctly:  
  
pyenv --version  
  
### 2. Installing Python 3.11  
  
Once Pyenv is set up, you can install Python 3.11 with the following steps:  
  
Install Python 3.11:  
  
```zsh  
pyenv install 3.11
```  
  
Verify Python 3.11 has been installed:  
  
pyenv versions  
  
### 3. Setting Python 3.11 as the Default Version  
  
To set Python 3.11 as the default global version, use the following command:  
  
```zsh  
pyenv local 3.11
```  
  
This will switch your system's Python interpreter to use Python 3.11 by default.  
  
### 4. Verification  
  
Check that Python 3.11 is now the active version:  
  
```zsh  
python --version
```  
  
You should see:  
  
```zsh  
Python 3.11.0
```

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
