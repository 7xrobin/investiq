# Investiq — command runway 💅
# Run `just` or `just help` to see every lewk available.

# Default Django port for the dev server
port := "8000"

# Show all available recipes
help:
    @just --list

# Install all dependencies into the uv-managed virtualenv
install:
    uv sync

# Apply database migrations
migrate:
    uv run python manage.py migrate

# Create new migrations from model changes
makemigrations:
    uv run python manage.py makemigrations

# Create a superuser for the Django admin
superuser:
    uv run python manage.py createsuperuser

# Collect static files (used in production)
collectstatic:
    uv run python manage.py collectstatic --noinput

# Open the Django shell (shell_plus via django-extensions)
shell:
    uv run python manage.py shell_plus

# Run the dev server (defaults to port 8000; override: just serve 9000)
serve port=port:
    uv run python manage.py runserver {{port}}

# Fresh start: install deps, migrate, then run the server
start: install migrate
    just serve

# Run any manage.py command: just manage "createsuperuser"
manage *args:
    uv run python manage.py {{args}}

# Run the test suite
test:
    uv run python manage.py test

# Django system checks
check:
    uv run python manage.py check
