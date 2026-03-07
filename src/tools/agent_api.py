
from src.agents import install_agent, configure_agent, validate_agent


def install_software(repo_url: str, software_name: str) -> str:
    """
    Downloads and installs software from a specified GitHub repository URL.
    This should be the FIRST step after a user request.

    Args:
        repo_url: The URL of the GitHub repository (e.g., 'https://github.com/user/project.git').
        software_name: The descriptive name of the software being installed.

    Returns:
        A success or failure string indicating the outcome of the installation process.
    """
    print(f"AgentAPI: Assigning installation task for {software_name}...")
    result = install_agent.run_installation(repo_url, software_name)
    return result

def configure_software(software_name: str, install_path: str = None) -> str:
    """
    Configures environment variables, system paths, and necessary dependencies 
    after successful installation. This step MUST follow a successful installation.

    Args:
        software_name: The name of the software to configure.
        install_path: Optional path where the software was installed, if known.

    Returns:
        A success or failure string indicating the outcome of the configuration process.
    """
    print(f"AgentAPI: Assigning configuration task for {software_name}...")
    result = configure_agent.run_configuration(software_name, install_path)
    return result

def validate_software(software_name: str, software_type: str) -> str:
    """
    Validates that the software is correctly installed and configured. 
    For coding tools (type='coding'), it runs a 'Hello World' test. 
    For applications (type='app'), it attempts to launch the program.

    Args:
        software_name: The name of the software to validate.
        software_type: Either 'coding' (runs code test) or 'app' (opens program).

    Returns:
        A success or failure string, including the output of any test script.
    """
    print(f"AgentAPI: Assigning validation task for {software_name}...")
    result = validate_agent.run_validation(software_name, software_type)
    return result

# You can add a list of all tools here for easy loading in orchestrator.py
agent_tools = [install_software, configure_software, validate_software]
