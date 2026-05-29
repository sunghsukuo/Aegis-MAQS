import sys
import json
from pathlib import Path

# Add backend directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.db_manager import db_session, execute_sql, DB_TYPE, init_db

BACKUP_FILE = Path(__file__).resolve().parent / "db_backup.json"

def get_tables():
    return ["capital_ledger", "transaction_history", "recommendations", "reports"]

def backup():
    print("[*] Starting database backup...")
    backup_data = {}
    
    with db_session() as conn:
        cursor = conn.cursor()
        for table in get_tables():
            # Check if table exists
            try:
                execute_sql(cursor, f"SELECT * FROM {table}", f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                records = []
                for row in rows:
                    if hasattr(row, "keys"): # sqlite Row or pymysql DictCursor
                        records.append({k: row[k] for k in row.keys()})
                    elif isinstance(row, dict):
                        records.append(row)
                    else:
                        # Fallback for tuple
                        colnames = [desc[0] for desc in cursor.description]
                        records.append(dict(zip(colnames, row)))
                
                # Convert any non-serializable fields (like datetime or decimals) to string
                for rec in records:
                    for k, v in rec.items():
                        if hasattr(v, "isoformat"): # datetime
                            rec[k] = v.isoformat()
                        elif hasattr(v, "to_eng_string"): # decimal
                            rec[k] = float(v)
                        elif isinstance(v, bytes):
                            rec[k] = v.decode("utf-8")
                
                backup_data[table] = records
                print(f"[✓] Backed up table '{table}': {len(records)} records.")
            except Exception as e:
                print(f"[!] Warning: Table '{table}' does not exist or failed to backup: {e}")
                backup_data[table] = []
                
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    print(f"[✓] Backup saved to {BACKUP_FILE}")

def restore():
    print("[*] Starting database restore...")
    if not BACKUP_FILE.exists():
        print(f"[✗] Backup file not found at {BACKUP_FILE}")
        sys.exit(1)
        
    with open(BACKUP_FILE, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
        
    with db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Drop existing tables safely to clear any new additions
        print("[*] Dropping existing tables...")
        for table in get_tables():
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        
    # 2. Recreate empty tables using init_db
    print("[*] Reinitializing database schema...")
    init_db()
    
    # 3. Populate backup data
    with db_session() as conn:
        cursor = conn.cursor()
        for table, records in backup_data.items():
            if not records:
                print(f"[*] Table '{table}' backup was empty. Skipping...")
                continue
                
            # Clear automatic seeding records in capital_ledger if any
            if table == "capital_ledger":
                execute_sql(cursor, "DELETE FROM capital_ledger", "DELETE FROM capital_ledger")
                
            columns = list(records[0].keys())
            
            # Placeholders
            if DB_TYPE == "mysql":
                placeholders = ", ".join(["%s"] * len(columns))
            else:
                placeholders = ", ".join(["?"] * len(columns))
                
            cols_str = ", ".join(columns)
            query = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
            
            # Insert records
            for rec in records:
                vals = [rec[col] for col in columns]
                execute_sql(cursor, query, query, tuple(vals))
                
            print(f"[✓] Restored table '{table}': {len(records)} records.")
            
    print("[✓] Database restore completed successfully!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python db_backup_restore.py [--backup|--restore]")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "--backup":
        backup()
    elif cmd == "--restore":
        restore()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
