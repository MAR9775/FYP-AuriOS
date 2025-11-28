"""
AuriOS Demo Script - Automated Software Installation System
Demonstrates Install Agent and Validate Agent with dual repository support
"""

import os
import sys
import time
import re
import subprocess # NEW: Required to launch the software

# --- Configuration Setup ---
# Add src directory to Python path (REQUIRED for import agents)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# NOTE: Using Mock classes if real ones are not available for the demo
try:
    from agents.install_agent import InstallAgent
    from agents.validate_agent import ValidateAgent
except ImportError:
    print("WARNING: Could not import InstallAgent/ValidateAgent. Using Mock classes.")
    class MockInstallAgent:
        def install_from_github(self, repo_owner, repo_name, **kwargs):
            if repo_owner == "MAR9775" and kwargs.get('simulate_fail'):
                 raise Exception("Simulated server connection failure for demo")
            print(f"  -> Executing install request for: {repo_owner}/{repo_name}")
            return {'success': True}

    class MockValidateAgent:
        def validate_installation(self, **kwargs):
             # Simulates validation passing for the demo
             return {
                 "command_available": {'passed': True, 'details': 'Command found.'},
                 "version_check": {'passed': True, 'details': 'Version matched expected pattern.'},
                 "executable_check": {'passed': True, 'details': 'Executable found at path.'}
             }
    
    InstallAgent = MockInstallAgent
    ValidateAgent = MockValidateAgent


# --- Progress Simulation Function ---
def show_progress_simulation(duration_seconds=7, message="Processing Installation"):
    """Simulates a visual progress bar filling up in the terminal."""
    fill_char = '█'
    empty_char = ' ' 
    bar_length = 40
    
    print(f"\n{message}...", end=' ')
    
    for i in range(bar_length + 1):
        hashes = fill_char * i
        spaces = empty_char * (bar_length - i)
        percent = (i / bar_length) * 100
        
        sys.stdout.write(f"\r{message}... [{hashes}{spaces}] {percent:.0f}%")
        sys.stdout.flush()
        
        time.sleep(duration_seconds / bar_length)
    
    print("\nInstallation step complete.")

# --- Helper Function for Launching (NEW) ---
def launch_software(software_config):
    """Launches the executable command for the installed software."""
    launch_command = software_config['validation']['command']
    print(f"\n Attempting to launch {software_config['name']} using command: '{launch_command}'")
    
    try:
        # Uses the default shell to execute the command (like running 'git' or 'code' in PowerShell)
        subprocess.Popen(launch_command, shell=True)
    except Exception as e:
        print(f" Failed to launch {software_config['name']}: {e}")
        return False

    print(" Launch command sent successfully!")
    return True

# --- Software Configuration Catalog ---
SOFTWARE_CATALOG = {
    "1": {
        "name": "Git for Windows",
        "primary_source": {
            "repo_owner": "MAR9775",
            "repo_name": "AurIOS-Software-Repository",
            "asset_pattern": "Git-.*-64-bit.exe",
            "tag": "v-git-2.43.0",
            # "simulate_fail": True # UNCOMMENT TO FORCE FALLBACK FOR DEMO
        },
        "fallback_source": {
            "repo_owner": "git-for-windows",
            "repo_name": "git",
            "asset_pattern": "-64-bit.exe"
        },
        "validation": {
            "command": "git", # Launch command
            "version_command": "git --version",
            "expected_version_pattern": r"git version (\d+\.\d+\.\d+)",
            "install_path": "C:/Program Files/Git",
            "executable": "C:/Program Files/Git/bin/git.exe",
            "directory_structure": [
                "C:/Program Files/Git/bin",
                "C:/Program Files/Git/cmd",
                "C:/Program Files/Git/usr"
            ]
        }
    },
    "2": {
        "name": "Visual Studio Code",
        "primary_source": {
            "repo_owner": "MAR9775",
            "repo_name": "AurIOS-Software-Repository",
            "asset_pattern": "VSCodeUserSetup-x64-.*.exe", # Corrected pattern
            "tag": "v-vscode-1.85.0"
        },
        "fallback_source": {
            "repo_owner": "microsoft",
            "repo_name": "vscode",
            "asset_pattern": "win32-x64-user.exe"
        },
        "validation": {
            "command": "code", # Launch command
            "version_command": "code --version",
            "expected_version_pattern": r"(\d+\.\d+\.\d+)",
            "install_path": f"C:/Users/{os.getenv('USERNAME')}/AppData/Local/Programs/Microsoft VS Code",
            "executable": f"C:/Users/{os.getenv('USERNAME')}/AppData/Local/Programs/Microsoft VS Code/Code.exe"
        }
    },
    "3": {
        "name": "Node.js",
        "primary_source": {
            "repo_owner": "MAR9775",
            "repo_name": "AurIOS-Software-Repository",
            "asset_pattern": "node-.*-x64.msi",
            "tag": "v-nodejs-20.10.0"
        },
        "fallback_source": {
            "repo_owner": "nodejs",
            "repo_name": "node",
            "asset_pattern": "-x64.msi"
        },
        "validation": {
            "command": "node", # Launch command
            "version_command": "node --version",
            "expected_version_pattern": r"v(\d+\.\d+\.\d+)",
            "install_path": "C:/Program Files/nodejs",
            "executable": "C:/Program Files/nodejs/node.exe",
            "additional_commands": ["npm --version"]
        }
    }
}


# --- Function Definitions (Same as before) ---

def display_banner():
    """Display AuriOS banner"""
    print("\n" + "="*60)
    print("         AuriOS - Automated Software Installation")
    print("           Intelligent Install & Validation System")
    print("="*60 + "\n")


def display_menu():
    """Display software selection menu"""
    print("\n📦 Available Software:")
    print("-" * 50)
    for key, software in SOFTWARE_CATALOG.items():
        status = " Available" if "primary_source" in software else "🔄 Coming Soon"
        print(f"  {key}. {software['name']:<30} {status}")
    print(f"  Q. Quit")
    print("-" * 50)


def install_software(software_config):
    """
    Install software with fallback mechanism and progress simulation.
    """
    print(f"\n Installing {software_config['name']}...")
    print("="*60)
    
    install_agent = InstallAgent()
    
    # Try primary source first (AuriOS Software Repository)
    print(f"\n Attempting download from AuriOS Software Repository...")
    primary = software_config.get('primary_source')
    
    try:
        simulate_fail = primary.get('simulate_fail', False) 
        
        result = install_agent.install_from_github(
            repo_owner=primary['repo_owner'],
            repo_name=primary['repo_name'],
            asset_pattern=primary['asset_pattern'],
            tag=primary.get('tag'),
            simulate_fail=simulate_fail 
        )
        
        if result['success']:
            show_progress_simulation(duration_seconds=7, message=f"Processing {software_config['name']} Installer (Primary)") 
            print(f"\n Installation successful from primary source!")
            return result
            
        raise Exception("Download failed from primary source (status returned False)")
            
    except Exception as e:
        print(f"\n  Primary source failed: {str(e)}")
        print(f" Falling back to official repository...")
        
        # Fallback to official source
        fallback = software_config.get('fallback_source')
        if fallback:
            try:
                result = install_agent.install_from_github(
                    repo_owner=fallback['repo_owner'],
                    repo_name=fallback['repo_name'],
                    asset_pattern=fallback['asset_pattern']
                )
                
                if result['success']:
                    show_progress_simulation(duration_seconds=7, message=f"Processing {software_config['name']} Installer (Fallback)") 
                    print(f"\n Installation successful from fallback source!")
                    return result
                
                raise Exception("Download failed from fallback source (status returned False)")
                    
            except Exception as fallback_error:
                print(f"\n Fallback also failed: {str(fallback_error)}")
                return {'success': False, 'error': str(fallback_error)}
    
    return {'success': False, 'error': 'All installation sources failed'}


def validate_software(software_config):
    """
    Validate software installation
    """
    print(f"\n Validating {software_config['name']} Installation...")
    print("="*60)
    
    validate_agent = ValidateAgent()
    validation_config = software_config['validation']
    
    # Perform comprehensive validation
    validation_results = validate_agent.validate_installation(
        software_name=software_config['name'],
        command=validation_config['command'],
        version_command=validation_config.get('version_command'),
        expected_version_pattern=validation_config.get('expected_version_pattern'),
        install_path=validation_config.get('install_path'),
        executable_path=validation_config.get('executable'),
        directory_structure=validation_config.get('directory_structure', [])
    )
    
    # Display results
    print("\n Validation Results:")
    print("-" * 60)
    
    passed = 0
    failed = 0
    
    for check, result in validation_results.items():
        status = " PASS" if result['passed'] else " FAIL"
        print(f"  {check.replace('_', ' ').title():<30} {status}")
        
        if not result['passed'] and 'error' in result:
            print(f"    └─ {result['error']}")
        elif result['passed'] and 'details' in result:
            print(f"    └─ {result['details']}")
        
        if result['passed']:
            passed += 1
        else:
            failed += 1
    
    print("-" * 60)
    print(f"\n Summary: {passed} passed, {failed} failed")
    
    if failed == 0:
        print(" All validation checks passed! Software is ready to use.")
    else:
        print("  Some validation checks failed. Installation may be incomplete.")
    
    return validation_results


def main():
    """Main demo execution"""
    display_banner()
    
    print("Welcome to AuriOS demonstration!")
    print("This demo showcases automated software installation and validation.")
    print("\n Features:")
    print("  • Dual-source installation (AuriOS repo + Official repos)")
    print("  • Automatic fallback mechanism")
    print("  • Comprehensive validation (5+ checks)")
    print("  • Progress tracking and error handling")
    
    while True:
        display_menu()
        
        choice = input("\n Select software to install (or Q to quit): ").strip()
        
        if choice.upper() == 'Q':
            print("\n Thank you for using AuriOS!")
            print("Visit: https://github.com/MAR9775/FYP-AuriOS")
            break
        
        if choice not in SOFTWARE_CATALOG:
            print("\n Invalid selection. Please try again.")
            continue
        
        software = SOFTWARE_CATALOG[choice]
        
        # Confirm installation
        confirm = input(f"\n Install {software['name']}? (y/n): ").strip().lower()
        
        if confirm != 'y':
            print("Installation cancelled.")
            continue
        
        # Install software
        install_result = install_software(software)
        
        if not install_result['success']:
            print(f"\n Installation failed: {install_result.get('error', 'Unknown error')}")
            retry = input("\nWould you like to try again? (y/n): ").strip().lower()
            if retry == 'y':
                continue
            else:
                break
        
        # Validate installation
        input("\n  Press Enter to validate installation...")
        validation_results = validate_software(software) # Store validation result
        
        # Ask to launch only if validation passed (NEW LOGIC)
        if all(r['passed'] for r in validation_results.values()):
            launch_q = input(f"\n Validation passed! Would you like to launch {software['name']} now? (y/n): ").strip().lower()
            if launch_q == 'y':
                launch_software(software)
        
        # Ask if user wants to install more
        another = input("\n\n Install another software? (y/n): ").strip().lower()
        if another != 'y':
            print("\n Demo complete!")
            print(" Check out the full project: https://github.com/MAR9775/FYP-AuriOS")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Demo interrupted by user.")
        print("Goodbye!")
    except Exception as e:
        print(f"\n\n Unexpected error: {str(e)}")
        print("Please report this issue at: https://github.com/MAR9775/FYP-AuriOS/issues")