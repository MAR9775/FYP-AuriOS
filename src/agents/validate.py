import os
from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from src.tools.validate import validate_tools
from src.prompts.validate import VALIDATE_PROMPT

# Load environment variables
load_dotenv()
LLM_MODEL = os.getenv("MODEL_NAME", "llama3")


def _create_ollama_model():
    """Creates and returns an Ollama-backed OpenAI chat model."""
    return OpenAIChatModel(
        model_name=LLM_MODEL,
        provider=OllamaProvider(base_url='http://localhost:11434/v1'),
    )


def create_validate_agent():
    """
    Creates and returns a Pydantic AI Agent for validating software.
    Uses Ollama as the LLM backend with tools from src.tools.validate.
    """
    model = _create_ollama_model()
    agent = Agent(
        model,
        instructions=VALIDATE_PROMPT,
        tools=validate_tools,
    )
    print(f"✅ Initialized Validate Agent with LLM: {LLM_MODEL}")
    return agent


# --- Main Execution ---
if __name__ == "__main__":
    validate_agent = create_validate_agent()

    print("\n--- Starting AurIOS Validate Agent ---")
    user_input = "Validate that python is installed and working as a coding tool."

    try:
        print(f"\nUser Input: {user_input}")
        result = validate_agent.run_sync(user_input)
        print("\n--- FINAL VALIDATE AGENT RESULT ---")
        print(result.output)
    except Exception as e:
        print(f"\n--- CRITICAL ERROR ---")
        print(f"An error occurred: {e}")
