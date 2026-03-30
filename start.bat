@echo off
cd /d "%~dp0"
start http://localhost:8501
streamlit run streamlit_app.py --server.port 8501
pause
