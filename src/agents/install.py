import os
from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from src.tools.install import install_tools
from src.prompts.install import INSTALL_PROMPT

# Load environment variables
load_dotenv()
LLM_MODEL = os.getenv("MODEL_NAME", "llama3")


def _create_ollama_model():
    """Creates and returns an Ollama-backed OpenAI chat model."""
    return OpenAIChatModel(
        model_name=LLM_MODEL,
        provider=OllamaProvider(base_url='http://localhost:11434/v1'),
    )


def create_install_agent():
    """
    Creates and returns a Pydantic AI Agent for installing software.
    Uses Ollama as the LLM backend with tools from src.tools.install.
    """
    model = _create_ollama_model()
    agent = Agent(
        model,
        instructions=INSTALL_PROMPT,
        tools=install_tools,
    )
    print(f"✅ Initialized Install Agent with LLM: {LLM_MODEL}")
    return agent


# --- Main Execution ---
if __name__ == "__main__":
    install_agent = create_install_agent()

    print("\n--- Starting AurIOS Install Agent ---")
    user_input = (
        "Please install Python from the repository "
        "'https://github.com/python/cpython.git' "
        "and validate it as a coding tool."
    )

    try:
        print(f"\nUser Input: {user_input}")
        result = install_agent.run_sync(user_input)
        print("\n--- FINAL INSTALL AGENT RESULT ---")
        print(result.output)
    except Exception as e:
        print(f"\n--- CRITICAL ERROR DURING EXECUTION ---")
        print(f"An error occurred in the install agent loop: {e}")
