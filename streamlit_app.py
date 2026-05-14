"""Run with: streamlit run streamlit_app.py"""
from dotenv import load_dotenv

load_dotenv(override=True)

from app.app import render

render()
