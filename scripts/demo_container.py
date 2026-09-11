"""Local isolated image smoke/restart drill. No published ports, live credentials or deployment."""

import subprocess
import time
from uuid import uuid4

name = "recall-verification-" + uuid4().hex[:8]
image = "recall-local:verification"
token = "local-container-verification-token-only"
subprocess.run(
    [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "-e",
        f"RECALL_TOKEN={token}",
        image,
    ],
    check=True,
    capture_output=True,
)


def execute(code):
    result = subprocess.run(
        ["docker", "exec", name, "python", "-c", code], capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def ready():
    for _ in range(100):
        result = subprocess.run(
            ["docker", "exec", name, "recall", "doctor"], capture_output=True, text=True
        )
        if result.returncode == 0:
            return
        time.sleep(0.1)
    raise RuntimeError("Container service did not become ready")


try:
    ready()
    execute("""
import httpx
c=httpx.Client(base_url='http://127.0.0.1:8765/v1',headers={'Authorization':'Bearer local-container-verification-token-only'})
def request(method,path,**kwargs):
 r=c.request(method,path,**kwargs);r.raise_for_status();return r.json()
card=request('POST','/cards',json={'term':'kernel','definition':'Inputs mapped to zero'})
s=request('POST','/sessions',json={'request_key':'container-demo'})
e=s['episodes'][0]
request('POST',f"/episodes/{e['id']}/rating",json={'rating':3,'expected_version':0,'request_key':'container-rating'})
from pathlib import Path
Path('/data/before.json').write_text(c.get('/history').text)
assert c.get('/history').json()[0]['rating']==3
""")
    subprocess.run(["docker", "restart", name], check=True, capture_output=True)
    ready()
    print(
        execute("""
import httpx,json
from pathlib import Path
c=httpx.Client(base_url='http://127.0.0.1:8765/v1',headers={'Authorization':'Bearer local-container-verification-token-only'})
assert c.get('/history').json()==json.loads(Path('/data/before.json').read_text())
assert len(c.get('/history').json())==1
print('Linux container: authenticated startup, add, rating, and restart persistence passed.')
""")
    )
    subprocess.run(["docker", "exec", name, "python", "-m", "pip", "check"], check=True)
finally:
    subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)
