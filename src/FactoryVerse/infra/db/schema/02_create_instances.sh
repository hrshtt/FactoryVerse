#!/bin/bash
# Create instance databases from template
# This script runs after the template database is created and configured

set -e

INSTANCE_COUNT=${FACTORIO_INSTANCE_COUNT:-1}

echo "Creating $INSTANCE_COUNT Factorio database instances from template..."

# Mark template as template database
echo "Marking factoryverse_template as template database..."
PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" --host localhost <<-EOSQL
    UPDATE pg_database SET datistemplate = true WHERE datname = 'factoryverse_template';
EOSQL

# Create instance databases from template
for i in $(seq 0 $((INSTANCE_COUNT - 1))); do
    DB_NAME="factoryverse_$i"
    echo "Creating database: $DB_NAME"
    
    # Create database from template
    PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" --host localhost <<-EOSQL
        CREATE DATABASE $DB_NAME TEMPLATE factoryverse_template;
EOSQL
    
    echo "Database $DB_NAME created successfully"
done

echo "All Factorio database instances created from template"
