import os
from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

from src.agents.install import create_install_agent
from src.agents.configure import create_configure_agent
from src.agents.validate import create_validate_agent
from src.prompts.orchestrator import ORCHESTRATOR_PROMPT

# Load environment variables
load_dotenv()
LLM_MODEL = os.getenv("MODEL_NAME", "llama3")


# --- Sub-Agent Tool Wrappers ---
# Each sub-agent is wrapped as a plain function so the orchestrator
# can dynamically invoke them via Pydantic AI tool calling.

def run_install_agent(request: str) -> str:
    """
    Delegates a software installation task to the Install Sub-Agent.
    The Install Agent will clone a GitHub repository and attempt to build/install the software.

    Args:
        request: A natural language description of what to install,
                 including the GitHub repo URL and software name.

    Returns:
        The Install Agent's result — a SUCCESS or FAILURE string with details.
    """
    try:
        agent = create_install_agent()
        result = agent.run_sync(request)
        return result.output or "ERROR: No output from install agent."
    except Exception as e:
        return f"FAILURE: Install agent encountered an error: {e}"


def run_configure_agent(request: str) -> str:
    """
    Delegates a software configuration task to the Configure Sub-Agent.
    The Configure Agent will set up system PATH and environment variables for installed software.

    Args:
        request: A natural language description of what to configure,
                 including the software name and install path.

    Returns:
        The Configure Agent's result — a SUCCESS or FAILURE string with details.
    """
    try:
        agent = create_configure_agent()
        result = agent.run_sync(request)
        return result.output or "ERROR: No output from configure agent."
    except Exception as e:
        return f"FAILURE: Configure agent encountered an error: {e}"


def run_validate_agent(request: str) -> str:
    """
    Delegates a software validation task to the Validate Sub-Agent.
    The Validate Agent will check if software is accessible and functional.

    Args:
        request: A natural language description of what to validate,
                 including the software name and type (coding or app).

    Returns:
        The Validate Agent's result — a SUCCESS or FAILURE string with details.
    """
    try:
        agent = create_validate_agent()
        result = agent.run_sync(request)
        return result.output or "ERROR: No output from validate agent."
    except Exception as e:
        return f"FAILURE: Validate agent encountered an error: {e}"


# --- Orchestrator Tools List ---
orchestrator_tools = [run_install_agent, run_configure_agent, run_validate_agent]


def _create_ollama_model():
    """Creates and returns an Ollama-backed OpenAI chat model."""
    return OpenAIChatModel(
        model_name=LLM_MODEL,
        provider=OllamaProvider(base_url='http://localhost:11434/v1'),
    )


# --- Create the Orchestrator ---
def create_orchestrator():
    """
    Creates and returns the Orchestrator — a Pydantic AI Agent that dynamically
    routes tasks to the install, configure, and validate sub-agents.
    """
    model = _create_ollama_model()
    agent = Agent(
        model,
        instructions=ORCHESTRATOR_PROMPT,
        tools=orchestrator_tools,
    )
    print(f"✅ Initialized Orchestrator Agent with LLM: {LLM_MODEL}")
    return agent


# --- Main Execution ---
if __name__ == "__main__":
    orchestrator = create_orchestrator()

    print("\n" + "=" * 60)
    print("         AuriOS — Local LLM Orchestrator")
    print("=" * 60)

    user_input = input("\n🔧 What would you like to install? > ").strip()

    if not user_input:
        user_input = (
            "Please install Python from the repository "
            "'https://github.com/python/cpython.git' "
            "and validate it as a coding tool."
        )
        print(f"Using default request: {user_input}")

    try:
        print(f"\n📥 User Request: {user_input}\n")
        result = orchestrator.run_sync(user_input)

        print("\n" + "=" * 60)
        print("         FINAL ORCHESTRATOR RESULT")
        print("=" * 60)
        print(result.output)

    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
