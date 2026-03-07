import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Try to load .env from parent directory
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

def wipe_database():
    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            print("Executing DETACH DELETE...")
            result = session.run("MATCH (n) DETACH DELETE n;")
            summary = result.consume()
            print(f"Deleted {summary.counters.nodes_deleted} nodes and {summary.counters.relationships_deleted} relationships.")
        driver.close()
        print("Database wiped successfully.")
    except Exception as e:
        print(f"Failed to wipe database: {e}")

if __name__ == "__main__":
    wipe_database()
