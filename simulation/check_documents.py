from neo4j import GraphDatabase
import os

uri = os.environ['NEO4J_URI']
user = os.environ['NEO4J_USER']
password = os.environ['NEO4J_PASSWORD']

driver = GraphDatabase.driver(uri, auth=(user, password))

query = """
MATCH (d:Document) 
RETURN d.title, elementId(d)
ORDER BY d.title
"""

with driver.session() as session:
    result = session.run(query)
    for r in result:
        print(f"'{r['d.title']}' : {r['elementId(d)']}")
