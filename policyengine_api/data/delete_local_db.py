import psycopg2

# Database configuration - update these as per your local setup
DB_NAME = "your_database_name"
DB_USER = "your_username"
DB_PASSWORD = "your_password"
DB_HOST = "localhost"
DB_PORT = "5432"


def delete_tables():
    try:
        # Connect to the PostgreSQL database
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Drop tables
        cursor.execute("DROP TABLE IF EXISTS economy;")
        cursor.execute("DROP TABLE IF EXISTS policy;")
        cursor.execute("DROP TABLE IF EXISTS household;")

        print("Local database deleted successfully.")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error deleting tables: {e}")


if __name__ == "__main__":
    delete_tables()
