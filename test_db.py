import os
import oracledb
from dotenv import load_dotenv

load_dotenv()

conn = oracledb.connect(
    user=os.environ.get("ORACLE_USER", "VF_AGENT"),
    password=os.environ.get("ORACLE_PASSWORD", ""),
    host=os.environ.get("ORACLE_HOST", "20.102.78.61"),
    port=int(os.environ.get("ORACLE_PORT", "1521")),
    service_name=os.environ.get("ORACLE_SERVICE", "FREEPDB1")
)

with conn.cursor() as cur:
    cur.execute("SELECT DISTINCT shop_city FROM VID.D_SHOP")
    cities = cur.fetchall()
    print("Cities:", cities[:20])

    cur.execute("SELECT DISTINCT shop_status FROM VID.D_SHOP")
    statuses = cur.fetchall()
    print("Statuses:", statuses)

    cur.execute("SELECT COUNT(*) FROM VID.D_SHOP WHERE UPPER(shop_city) LIKE '%ISTANBUL%'")
    print("Count Istanbul UPPER:", cur.fetchone()[0])
    
    cur.execute("SELECT COUNT(*) FROM VID.D_SHOP WHERE shop_city LIKE '%ISTANBUL%' OR shop_city LIKE '%Istanbul%'")
    print("Count Istanbul LIKE:", cur.fetchone()[0])
