#!/bin/bash
# Finalize each instance database after creation
# This must run after all schema files are loaded

set -e

INSTANCE_COUNT=${FACTORIO_INSTANCE_COUNT:-1}

echo "Finalizing $INSTANCE_COUNT Factorio database instances..."

for i in $(seq 0 $((INSTANCE_COUNT - 1))); do
    DB_NAME="factoryverse_$i"
    RCON_PORT=$((27015 + i))
    
    echo "Finalizing database: $DB_NAME (RCON port: $RCON_PORT)"
    
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DB_NAME" <<-EOSQL
        SET search_path TO factoryverse, public;
        SELECT init_factorio_instance($i, $RCON_PORT);
EOSQL
    
    echo "Database $DB_NAME finalized successfully"
done

echo "All Factorio database instances finalized"
