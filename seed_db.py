import sqlite3, random, datetime, os
import pandas as pd

DB_PATH = os.getenv("DB_PATH", "toy.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS orders;

CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  name TEXT,
  country TEXT,
  signup_date TEXT
);

CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  name TEXT,
  category TEXT,
  price REAL
);

CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER,
  product_id INTEGER,
  quantity INTEGER,
  order_date TEXT,
  FOREIGN KEY(customer_id) REFERENCES customers(customer_id),
  FOREIGN KEY(product_id) REFERENCES products(product_id)
);
""")

countries = ["AR","MX","CL","CO","PE","UY"]
customers = [{'customer_id': i, 'name': f'Customer {i}',
              'country': random.choice(countries),
              'signup_date': (datetime.date(2024,1,1) + datetime.timedelta(days=random.randint(0,600))).isoformat()}
             for i in range(1,301)]

categories = ["Electronics","Home","Sports","Beauty","Books"]
products = [{'product_id': i, 'name': f'Product {i}',
             'category': random.choice(categories),
             'price': round(random.uniform(5,500),2)}
            for i in range(1,151)]

orders = []
oid = 1
for _ in range(4000):
    c = random.randint(1,300)
    p = random.randint(1,150)
    q = random.randint(1,5)
    d = (datetime.date(2024,1,1) + datetime.timedelta(days=random.randint(0,600))).isoformat()
    orders.append({'order_id': oid, 'customer_id': c, 'product_id': p, 'quantity': q, 'order_date': d})
    oid += 1

pd.DataFrame(customers).to_sql("customers", conn, if_exists="append", index=False)
pd.DataFrame(products).to_sql("products", conn, if_exists="append", index=False)
pd.DataFrame(orders).to_sql("orders", conn, if_exists="append", index=False)

conn.commit(); conn.close()
print(f"DB creada en {DB_PATH}")
