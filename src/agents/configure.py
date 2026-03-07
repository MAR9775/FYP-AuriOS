import os
from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from src.tools.configure import configure_tools
from src.prompts.configure import CONFIGURE_PROMPT

# Load environment variables
load_dotenv()
LLM_MODEL = os.getenv("MODEL_NAME", "llama3")


def _create_ollama_model():
    """Creates and returns an Ollama-backed OpenAI chat model."""
    return OpenAIChatModel(
        model_name=LLM_MODEL,
        provider=OllamaProvider(base_url='http://localhost:11434/v1'),
    )


def create_configure_agent():
    """
    Creates and returns a Pydantic AI Agent for configuring software.
    Uses Ollama as the LLM backend with tools from src.tools.configure.
    """
    model = _create_ollama_model()
    agent = Agent(
        model,
        instructions=CONFIGURE_PROMPT,
        tools=configure_tools,
    )
    print(f"✅ Initialized Configure Agent with LLM: {LLM_MODEL}")
    return agent


# --- Main Execution ---
if __name__ == "__main__":
    configure_agent = create_configure_agent()

    print("\n--- Starting AurIOS Configure Agent ---")
    user_input = "Configure Python at /tmp/aurios_installs/python"

    try:
        print(f"\nUser Input: {user_input}")
        result = configure_agent.run_sync(user_input)
        print("\n--- FINAL CONFIGURE AGENT RESULT ---")
        print(result.output)
    except Exception as e:
        print(f"\n--- CRITICAL ERROR ---")
        print(f"An error occurred: {e}")
