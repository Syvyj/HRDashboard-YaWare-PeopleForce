"""
Migration script to add is_control_manager column to users table
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from web_dashboard import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        # Check if column exists
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'is_control_manager' in columns:
            print("✓ Column 'is_control_manager' already exists")
            return
        
        # Add the column
        print("Adding 'is_control_manager' column...")
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE users ADD COLUMN is_control_manager BOOLEAN DEFAULT 0'))
            conn.commit()
        
        print("✓ Column added successfully")
        
        # Update existing users with manager_filter to be control managers
        print("Updating existing control managers...")
        result = db.session.execute(text(
            "UPDATE users SET is_control_manager = 1 WHERE manager_filter IS NOT NULL AND manager_filter != ''"
        ))
        db.session.commit()
        print(f"✓ Updated {result.rowcount} users")

if __name__ == '__main__':
    migrate()
