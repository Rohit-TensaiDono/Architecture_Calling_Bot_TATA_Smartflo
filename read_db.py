import sqlite3

_conn = sqlite3.connect("solar_calls.db")
_conn.row_factory = sqlite3.Row
calls = _conn.execute("SELECT * FROM calls ORDER BY started_at DESC LIMIT 10").fetchall()
print("--- LATEST CALLS ---")
for c in calls:
    data = dict(c)
    print(f"ID: {data['id']} | Session: {data['session_id'][:8]} | DID: {data['mobile_number']} | Customer: {data['customer_number']} | Status: {data['call_status']} | Time: {data['started_at'][11:19]}")
    print(f"  Lead: Prop={data['property_type']} | Bill={data['bill_range']} | Time={data['timeline']} | Pay={data['payment_pref']}")

print("\n--- CONVERSATIONS FOR LATEST CALL ---")
if calls:
    convs = _conn.execute("SELECT * FROM conversations WHERE session_id=? ORDER BY turn", (calls[0]["session_id"],)).fetchall()
    for c in convs:
        print(f"  Turn {c['turn']} [{c['state']}]")
        print(f"   Q: {c['question'][:40]}...")
        print(f"   A: {c['answer']}")
else:
    print("No calls found in DB.")
