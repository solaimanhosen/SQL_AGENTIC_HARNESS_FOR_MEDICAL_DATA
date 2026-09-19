import sqlite3

conn = sqlite3.connect("synthea.db")
cursor = conn.cursor()

cursor.execute("""
SELECT name
FROM sqlite_master
WHERE type='table'
ORDER BY name
""")

for row in cursor.fetchall():
    print(row[0])
