import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class config:

    SECRET_KEY = os.getenv("SECRET_KEY")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "database", "db.sqlite3")

    SQLALCHEMY_TRACK_MODIFICATIONS = False