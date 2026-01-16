
import requests
import socket
import json
import sys

OUTPUT_FILE = "llm_test_results.txt"

def log(msg):
    print(msg)
    with open(OUTPUT_FILE, "a") as f:
        f.write(msg + "\n")

def check_port(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def test_endpoint(base_url):
    log(f"Testing {base_url}...")
    
    # 1. Check /models
    try:
        resp = requests.get(f"{base_url}/models", timeout=2)
        if resp.status_code != 200:
            log(f"  FAILED /models: {resp.status_code}")
            return False
        
        models = resp.json().get('data', [])
        model_ids = [m['id'] for m in models]
        log(f"  Found models: {model_ids}")
        
    except Exception as e:
        log(f"  Error checking models: {e}")
        return False

    # 2. Test embeddings
    log("  Testing embeddings...")
    embedding_models = ['text-embedding-ada-002'] + model_ids
    
    for model in embedding_models:
        log(f"    Trying model: {model}")
        try:
            payload = {
                "input": "test embedding support",
                "model": model
            }
            resp = requests.post(f"{base_url}/embeddings", json=payload, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and len(data['data']) > 0 and 'embedding' in data['data'][0]:
                    emb = data['data'][0]['embedding']
                    log(f"    SUCCESS! Generated embedding (dim: {len(emb)})")
                    return True
            else:
                log(f"    Failed: {resp.status_code} - {resp.text[:100]}")
                
        except Exception as e:
            log(f"    Error: {e}")
            
    return False

def main():
    # Clear file
    with open(OUTPUT_FILE, "w") as f:
        f.write("Starting LLM Test...\n")
        
    targets = [
        ("192.168.31.199", 1234),
        ("127.0.0.1", 1234),
        ("localhost", 1234)
    ]
    
    success = False
    for host, port in targets:
        if check_port(host, port):
            log(f"Port {port} open on {host}")
            url = f"http://{host}:{port}/v1"
            if test_endpoint(url):
                log(f"\nVERIFIED: {url} supports embeddings!")
                success = True
                break
        else:
            log(f"Port {port} closed on {host}")
            
    if not success:
        log("\nFAILURE: No working embedding endpoint found.")

if __name__ == "__main__":
    main()
