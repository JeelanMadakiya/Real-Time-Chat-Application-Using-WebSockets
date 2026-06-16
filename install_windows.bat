@echo off
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo Installation complete. Start Redis, then run run_windows.bat
passlib==1.7.4
bcrypt==4.0.1
