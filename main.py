# Implement FastAPI here for endpoints to access the orchestrator agent.
from fastapi import FastAPI
from src.agents.orchestrator import create_orchestrator

app = FastAPI()


@app.post("/install")
def install(repo_url: str, software_name: str):
    agent = create_orchestrator()
    result = agent.run_sync(f"Install {software_name} from {repo_url}")
    return {"output": result.output}


@app.post("/configure")
def configure(software_name: str, install_path: str = None):
    agent = create_orchestrator()
    result = agent.run_sync(f"Configure {software_name} at {install_path}")
    return {"output": result.output}


@app.post("/validate")
def validate(software_name: str, software_type: str):
    agent = create_orchestrator()
    result = agent.run_sync(f"Validate {software_name} of type {software_type}")
    return {"output": result.output}


@app.post("/chat")
def chat(user_input: str):
    agent = create_orchestrator()
    result = agent.run_sync(user_input)
    return {"output": result.output}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
