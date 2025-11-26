import os
from langchain.agents import AgentExecutor, create_react_agent
from langchain_community.llms import Ollama
from langchain_core.prompts import PromptTemplate
from src.agent_api import agent_tools # Import the tools we defined

# --- Configuration ---
# NOTE: Replace 'llama3' with the actual model you have pulled in Ollama
LLM_MODEL = "llama3" 
SYSTEM_PROMPT = """
You are AurIOS, a Local LLM Orchestrator that manages software installation, configuration, and validation 
on a local system. You must strictly follow the ReAct framework: 
Thought, Action, Observation.

Your goal is to fulfill user requests by calling the provided tools sequentially:
1. First, call install_software.
2. If installation is SUCCESS, call configure_software.
3. If configuration is SUCCESS, call validate_software.

NEVER attempt configuration or validation unless the preceding step was explicitly SUCCESS.
The final answer MUST report the final status and the path of the installed software.
"""

# --- 1. Define the Prompt Template for ReAct ---
prompt = PromptTemplate.from_template(
    template="""{system_prompt}\n\n{input}\n{agent_scratchpad}"""
).partial(system_prompt=SYSTEM_PROMPT)

# --- 2. Initialize the Local LLM ---
def initialize_llm():
    try:
        # Assumes Ollama is running locally on the default port
        llm = Ollama(model=LLM_MODEL)
        print(f"✅ Initialized LLM: {LLM_MODEL}")
        return llm
    except Exception as e:
        print(f"❌ Error initializing Ollama LLM. Is Ollama running and model '{LLM_MODEL}' pulled? Details: {e}")
        return None

# --- 3. Create the ReAct Agent ---
def create_orchestrator(llm, tools):
    # Create the core ReAct agent executable
    agent = create_react_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    return agent_executor

# --- 4. Main Execution Loop ---
if __name__ == "__main__":
    
    # Initialize the LLM
    orchestrator_llm = initialize_llm()
    if not orchestrator_llm:
        print("\nExiting. Please check your Ollama setup.")
        exit()

    # Create the Agent Executor
    orchestrator = create_orchestrator(orchestrator_llm, agent_tools)
    
    # Example Request for the LLM
    print("\n--- Starting AurIOS Orchestrator ---")
    user_input = "Please install Python from the repository 'https://github.com/python/cpython.git' and validate it as a coding tool."

    try:
        # Run the Agent Executor with the user input
        print(f"\nUser Input: {user_input}")
        result = orchestrator.invoke({"input": user_input})
        
        print("\n--- FINAL ORCHESTRATOR RESULT ---")
        print(result['output'])
        
    except Exception as e:
        print(f"\n--- CRITICAL ERROR DURING EXECUTION ---")
        print(f"An error occurred in the orchestrator loop: {e}")
