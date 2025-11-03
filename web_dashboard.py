from __future__ import annotations
import click
from flask.cli import with_appcontext
from dashboard_app import create_app
from dashboard_app.extensions import db
from dashboard_app.models import User

app = create_app()


@app.cli.command('create-user')
@click.argument('email')
@click.argument('name')
@click.argument('password')
@click.option('--managers', default='', help='Comma-separated control manager IDs (e.g. "1,2")')
@click.option('--admin', is_flag=True, default=False, help='Grant full admin access')
@with_appcontext
def create_user(email: str, name: str, password: str, managers: str, admin: bool):
    email = email.strip().lower()
    if User.query.filter_by(email=email).first():
        click.echo('Користувач з таким email вже існує.')
        return
    user = User(email=email, name=name, manager_filter=managers, is_admin=admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f'Створено користувача {email}')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
