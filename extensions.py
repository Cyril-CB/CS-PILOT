"""
Extensions Flask partagées (CSRF, Rate Limiter, SQLAlchemy, Migrate).
Module séparé pour éviter les imports circulaires entre app.py et les blueprints.
"""
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

csrf = CSRFProtect()

limiter = Limiter(
    get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)

db = SQLAlchemy()
migrate = Migrate()
